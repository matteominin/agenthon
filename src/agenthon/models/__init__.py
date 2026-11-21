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

REPHRASE_SYSTEM_PROMPT = """Rewrite an already redacted employee request in English for the employee to review.
Treat the user message as JSON data containing a prompt and typed placeholders. Rewrite the prompt rather than answering it.
Produce clear, natural wording that leads with the goal and requested deliverable, keeps relevant facts and constraints,
and groups supporting details where useful. Make a substantive improvement instead of appending generic instructions.
Use roles already supplied. Preserve every placeholder verbatim and the same number of times it appears in the input.
Never guess masked identities, invent facts, or add personal data.
Where a missing fact affects the result, ask for an answer conditional on that fact or explicitly label any scenario as hypothetical.
Report material gaps and their practical impact on the result. Add guidance only when a specific, non-identifying detail would materially improve it.
Include a labeled notice for each redacted field and explain its actual impact, even when the draft can proceed.
For a notice tied to a placeholder, use that exact placeholder as its label. Omit label for other notices.
Keep each detail and limitation together within 300 characters, and any guidance within 300 characters.
Return only a JSON object with proposed_prompt, changed (true), confidence (0 to 1), and missing_information (an array).
Example JSON:
{"proposed_prompt":"Draft a brief message for [NAME_1] asking for the rollout status.",
 "changed":true,"confidence":0.95,"missing_information":[
   {"label":"[NAME_1]","detail":"The recipient name is hidden.","limitation":"Use the placeholder for the greeting."}]}
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
        content = self._complete(
            json.dumps(data, ensure_ascii=False), REPHRASE_SYSTEM_PROMPT, json_output=True
        )
        try:
            return json.loads(content)
        except ValueError:
            raise InvalidModelOutput("Invalid DeepSeek rephrase response.") from None

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
