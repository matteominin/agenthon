import unittest

from agenthon.rephrase import rephrase
from agenthon.suggestion import suggest


class SuggestionTests(unittest.TestCase):
    def test_delivery_detail_is_an_advisory_only(self):
        entities = [{"type": "email", "label": "[EMAIL_1]"}]
        rephrased = rephrase({
            "prompt": "Draft a report reminder to [EMAIL_1].",
            "entities": entities,
        })
        items = suggest(rephrased, entities)["items"]

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["label"], "[EMAIL_1]")
        self.assertIn("exact address is unavailable", items[0]["message"])
        self.assertNotIn("action", items[0])

    def test_privacy_severity_and_context_utility_are_independent(self):
        entities = [{"type": "tax_id", "label": "[SSN_1]"}]
        rephrased = rephrase({
            "prompt": "Build a staffing roster for the crew. Payroll identifier [SSN_1] is on file.",
            "entities": entities,
        })
        items = suggest(rephrased, entities)["items"]

        tax_id = next(item for item in items if item.get("label") == "[SSN_1]")
        self.assertEqual(tax_id["severity"], "high")
        self.assertNotIn("action", tax_id)
        actions = [item for item in items if item.get("action") == "add_context"]
        self.assertEqual(len(actions), 2)
        self.assertTrue(all("severity" not in item and "label" not in item for item in actions))
        self.assertTrue(any("assignments are feasible" in item["message"] for item in items))
        self.assertTrue(any("availability windows" in item["message"] for item in actions))
