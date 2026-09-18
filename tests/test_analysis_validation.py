import unittest

from analysis_validation import normalize_model_answers


class NormalizeModelAnswersTests(unittest.TestCase):
    def setUp(self):
        self.expected = {
            "entry.single": {"choices": ["ก. แมว", "ข. หมา"], "is_multi": False},
            "entry.multi": {"choices": ["1", "2", "3"], "is_multi": True},
            "entry.text": {"choices": [], "is_multi": False},
        }

    def test_normalizes_valid_answers(self):
        data = {
            "answers": [
                {
                    "entry_id": "entry.single",
                    "answer": ["ก. แมว"],
                    "confidence": 92,
                    "reasoning": "ถูกต้อง",
                },
                {
                    "entry_id": "entry.multi",
                    "answer": ["1", "3", "3"],
                    "confidence": 101,
                    "reasoning": "เลือกสองข้อ",
                },
            ]
        }

        result = normalize_model_answers(data, self.expected)

        self.assertEqual(result["entry.single"]["answer"], "ก. แมว")
        self.assertEqual(result["entry.multi"]["answer"], ["1", "3"])
        self.assertEqual(result["entry.multi"]["confidence"], 100)

    def test_rejects_unknown_ids_and_ambiguous_choices(self):
        data = {
            "answers": [
                {
                    "entry_id": "entry.unknown",
                    "answer": ["anything"],
                    "confidence": 99,
                    "reasoning": "invented",
                },
                {
                    "entry_id": "entry.single",
                    "answer": ["คำตอบที่ไม่มีในตัวเลือก"],
                    "confidence": 99,
                    "reasoning": "bad match",
                },
            ]
        }

        result = normalize_model_answers(data, self.expected)

        self.assertNotIn("entry.unknown", result)
        self.assertEqual(result["entry.single"]["answer"], "")
        self.assertEqual(result["entry.single"]["confidence"], 0)

    def test_accepts_legacy_string_and_free_text(self):
        data = {
            "answers": [
                {
                    "entry_id": "entry.text",
                    "answer": "กรุงเทพมหานคร",
                    "confidence": "80",
                    "reasoning": "คำตอบสั้น",
                }
            ]
        }

        result = normalize_model_answers(data, self.expected)

        self.assertEqual(result["entry.text"]["answer"], "กรุงเทพมหานคร")
        self.assertEqual(result["entry.text"]["confidence"], 80)


if __name__ == "__main__":
    unittest.main()
