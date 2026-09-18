"""Validation helpers for Gemini answers.

This module intentionally has no Streamlit or Gemini dependency so the answer
normalisation rules can be tested without starting the web application.
"""
from __future__ import annotations

import re
import unicodedata
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
        if not spec or entry_id in result:
            continue

        raw_value = item.get("answer", [])
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        values = [str(value).strip() for value in values if str(value).strip()]

        choices = [str(choice) for choice in spec.get("choices", [])]
        is_multi = bool(spec.get("is_multi", False))

        if choices:
            matched: list[str] = []
            for value in values:
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
            reasoning = "AI ไม่ได้ให้คำอธิบาย"

        result[entry_id] = {
            "answer": answer,
            "confidence": confidence,
            "reasoning": reasoning[:1200],
        }

    return result
