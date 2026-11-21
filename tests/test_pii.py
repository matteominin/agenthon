from importlib.util import find_spec
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from agenthon.pii import PIIDetector


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "data/demo/requests.json").read_text())


def find_demo_names(prompt):
    return (
        match.span()
        for match in re.finditer(r"\b(?:Jordan Miller|Maya Brooks|Alex Carter)\b", prompt)
    )


class PIITests(unittest.TestCase):
    def setUp(self):
        self.detector = PIIDetector(find_demo_names)

    def check_demo(self, detector, validate=None):
        for case in CASES:
            with self.subTest(case=case["id"]):
                prompt = case["prompt"]
                payload, private = detector.detect(prompt)
                if validate is not None:
                    validate(payload)
                if case["expected_risk_flag"]:
                    self.assertEqual(payload["status"], "detected")
                    kinds = {entity["type"] for entity in payload["entities"]}
                    contact_type = "phone" if case["id"] == "demo-local" else "email"
                    self.assertEqual(kinds, {"name", contact_type})
                    for label, value in private.items():
                        self.assertIn(label, payload["redacted_prompt"])
                        self.assertNotIn(value, payload["redacted_prompt"])
                else:
                    self.assertEqual(payload["status"], "clear")
                    self.assertEqual(payload["redacted_prompt"], prompt)
                    self.assertEqual(private, {})

    def test_demo_cases(self):
        self.check_demo(self.detector)

    def test_demo_cases_with_local_model_and_schema(self):
        if find_spec("en_core_web_sm") is None or find_spec("jsonschema") is None:
            self.skipTest("The local spaCy model and jsonschema are needed for this integration test.")
        from test_contracts import validator

        self.check_demo(PIIDetector(), validator("agents").validate)

    def test_common_formats_and_surrounding_punctuation(self):
        payload, private = self.detector.detect(
            "Email <Maya+work@team.example.test>. Call (202) 555-0142 ext. 21. "
            "Compare 123-45-6789 with SSN: 321765432."
        )
        self.assertEqual(
            payload["redacted_prompt"],
            "Email <[EMAIL_1]>. Call [PHONE_1]. Compare [SSN_1] with SSN: [SSN_2].",
        )
        self.assertEqual(private, {
            "[EMAIL_1]": "Maya+work@team.example.test",
            "[PHONE_1]": "(202) 555-0142 ext. 21",
            "[SSN_1]": "123-45-6789",
            "[SSN_2]": "321765432",
        })

    @unittest.skipUnless(find_spec("en_core_web_sm"), "The local spaCy model is unavailable.")
    def test_italian_conditional_preserves_text_and_still_detects_real_names(self):
        detector = PIIDetector()
        for quantity in ("due", "2"):
            with self.subTest(quantity=quantity):
                prompt = f"Se ho {quantity} biscotti, e un tipo ne mangia uno, quanti biscotti mi rimangono?"
                payload, private = detector.detect(prompt)
                self.assertEqual(payload["status"], "clear")
                self.assertEqual(payload["redacted_prompt"], prompt)
                self.assertEqual(private, {})

        prompt = "Se ho due biscotti per Maya Brooks, quanti me ne rimangono? Contattala a maya@example.test."
        payload, private = detector.detect(prompt)
        self.assertEqual(
            payload["redacted_prompt"],
            "Se ho due biscotti per [NAME_1], quanti me ne rimangono? Contattala a [EMAIL_1].",
        )
        self.assertEqual(private, {"[NAME_1]": "Maya Brooks", "[EMAIL_1]": "maya@example.test"})
        _, private = detector.detect("Se Ho emailed the team.")
        self.assertEqual(private, {"[NAME_1]": "Se Ho"})

    def test_dates_product_codes_and_literal_labels_stay_intact(self):
        prompt = "Ask the site coordinator by Friday at 16:30 on 2026-11-21 about SKU2025550142 and [SSN_1]."
        payload, private = self.detector.detect(prompt)
        self.assertEqual(payload["status"], "clear")
        self.assertEqual(payload["redacted_prompt"], prompt)
        self.assertEqual(private, {})

    def test_contract_identifiers_need_context_and_keep_their_label_on_edit(self):
        payload, private = self.detector.detect("Convert report837xy.jpg and keep the filename.")
        self.assertEqual(payload["status"], "clear")
        self.assertEqual(private, {})

        payload, private = self.detector.detect("Convert the file for contract ID: CT-837xy.")
        self.assertEqual(payload["entities"], [{"label": "[CONTRACT_ID_1]", "type": "contract_id"}])
        self.assertEqual(private, {"[CONTRACT_ID_1]": "CT-837xy"})
        revised, _ = self.detector.detect("Use CT-837xy.pdf.", private)
        self.assertEqual(revised["redacted_prompt"], "Use [CONTRACT_ID_1].pdf.")

    def test_repeated_values_and_values_from_prior_review_keep_their_labels(self):
        initial, previous = self.detector.detect(
            "Jordan Miller asked Jordan Miller to email jordan@example.test."
        )
        self.assertEqual(initial["redacted_prompt"], "[NAME_1] asked [NAME_1] to email [EMAIL_1].")
        edited, private = self.detector.detect(
            "Try new@example.test, jordan@example.test, or jordan miller.", previous
        )
        self.assertEqual(edited["redacted_prompt"], "Try [EMAIL_2], [EMAIL_1], or [NAME_1].")
        self.assertEqual(private["[EMAIL_1]"], "jordan@example.test")
        self.assertEqual(private["[NAME_1]"], "jordan miller")

    def test_literal_labels_and_removed_history_do_not_get_reassigned(self):
        payload, private = self.detector.detect(
            "Literal [EMAIL_1], old@example.test and new@example.test.",
            {"[EMAIL_1]": "old@example.test", "[EMAIL_2]": "gone@example.test"},
        )
        self.assertEqual(payload["redacted_prompt"], "Literal [EMAIL_1], [EMAIL_3] and [EMAIL_4].")
        self.assertEqual(private, {"[EMAIL_3]": "old@example.test", "[EMAIL_4]": "new@example.test"})

    def test_demo_edit_preserves_retained_label_and_reuses_email_label(self):
        case = next(item for item in CASES if item["id"] == "demo-edit")
        _, previous = self.detector.detect(case["prompt"])
        payload, private = self.detector.detect(case["edited_prompt"] + " Keep [NAME_1].", previous)
        self.assertEqual(payload["status"], "detected")
        self.assertTrue(payload["redacted_prompt"].endswith("Send it to [EMAIL_1]. Keep [NAME_1]."))
        self.assertEqual(payload["entities"], [{"label": "[EMAIL_1]", "type": "email"}])
        self.assertEqual(private, {"[EMAIL_1]": previous["[EMAIL_1]"]})

    def test_missing_local_model_is_uncertain_even_with_regex_findings(self):
        with patch("agenthon.pii._load_name_finder", side_effect=OSError):
            payload, private = PIIDetector().detect("Email user@example.test.")
        self.assertEqual(payload["status"], "uncertain")
        self.assertEqual(payload["confidence"], 0)
        self.assertEqual(payload["redacted_prompt"], "Email [EMAIL_1].")
        self.assertEqual(private, {"[EMAIL_1]": "user@example.test"})

    def test_local_inference_failure_is_uncertain_and_timeout_can_be_retried(self):
        def unavailable(prompt):
            raise OSError("Name model unavailable")

        def timeout(prompt):
            raise TimeoutError

        payload, private = PIIDetector(unavailable).detect("Email user@example.test.")
        self.assertEqual(payload["status"], "uncertain")
        self.assertEqual(private, {"[EMAIL_1]": "user@example.test"})
        with self.assertRaises(TimeoutError):
            PIIDetector(timeout).detect("Write an email.")
