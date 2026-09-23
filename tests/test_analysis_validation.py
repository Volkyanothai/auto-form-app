import unittest

from analysis_validation import (
    answer_matches_review_filter,
    answers_equivalent,
    build_balanced_batches,
    build_recovery_batches,
    calculate_answer_reliability,
    choose_autofill_value,
    merge_adjudication_result,
    merge_verification_result,
    normalize_model_answers,
    should_verify_answer,
    submission_fingerprint,
    verification_priority,
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

    def test_preserves_whole_choice_with_separator_and_later_valid_duplicate(self):
        expected = {"entry.1": {"choices": ["แดง, เหลือง", "น้ำเงิน"], "is_multi": False}}
        data = {"answers": [
            {"entry_id": "entry.1", "answer": ["ไม่ใช่ตัวเลือก"], "confidence": 80},
            {"entry_id": "entry.1", "answer": ["แดง, เหลือง"], "confidence": 90},
        ]}
        result = normalize_model_answers(data, expected)
        self.assertEqual(result["entry.1"]["answer"], "แดง, เหลือง")
        self.assertEqual(result["entry.1"]["empty_reason"], "")

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

    def test_prioritizes_images_inside_a_fixed_verification_budget(self):
        image_score = verification_priority(
            "อ่านข้อความจากรูป", "A", 95, has_images=True
        )
        plain_score = verification_priority("เมืองหลวงอังกฤษ", "ลอนดอน", 65)

        self.assertGreater(image_score, plain_score)

    def test_adjudicator_can_keep_original_or_choose_independent_candidate(self):
        original = {"answer": "ลอนดอน", "confidence": 70, "reasoning": "รอบแรก"}
        candidate = {"answer": "ปารีส", "confidence": 80, "reasoning": "รอบสอง"}

        kept = merge_adjudication_result(
            original, candidate,
            {"answer": "ลอนดอน", "confidence": 92, "reasoning": "ตรวจหลักฐานแล้ว"},
        )
        revised = merge_adjudication_result(
            original, candidate,
            {"answer": "ปารีส", "confidence": 94, "reasoning": "ตรวจหลักฐานแล้ว"},
        )

        self.assertEqual(kept["answer"], "ลอนดอน")
        self.assertEqual(kept["verification"], "adjudicated")
        self.assertEqual(revised["answer"], "ปารีส")
        self.assertEqual(revised["initial_answer"], "ลอนดอน")
        self.assertEqual(revised["verification"], "adjudicated_revised")


class ReliabilityScoreTests(unittest.TestCase):
    def test_verified_choice_is_safe(self):
        result = calculate_answer_reliability(
            {"answer": "ลอนดอน", "confidence": 90, "verification": "verified"},
            has_choices=True,
        )

        self.assertEqual(result["risk_level"], "safe")
        self.assertGreaterEqual(result["reliability_score"], 80)

    def test_missing_expected_image_is_risky_even_with_high_self_confidence(self):
        result = calculate_answer_reliability(
            {"answer": "โรงเรียน ก", "confidence": 99, "verification": "not_needed"},
            image_expected=True,
            has_images=False,
        )

        self.assertEqual(result["risk_level"], "risky")
        self.assertIn("โจทย์อ้างถึงรูปแต่ระบบไม่มีรูปพร้อมวิเคราะห์", result["risk_reasons"])

    def test_conflict_stays_below_safe_threshold(self):
        result = calculate_answer_reliability(
            {"answer": "A", "confidence": 100, "verification": "conflict"},
            has_choices=True,
        )

        self.assertNotEqual(result["risk_level"], "safe")


class ReviewAndSubmissionSafetyTests(unittest.TestCase):
    def test_thirty_question_form_retries_twelve_missing_in_smaller_batches(self):
        questions = list(range(1, 31))
        first_answers = {number: f"answer {number}" for number in questions[:18]}
        missing = [number for number in questions if number not in first_answers]

        paired = build_recovery_batches(missing, lambda _: 0, attempt=0)
        self.assertEqual([len(batch) for batch in paired], [2] * 6)
        self.assertEqual([item for batch in paired for item in batch], missing)

        # Simulate two questions still missing after the pair retry.
        recovered = {**first_answers, **{n: f"answer {n}" for n in missing[:-2]}}
        last_missing = [number for number in questions if number not in recovered]
        singles = build_recovery_batches(last_missing, lambda _: 0, attempt=1)
        self.assertEqual(singles, [[29], [30]])
        self.assertEqual(len(first_answers), 18)  # existing results remain intact

    def test_review_filters_use_system_risk_and_image_state(self):
        safe = {"answer": "A", "risk_level": "safe"}
        risky = {"answer": "B", "risk_level": "review"}
        empty = {"answer": "", "risk_level": "risky"}

        self.assertFalse(answer_matches_review_filter(safe, "needs_review"))
        self.assertTrue(answer_matches_review_filter(risky, "needs_review"))
        self.assertTrue(answer_matches_review_filter(empty, "unanswered"))
        self.assertTrue(answer_matches_review_filter(safe, "images", has_images=True))

    def test_submission_fingerprint_is_order_independent_but_value_sensitive(self):
        first = {"entry.2": ["B", "C"], "entry.1": "A"}
        reordered = {"entry.1": "A", "entry.2": ["B", "C"]}
        changed = {"entry.1": "X", "entry.2": ["B", "C"]}

        self.assertEqual(submission_fingerprint(first), submission_fingerprint(reordered))
        self.assertNotEqual(submission_fingerprint(first), submission_fingerprint(changed))

    def test_autofill_refreshes_blank_or_previous_value_but_keeps_manual_edit(self):
        self.assertEqual(choose_autofill_value("", "", "สมชาย"), "สมชาย")
        self.assertEqual(choose_autofill_value("สมชาย", "สมชาย", "สมหญิง"), "สมหญิง")
        self.assertEqual(choose_autofill_value("ชื่อที่แก้เอง", "สมชาย", "สมหญิง"), "ชื่อที่แก้เอง")
        self.assertEqual(choose_autofill_value("ชื่อเดิม", "ชื่อเดิม", ""), "ชื่อเดิม")


if __name__ == "__main__":
    unittest.main()
