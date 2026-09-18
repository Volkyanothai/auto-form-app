import unittest

from analysis_validation import (
    answers_equivalent,
    build_balanced_batches,
    merge_verification_result,
    normalize_model_answers,
    should_verify_answer,
)


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

    def test_accepts_unique_choice_label_without_fuzzy_matching(self):
        data = {
            "answers": [
                {
                    "entry_id": "entry.single",
                    "answer": ["คำตอบคือ ก"],
                    "confidence": 75,
                    "reasoning": "เลือกข้อ ก",
                }
            ]
        }

        result = normalize_model_answers(data, self.expected)

        self.assertEqual(result["entry.single"]["answer"], "ก. แมว")

    def test_accepts_explicit_option_index(self):
        data = {
            "answers": [{
                "entry_id": "entry.single",
                "answer": ["ตัวเลือกที่ 2"],
                "confidence": 80,
                "reasoning": "เลือกตัวเลือกที่สอง",
            }]
        }

        result = normalize_model_answers(data, self.expected)

        self.assertEqual(result["entry.single"]["answer"], "ข. หมา")

    def test_accepts_bare_option_number_after_exact_match_fails(self):
        expected = {
            "entry.capital": {
                "choices": ["ลอนดอน", "ปารีส", "นิวยอร์ก", "กรุงเทพ"],
                "is_multi": False,
            }
        }
        data = {
            "answers": [{
                "entry_id": "entry.capital",
                "answer": ["1"],
                "confidence": 90,
                "reasoning": "ตัวเลือกแรก",
            }]
        }

        result = normalize_model_answers(data, expected)

        self.assertEqual(result["entry.capital"]["answer"], "ลอนดอน")

    def test_accepts_one_exact_choice_inside_a_sentence(self):
        data = {
            "answers": [{
                "entry_id": "entry.single",
                "answer": ["คำตอบคือ ก. แมว เพราะเป็นสัตว์ตามโจทย์"],
                "confidence": 80,
                "reasoning": "เลือกแมว",
            }]
        }

        result = normalize_model_answers(data, self.expected)

        self.assertEqual(result["entry.single"]["answer"], "ก. แมว")

    def test_splits_checkbox_answers_returned_in_one_string(self):
        data = {
            "answers": [{
                "entry_id": "entry.multi",
                "answer": ["1 และ 3"],
                "confidence": 90,
                "reasoning": "มีสองคำตอบ",
            }]
        }

        result = normalize_model_answers(data, self.expected)

        self.assertEqual(result["entry.multi"]["answer"], ["1", "3"])


class BalancedBatchTests(unittest.TestCase):
    def test_four_text_questions_use_one_batch(self):
        items = [{"images": 0} for _ in range(4)]
        batches = build_balanced_batches(items, lambda item: item["images"])
        self.assertEqual([len(batch) for batch in batches], [4])

    def test_many_text_questions_are_batched_efficiently(self):
        items = [{"images": 0} for _ in range(20)]
        batches = build_balanced_batches(items, lambda item: item["images"])
        self.assertEqual([len(batch) for batch in batches], [8, 8, 4])

    def test_image_budget_splits_heavy_questions(self):
        items = [{"images": 3} for _ in range(5)]
        batches = build_balanced_batches(items, lambda item: item["images"])
        self.assertEqual([len(batch) for batch in batches], [2, 2, 1])


class SelectiveVerificationTests(unittest.TestCase):
    def test_compares_checkbox_answers_without_order(self):
        self.assertTrue(answers_equivalent(["A", "B"], ["b", "a"]))
        self.assertFalse(answers_equivalent(["A"], ["B"]))

    def test_verifies_images_low_confidence_and_tricky_wording(self):
        self.assertTrue(should_verify_answer("จากภาพคืออะไร", "แมว", 95, has_images=True))
        self.assertTrue(should_verify_answer("เมืองหลวงคือ", "ลอนดอน", 62))
        self.assertTrue(should_verify_answer("ข้อใดไม่ถูกต้อง", "ข้อ 2", 92))
        self.assertFalse(should_verify_answer("เมืองหลวงอังกฤษคือ", "ลอนดอน", 92))

    def test_failed_verifier_never_erases_first_answer(self):
        original = {"answer": "ลอนดอน", "confidence": 76, "reasoning": "รอบแรก"}

        merged = merge_verification_result(original, None)

        self.assertEqual(merged["answer"], "ลอนดอน")
        self.assertEqual(merged["reasoning"], "รอบแรก")
        self.assertEqual(merged["verification"], "failed")

    def test_low_confidence_conflict_keeps_first_answer(self):
        original = {"answer": "ลอนดอน", "confidence": 76, "reasoning": "รอบแรก"}
        candidate = {"answer": "ปารีส", "confidence": 60, "reasoning": "รอบตรวจ"}

        merged = merge_verification_result(original, candidate)

        self.assertEqual(merged["answer"], "ลอนดอน")
        self.assertEqual(merged["verification"], "conflict")
        self.assertEqual(merged["verification_candidate"], "ปารีส")

    def test_high_confidence_correction_retains_initial_answer(self):
        original = {"answer": "ลอนดอน", "confidence": 76, "reasoning": "รอบแรก"}
        candidate = {"answer": "ปารีส", "confidence": 93, "reasoning": "ตรวจใหม่"}

        merged = merge_verification_result(original, candidate)

        self.assertEqual(merged["answer"], "ปารีส")
        self.assertEqual(merged["initial_answer"], "ลอนดอน")
        self.assertEqual(merged["verification"], "revised")

    def test_matching_checkbox_verification_is_order_independent(self):
        original = {"answer": ["A", "B"], "confidence": 70}
        candidate = {"answer": ["b", "a"], "confidence": 91, "reasoning": "ตรงกัน"}

        merged = merge_verification_result(original, candidate)

        self.assertEqual(merged["answer"], ["A", "B"])
        self.assertEqual(merged["confidence"], 91)
        self.assertEqual(merged["verification"], "verified")


if __name__ == "__main__":
    unittest.main()
