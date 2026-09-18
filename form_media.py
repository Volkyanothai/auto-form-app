"""Google Forms rendered-image discovery helpers.

Google Forms does not place every downloadable image URL inside
``FB_PUBLIC_LOAD_DATA_``.  The responder page renders those assets under the
question item's ``data-item-id`` instead.  This module reads that relationship
without depending on Google's CSS class names.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit


_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


@dataclass(frozen=True)
class RenderedImageRef:
    item_id: str
    url: str
    choice_value: Optional[str] = None
    alt_text: str = ""
    role: Optional[str] = None


def is_trusted_google_form_image_url(url: str) -> bool:
    """Limit server-side downloads to image hosts emitted by Google Forms."""
    try:
        parsed = urlsplit(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return False
    if host == "docs.google.com" and parsed.path.startswith("/forms-images-rt/"):
        return True
    return host.endswith(".googleusercontent.com") or host.endswith(".ggpht.com")


def upgrade_google_form_image_url(url: str, size: int = 1600) -> str:
    """Request a useful source resolution while retaining the signed path."""
    url = html.unescape(str(url)).rstrip("\\/")
    if not is_trusted_google_form_image_url(url):
        return url
    base = re.sub(
        r"=(?:w\d+(?:-h\d+)?|h\d+|s\d+)(?:-[a-zA-Z]\w*)*$",
        "",
        url,
    )
    return f"{base}=s{max(256, min(int(size), 2048))}"


class _FormsImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: List[Tuple[str, Dict[str, str]]] = []
        self.refs: List[RenderedImageRef] = []

    @staticmethod
    def _attrs(attrs: Iterable[Tuple[str, Optional[str]]]) -> Dict[str, str]:
        return {str(key).lower(): value or "" for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        attr_map = self._attrs(attrs)
        if tag == "img" or any(
            key in attr_map for key in ("data-src", "srcset", "data-background-image")
        ) or "url(" in attr_map.get("style", "").lower():
            self._capture_image(attr_map)
        if tag not in _VOID_TAGS:
            self.stack.append((tag, attr_map))

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attr_map = self._attrs(attrs)
        if tag.lower() == "img" or any(
            key in attr_map for key in ("data-src", "srcset", "data-background-image")
        ) or "url(" in attr_map.get("style", "").lower():
            self._capture_image(attr_map)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def _capture_image(self, attrs: Mapping[str, str]) -> None:
        candidates: List[str] = [attrs.get("data-src", "")]
        srcset = attrs.get("srcset", "")
        if srcset:
            candidates.extend(
                part.strip().split()[0]
                for part in reversed(srcset.split(","))
                if part.strip()
            )
        candidates.extend([
            attrs.get("src", ""),
            attrs.get("data-background-image", ""),
        ])
        candidates.extend(re.findall(
            r"url\(\s*['\"]?([^'\")]+)",
            attrs.get("style", ""),
            flags=re.IGNORECASE,
        ))

        url = ""
        for candidate in candidates:
            candidate = html.unescape(candidate or "").strip()
            if candidate.startswith("//"):
                candidate = "https:" + candidate
            if is_trusted_google_form_image_url(candidate):
                url = candidate
                break
        if not url:
            return

        item_id = attrs.get("data-item-id", "").strip()
        choice_value: Optional[str] = (
            html.unescape(attrs.get("data-value", "")).strip() or None
        )
        role: Optional[str] = attrs.get("role", "").lower() or None
        for _, ancestor in reversed(self.stack):
            if role is None and ancestor.get("role"):
                role = ancestor["role"].lower()
            if choice_value is None and ancestor.get("data-value"):
                choice_value = html.unescape(ancestor["data-value"]).strip() or None
            if not item_id and ancestor.get("data-item-id"):
                item_id = ancestor["data-item-id"].strip()
            if not item_id and ancestor.get("data-params"):
                params = html.unescape(ancestor["data-params"])
                match = re.search(r"\[\s*(\d+)\s*,", params)
                if match:
                    item_id = match.group(1)
            if item_id and choice_value is not None:
                break

        # Images outside an item are form theme/header assets, not question
        # media. Sending those to Gemini only adds noise.
        if not item_id:
            return
        self.refs.append(RenderedImageRef(
            item_id=item_id,
            url=url,
            choice_value=choice_value,
            alt_text=html.unescape(attrs.get("alt", "")).strip(),
            role=role,
        ))


def extract_rendered_image_refs(raw_html: str) -> Dict[str, List[RenderedImageRef]]:
    parser = _FormsImageParser()
    try:
        parser.feed(raw_html or "")
        parser.close()
    except Exception:
        # HTMLParser can still have collected useful refs before malformed HTML.
        pass

    grouped: Dict[str, List[RenderedImageRef]] = {}
    seen: set[Tuple[str, str, Optional[str]]] = set()
    for ref in parser.refs:
        marker = (ref.item_id, ref.url, ref.choice_value)
        if marker in seen:
            continue
        seen.add(marker)
        grouped.setdefault(ref.item_id, []).append(ref)
    return grouped


def split_item_image_refs(
    refs: Sequence[RenderedImageRef],
    choices: Sequence[str],
) -> Tuple[List[RenderedImageRef], Dict[int, List[RenderedImageRef]]]:
    """Separate question images from images nested in answer choices."""
    choice_lookup = {str(choice).strip().casefold(): index for index, choice in enumerate(choices)}
    question_refs: List[RenderedImageRef] = []
    choice_refs: Dict[int, List[RenderedImageRef]] = {}

    for ref in refs:
        choice_index = None
        if ref.choice_value:
            choice_index = choice_lookup.get(ref.choice_value.strip().casefold())
        if choice_index is None:
            question_refs.append(ref)
        else:
            choice_refs.setdefault(choice_index, []).append(ref)
    return question_refs, choice_refs


class _NamedInputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: Dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "input":
            return
        attr_map = {str(key).lower(): value or "" for key, value in attrs}
        name = attr_map.get("name", "").strip()
        if name:
            self.values[name] = attr_map.get("value", "")


def extract_form_page_state(raw_html: str) -> Dict[str, str]:
    """Read the hidden state needed to request the next Google Forms page."""
    parser = _NamedInputParser()
    try:
        parser.feed(raw_html or "")
        parser.close()
    except Exception:
        pass
    return {
        key: parser.values.get(key, "")
        for key in ("fvv", "partialResponse", "pageHistory", "fbzx")
    }


def build_preview_page_payloads(form_data: object) -> List[Dict[str, str]]:
    """Create harmless placeholders for page navigation, never final submission."""
    try:
        entries = form_data[1][1]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return []
    if not isinstance(entries, list):
        return []

    pages: List[Dict[str, str]] = [{}]
    for item in entries:
        if not isinstance(item, list) or len(item) < 4:
            continue
        question_type = item[3]
        if question_type == 8:  # page break
            pages.append({})
            continue
        if question_type == 11 or len(item) < 5 or not isinstance(item[4], list):
            continue

        for spec in item[4]:
            if not isinstance(spec, list) or not spec:
                continue
            entry_id = spec[0]
            if entry_id is None:
                continue
            field_name = f"entry.{entry_id}"
            choices = spec[1] if len(spec) > 1 else None
            placeholder = "preview"
            if isinstance(choices, list):
                first_choice = next(
                    (
                        str(choice[0])
                        for choice in choices
                        if isinstance(choice, list) and choice and choice[0] is not None
                    ),
                    None,
                )
                if first_choice:
                    placeholder = first_choice
            pages[-1].setdefault(field_name, placeholder)
    return pages


def find_blob_image_page_indexes(form_data: object) -> List[int]:
    """Return zero-based pages containing Google's opaque image tokens."""
    try:
        entries = form_data[1][1]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return []
    if not isinstance(entries, list):
        return []

    page_index = 0
    pages: set[int] = set()
    for item in entries:
        if not isinstance(item, list) or len(item) < 4:
            continue
        if item[3] == 8:  # page break
            page_index += 1
            continue
        if "s-blob-v1-IMAGE-" in repr(item):
            pages.add(page_index)
    return sorted(pages)
