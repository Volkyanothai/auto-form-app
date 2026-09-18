"""Validation helpers for Gemini answers.

This module intentionally has no Streamlit or Gemini dependency so the answer
normalisation rules can be tested without starting the web application.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Mapping


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


def _normalise_label(text: str) -> str:
    return re.sub(
        r"^(?:ข้อ\s*)?[\(\[]?([ก-ฮa-zA-Z0-9]+)[\)\].]?\s*",
        r"\1 ",
        str(text).strip(),
    ).strip().casefold()


def _strict_choice_match(answer: Any, choices: list[str]) -> str | None:
    """Return the canonical choice without fuzzy guessing."""
    candidate = str(answer).strip()
    if not candidate:
        return None

    for choice in choices:
        if candidate == choice.strip():
            return choice

    folded = candidate.casefold()
    for choice in choices:
        if folded == choice.strip().casefold():
            return choice

    labelled = _normalise_label(candidate)
    labelled_matches = [choice for choice in choices if _normalise_label(choice) == labelled]
    if len(labelled_matches) == 1:
        return labelled_matches[0]
    return None


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
                canonical = _strict_choice_match(value, choices)
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
