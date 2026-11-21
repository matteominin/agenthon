import json
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from fastapi.testclient import TestClient
import gradio as gr
from gradio.state_holder import SessionState

from agenthon.pii import PIIDetector
from agenthon.proxy import Proxy
from agenthon.ui.admin import build_admin
from agenthon.ui.app import build_services
from agenthon.ui.chat import BUTTONS
from test_contracts import ROOT, validator
from test_proxy import find_names


CASES = {case["id"]: case for case in json.loads((ROOT / "data/demo/requests.json").read_text())}
ADMIN = validator("admin_request")
TRACE = validator("trace_event")


class AdminTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch("agenthon.pii._load_name_finder", return_value=find_names))
        self.entries = {}
        self.events = {}
        with gr.Blocks(analytics_enabled=False) as self.app:
            build_admin(self.app, self.list_requests, self.list_trace)
        self.session = SessionState(self.app)

    def add_entry(self, case, timestamp, **changes):
        self.entries[case] = {
            "request_id": case,
            "timestamp": timestamp,
            "status": "processing",
            "risk_flag": False,
            "original_prompt": CASES[case]["prompt"],
            "sent_prompt": None,
            "response": None,
            "route": None,
            **changes,
        }
        ADMIN.validate(self.entries[case])

    def list_requests(self):
        return list(self.entries.values())

    def list_trace(self, request_id):
        return self.events.get(request_id, [])

    async def trigger(self, event_name, row=None, filters=("All", "All", "All")):
        dependency = next(
            event for event in self.app.config["dependencies"]
            if any(name == event_name for _, name in event["targets"])
        )
        event_data = None
        if row is not None:
            event_data = gr.EventData(None, {"request_id": row[1]})
        result = await self.app.process_api(
            dependency["id"], [None] * (len(dependency["inputs"]) - 3) + list(filters), state=self.session, event_data=event_data,
        )
        output = result["data"]
        if isinstance(output[2], str):
            table = ElementTree.fromstring(output[2])
            output[2] = {"data": [["".join(td.itertext()) for td in tr] for tr in table.findall("./tbody/tr")]}
        return output

    async def test_empty_then_shows_processing_and_failed_requests_in_time_order(self):
        initial = await self.trigger("load")
        self.assertEqual(initial[3], "No requests yet.")
        self.add_entry("demo-clean", "2026-11-21T12:00:45Z", status="failed")
        self.add_entry("demo-edit", "2026-11-21T07:01:00-05:00")
        updated = await self.trigger("tick")
        rows = updated[2]["data"]
        self.assertEqual([row[1] for row in rows], ["demo-edit", "demo-clean"])
        self.assertEqual(rows[0], ["2026-11-21 12:01:00", "demo-edit", "Processing", "Pending", "—", "Unavailable", "—"])
        selected = await self.trigger("click", rows[1])
        self.assertIn("Failed", selected[5])
        self.assertEqual(selected[6], CASES["demo-clean"]["prompt"])
        self.assertEqual(selected[7:9], ["Unavailable", "Unavailable"])

    async def test_selection_persists_as_risk_and_response_arrive_and_rows_reorder(self):
        case = "demo-local"
        timestamp = "2026-11-21T12:00:00Z"
        self.add_entry(case, timestamp)
        initial = await self.trigger("load")
        clicked_row = initial[2]["data"][0]
        self.add_entry("demo-clean", "2026-11-21T12:01:00Z")
        await self.trigger("tick")
        selected = await self.trigger("click", clicked_row)
        self.assertIn(case, selected[5])
        self.assertNotIn("PII Risk", selected[5])
        self.add_entry(case, timestamp, status="review_required", risk_flag=True)
        flagged = await self.trigger("tick")
        self.assertEqual(flagged[2]["data"][1][4], "Detected")
        self.assertIn("PII Risk", flagged[5])
        self.assertEqual(flagged[8], "Unavailable")

        trace = {
            "timestamp": "2026-11-21T12:02:00Z",
            "request_id": case,
            "agent": "model",
            "input": {"route": "local_simulated"},
            "output": {"status": "completed"},
            "action": "complete",
            "confidence": None,
        }
        TRACE.validate(trace)
        self.events[case] = [trace]
        self.add_entry(
            case, timestamp, status="completed", risk_flag=True, route="local_simulated",
            sent_prompt="Ask the site coordinator to confirm the delivery window.", response="Demo response",
        )
        completed = await self.trigger("tick")
        self.assertEqual(completed[2]["data"][1][2:], [
            "Completed", "Local (simulated with DeepSeek)", "Detected", "Unavailable", "None detected",
        ])
        self.assertIn("PII Risk", completed[5])
        self.assertEqual(completed[6:9], [
            CASES[case]["prompt"], self.entries[case]["sent_prompt"], "Demo response",
        ])
        self.assertEqual(completed[9]["data"][0][1:3], ["model", "complete"])
        unchanged = await self.trigger("tick")
        self.assertEqual(unchanged[2]["__type__"], "update")
        self.assertNotIn("value", unchanged[2])

    async def test_t4_history_and_trace_follow_the_selected_request(self):
        proxy = Proxy(lambda prompt, route: "Demo response", detector=PIIDetector(find_names=find_names))
        _, self.app = build_services(proxy)
        self.session = SessionState(self.app)

        clean = proxy.submit({"prompt": CASES["demo-clean"]["prompt"]})
        original = CASES["demo-local"]["prompt"]
        review = proxy.submit({"prompt": original})
        snapshot = await self.trigger("load")
        pending_row, clean_row = snapshot[2]["data"]
        self.assertEqual(clean_row[1:], [clean["request_id"], "Completed", "DeepSeek", "—", "Unavailable", "None detected"])
        self.assertEqual(pending_row[1:], [review["request_id"], "Review required", "Pending", "Detected", "Unavailable", "—"])
        pending = await self.trigger("click", pending_row)
        self.assertEqual(pending[6:9], [original, "Unavailable", "Unavailable"])

        proxy.decide({
            "request_id": review["request_id"], "revision": review["revision"], "action": "local_simulated",
        })
        completed = await self.trigger("tick")
        self.assertEqual(completed[2]["data"][0][2:], [
            "Completed", "Local (simulated with DeepSeek)", "Detected", "Unavailable", "None detected",
        ])
        self.assertEqual(completed[6:9], [original, review["proposed_prompt"], "Demo response"])
        events = completed[9]["data"]
        self.assertEqual([row[2] for row in events], [e["action"] for e in proxy.trace_events(review["request_id"])])
        self.assertEqual(events[-1][2], "complete")
        outputs = {row[2]: row[4] for row in events}
        self.assertIn("Redacted prompt preserved.", outputs["rephrase"])
        self.assertIn("Suggested actions:", outputs["suggest"])
        filtered = await self.trigger("input", filters=("Detected", "Medium", "Completed"))
        self.assertEqual([row[1] for row in filtered[2]["data"]], [review["request_id"]])
        empty = await self.trigger("input", filters=("Detected", "High", "Completed"))
        self.assertEqual(empty[2]["data"], [])
        self.assertEqual(empty[3], "No requests match these filters.")
        self.assertFalse(empty[4]["visible"])

    async def test_transport_sender_and_prevented_count_survive_an_edit_and_approval(self):
        proxy = Proxy(lambda prompt, route: "Demo response", detector=PIIDetector(find_names=find_names))
        transport, self.app = build_services(proxy)
        self.session = SessionState(self.app)
        owner = {"user": "employee-42", "chat": "chat-1"}
        case = CASES["demo-edit"]
        with TestClient(transport) as client:
            review = client.post("/turn", json={**owner, "prompt": case["prompt"]}).json()
            pending = await self.trigger("load")
            self.assertEqual(pending[2]["data"][0][-2:], ["employee-42", "—"])
            self.assertIn("<strong>≥0</strong>", pending[10])

            token = review["approval"]["token"]
            edit = f"{BUTTONS['edit']} [TDB:{token}]\n{case['edited_prompt']}\n[/TDB edit]"
            edited = client.post("/turn", json={**owner, "prompt": edit}).json()
            approval = edited["approval"]["text"]
            client.post("/turn", json={**owner, "prompt": approval}).raise_for_status()

        completed = await self.trigger("tick")
        row = completed[2]["data"][0]
        self.assertEqual(row[-2:], ["employee-42", "None detected"])
        self.assertIn("<strong>≥2</strong>", completed[10])
        detail = await self.trigger("click", row)
        self.assertIn("employee-42", detail[5])
        self.assertIn("DeepSeek replied.", detail[5])
        filtered = await self.trigger("input", filters=("All", "All", "Failed"))
        self.assertEqual(filtered[2]["data"], [])
        self.assertIn("<strong>≥2</strong>", filtered[10])

    async def test_sent_prompt_shows_values_by_category_and_unconfirmed_delivery(self):
        prompt = "Contact Jordan Miller at ops&legal@example.test."
        self.add_entry("demo-clean", "2026-11-21T12:01:00Z", status="completed",
                       sent_prompt=prompt, route="deepseek", response="Demo response")
        self.add_entry("demo-local", "2026-11-21T12:00:00Z", status="failed",
                       sent_prompt=prompt, route="local_simulated")
        loaded = await self.trigger("load")
        sent, failed = loaded[2]["data"]
        self.assertEqual(sent[-1], "Name, Email")
        self.assertEqual(failed[-1], "Name, Email (unconfirmed)")
        detail = await self.trigger("click", sent)
        self.assertIn("<b>Name</b> · Jordan Miller", detail[5])
        self.assertIn("<b>Email</b> · ops&amp;legal@example.test", detail[5])
        detail = await self.trigger("click", failed)
        self.assertIn("Delivery to DeepSeek unconfirmed.", detail[5])

    async def test_incomplete_audit_displays_available_categories(self):
        self.add_entry("demo-clean", "2026-11-21T12:01:00Z", status="completed",
                       sent_prompt="Contact ops@example.test.", route="deepseek", response="Demo response")
        with patch("agenthon.pii._load_name_finder", side_effect=OSError):
            loaded = await self.trigger("load")
        self.assertEqual(loaded[2]["data"][0][-1], "Email (partial check)")
