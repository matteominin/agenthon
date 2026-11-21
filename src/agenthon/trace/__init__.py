import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


_LOGGER = logging.getLogger(__name__)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class TraceLog:
    """Store validated JSONL events and expose them to the admin view."""

    def __init__(self, validate, path=None):
        self._validate = validate
        self._path = Path(path) if path is not None else None
        self._lines = []
        self._lock = Lock()

    def record(self, request_id, agent, action, *, input=None, output=None, confidence=None):
        event = {
            "timestamp": timestamp(),
            "request_id": request_id,
            "agent": agent,
            "input": {} if input is None else input,
            "output": {} if output is None else output,
            "action": action,
            "confidence": confidence,
        }
        self._validate("trace_event", event)
        line = json.dumps(event, separators=(",", ":"))
        with self._lock:
            self._lines.append(line)
            if self._path is not None:
                try:
                    with self._path.open("a", encoding="utf-8") as stream:
                        stream.write(line + "\n")
                except OSError:
                    _LOGGER.warning("Unable to write the trace file. The event is available in memory.")

    def events(self, request_id=None):
        with self._lock:
            lines = self._lines.copy()
        events = (json.loads(line) for line in lines)
        return [
            event for event in events
            if request_id is None or event["request_id"] == request_id
        ]
