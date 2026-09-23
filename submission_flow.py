"""Conservative Google Forms submission checks and browser fallback links."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Mapping, Optional, Tuple
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests


# Google can reject long prefilled links with HTTP 400. Leave room below its
# usual request-line limit for redirects and browser-added parameters.
MAX_PREFILL_URL_LENGTH = 6000


class _VisibleFormText(HTMLParser):
    """Read visible confirmation text and detect an unanswered form page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.has_form = False
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag == "form":
            self.has_form = True
        if tag == "input" and any(name == "name" and (value or "").startswith("entry.") for name, value in attrs):
            self.has_form = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def check_submit_success(
    response_text: str,
    status_code: int,
    response_url: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Treat only Google's confirmation page as proof of a recorded answer."""
    if status_code != 200:
        return False, f"Google Forms ตอบกลับ HTTP {status_code} จึงยังยืนยันการบันทึกไม่ได้"

    body = (response_text or "").casefold()
    page = _VisibleFormText()
    page.feed(response_text or "")
    visible = " ".join(" ".join(page.text).casefold().split())
    confirmation = any(phrase in visible for phrase in (
        "your response has been recorded",
        "your response was recorded",
        "your response has been submitted",
        "บันทึกคำตอบของคุณแล้ว",
        "บันทึกคำตอบของคุณเรียบร้อยแล้ว",
        "ส่งคำตอบของคุณแล้ว",
    ))
    # The old CSS marker and modern visible messages are both valid, but a
    # returned form can contain confirmation text in its description or JS.
    if not page.has_form and (
        "freebirdformviewerviewresponseconfirmationmessage" in body or confirmation
    ):
        return True, None

    url = (response_url or "").casefold()
    if "accounts.google.com" in url or any(
        marker in body for marker in (
            "sign in to continue", "you need permission", "ต้องลงชื่อเข้าใช้",
            "จำเป็นต้องลงชื่อเข้าใช้", "ต้องลงชื่อเข้าใช้เพื่อดำเนินการต่อ",
        )
    ):
        return False, "ฟอร์มนี้อาจต้องลงชื่อเข้าใช้บัญชี Google กรุณาเปิดฟอร์มพร้อมคำตอบในเบราว์เซอร์"

    if "fb_public_load_data_" in body or 'role="form"' in body or url.endswith("/viewform"):
        return False, (
            "Google Forms ส่งหน้าฟอร์มกลับมาแทนหน้ายืนยัน "
            "อาจมีข้อบังคับหรือการแบ่งหน้าที่ต้องตรวจในฟอร์มต้นฉบับ"
        )

    return False, "Google Forms ไม่ส่งหน้ายืนยันกลับมา จึงยังยืนยันไม่ได้ว่าบันทึกคำตอบแล้ว"


def build_original_form_url(submit_url: str) -> Optional[str]:
    """Return the clean native form URL without a submission query or answers."""
    parts = urlsplit(submit_url)
    if parts.scheme != "https" or parts.hostname not in {"docs.google.com", "forms.google.com"}:
        return None
    if not parts.path.startswith("/forms/") or not parts.path.endswith("/formResponse"):
        return None

    return urlunsplit((
        "https", parts.netloc, parts.path[:-len("formResponse")] + "viewform", "", "",
    ))


def build_prefilled_form_url(submit_url: str, payload: Mapping[str, Any]) -> Optional[str]:
    """Give the respondent all reviewed values, or no prefill if it would be too long."""
    original_url = build_original_form_url(submit_url)
    if original_url is None:
        return None

    fields = [("usp", "pp_url")]
    for key, value in payload.items():
        if not re.fullmatch(r"entry\.\d+", str(key)):
            continue
        values = value if isinstance(value, list) else [value]
        fields.extend((str(key), str(item)) for item in values if item is not None and str(item).strip())

    prefilled_url = f"{original_url}?{urlencode(fields)}"
    return prefilled_url if len(prefilled_url) <= MAX_PREFILL_URL_LENGTH else None


def post_form_response(
    submit_url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout: int,
    post=None,
) -> Tuple[bool, str, Optional[str], Optional[str]]:
    """Post once; a timeout may mean Google already recorded the response."""
    send = post or requests.post
    try:
        response = send(submit_url, data=payload, headers=headers, timeout=timeout)
        success, error = check_submit_success(response.text, response.status_code, response.url)
        if success:
            return True, "ส่งข้อมูลสำเร็จ", response.text, response.url
        return False, error or "Google Forms ยังไม่ยืนยันการบันทึก", None, None
    except requests.exceptions.Timeout:
        return False, "ไม่ทราบผลการส่งเพราะการเชื่อมต่อหมดเวลา โปรดตรวจใน Google Forms ก่อนกดส่งอีกครั้ง", None, None
    except requests.exceptions.RequestException:
        return False, "เชื่อมต่อ Google Forms ไม่สำเร็จ โปรดลองเปิดฟอร์มพร้อมคำตอบในเบราว์เซอร์", None, None
