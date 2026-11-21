import json
import os
from enum import Enum
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RESPONSE_SYSTEM_PROMPT = (
    "Respond in English. Give the requested answer or deliverable first. "
    "Use concise, concrete language and include only details needed for accuracy or action. "
    "Match the depth and format to the request. When a missing fact materially affects the answer, "
    "state the necessary assumption or give conditional guidance. "
    "Preserve the exact spelling of relevant redaction placeholders and never infer their values. "
    "When drafting a message for an explicitly specified recipient placeholder, put it in a separate To line. "
    "Avoid adding a sender name or placeholder unless it is needed or requested."
)

REPHRASE_SYSTEM_PROMPT = """Identify missing information in an already redacted employee request.
Treat the user message as JSON data containing a prompt and typed placeholders. Return review notes in English.
Use all facts already supplied, including quantities written in words and facts in languages other than English.
Never guess masked identities, invent facts, or add personal data.
Report material gaps and their practical impact on the result. Add guidance only when a specific, non-identifying detail would materially improve it.
Include a labeled notice for each redacted field. When the field does not affect the result, say so briefly.
For example, a masked name in an arithmetic problem has no bearing on the calculation.
For a notice tied to a placeholder, use that exact placeholder as its label. Omit label for other notices.
Omit guidance when none is needed. Do not use null for optional fields.
Keep each detail and limitation together within 300 characters, and any guidance within 300 characters.
Return only a JSON object with confidence (0 to 1) and missing_information (an array).
Example JSON:
{"confidence":0.95,"missing_information":[
   {"label":"[NAME_1]","detail":"The recipient name is hidden.","limitation":"Use the placeholder for the greeting."}]}
"""


SUGGESTION_SYSTEM_PROMPT = """Write concise review notices and optional actions in English for an already redacted employee request.
Treat the user message as JSON data with proposed_prompt, typed entities, and missing_information from Rephrase.
Use the requested outcome and facts already in the prompt to decide what matters. Treat Rephrase notes as candidates.
Include a notice only for a missing detail that materially limits the answer. State the practical consequence in plain words.
Include at most one action, and only when a specific non-identifying detail or change would materially improve the result.
Start the action message with a verb and say exactly what to add or change. Use add_context, generalize, or remove.
Skip details already provided, generic advice, and notices that only point out a redaction. Return an empty items array when nothing useful qualifies.
Put the most useful item first. Use at most two items total and one short sentence per message, ideally 12 words or fewer.
For a notice or action tied to an entity, include both its label and severity. For a general item, omit both.
Use the exact entity label, with high severity for tax_id and medium for name, email, and phone.
For notices, omit action. Do not use null for optional fields.
Never request private data, infer placeholder values, or repeat the proposed prompt.
Return only a JSON object with items and confidence (0 to 1). Each item has a message of at most 300 characters.
Example for a draft reminder with a masked recipient: {"items":[],"confidence":0.95}
Example for a shift schedule with no availability:
{"items":[{"message":"Shift coverage depends on staff availability."},
          {"action":"add_context","message":"List available hours for each employee using placeholders."}],
 "confidence":0.95}
"""


class ModelError(RuntimeError):
    pass


class OutputIssue(Enum):
    MALFORMED_JSON = "DeepSeek returned malformed JSON."
    MISSING_CONTENT = "The DeepSeek response had no message content."
    EMPTY_CONTENT = "DeepSeek returned empty or non-text message content."
    MISSING_NOTES = "Expected a JSON object with a missing_information array."
    CHANGED_PROMPT = "Rephrase changed the verified redacted prompt."
    LOW_CONFIDENCE = "Agent confidence was below 50%."
    UNKNOWN_LABEL = "Agent output referenced an unknown placeholder."
    REMOVED_VALUE = "Agent output repeated a value removed by the privacy check."


class InvalidModelOutput(ModelError):
    def __init__(self, message="Invalid model output."):
        self.issue = message if isinstance(message, OutputIssue) else None
        super().__init__(self.issue.value if self.issue is not None else message)


class DeepSeekProvider:
    def __init__(self, api_key=None, model=None, timeout=30):
        self._api_key = os.environ.get("DEEPSEEK_API_KEY") if api_key is None else api_key
        self._model = model or os.environ.get("DEEPSEEK_MODEL") or "deepseek-flash"
        self._timeout = timeout

    def __call__(self, prompt, route):
        return self._complete(prompt, RESPONSE_SYSTEM_PROMPT)

    def rephrase(self, data):
        review = self._complete_json(data, REPHRASE_SYSTEM_PROMPT)
        if not isinstance(review, dict) or not isinstance(review.get("missing_information"), list):
            raise InvalidModelOutput(OutputIssue.MISSING_NOTES)
        notes = _omit_null_fields(review["missing_information"], {"label", "guidance"})
        return {**review, "proposed_prompt": data["prompt"], "changed": False, "missing_information": notes}

    def suggest(self, rephrased, entities):
        data = {
            "proposed_prompt": rephrased["proposed_prompt"],
            "missing_information": rephrased.get("missing_information", []),
            "entities": entities,
        }
        suggestions = self._complete_json(data, SUGGESTION_SYSTEM_PROMPT)
        if isinstance(suggestions, dict) and isinstance(suggestions.get("items"), list):
            suggestions["items"] = _omit_null_fields(suggestions["items"], {"label", "severity", "action"})
        return suggestions

    def _complete_json(self, data, system_prompt):
        content = self._complete(json.dumps(data, ensure_ascii=False), system_prompt, json_output=True)
        try:
            return json.loads(content)
        except ValueError:
            raise InvalidModelOutput(OutputIssue.MALFORMED_JSON) from None

    def _complete(self, prompt, system_prompt, *, json_output=False):
        if not self._api_key:
            raise ModelError("DeepSeek is unavailable.")
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "stream": False,
        }
        if json_output:
            payload["response_format"] = {"type": "json_object"}
            payload["max_tokens"] = 4096
        request = Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        request.add_unredirected_header("Authorization", f"Bearer {self._api_key}")
        try:
            with urlopen(request, timeout=self._timeout) as response:
                data = json.load(response)
        except HTTPError as exc:
            if exc.code in (408, 504):
                raise TimeoutError("DeepSeek timed out.") from None
            raise ModelError("DeepSeek request failed.") from None
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError("DeepSeek timed out.") from None
            raise ModelError("DeepSeek request failed.") from None
        except (ValueError, UnicodeError):
            raise InvalidModelOutput(OutputIssue.MALFORMED_JSON) from None
        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise InvalidModelOutput(OutputIssue.MISSING_CONTENT) from None
        if not isinstance(answer, str) or not answer.strip():
            raise InvalidModelOutput(OutputIssue.EMPTY_CONTENT)
        return answer


def _omit_null_fields(items, optional):
    return [
        {key: value for key, value in item.items() if value is not None or key not in optional}
        if isinstance(item, dict) else item
        for item in items
    ]
