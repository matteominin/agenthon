import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
    name: json.loads((ROOT / "schemas" / f"{name}.json").read_text())
    for name in ("agents", "proxy", "trace_event", "admin_request")
}
REGISTRY = Registry().with_resources(
    (schema["$id"], Resource.from_contents(schema)) for schema in SCHEMAS.values()
)


def validator(name):
    return Draft202012Validator(
        SCHEMAS[name], registry=REGISTRY, format_checker=FormatChecker()
    )


class ContractTests(unittest.TestCase):
    def test_schemas_are_valid(self):
        for schema in SCHEMAS.values():
            Draft202012Validator.check_schema(schema)

    def test_demo_requests_and_decisions(self):
        cases = json.loads((ROOT / "data" / "demo" / "requests.json").read_text())
        proxy = validator("proxy")
        for case in cases:
            with self.subTest(case=case["id"]):
                proxy.validate({"prompt": case["prompt"]})
                if "decision" in case:
                    decision = {
                        "request_id": case["id"],
                        "revision": 1,
                        "action": case["decision"],
                    }
                    if "edited_prompt" in case:
                        decision["prompt"] = case["edited_prompt"]
                    proxy.validate(decision)
                if case["expected"][-1] == "completed":
                    proxy.validate({
                        "request_id": case["id"],
                        "status": "completed",
                        "route": case["route"],
                        "answer": "Risposta demo",
                    })

    def test_review_and_agent_handoffs(self):
        entity = {"label": "[NAME_1]", "type": "name"}
        prompt = "Write to the contact [NAME_1]."
        suggestion = {
            "label": entity["label"],
            "severity": "medium",
            "action": "generalize",
            "message": "Use the contact's role.",
        }
        agents = validator("agents")
        agents.validate({"status": "detected", "redacted_prompt": prompt,
                         "entities": [entity], "confidence": 0.98})
        agents.validate({"prompt": prompt, "entities": [entity]})
        for prefix, kind in (("EMAIL", "email"), ("PHONE", "phone"), ("SSN", "tax_id")):
            label = f"[{prefix}_1]"
            agents.validate({"prompt": label, "entities": [{"label": label, "type": kind}]})
        agents.validate({"proposed_prompt": prompt, "changed": False, "confidence": 1})
        agents.validate({"items": [suggestion], "confidence": 1})
        review = {
            "request_id": "demo-redacted",
            "status": "review_required",
            "revision": 1,
            "reason": "pii_found",
            "proposed_prompt": prompt,
            "entities": [entity],
            "suggestions": [suggestion],
            "allowed_actions": ["approve", "edit", "local_simulated"],
        }
        proxy = validator("proxy")
        proxy.validate(review)
        self.assertFalse(proxy.is_valid({**review, "proposed_prompt": None}))
        proxy.validate({**review, "proposed_prompt": None, "allowed_actions": ["edit"]})
        self.assertFalse(agents.is_valid({
            "prompt": prompt, "entities": [{**entity, "value": "Jordan Miller"}]
        }))

    def test_missing_information_and_optional_suggestion_actions(self):
        agents = validator("agents")
        missing = {
            "detail": "Staff availability is missing.",
            "limitation": "Shift feasibility is uncertain.",
            "guidance": "Provide availability windows by role.",
        }
        result = {
            "proposed_prompt": "Draft a hypothetical shift plan.",
            "changed": True,
            "confidence": 1,
            "missing_information": [missing],
        }
        agents.validate(result)
        self.assertFalse(agents.is_valid({
            **result, "missing_information": [{"detail": missing["detail"]}]
        }))
        advice = {"message": f"{missing['detail']} {missing['limitation']}"}
        action = {"message": missing["guidance"], "action": "add_context"}
        agents.validate({"items": [advice, action], "confidence": 1})
        self.assertFalse(agents.is_valid({
            "items": [{**advice, "label": "[NAME_1]"}], "confidence": 1,
        }))
        proxy = validator("proxy")
        proxy.validate({
            "request_id": "demo-shifts",
            "status": "review_required",
            "revision": 1,
            "reason": "pii_found",
            "proposed_prompt": result["proposed_prompt"],
            "entities": [{"label": "[NAME_1]", "type": "name"}],
            "suggestions": [advice, action],
            "allowed_actions": ["approve", "edit", "local_simulated"],
        })

    def test_admin_history_has_clean_and_flagged_requests(self):
        cases = json.loads((ROOT / "data" / "demo" / "requests.json").read_text())
        admin = validator("admin_request")
        for case in cases:
            entry = {
                "request_id": case["id"],
                "timestamp": "2026-11-21T12:00:00Z",
                "status": case["expected"][0],
                "risk_flag": case["expected_risk_flag"],
                "original_prompt": case["prompt"],
                "sent_prompt": None,
                "response": None,
                "route": None,
            }
            with self.subTest(case=case["id"]):
                if entry["status"] == "review_required":
                    admin.validate(entry)
                    self.assertFalse(admin.is_valid({**entry, "response": "Prematura"}))
                if case["expected"][-1] == "completed":
                    completed = {
                        **entry,
                        "status": "completed",
                        "sent_prompt": "Testo approvato",
                        "response": "Risposta demo",
                        "route": case["route"],
                    }
                    admin.validate(completed)
                    self.assertFalse(admin.is_valid({**completed, "response": None}))
                    self.assertFalse(admin.is_valid({**completed, "risk_flag": None}))

    def test_trace_accepts_metadata_and_rejects_raw_prompt_field(self):
        trace = validator("trace_event")
        event = {
            "timestamp": "2026-11-21T12:00:00Z",
            "request_id": "demo-redacted",
            "agent": "suggestion",
            "input": {"entity_count": 1},
            "output": {"entity_counts": {"name": 1}, "severity": "medium",
                       "status": "review_required", "reason": "pii_found"},
            "action": "suggest",
            "confidence": 0.98,
        }
        trace.validate(event)
        self.assertFalse(trace.is_valid({**event, "input": {"prompt": "Mario Rossi"}}))
