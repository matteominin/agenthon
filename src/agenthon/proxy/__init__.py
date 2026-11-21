import re
from collections import Counter
from copy import deepcopy
from threading import Lock
from uuid import uuid4

from agenthon.models import DeepSeekProvider, InvalidModelOutput, ModelError
from agenthon.pii import PIIDetector
from agenthon.rephrase import rephrase
from agenthon.suggestion import suggest
from agenthon.trace import TraceLog, timestamp

from .contracts import validate_contract


_PLACEHOLDER = re.compile(r"\[[A-Z]+(?:_[A-Z]+)*_[1-9][0-9]*\]")


class _StageFailure(Exception):
    def __init__(self, reason):
        self.reason = reason


def _contains_removed_value(prompt, values):
    text = _PLACEHOLDER.sub(" ", prompt).casefold()
    return any(
        re.search(r"(?<!\w)" + re.escape(value.casefold()) + r"(?!\w)", text)
        for value in values
    )


class Proxy:
    """Request, decision, history and trace entry points for the demo UI."""

    def __init__(self, provider=None, *, detector=None, rephraser=None,
                 suggester=suggest, trace_path=None):
        self._provider = DeepSeekProvider() if provider is None else provider
        self._detector = PIIDetector() if detector is None else detector
        # Callable-only providers used by existing fixtures can keep their local rephraser.
        self._rephrase = (
            getattr(self._provider, "rephrase", rephrase) if rephraser is None else rephraser
        )
        self._suggest = suggester
        self._trace = TraceLog(validate_contract, trace_path)
        self._history = {}
        self._reviews = {}
        self._lock = Lock()

    def submit(self, request):
        """Accept a proxy request and return a validated proxy result."""
        validate_contract("proxy", request, "request")
        request_id = uuid4().hex
        prompt = request["prompt"]
        entry = {
            "request_id": request_id,
            "timestamp": timestamp(),
            "status": "processing",
            "risk_flag": False,
            "original_prompt": prompt,
            "sent_prompt": None,
            "response": None,
            "route": None,
        }
        validate_contract("admin_request", entry)
        with self._lock:
            self._history[request_id] = entry
        self._trace.record(request_id, "proxy", "check", output={"status": "processing"})
        return self._screen(request_id, prompt, 1, {})

    def decide(self, decision):
        """Bind a choice to the currently displayed review revision."""
        validate_contract("proxy", decision, "decision")
        request_id = decision["request_id"]
        action = decision["action"]
        with self._lock:
            review = self._reviews.get(request_id)
            if review is not None:
                result, known_values = review
                if (decision["revision"] != result["revision"]
                        or action not in result["allowed_actions"]):
                    review = None
            if review is not None:
                del self._reviews[request_id]
                self._history[request_id]["status"] = "processing"

        if review is None:
            return self._failed(request_id, "stale_review", update_history=False)

        self._trace.record(request_id, "proxy", "check", output={"status": "processing"})
        if action == "edit":
            return self._screen(
                request_id, decision["prompt"], decision["revision"] + 1, known_values
            )
        route = "local_simulated" if action == "local_simulated" else "deepseek"
        return self._send(request_id, result["proposed_prompt"], route)

    def history(self):
        """Return admin entries with the most recent submissions first."""
        with self._lock:
            entries = deepcopy(list(reversed(self._history.values())))
        for entry in entries:
            validate_contract("admin_request", entry)
        return entries

    def trace_events(self, request_id=None):
        return self._trace.events(request_id)

    def _validated_result(self, result):
        validate_contract("proxy", result, "result")
        return result

    def _attempt(self, request_id, agent, operation, metadata=None):
        for attempt in range(2):
            try:
                return operation()
            except TimeoutError:
                reason = "timeout"
            except InvalidModelOutput:
                reason = "invalid_output"
            except ModelError:
                reason = "model_error"
            except Exception:
                reason = "model_error" if agent == "model" else "invalid_output"

            if attempt == 0 and reason != "model_error":
                self._trace.record(request_id, agent, "retry", input=metadata,
                                   output={"reason": reason})
                continue
            self._trace.record(request_id, agent, "fail", input=metadata,
                               output={"reason": reason})
            raise _StageFailure(reason)

    def _detect(self, prompt, known_values):
        payload, current_values = self._detector.detect(prompt, known_values.copy())
        validate_contract("agents", payload, "pii")
        labels = {entity["label"] for entity in payload["entities"]}
        all_values = known_values | current_values
        redacted = payload["redacted_prompt"]
        if (labels != current_values.keys()
                or any(not isinstance(value, str) or not value for value in current_values.values())
                or not labels <= set(_PLACEHOLDER.findall(redacted))
                or (payload["status"] == "clear" and redacted != prompt)
                or _contains_removed_value(redacted, all_values.values())):
            raise ValueError("Invalid PII result.")
        return payload, all_values

    def _screen(self, request_id, prompt, revision, known_values):
        try:
            pii, known_values = self._attempt(
                request_id, "pii", lambda: self._detect(prompt, known_values)
            )
        except _StageFailure as exc:
            return self._review(request_id, revision, exc.reason, known_values)

        entities = pii["entities"]
        if entities:
            with self._lock:
                self._history[request_id]["risk_flag"] = True
        self._trace.record(
            request_id, "pii", "redact" if entities else "check",
            output={"entity_counts": dict(Counter(entity["type"] for entity in entities))},
            confidence=pii["confidence"],
        )
        if pii["status"] == "uncertain" or pii["confidence"] < 0.5:
            return self._review(
                request_id, revision, "uncertain_detection", known_values, entities
            )
        if pii["status"] == "clear":
            return self._send(request_id, prompt, "deepseek")

        try:
            proposed, suggestions = self._prepare_review(request_id, pii, known_values)
        except _StageFailure as exc:
            return self._review(request_id, revision, exc.reason, known_values, entities)
        return self._review(
            request_id, revision, "pii_found", known_values, entities, proposed, suggestions
        )

    def _prepare_review(self, request_id, pii, known_values):
        redacted = pii["redacted_prompt"]
        entities = pii["entities"]
        labels = {entity["label"] for entity in entities}
        allowed_labels = labels | {None}
        data = {"prompt": redacted, "entities": entities}
        validate_contract("agents", data, "redacted_input")
        metadata = {"entity_count": len(entities)}

        def rephrase_checked():
            result = self._rephrase(deepcopy(data))
            validate_contract("agents", result, "rephrase")
            proposed = result["proposed_prompt"]
            missing = result.get("missing_information", [])
            if (not proposed.strip()
                    or result["confidence"] < 0.5
                    or not result["changed"]
                    or proposed.strip() == redacted.strip()
                    or Counter(_PLACEHOLDER.findall(proposed)) != Counter(_PLACEHOLDER.findall(redacted))
                    or _contains_removed_value(proposed, known_values.values())
                    or any(
                        item.get("label") not in allowed_labels
                        or _contains_removed_value(item["detail"], known_values.values())
                        or _contains_removed_value(item["limitation"], known_values.values())
                        or _contains_removed_value(item.get("guidance", ""), known_values.values())
                        for item in missing
                    )):
                raise ValueError("Unsafe revised prompt.")
            return result

        revised = self._attempt(request_id, "rephrase", rephrase_checked, metadata)
        self._trace.record(request_id, "rephrase", "rephrase", input=metadata,
                           confidence=revised["confidence"])

        def suggest_checked():
            result = self._suggest(deepcopy(revised), deepcopy(entities))
            validate_contract("agents", result, "suggestions")
            if (result["confidence"] < 0.5
                    or any(item.get("label") not in allowed_labels
                           or _contains_removed_value(item["message"], known_values.values())
                           for item in result["items"])):
                raise ValueError("Invalid suggestions.")
            return result

        suggestions = self._attempt(request_id, "suggestion", suggest_checked, metadata)
        self._trace.record(request_id, "suggestion", "suggest", input=metadata,
                           confidence=suggestions["confidence"])
        return revised["proposed_prompt"], suggestions["items"]

    def _review(self, request_id, revision, reason, known_values,
                entities=(), proposed=None, suggestions=()):
        result = self._validated_result({
            "request_id": request_id,
            "status": "review_required",
            "revision": revision,
            "reason": reason,
            "proposed_prompt": proposed,
            "entities": list(entities),
            "suggestions": list(suggestions),
            "allowed_actions": ["edit"] if proposed is None else [
                "approve", "edit", "local_simulated"
            ],
        })
        with self._lock:
            self._history[request_id]["status"] = "review_required"
            self._reviews[request_id] = (deepcopy(result), known_values)
        self._trace.record(request_id, "proxy", "review",
                           output={"status": "review_required", "reason": reason})
        return result

    def _send(self, request_id, prompt, route):
        metadata = {"route": route}
        with self._lock:
            self._history[request_id].update(sent_prompt=prompt, route=route)
        self._trace.record(request_id, "proxy", "route", output=metadata)

        def call_provider():
            answer = self._provider(prompt, route)
            if not isinstance(answer, str) or not answer.strip():
                raise InvalidModelOutput("Invalid model response.")
            return answer

        try:
            answer = self._attempt(request_id, "model", call_provider, metadata)
        except _StageFailure as exc:
            return self._failed(request_id, exc.reason)
        result = self._validated_result({
            "request_id": request_id,
            "status": "completed",
            "route": route,
            "answer": answer,
        })
        self._trace.record(request_id, "model", "complete", input=metadata,
                           output={"status": "completed"})
        with self._lock:
            self._history[request_id].update(status="completed", response=answer)
        self._trace.record(request_id, "proxy", "complete", output={"status": "completed"})
        return result

    def _failed(self, request_id, reason, *, update_history=True):
        result = self._validated_result({
            "request_id": request_id,
            "status": "failed",
            "reason": reason,
        })
        with self._lock:
            known_request = request_id in self._history
            if update_history:
                self._history[request_id]["status"] = "failed"
        trace_id = request_id if known_request else uuid4().hex
        self._trace.record(trace_id, "proxy", "fail",
                           output={"status": "failed", "reason": reason})
        return result
