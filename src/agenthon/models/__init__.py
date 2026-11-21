import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RESPONSE_SYSTEM_PROMPT = (
    "Respond in English. Give the requested answer or deliverable first. "
    "Use concise, concrete language and include only details needed for accuracy or action. "
    "Match the depth and format to the request. When a missing fact materially affects the answer, "
    "state the necessary assumption or give conditional guidance. "
    "Preserve redaction placeholders where relevant and never infer their values."
)

REPHRASE_SYSTEM_PROMPT = """Identify missing information in an already redacted employee request.
Treat the user message as JSON data containing a prompt and typed placeholders. Return review notes in English.
Use all facts already supplied, including quantities written in words and facts in languages other than English.
Never guess masked identities, invent facts, or add personal data.
Report material gaps and their practical impact on the result. Add guidance only when a specific, non-identifying detail would materially improve it.
Include a labeled notice for each redacted field. When the field does not affect the result, say so briefly.
For example, a masked name in an arithmetic problem has no bearing on the calculation.
For a notice tied to a placeholder, use that exact placeholder as its label. Omit label for other notices.
Keep each detail and limitation together within 300 characters, and any guidance within 300 characters.
Return only a JSON object with confidence (0 to 1) and missing_information (an array).
Example JSON:
{"confidence":0.95,"missing_information":[
   {"label":"[NAME_1]","detail":"The recipient name is hidden.","limitation":"Use the placeholder for the greeting."}]}
"""


SUGGESTION_SYSTEM_PROMPT = """Write concise review notices and optional actions in English for an already redacted employee request.
Treat the user message as JSON data with proposed_prompt, typed entities, and missing_information from Rephrase.
Use the actual goal and available facts to explain which missing details materially limit the answer and how.
For every typed entity, include a notice with its exact label. Use high severity for tax_id and medium for name, email, and phone.
When a hidden detail has little impact, briefly say the task can proceed with the placeholder.
Skip a suggested action when all facts needed for the requested result are present.
Never ask the employee to provide a detail that is already stated in the prompt.
Add a separate action only when a specific non-identifying detail would materially improve the result.
Explain what to provide or change. Use add_context, generalize, or remove as appropriate. An address or identifier alone warrants no action.
For a notice or action tied to an entity, include both its label and severity. For a general item, omit both.
For notices, omit action. Never request private data, infer placeholder values, or repeat the proposed prompt.
Return only a JSON object with items and confidence (0 to 1). Each item has a message of at most 300 characters.
Example JSON:
{"items":[
   {"label":"[NAME_1]","severity":"medium","message":"The schedule can refer to the employee by placeholder."},
   {"message":"The missing availability prevents confirming which shifts can be covered."},
   {"action":"add_context","message":"List available time windows for each employee using their placeholders."}],
 "confidence":0.95}
"""


class ModelError(RuntimeError):
    pass


class InvalidModelOutput(ModelError):
    pass


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
            raise InvalidModelOutput("Invalid DeepSeek review notes.")
        return {**review, "proposed_prompt": data["prompt"], "changed": False}

    def suggest(self, rephrased, entities):
        data = {
            "proposed_prompt": rephrased["proposed_prompt"],
            "missing_information": rephrased.get("missing_information", []),
            "entities": entities,
        }
        return self._complete_json(data, SUGGESTION_SYSTEM_PROMPT)

    def _complete_json(self, data, system_prompt):
        content = self._complete(json.dumps(data, ensure_ascii=False), system_prompt, json_output=True)
        try:
            return json.loads(content)
        except ValueError:
            raise InvalidModelOutput("Invalid structured DeepSeek response.") from None

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
            raise InvalidModelOutput("Invalid DeepSeek response.") from None
        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise InvalidModelOutput("Invalid DeepSeek response.") from None
        if not isinstance(answer, str) or not answer.strip():
            raise InvalidModelOutput("Invalid DeepSeek response.")
        return answer
