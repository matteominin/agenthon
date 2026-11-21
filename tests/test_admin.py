import json
import unittest

import gradio as gr
from gradio.state_holder import SessionState

from agenthon.ui.admin import build_admin
from test_contracts import ROOT, validator


CASES = {case["id"]: case for case in json.loads((ROOT / "data/demo/requests.json").read_text())}
ADMIN = validator("admin_request")
TRACE = validator("trace_event")


class AdminTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
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

    async def trigger(self, event_name, row=None):
        dependency = next(
            event for event in self.app.config["dependencies"]
            if any(name == event_name for _, name in event["targets"])
        )
        event_data = None
        if row is not None:
            event_data = gr.EventData(None, {"index": [0, 0], "value": row[0], "row_value": row})
        result = await self.app.process_api(
            dependency["id"], [None] * len(dependency["inputs"]), state=self.session, event_data=event_data,
        )
        return result["data"]

    async def test_empty_then_shows_processing_and_failed_requests_in_time_order(self):
        initial = await self.trigger("load")
        self.assertEqual(initial[3], "No requests yet.")
        self.add_entry("demo-clean", "2026-11-21T12:00:45Z", status="failed")
        self.add_entry("demo-edit", "2026-11-21T07:01:00-05:00")
        updated = await self.trigger("tick")
        rows = updated[2]["data"]
        self.assertEqual([row[1] for row in rows], ["demo-edit", "demo-clean"])
        self.assertEqual(rows[0], ["2026-11-21 12:01:00", "demo-edit", "Processing", "Pending", "—"])
        selected = await self.trigger("select", rows[1])
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
        selected = await self.trigger("select", clicked_row)
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
        self.assertEqual(completed[2]["data"][1][2:], ["Completed", "Local (simulated with DeepSeek)", "Detected"])
        self.assertIn("PII Risk", completed[5])
        self.assertEqual(completed[6:9], [
            CASES[case]["prompt"], self.entries[case]["sent_prompt"], "Demo response",
        ])
        self.assertEqual(completed[9].root, [trace])
        unchanged = await self.trigger("tick")
        self.assertEqual(unchanged[2], {"__type__": "update"})
