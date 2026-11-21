import json
import re
import unittest
from unittest.mock import patch

from agenthon.pii import PIIDetector
from agenthon.proxy import Proxy
from agenthon.ui.chat import BUTTONS, Chat, _restore_answer, review_card
from agenthon.ui.openwebui_pipe import Pipe
from test_contracts import ROOT
from test_proxy import find_names


CASES = json.loads((ROOT / "data/demo/requests.json").read_text())
OWNER = ("employee", "chat-1")


def tagged_choice(action, token, draft=None):
    text = BUTTONS[action] if draft is None else f"{BUTTONS[action]}\n\n{draft}"
    return text + "\U000e0001" + "".join(chr(0xE0000 + ord(char)) for char in token) + "\U000e007f"


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
                    self.assertNotIn("Missing information", result["embed"])
                    token = re.search(r'data-reference="([A-Za-z0-9_-]{16})"', result["embed"])[1]
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

    def test_new_email_in_edited_prompt_requires_a_new_review(self):
        self.chat.turn(OWNER, CASES[2]["prompt"])
        token, = self.chat.pending
        new_email = "rollout.lead@example.test"
        draft = f"Draft a rollout reminder for [EMAIL_1] and {new_email}."
        choice = f"{BUTTONS['edit']} [TDB:{token}]\n{draft}\n[/TDB edit]"

        result = self.chat.turn(OWNER, choice)
        self.assertIn("detected in the edited prompt", result["message"])
        self.assertIn("[EMAIL_2]", result["embed"])
        self.assertEqual(self.sent, [])
        self.assertIsNone(self.proxy.history()[0]["sent_prompt"])
        self.assertIn("out of date", self.chat.turn(OWNER, f"{BUTTONS['approve']} [TDB:{token}]")["message"])

        new_token, = self.chat.pending
        self.assertEqual(
            self.chat.turn(OWNER, f"{BUTTONS['approve']} [TDB:{new_token}]"),
            {"message": "Demo response"},
        )
        sent, route = self.sent[0]
        self.assertEqual(route, "deepseek")
        self.assertIn("[EMAIL_2]", sent)
        self.assertNotIn(new_email, sent)

    def test_chat_restores_only_placeholders_kept_in_the_edited_prompt(self):
        phone = "+1-202-555-0142"
        email = "jordan.miller@example.test"
        answer = "To: [PHONE_1]\nConfirm delivery at 14:30. [EMAIL_1] [NAME]"

        def provider(prompt, route):
            self.sent.append((prompt, route))
            return answer

        proxy = Proxy(provider, detector=PIIDetector(find_names=find_names))
        chat = Chat(proxy)
        chat.turn(OWNER, f"Draft a text to {phone} and an email to {email} asking to confirm delivery at 14:30.")
        token, = chat.pending
        draft = "Draft a text to [PHONE_1] asking to confirm delivery at 14:30."
        command = tagged_choice("edit", token, draft)
        self.assertIn("out of date", chat.turn(("other", OWNER[1]), command)["message"])
        result = chat.turn(OWNER, command)

        self.assertIn(f"To: {phone}", result["message"])
        self.assertIn("[EMAIL_1] [NAME]", result["message"])
        self.assertNotIn(email, result["message"])
        self.assertEqual(self.sent, [(draft, "deepseek")])
        self.assertEqual(proxy.history()[0]["response"], answer)
        self.assertNotIn(phone, json.dumps(proxy.trace_events()))
        self.assertIn("out of date", chat.turn(OWNER, command)["message"])

    def test_approval_restores_values_from_the_previous_and_current_revision(self):
        phone = "+1-202-555-0142"
        email = "jordan.miller@example.test"
        proxy = Proxy(lambda prompt, route: "To [PHONE_1] and [EMAIL_1]",
                      detector=PIIDetector(find_names=find_names))
        chat = Chat(proxy)
        chat.turn(OWNER, f"Draft a text to {phone}.")
        token, = chat.pending
        approval = tagged_choice("edit", token, f"Draft a text to [PHONE_1] and an email to {email}.")
        updated = chat.turn(OWNER, approval)
        self.assertIn("detected in the edited prompt", updated["message"])
        new_token, = chat.pending
        answer = chat.turn(OWNER, tagged_choice("approve", new_token))["message"]

        self.assertIn(f"To {phone} and {email}", answer)
        self.assertEqual(proxy.history()[0]["sent_prompt"], "Draft a text to [PHONE_1] and an email to [EMAIL_1].")

    def test_restoration_preserves_markdown_and_leaves_link_destinations_anonymized(self):
        label = "[CONTRACT_ID_1]"
        answer = (
            f"**Convert** `{label}.jpg` to PDF.\n\n"
            f"- Output: `{label}.pdf`\n"
            f"- ![preview](https://example.test/{label}.jpg)\n"
            f"- [Archive](?id={label})\n"
            f'<img src="/?id={label}">'
        )
        restored = _restore_answer(answer, f"Convert {label}.", {label: "CT_837xy"})
        self.assertEqual(
            restored,
            answer.replace(f"`{label}.jpg`", "`CT_837xy.jpg`").replace(f"`{label}.pdf`", "`CT_837xy.pdf`"),
        )

    def test_contract_id_is_reviewed_and_restored_in_the_filename(self):
        contract_id = "837xy2789c2c2kl"
        prompt = f'Convert my contract with id "{contract_id}" from {contract_id}.jpg to PDF.'
        answer = (
            "Name the output exactly `[CONTRACT_ID_1].pdf`.\n\n"
            "**Convert the file:**\n\n"
            "```sh\nmagick [CONTRACT_ID_1].jpg [CONTRACT_ID_1].pdf\n```"
        )

        def provider(text, route):
            self.sent.append((text, route))
            return answer

        proxy = Proxy(provider, detector=PIIDetector(find_names=find_names))
        chat = Chat(proxy)
        card = chat.turn(OWNER, prompt)["embed"]
        self.assertIn("Contract ID", card)
        self.assertIn('data-label="[CONTRACT_ID_1]">', card)
        self.assertFalse(self.sent)

        token, = chat.pending
        response = chat.turn(OWNER, tagged_choice("approve", token))["message"]
        self.assertIn(f"magick {contract_id}.jpg {contract_id}.pdf", response)
        self.assertTrue(response.startswith("**Convert the file:**"))
        self.assertNotIn("Name the output", response)
        self.assertEqual(self.sent, [(
            'Convert my contract with id "[CONTRACT_ID_1]" from [CONTRACT_ID_1].jpg to PDF.',
            "deepseek",
        )])
        request = proxy.history()[0]
        self.assertTrue(request["risk_flag"])
        self.assertEqual(request["response"], answer)
        self.assertNotIn(contract_id, json.dumps(proxy.trace_events(request["request_id"])))

    def test_review_lists_originals_and_renders_safe_markdown(self):
        result = self.chat.turn(OWNER, "Draft a **reminder** for Jordan Miller at jordan.miller@example.test.")
        card = result["embed"]
        self.assertIn(
            "<p>Draft a <strong>reminder</strong> for [NAME_1] at [EMAIL_1].</p>", card
        )
        self.assertIn('data-label="[EMAIL_1]">jordan.miller@example.test</span>', card)
        self.assertIn('data-label="[NAME_1]">Jordan Miller</span>', card)
        token = next(iter(self.chat.pending))
        ref = self.chat.pending[token][1]
        self.assertEqual(self.proxy.review_originals(ref["request_id"], 99), {})
        self.chat.turn(OWNER, f"{BUTTONS['approve']} [TDB:{token}]")
        self.assertEqual(self.proxy.review_originals(**ref), {})
        sent, route = self.sent[0]
        self.assertEqual(route, "deepseek")
        self.assertIn("**reminder**", sent)
        self.assertNotIn("Jordan Miller", sent)
        self.assertNotIn("jordan.miller@example.test", sent)

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
        token = re.search(r'data-reference="([A-Za-z0-9_-]{16})"', review["embed"])[1]
        self.assertIn("out of date", chat.turn(OWNER, f"{BUTTONS['approve']} [TDB:{token}]")["message"])
        draft = "  Ask for a delivery estimate.\n"
        result = chat.turn(OWNER, tagged_choice("edit", token, draft))
        proxy.decide.assert_called_once_with({
            "request_id": "demo-edit", "revision": 4, "action": "edit", "prompt": draft,
        })
        self.assertEqual(result["message"], "Request failed. The request timed out.")

    def test_unverified_review_only_offers_edit_and_hides_notices(self):
        html = review_card({"proposed_prompt": None, "allowed_actions": ["edit"],
            "reason": "uncertain_detection", "entities": [{"label": "[SSN_1]", "type": "tax_id"}],
            "suggestions": [{"message": "<notice>"}]}, "abcdefghijklmnop")
        self.assertIn("High severity", html)
        self.assertNotIn("&lt;notice&gt;", html)
        self.assertNotIn('data-choice="approve"', html)
        self.assertNotIn('data-choice="local_simulated"', html)
        self.assertNotIn("Suggested actions", html)

    def test_review_displays_suggested_actions_when_available(self):
        html = review_card({
            "proposed_prompt": "Plan the shift for [NAME_1].",
            "allowed_actions": ["approve", "edit"],
            "reason": "pii_found",
            "entities": [],
            "suggestions": [
                {"message": "Shift details are missing."},
                {"message": "Add <availability>.", "action": "edit"},
            ],
        }, "abcdefghijklmnop")
        self.assertIn("<summary>Suggested actions</summary>", html)
        self.assertIn("Add &lt;availability&gt;.", html)
        self.assertNotIn("Shift details are missing.", html)


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
