"""Validation helpers for Gemini answers.

This module intentionally has no Streamlit or Gemini dependency so the answer
normalisation rules can be tested without starting the web application.
"""
from __future__ import annotations

import re
import unicodedata
import hashlib
import json
from typing import Any, Callable, Dict, List, Mapping, Sequence, TypeVar


AI_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string"},
                    # Always use an array. A single, consistent type is more
                    # reliable than asking the model for string-or-array.
                    "answer": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "confidence": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "reasoning": {"type": "string"},
                },
                "required": ["entry_id", "answer", "confidence", "reasoning"],
            },
        }
    },
    "required": ["answers"],
}


T = TypeVar("T")


def _canonical_text(text: Any) -> str:
    value = unicodedata.normalize("NFKC", str(text))
    value = value.replace("\u200b", "")
    value = re.sub(r"\s+", " ", value).strip().casefold()
    return value


def _strip_answer_prefix(text: str) -> str:
    return re.sub(
        r"^(?:คำตอบ(?:คือ)?|ตอบ|answer(?:\s+is)?)\s*[:：\-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def _leading_label(text: str) -> str | None:
    match = re.match(
        r"^(?:ข้อ\s*)?[\(\[]?([ก-ฮa-zA-Z]|\d+)[\)\].:：\-]?(?:\s+|$)",
        text.strip(),
        flags=re.IGNORECASE,
    )
    return match.group(1).casefold() if match else None


def _explicit_choice_index(text: str, choice_count: int) -> int | None:
    """Return a zero-based option index only when the wording is explicit."""
    match = re.match(
        r"^(?:ตัวเลือก(?:ที่)?|ข้อ|คำตอบ(?:คือ)?\s*(?:ข้อ|ตัวเลือก)?|choice|option)\s*"
        r"([0-9]+)\s*$",
        _strip_answer_prefix(text),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    index = int(match.group(1)) - 1
    return index if 0 <= index < choice_count else None


def _bare_choice_index(text: str, choice_count: int) -> int | None:
    """Resolve a bare option label after exact choice matching has failed."""
    token = _strip_answer_prefix(text).strip().casefold()
    if re.fullmatch(r"[0-9]+", token):
        index = int(token) - 1
        return index if 0 <= index < choice_count else None

    latin = "abcdefghijklmnopqrstuvwxyz"
    thai = "กขคงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ"
    if len(token) == 1:
        if token in latin:
            index = latin.index(token)
            return index if index < choice_count else None
        if token in thai:
            index = thai.index(token)
            return index if index < choice_count else None
    return None


def _choice_mentioned_unambiguously(text: str, choices: list[str]) -> str | None:
    """Accept a choice embedded in a sentence only when exactly one is present."""
    candidate = _canonical_text(text)
    matches: list[str] = []
    for choice in choices:
        choice_text = _canonical_text(choice)
        if not choice_text:
            continue
        pattern = r"(?<!\w)" + re.escape(choice_text) + r"(?!\w)"
        if re.search(pattern, candidate, flags=re.IGNORECASE):
            matches.append(choice)
    return matches[0] if len(matches) == 1 else None


def _strict_choice_match(answer: Any, choices: list[str]) -> str | None:
    """Return the canonical choice without fuzzy guessing."""
    candidate = str(answer).strip()
    if not candidate:
        return None

    candidates = [candidate, _strip_answer_prefix(candidate)]
    canonical_candidates = {_canonical_text(value) for value in candidates if value}
    for choice in choices:
        if _canonical_text(choice) in canonical_candidates:
            return choice

    explicit_index = _explicit_choice_index(candidate, len(choices))
    if explicit_index is not None:
        return choices[explicit_index]

    bare_index = _bare_choice_index(candidate, len(choices))
    if bare_index is not None:
        return choices[bare_index]

    # Gemini occasionally prefixes the exact option text with its list number,
    # e.g. "2. London". Strip that prefix, but still require an exact choice.
    numbered = re.match(r"^(?:ข้อ|ตัวเลือก|choice|option)?\s*\d+\s*[\).:：\-]\s*(.+)$", candidate, re.IGNORECASE)
    if numbered:
        remainder = _canonical_text(numbered.group(1))
        exact = [choice for choice in choices if _canonical_text(choice) == remainder]
        if len(exact) == 1:
            return exact[0]

    # รับคำตอบแบบ "ก" หรือ "ข้อ ก" ได้เมื่อ label นั้นชี้ไปยังตัวเลือกเดียว
    # โดยไม่ใช้ fuzzy matching ที่เสี่ยงเลือกคำตอบผิด
    candidate_label = _leading_label(_strip_answer_prefix(candidate))
    if candidate_label:
        labelled_matches = [
            choice for choice in choices if _leading_label(choice) == candidate_label
        ]
        if len(labelled_matches) == 1:
            return labelled_matches[0]

    mentioned = _choice_mentioned_unambiguously(candidate, choices)
    if mentioned is not None:
        return mentioned
    return None


def build_balanced_batches(
    items: Sequence[T],
    image_count: Callable[[T], int],
    max_text_items: int = 8,
    max_image_items: int = 4,
    max_images: int = 6,
) -> List[List[T]]:
    """Batch text questions densely while keeping image requests bounded."""
    batches: List[List[T]] = []
    current: List[T] = []
    current_images = 0

    for item in items:
        item_images = max(0, int(image_count(item)))
        next_has_images = current_images + item_images > 0
        item_limit = max_image_items if next_has_images else max_text_items
        would_overflow = bool(current) and (
            len(current) >= item_limit
            or current_images + item_images > max_images
        )
        if would_overflow:
            batches.append(current)
            current = []
            current_images = 0

        current.append(item)
        current_images += item_images

    if current:
        batches.append(current)
    return batches


def build_recovery_batches(
    items: Sequence[T],
    image_count: Callable[[T], int],
    attempt: int,
) -> List[List[T]]:
    """Retry unanswered items in pairs, then individually if needed."""
    size = 2 if attempt == 0 else 1
    return build_balanced_batches(
        items, image_count,
        max_text_items=size,
        max_image_items=size,
        max_images=2,
    )


def answers_equivalent(left: Any, right: Any) -> bool:
    """Compare normalized single/multi answers without depending on order."""
    left_values = left if isinstance(left, list) else ([left] if left else [])
    right_values = right if isinstance(right, list) else ([right] if right else [])
    left_normalized = sorted({_canonical_text(value) for value in left_values if str(value).strip()})
    right_normalized = sorted({_canonical_text(value) for value in right_values if str(value).strip()})
    return left_normalized == right_normalized


def should_verify_answer(
    title: str,
    answer: Any,
    confidence: int,
    *,
    has_images: bool = False,
    is_multi: bool = False,
) -> bool:
    """Select only answers whose expected accuracy benefits from a second pass."""
    if not answer:
        return False
    if has_images or is_multi or int(confidence or 0) < 80:
        return True
    risky_markers = (
        "ไม่ถูก", "ไม่ใช่", "ยกเว้น", "ผิด", "ถูกทุกข้อ", "ถูกกี่ข้อ",
        "เลือกได้หลาย", "จากภาพ", "จากรูป", "แผนภาพ", "กราฟ", "ตาราง",
        "คำนวณ", "จงหา", "สมการ", "ข้อใดกล่าว",
        "except", "incorrect", "not true", "diagram", "graph", "calculate",
    )
    folded = _canonical_text(title)
    return any(marker in folded for marker in risky_markers)


def verification_priority(
    title: str,
    answer: Any,
    confidence: int,
    *,
    has_images: bool = False,
    is_multi: bool = False,
) -> int:
    """Rank risky answers so a fixed API budget is spent where it matters."""
    if not answer:
        return -1
    score = max(0, 70 - int(confidence or 0))
    if has_images:
        score += 100
    if is_multi:
        score += 55
    folded = _canonical_text(title)
    high_risk_markers = (
        "ไม่ถูก", "ไม่ใช่", "ยกเว้น", "ผิด", "except", "incorrect",
        "not true", "คำนวณ", "จงหา", "สมการ", "calculate",
    )
    visual_markers = ("จากภาพ", "จากรูป", "แผนภาพ", "กราฟ", "ตาราง", "diagram", "graph")
    if any(marker in folded for marker in high_risk_markers):
        score += 45
    if any(marker in folded for marker in visual_markers):
        score += 35
    return score


def merge_adjudication_result(
    original: Mapping[str, Any],
    candidate: Mapping[str, Any] | None,
    judge: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Resolve an independent-pass disagreement without losing provenance."""
    merged = dict(original)
    candidate = candidate if isinstance(candidate, Mapping) else {}
    judge = judge if isinstance(judge, Mapping) else {}
    candidate_answer = candidate.get("answer")
    judge_answer = judge.get("answer")
    merged["verification_candidate"] = candidate_answer
    merged["verification_reasoning"] = candidate.get("reasoning", "")

    if not judge_answer:
        merged["verification"] = "conflict"
        return merged

    merged["adjudication_reasoning"] = judge.get("reasoning", "")
    if answers_equivalent(judge_answer, merged.get("answer")):
        merged["verification"] = "adjudicated"
        merged["confidence"] = max(
            int(merged.get("confidence", 0) or 0),
            int(judge.get("confidence", 0) or 0),
        )
        return merged

    if candidate_answer and answers_equivalent(judge_answer, candidate_answer):
        merged["initial_answer"] = merged.get("answer")
        merged["answer"] = candidate_answer
        merged["confidence"] = max(
            int(candidate.get("confidence", 0) or 0),
            int(judge.get("confidence", 0) or 0),
        )
        merged["reasoning"] = judge.get("reasoning") or candidate.get("reasoning", "")
        merged["verification"] = "adjudicated_revised"
        return merged

    merged["verification"] = "conflict"
    merged["adjudication_candidate"] = judge_answer
    return merged


def calculate_answer_reliability(
    answer_data: Mapping[str, Any],
    *,
    has_images: bool = False,
    image_expected: bool = False,
    has_choices: bool = False,
) -> Dict[str, Any]:
    """Compute evidence-based reliability instead of trusting self-confidence alone."""
    if not answer_data.get("answer"):
        return {
            "reliability_score": 0,
            "risk_level": "risky",
            "risk_reasons": ["ระบบยังไม่มีคำตอบ"],
        }

    try:
        model_confidence = max(0, min(100, int(answer_data.get("confidence", 0) or 0)))
    except (TypeError, ValueError):
        model_confidence = 0

    score = 50 + round(model_confidence * 0.35)
    reasons: list[str] = []
    if has_choices:
        score += 5

    verification = str(answer_data.get("verification", "not_needed"))
    if verification == "verified":
        score += 12
        reasons.append("คำตอบจากสองรอบตรงกัน")
    elif verification in {"adjudicated", "adjudicated_revised"}:
        score += 8
        reasons.append("ผ่านรอบตัดสินเมื่อผลตรวจไม่ตรงกัน")
    elif verification == "conflict":
        score -= 35
        reasons.append("ผลวิเคราะห์หลายรอบยังขัดแย้งกัน")
    elif verification == "failed":
        score -= 12
        reasons.append("รอบตรวจทานไม่สำเร็จ")
    elif verification == "budget_skipped":
        reasons.append("ไม่ได้ตรวจซ้ำเพื่อควบคุมลิมิต API")

    if image_expected and not has_images:
        score -= 40
        reasons.append("โจทย์อ้างถึงรูปแต่ระบบไม่มีรูปพร้อมวิเคราะห์")
    elif has_images:
        reasons.append("รูปประกอบพร้อมใช้")

    if answer_data.get("source_pass") == "repair":
        score -= 8
        reasons.append("คำตอบได้จากรอบกู้คืน")

    score = max(0, min(100, score))
    risk_level = "safe" if score >= 80 else ("review" if score >= 55 else "risky")
    if not reasons:
        reasons.append("ประเมินจากความมั่นใจและความถูกต้องของรูปแบบคำตอบ")
    return {
        "reliability_score": score,
        "risk_level": risk_level,
        "risk_reasons": reasons,
    }


def answer_matches_review_filter(
    answer_data: Mapping[str, Any],
    filter_key: str,
    *,
    has_images: bool = False,
) -> bool:
    """Pure filtering rule used by the review UI and regression tests."""
    if filter_key == "needs_review":
        return answer_data.get("risk_level", "risky") != "safe"
    if filter_key == "unanswered":
        return not bool(answer_data.get("answer"))
    if filter_key == "images":
        return has_images
    return True


def submission_fingerprint(payload: Mapping[str, Any]) -> str:
    """Stable identifier used to suppress accidental duplicate submissions."""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def choose_autofill_value(current: Any, previous_auto: Any, desired: Any) -> str:
    """Refresh generated values while preserving a user's manual review edit."""
    current_text = "" if current is None else str(current)
    previous_text = "" if previous_auto is None else str(previous_auto)
    desired_text = "" if desired is None else str(desired)
    if not desired_text:
        return current_text
    if not current_text or current_text == previous_text:
        return desired_text
    return current_text


def merge_verification_result(
    original: Mapping[str, Any],
    candidate: Mapping[str, Any] | None,
    *,
    revision_threshold: int = 85,
) -> Dict[str, Any]:
    """Merge a verifier result without ever losing a usable first answer.

    An agreement increases confidence, a high-confidence disagreement replaces
    the answer while retaining the original, and every uncertain/failing path
    keeps the first-pass answer intact.
    """
    merged = dict(original)
    candidate = candidate if isinstance(candidate, Mapping) else {}
    candidate_answer = candidate.get("answer")

    if not candidate_answer:
        merged["verification"] = "failed"
        return merged

    merged["verification_reasoning"] = candidate.get("reasoning", "")
    if answers_equivalent(merged.get("answer"), candidate_answer):
        merged["verification"] = "verified"
        merged["confidence"] = max(
            int(merged.get("confidence", 0) or 0),
            int(candidate.get("confidence", 0) or 0),
        )
        return merged

    candidate_confidence = int(candidate.get("confidence", 0) or 0)
    if candidate_confidence >= revision_threshold:
        initial_answer = merged.get("answer")
        merged["answer"] = candidate_answer
        merged["confidence"] = candidate_confidence
        merged["reasoning"] = candidate.get("reasoning", merged.get("reasoning", ""))
        merged["verification"] = "revised"
        merged["initial_answer"] = initial_answer
        return merged

    merged["verification"] = "conflict"
    merged["verification_candidate"] = candidate_answer
    return merged


def normalize_model_answers(
    data: Mapping[str, Any],
    expected: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Validate model output and discard invented IDs or ambiguous choices."""
    result: Dict[str, Dict[str, Any]] = {}
    raw_answers = data.get("answers", []) if isinstance(data, Mapping) else []
    if not isinstance(raw_answers, list):
        return result

    for item in raw_answers:
        if not isinstance(item, Mapping):
            continue
        entry_id = str(item.get("entry_id", "")).strip()
        spec = expected.get(entry_id)
        if not spec:
            continue

        raw_value = item.get("answer", [])
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        values = [str(value).strip() for value in values if str(value).strip()]

        choices = [str(choice) for choice in spec.get("choices", [])]
        is_multi = bool(spec.get("is_multi", False))

        if choices:
            matched: list[str] = []
            for value in values:
                # A complete option may itself contain a comma, semicolon or
                # "and". Match it before treating those characters as a list.
                whole_choice = next(
                    (choice for choice in choices if _canonical_text(value) == _canonical_text(choice)),
                    None,
                )
                if whole_choice is not None:
                    if whole_choice not in matched:
                        matched.append(whole_choice)
                    continue
                # Some model versions return multiple checkbox choices in one
                # string even though the schema requests an array. Split only
                # on explicit separators, then validate each fragment.
                fragments = re.split(
                    r"\s*(?:,|;|\n|\||\s+และ\s+|\s+and\s+)\s*",
                    value,
                    flags=re.IGNORECASE,
                )
                for fragment in fragments:
                    canonical = _strict_choice_match(fragment, choices)
                    if canonical is not None and canonical not in matched:
                        matched.append(canonical)
            answer: Any = matched if is_multi else (matched[0] if matched else "")
        else:
            # Free-text questions should contain one answer item. Joining extra
            # items is safer than silently discarding text from the model.
            answer = "\n".join(values)

        try:
            confidence = int(item.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0
        confidence = max(0, min(100, confidence)) if answer else 0

        reasoning = str(item.get("reasoning", "")).strip()
        if not reasoning:
            reasoning = "ไม่มีคำอธิบายประกอบ"

        # The model sometimes emits an empty/invalid duplicate first. Keep a
        # usable later answer instead of permanently retaining that blank.
        if entry_id in result and (result[entry_id]["answer"] or not answer):
            continue
        result[entry_id] = {
            "answer": answer,
            "confidence": confidence,
            "reasoning": reasoning[:1200],
            "empty_reason": (
                "choice_mismatch" if not answer and choices and values
                else "model_blank" if not answer else ""
            ),
        }

    return result
