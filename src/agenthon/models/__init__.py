import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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
        if not self._api_key:
            raise ModelError("DeepSeek is unavailable.")
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "Respond in English."},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "stream": False,
        }
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
