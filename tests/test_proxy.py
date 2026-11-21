import io
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from importlib.util import find_spec
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import patch

from agenthon.models import DeepSeekProvider, ModelError
from agenthon.pii import PIIDetector
from agenthon.proxy import Proxy


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "data" / "demo" / "requests.json").read_text())
NAMES = ("Jordan Miller", "Maya Brooks", "Alex Carter")


def find_names(prompt):
    return [
        (index, index + len(name))
        for name in NAMES
        if (index := prompt.find(name)) != -1
    ]


def choice(review, action="approve", **extra):
    return {
        "request_id": review["request_id"],
        "revision": review["revision"],
        "action": action,
        **extra,
    }


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.detector = PIIDetector(find_names=find_names)
        self.proxy = Proxy(self.provider, detector=self.detector)

    def provider(self, prompt, route):
        self.calls.append((prompt, route))
        return "Demo answer."

    def test_demo_fixtures_use_exact_visible_text_and_keep_risk(self):
        self.check_demo_fixtures(self.proxy)

    @unittest.skipUnless(find_spec("en_core_web_sm"), "The local spaCy model is unavailable.")
    def test_demo_fixtures_with_local_name_model(self):
        self.check_demo_fixtures(Proxy(self.provider))

    def check_demo_fixtures(self, proxy):
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.calls.clear()
                first = proxy.submit({"prompt": case["prompt"]})
                observed = [first["status"]]
                entry = proxy.history()[0]
                self.assertEqual(entry["request_id"], first["request_id"])
                self.assertEqual(entry["original_prompt"], case["prompt"])
                self.assertEqual(entry["risk_flag"], case["expected_risk_flag"])
                if first["status"] == "review_required":
                    self.assertFalse(self.calls)
                    self.assertIsNone(entry["sent_prompt"])
                    self.assertIsNone(entry["response"])
                    extra = {"prompt": case["edited_prompt"]} if "edited_prompt" in case else {}
                    last = proxy.decide(choice(first, case["decision"], **extra))
                    observed.append(last["status"])
                else:
                    last = first
                self.assertEqual(observed, case["expected"])

                entry = proxy.history()[0]
                self.assertEqual(entry["risk_flag"], case["expected_risk_flag"])
                self.assertEqual(entry["route"], case.get("route"))
                if last["status"] == "completed":
                    expected = first.get("proposed_prompt", case["prompt"])
                    self.assertEqual(self.calls, [(expected, case["route"])])
                    self.assertEqual(entry["sent_prompt"], expected)
                    self.assertEqual(entry["response"], "Demo answer.")
                else:
                    self.assertEqual(last["revision"], first["revision"] + 1)
                    email_label = next(
                        item["label"] for item in first["entities"] if item["type"] == "email"
                    )
                    self.assertIn(email_label, last["proposed_prompt"])
                    self.assertEqual(self.calls, [])

    def test_edit_rechecks_known_values_and_cannot_reuse_an_old_review(self):
        first = self.proxy.submit({"prompt": CASES[1]["prompt"]})
        second = self.proxy.decide(choice(
            first, "edit", prompt="Draft an email to jordan miller about the report."
        ))
        self.assertEqual(second["status"], "review_required")
        self.assertIn("[NAME_1]", second["proposed_prompt"])
        self.assertNotIn("jordan miller", second["proposed_prompt"].lower())
        self.assertEqual(self.proxy.decide(choice(first))["reason"], "stale_review")
        self.assertEqual(self.calls, [])
        text = "Draft an email to the project lead about the report."
        completed = self.proxy.decide(choice(second, "edit", prompt=text))
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(self.calls, [(text, "deepseek")])
        self.assertTrue(self.proxy.history()[0]["risk_flag"])

    def test_client_cannot_change_review_payload_returned_by_submit(self):
        review = self.proxy.submit({"prompt": CASES[1]["prompt"]})
        expected = review["proposed_prompt"]
        review["proposed_prompt"] = CASES[1]["prompt"]
        review["allowed_actions"].clear()
        result = self.proxy.decide(choice(review))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.calls, [(expected, "deepseek")])
        self.assertEqual(self.proxy.decide(choice(review))["reason"], "stale_review")

    def test_uncertain_detection_offers_edit_only_and_keeps_detected_risk(self):
        def broken_names(prompt):
            raise OSError("model missing")

        proxy = Proxy(self.provider, detector=PIIDetector(find_names=broken_names))
        review = proxy.submit({"prompt": CASES[1]["prompt"]})
        self.assertEqual(review["status"], "review_required")
        self.assertEqual(review["reason"], "uncertain_detection")
        self.assertEqual(review["allowed_actions"], ["edit"])
        self.assertIsNone(review["proposed_prompt"])
        self.assertTrue(proxy.history()[0]["risk_flag"])
        self.assertEqual(proxy.decide(choice(review))["reason"], "stale_review")
        self.assertFalse(self.calls)

    def test_malformed_pii_retries_before_edit_only_review(self):
        class InvalidDetector:
            def detect(self, prompt, previous):
                return {"redacted_prompt": prompt}, {}

        proxy = Proxy(self.provider, detector=InvalidDetector())
        review = proxy.submit({"prompt": CASES[1]["prompt"]})
        self.assertEqual(review["reason"], "invalid_output")
        self.assertEqual(review["allowed_actions"], ["edit"])
        attempts = [event["action"] for event in proxy.trace_events() if event["agent"] == "pii"]
        self.assertEqual(attempts, ["retry", "fail"])
        self.assertFalse(self.calls)

    def test_rephrase_cannot_remove_placeholders_or_reinsert_pii(self):
        for transform in (
            lambda prompt: prompt.replace("[NAME_1]", "the lead"),
            lambda prompt: f"{prompt}\nJordan Miller",
        ):
            with self.subTest(transform=transform):
                def unsafe(data):
                    return {
                        "proposed_prompt": transform(data["prompt"]),
                        "changed": True,
                        "confidence": 1,
                    }

                proxy = Proxy(self.provider, detector=self.detector, rephraser=unsafe)
                result = proxy.submit({"prompt": CASES[1]["prompt"]})
                self.assertEqual(result["reason"], "invalid_output")
                self.assertEqual(result["allowed_actions"], ["edit"])
                self.assertTrue(proxy.history()[0]["risk_flag"])
                attempts = [event["action"] for event in proxy.trace_events()
                            if event["agent"] == "rephrase"]
                self.assertEqual(attempts, ["retry", "fail"])
                self.assertFalse(self.calls)

    def test_missing_staffing_information_is_visible_separately_from_actions(self):
        result = self.proxy.submit({
            "prompt": "Build a work shift schedule for Maya Brooks on Tuesday."
        })
        self.assertEqual(result["status"], "review_required")
        self.assertIn("[NAME_1]", result["proposed_prompt"])
        self.assertTrue(any("action" not in item for item in result["suggestions"]))
        self.assertTrue(any(item.get("action") == "add_context" for item in result["suggestions"]))

    def test_failed_model_calls_retry_only_timeouts_and_invalid_output(self):
        cases = [
            (TimeoutError("detail"), "timeout", 2),
            ("", "invalid_output", 2),
            (ModelError("detail"), "model_error", 1),
        ]
        for output, reason, call_count in cases:
            with self.subTest(reason=reason):
                self.calls.clear()

                def broken_provider(prompt, route):
                    self.calls.append((prompt, route))
                    if isinstance(output, Exception):
                        raise output
                    return output

                proxy = Proxy(broken_provider, detector=self.detector)
                result = proxy.submit({"prompt": CASES[0]["prompt"]})
                self.assertEqual((result["status"], result["reason"]), ("failed", reason))
                self.assertEqual(len(self.calls), call_count)
                self.assertEqual(proxy.history()[0]["status"], "failed")
                self.assertIsNone(proxy.history()[0]["response"])

    def test_transient_timeout_can_recover(self):
        def provider(prompt, route):
            self.calls.append((prompt, route))
            if len(self.calls) == 1:
                raise TimeoutError()
            return "Second attempt succeeded."

        proxy = Proxy(provider, detector=self.detector)
        result = proxy.submit({"prompt": CASES[0]["prompt"]})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.calls), 2)

    def test_admin_can_read_in_flight_requests_and_decisions_are_atomic(self):
        entered = Event()
        release = Event()

        def blocking_provider(prompt, route):
            entered.set()
            if not release.wait(3):
                raise AssertionError("Test provider was not released")
            return self.provider(prompt, route)

        proxy = Proxy(blocking_provider, detector=self.detector)
        review = proxy.submit({"prompt": CASES[1]["prompt"]})
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(proxy.decide, choice(review))
            try:
                self.assertTrue(entered.wait(3))
                entry = proxy.history()[0]
                self.assertEqual(entry["status"], "processing")
                self.assertIsNone(entry["response"])
                self.assertTrue(entry["risk_flag"])
                self.assertEqual(proxy.decide(choice(review))["reason"], "stale_review")
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=3)["status"], "completed")
        self.assertEqual(len(self.calls), 1)

    def test_trace_jsonl_contains_metadata_and_no_raw_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            proxy = Proxy(self.provider, detector=self.detector, trace_path=path)
            review = proxy.submit({"prompt": CASES[1]["prompt"]})
            proxy.decide(choice(review))
            raw = path.read_text()
            events = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual(events, proxy.trace_events(review["request_id"]))
        self.assertEqual({event["agent"] for event in events},
                         {"proxy", "pii", "rephrase", "suggestion", "model"})
        for value in ("Jordan Miller", "jordan.miller@example.test", "Demo answer."):
            self.assertNotIn(value, raw)

    def test_trace_file_failure_preserves_history_and_in_memory_events(self):
        with tempfile.TemporaryDirectory() as directory:
            proxy = Proxy(self.provider, detector=self.detector, trace_path=directory)
            with self.assertLogs("agenthon.trace", level="WARNING"):
                result = proxy.submit({"prompt": CASES[0]["prompt"]})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(proxy.history()[0]["status"], "completed")
        self.assertEqual(proxy.trace_events()[-1]["action"], "complete")

    def test_invalid_inputs_return_validation_error_without_echoing_values(self):
        with self.assertRaisesRegex(ValueError, r"^Invalid structured data\.$"):
            self.proxy.submit({"prompt": "private@example.test", "extra": True})
        self.assertEqual(self.proxy.history(), [])

    def test_unknown_request_id_is_excluded_from_trace(self):
        client_id = "private@example.test"
        result = self.proxy.decide({"request_id": client_id, "revision": 1, "action": "approve"})
        self.assertEqual(result["reason"], "stale_review")
        self.assertNotIn(client_id, json.dumps(self.proxy.trace_events()))

    def test_non_json_confidence_forces_edit_only_review(self):
        def invalid_rephrase(data):
            return {"proposed_prompt": data["prompt"], "changed": False, "confidence": float("nan")}

        proxy = Proxy(self.provider, detector=self.detector, rephraser=invalid_rephrase)
        result = proxy.submit({"prompt": CASES[1]["prompt"]})
        self.assertEqual(result["reason"], "invalid_output")
        self.assertEqual(result["allowed_actions"], ["edit"])
        self.assertFalse(self.calls)


