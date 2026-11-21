import unittest

from agenthon.rephrase import rephrase


class RephraseTests(unittest.TestCase):
    def test_draft_keeps_the_goal_role_and_every_placeholder(self):
        prompt = (
            "Draft an email to the project lead, [NAME_1] ([EMAIL_1]), "
            "asking for an update on the quarterly report."
        )
        entities = [
            {"type": "name", "label": "[NAME_1]"},
            {"type": "email", "label": "[EMAIL_1]"},
        ]
        result = rephrase({"prompt": prompt, "entities": entities})

        self.assertTrue(result["changed"])
        self.assertIn("Objective\nDraft an email asking for an update on the quarterly report.",
                      result["proposed_prompt"])
        self.assertIn("Recipient\nthe project lead, [NAME_1] ([EMAIL_1])", result["proposed_prompt"])
        self.assertIn("Use any roles and facts already given", result["proposed_prompt"])
        self.assertNotIn("Jordan Miller", result["proposed_prompt"])
        self.assertNotIn("jordan.miller@example.test", result["proposed_prompt"])
        self.assertEqual([entity["label"] for entity in entities],
                         [detail["label"] for detail in result["missing_information"]])

    def test_shift_plan_with_missing_inputs_uses_explicit_hypotheses(self):
        prompt = "Create a weekly work shift schedule for [NAME_1] and [NAME_2]. The site closes Friday."
        entities = [{"type": "name", "label": label} for label in ("[NAME_1]", "[NAME_2]")]
        result = rephrase({"prompt": prompt, "entities": entities})

        self.assertIn("Label each scenario as hypothetical", result["proposed_prompt"])
        self.assertIn(prompt, result["proposed_prompt"])
        missing = [item["detail"] for item in result["missing_information"] if "label" not in item]
        self.assertEqual(missing, ["Individual shift availability is missing.",
                                   "Staff skills or qualifications are missing."])

    def test_provided_context_is_not_reported_missing(self):
        prompt = (
            "Prepare a shift plan for [NAME_1]. [NAME_1] can work Friday from 09:00. "
            "They are trained in first aid."
        )
        entities = [{"type": "name", "label": "[NAME_1]"}]
        result = rephrase({"prompt": prompt, "entities": entities})

        self.assertEqual(len(result["missing_information"]), 1)
        self.assertNotIn("hypothetical", result["proposed_prompt"])

    def test_request_about_a_shift_schedule_does_not_require_creating_one(self):
        prompt = "Draft an email about the shift schedule."
        result = rephrase({"prompt": prompt, "entities": []})

        self.assertEqual(result["proposed_prompt"], prompt)
        self.assertFalse(result["changed"])
        self.assertEqual(result["missing_information"], [])
