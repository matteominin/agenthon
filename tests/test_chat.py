import json
import re
import unittest
from unittest.mock import patch

from agenthon.pii import PIIDetector
from agenthon.proxy import Proxy
from agenthon.ui.chat import BUTTONS, Chat, review_card
from agenthon.ui.openwebui_pipe import Pipe
from test_contracts import ROOT
from test_proxy import find_names


CASES = json.loads((ROOT / "data/demo/requests.json").read_text())
OWNER = ("employee", "chat-1")


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        def provider(prompt, route):
            self.sent.append((prompt, route))
            return "Demo response"
        self.proxy = Proxy(provider, detector=PIIDetector(find_names=find_names))
        self.chat = Chat(self.proxy)

    def test_all_demo_cases_and_stale_or_foreign_decisions(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.sent.clear()
                result = self.chat.turn(OWNER, case["prompt"])
                if "decision" in case:
                    self.assertEqual(self.sent, [])
                    self.assertIn("Missing information", result["embed"])
                    token = re.search(r'\[TDB:([A-Za-z0-9_-]{16})\]', result["embed"])[1]
                    action = case["decision"]
                    choice = f"{BUTTONS[action]} [TDB:{token}]"
                    if action == "edit":
                        choice += "\n" + case["edited_prompt"] + "\n[/TDB edit]"
                    for foreign in [("other", OWNER[1]), (OWNER[0], "other")]:
                        self.assertIn("out of date", self.chat.turn(foreign, choice)["message"])
                    result = self.chat.turn(OWNER, choice)
                    self.assertIn("out of date", self.chat.turn(OWNER, choice)["message"])
                entry = self.proxy.history()[0]
                self.assertEqual(entry["risk_flag"], case["expected_risk_flag"])
                if case["expected"][-1] == "completed":
                    self.assertEqual(result, {"message": "Demo response"})
                    self.assertEqual(self.sent, [(entry["sent_prompt"], case["route"])])
                else:
                    self.assertEqual(self.sent, [])
                    self.assertIn("[EMAIL_1]", result["embed"])

    def test_edit_submits_exact_draft_and_disabled_approval_is_rejected(self):
        from unittest.mock import Mock

        proxy = Mock()
        proxy.submit.return_value = {
            "status": "review_required", "reason": "uncertain_detection", "request_id": "demo-edit",
            "revision": 4, "allowed_actions": ["edit"], "proposed_prompt": None, "entities": [],
            "suggestions": [],
        }
        proxy.decide.return_value = {"status": "failed", "reason": "timeout"}
        chat = Chat(proxy)
        review = chat.turn(OWNER, "Draft a reminder.")
        token = re.search(r"\[TDB:([A-Za-z0-9_-]{16})\]", review["embed"])[1]
        self.assertIn("out of date", chat.turn(OWNER, f"{BUTTONS['approve']} [TDB:{token}]")["message"])
        draft = "  Ask for a delivery estimate.\n"
        result = chat.turn(OWNER, f"{BUTTONS['edit']} [TDB:{token}]\n{draft}\n[/TDB edit]")
        proxy.decide.assert_called_once_with({
            "request_id": "demo-edit", "revision": 4, "action": "edit", "prompt": draft,
        })
        self.assertEqual(result["message"], "Request failed. The request timed out.")

    def test_unverified_review_only_offers_edit_and_escapes_notices(self):
        html = review_card({"proposed_prompt": None, "allowed_actions": ["edit"],
            "reason": "uncertain_detection", "entities": [{"label": "[SSN_1]", "type": "tax_id"}],
            "suggestions": [{"message": "<notice>"}]}, "abcdefghijklmnop")
        self.assertIn("High severity", html)
        self.assertIn("&lt;notice&gt;", html)
        self.assertNotIn('data-choice="approve"', html)
        self.assertNotIn('data-choice="local_simulated"', html)
        self.assertNotIn("Suggested actions", html)


class PipeTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipe_emits_inline_review_and_skips_background_tasks(self):
        body = {"messages": [{"role": "user", "content": "Draft an email."}]}
        events = []
        async def emit(event):
            events.append(event)
        with patch("agenthon.ui.openwebui_pipe.urlopen") as network:
            network.return_value.__enter__.return_value.read.return_value = json.dumps(
                {"message": "Review required.", "embed": "<article>Review</article>"}
            ).encode()
            pipe = Pipe()
            self.assertEqual(await pipe.pipe(body, {"id": "u"}, {"chat_id": "c"}, emit, "title_generation"), "")
            network.assert_not_called()
            self.assertEqual(await pipe.pipe(body, {"id": "u"}, {"chat_id": "c"}, emit), "Review required.")
            self.assertEqual(json.loads(network.call_args.args[0].data)["prompt"], "Draft an email.")
            self.assertEqual(events, [{"type": "embeds", "data": {"embeds": ["<article>Review</article>"]}}])