class DeepSeekTests(unittest.TestCase):
    def test_requests_english_and_keeps_the_user_message_exact(self):
        class FakeResponse(io.BytesIO):
            pass

        def send(request, *, timeout):
            self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
            self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
            self.assertEqual(timeout, 3)
            payload = json.loads(request.data)
            self.assertEqual(payload["model"], "test-model")
            self.assertEqual(payload["messages"], [
                {"role": "system", "content": "Respond in English."},
                {"role": "user", "content": "  Draft a message for [NAME_1].\n"},
            ])
            return FakeResponse(b'{"choices":[{"message":{"content":"Hello."}}]}')

        provider = DeepSeekProvider(api_key="test-key", model="test-model", timeout=3)
        with patch("agenthon.models.urlopen", side_effect=send) as transport:
            for route in ("deepseek", "local_simulated"):
                self.assertEqual(provider("  Draft a message for [NAME_1].\n", route), "Hello.")
            self.assertEqual(transport.call_count, 2)

    def test_missing_api_key_fails_before_network_access(self):
        with patch("agenthon.models.urlopen") as transport:
            with self.assertRaises(ModelError):
                DeepSeekProvider(api_key="")("Clean prompt", "deepseek")
        transport.assert_not_called()

    @unittest.skipUnless(os.environ.get("TDB_TEST_DEEPSEEK") == "1", "Live DeepSeek test is opt-in.")
    def test_live_demo_with_synthetic_prompts(self):
        self.assertTrue(os.environ.get("DEEPSEEK_API_KEY"), "Set DEEPSEEK_API_KEY.")
        proxy = Proxy()
        for case in CASES:
            with self.subTest(case=case["id"]):
                first = proxy.submit({"prompt": case["prompt"]})
                self.assertEqual(first["status"], case["expected"][0], first.get("reason"))
                result = first
                if "decision" in case:
                    extra = {"prompt": case["edited_prompt"]} if "edited_prompt" in case else {}
                    result = proxy.decide(choice(first, case["decision"], **extra))
                self.assertEqual(result["status"], case["expected"][-1], result.get("reason"))
                entry = proxy.history()[0]
                self.assertEqual(entry["route"], case.get("route"))
                self.assertEqual(entry["risk_flag"], case["expected_risk_flag"])


if __name__ == "__main__":
    unittest.main()
