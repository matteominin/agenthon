import json
import unittest

import gradio as gr
from gradio.state_holder import SessionState

from agenthon.pii import PIIDetector
from agenthon.proxy import Proxy
from agenthon.ui.chat import build_chat
from test_contracts import ROOT, validator


CASES = {case["id"]: case for case in json.loads((ROOT / "data/demo/requests.json").read_text())}
PROXY = validator("proxy")


class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.decisions = []
        self.revision = 1
        self.result_override = None
        self.request_id = "demo-redacted"
        self.proposal = "Draft a note to [NAME_1] without using [EMAIL_1]."
        with gr.Blocks(analytics_enabled=False) as self.app:
            build_chat(
                self.submit_request,
                self.submit_decision,
            )
        self.session = SessionState(self.app)

    def review(self, *, proposal):
        return {
            "request_id": self.request_id,
            "status": "review_required",
            "revision": self.revision,
            "reason": "pii_found" if proposal else "uncertain_detection",
            "proposed_prompt": proposal,
            "entities": [
                {"label": "[NAME_1]", "type": "name"},
                {"label": "[EMAIL_1]", "type": "email"},
            ] if proposal else [],
            "suggestions": [
                {"label": "[NAME_1]", "severity": "low", "action": "generalize", "message": "Use their role."},
                {"label": "[EMAIL_1]", "severity": "high", "message": "The recipient address was removed."},
                {"message": "The delivery date is missing <unknown>."},
            ] if proposal else [],
            "allowed_actions": ["approve", "edit", "local_simulated"] if proposal else ["edit"],
        }

    def completed(self, route):
        return {"request_id": self.request_id, "status": "completed", "route": route, "answer": "Demo answer"}

    def submit_request(self, payload):
        PROXY.validate(payload)
        self.requests.append(payload)
        self.request_id = next(case["id"] for case in CASES.values() if case["prompt"] == payload["prompt"])
        result = self.completed("deepseek") if self.request_id == "demo-clean" else self.review(proposal=self.proposal)
        PROXY.validate(result)
        return result

    def submit_decision(self, payload):
        PROXY.validate(payload)
        self.decisions.append(payload)
        if self.result_override == "timeout":
            raise TimeoutError
        if self.result_override is not None:
            result = self.result_override
        elif payload["action"] == "edit":
            self.revision += 1
            result = self.review(proposal="Ask for a rollout update without using [EMAIL_1].")
        else:
            route = "local_simulated" if payload["action"] == "local_simulated" else "deepseek"
            result = self.completed(route)
        PROXY.validate(result)
        return result

    async def click(self, label, *inputs):
        button_id = next(
            component["id"] for component in self.app.config["components"]
            if component["type"] == "button" and component["props"]["value"] == label
        )
        event = next(
            event for event in self.app.config["dependencies"] if (button_id, "click") in event["targets"]
        )
        result = await self.app.process_api(event["id"], list(inputs), state=self.session)
        data = result["data"]
        if hasattr(data[1], "root"):
            data[1] = data[1].root
        return data

    async def send(self, case):
        return await self.click("Send", CASES[case]["prompt"], None)

    async def test_clean_prompt_shows_answer_and_keeps_composer_available(self):
        result = await self.send("demo-clean")
        self.assertEqual(result[2][-1]["content"][0]["text"], "Demo answer")
        self.assertTrue(result[3]["visible"])
        self.assertFalse(result[6]["visible"])

    async def test_review_shows_preview_severity_notices_and_actions_then_approves(self):
        result = await self.send("demo-redacted")
        self.assertEqual(result[8]["value"], self.proposal)
        self.assertIn("Low severity", result[9])
        self.assertIn("High severity", result[9])
        self.assertIn("Missing information", result[9])
        self.assertIn("&lt;unknown&gt;", result[9])
        self.assertIn("Use a more general detail", result[9])
        self.assertTrue(all(result[index]["visible"] for index in (10, 11, 12)))
        final = await self.click("Send redacted version", None, result[1])
        self.assertEqual(self.decisions, [{"request_id": "demo-redacted", "revision": 1, "action": "approve"}])
        self.assertFalse(final[6]["visible"])
        self.assertEqual(final[2][-1]["content"][0]["text"], "Demo answer")

    async def test_edit_sends_exact_text_and_stale_click_cannot_approve_new_revision(self):
        review = await self.send("demo-edit")
        opened = await self.click("Edit", None, review[1])
        self.assertTrue(opened[8]["interactive"])
        self.assertFalse(opened[10]["visible"])
        self.assertFalse(opened[12]["visible"])
        draft = " " + CASES["demo-edit"]["edited_prompt"] + "\n"
        revised = await self.click("Check and send edited prompt", None, review[1], draft)
        self.assertEqual(self.decisions, [{
            "request_id": "demo-edit", "revision": 1, "action": "edit", "prompt": draft,
        }])
        self.assertEqual(revised[1]["revision"], 2)
        self.assertTrue(revised[6]["visible"])
        await self.click("Send redacted version", None, review[1])
        self.assertEqual(len(self.decisions), 1)
        await self.click("Send redacted version", None, revised[1])
        self.assertEqual(self.decisions[-1]["revision"], 2)

    async def test_local_route_uses_displayed_revision(self):
        review = await self.send("demo-local")
        final = await self.click("Use local model (simulated with DeepSeek)", None, review[1])
        self.assertEqual(self.decisions, [{
            "request_id": "demo-local", "revision": 1, "action": "local_simulated",
        }])
        self.assertEqual(final[2][-1]["content"][0]["text"], "Demo answer")

    async def test_unverified_prompt_offers_only_edit_and_preserves_draft_on_timeout(self):
        self.proposal = None
        review = await self.send("demo-redacted")
        self.assertTrue(review[8]["interactive"])
        self.assertTrue(review[13]["visible"])
        self.assertFalse(any(review[index]["visible"] for index in (10, 11, 12, 14)))
        self.assertNotIn("Suggested actions", review[9])
        await self.click("Send redacted version", None, review[1])
        self.assertEqual(self.decisions, [])
        self.result_override = "timeout"
        result = await self.click("Check and send edited prompt", None, review[1], "A draft")
        self.assertIn("timed out", result[5]["value"])
        self.assertEqual(result[8]["value"], "A draft")

    async def test_t4_proxy_notices_and_actions_render_and_approve(self):
        provider_calls = []

        def provider(prompt, route):
            provider_calls.append((prompt, route))
            return "Demo answer"

        proxy = Proxy(provider, detector=PIIDetector(find_names=lambda _: []))
        with gr.Blocks(analytics_enabled=False) as self.app:
            build_chat(proxy.submit, proxy.decide)
        self.session = SessionState(self.app)

        review = await self.send("demo-redacted")
        self.assertIn("Missing information", review[9])
        self.assertIn("[EMAIL_1]", review[8]["value"])
        self.assertEqual(provider_calls, [])
        final = await self.click("Send redacted version", None, review[1])
        self.assertEqual(provider_calls, [(review[8]["value"], "deepseek")])
        self.assertEqual(final[2][-1]["content"][0]["text"], "Demo answer")
        self.assertTrue(proxy.history()[0]["risk_flag"])

    async def test_proxy_failure_is_visible_in_chat_view(self):
        review = await self.send("demo-redacted")
        self.result_override = {"request_id": "demo-redacted", "status": "failed", "reason": "model_error"}
        result = await self.click("Send redacted version", None, review[1])
        self.assertIn("Request failed", result[5]["value"])
        self.assertFalse(result[6]["visible"])
        self.assertTrue(result[3]["visible"])
