"""Conservative Google Forms submission checks and browser fallback links."""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional, Tuple
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
from form_media import extract_form_page_state


# Google can reject long prefilled links with HTTP 400. Leave room below its
# usual request-line limit for redirects and browser-added parameters.
MAX_PREFILL_URL_LENGTH = 6000


def check_submit_success(
    response_text: str,
    status_code: int,
    response_url: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Treat only Google's confirmation page as proof of a recorded answer."""
    if status_code != 200:
        return False, f"Google Forms ตอบกลับ HTTP {status_code} จึงยังยืนยันการบันทึกไม่ได้"

    body = (response_text or "").casefold()
    if "freebirdformviewerviewresponseconfirmationmessage" in body:
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


def build_entry_page_map(form_data: Any) -> dict[str, int]:
    """Keep personal fields as well as exam questions on their actual form page."""
    result: dict[str, int] = {}
    try:
        entries = form_data[1][1]
    except (IndexError, KeyError, TypeError):
        return result
    if not isinstance(entries, list):
        return result
    page = 0
    for item in entries:
        if not isinstance(item, list) or len(item) < 4:
            continue
        if item[3] == 8:
            page += 1
            continue
        if len(item) < 5 or not isinstance(item[4], list):
            continue
        for spec in item[4]:
            if isinstance(spec, list) and spec and spec[0] is not None:
                result[f"entry.{spec[0]}"] = page
    return result


def extract_entry_page_map(raw_html: str) -> dict[str, int]:
    """Read the current form's entry IDs and page breaks before submission."""
    match = re.search(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*?\]);\s*</script>", raw_html, re.DOTALL)
    if not match:
        return {}
    try:
        return build_entry_page_map(json.loads(match.group(1)))
    except (ValueError, TypeError):
        return {}


def post_form_response_with_pages(
    submit_url: str,
    payload: Mapping[str, Any],
    entry_pages: Mapping[str, int],
    headers: Mapping[str, str],
    timeout: int,
    session_factory=None,
) -> Tuple[bool, str, Optional[str], Optional[str]]:
    """Walk real form pages with one HTTP session; submit the final page once.

    An uncertain final POST is never repeated. The intermediate requests use
    Google's continue action, and each response must prove we advanced to the
    next expected page before any subsequent request is made.
    """
    view_url = build_original_form_url(submit_url)
    if not view_url:
        return False, "ลิงก์ส่งคำตอบไม่ใช่ Google Forms ที่รองรับ", None, None
    try:
        pages = [int(page) for page in str(payload.get("pageHistory", "0")).split(",")]
    except (TypeError, ValueError):
        pages = []
    if not pages or pages[0] != 0 or len(pages) != len(set(pages)) or any(page < 0 for page in pages):
        return False, "ลำดับหน้าของฟอร์มไม่ถูกต้อง จึงยังไม่ส่งคำตอบ", None, None

    with (session_factory or requests.Session)() as session:
        try:
            response = session.get(view_url, headers=headers, timeout=timeout)
            if response.status_code != 200:
                return False, f"เปิดฟอร์มก่อนส่งไม่สำเร็จ (HTTP {response.status_code})", None, None
            state = extract_form_page_state(response.text)
            if not state.get("fbzx") or "FB_PUBLIC_LOAD_DATA_" not in response.text:
                return False, "Google ไม่เปิดหน้าฟอร์มสำหรับการส่งอัตโนมัติ กรุณาตรวจสิทธิ์เข้าถึงฟอร์ม", None, None
            live_pages = extract_entry_page_map(response.text)
            if not live_pages and len(pages) > 1:
                return False, "อ่านลำดับหน้าฟอร์มล่าสุดไม่ได้ จึงยังไม่ส่งคำตอบ", None, None
            actual_pages = live_pages or entry_pages
            if any(key.startswith("entry.") and key not in actual_pages for key in payload):
                return False, "ฟอร์มมีการแก้ไขคำถามหลังวิเคราะห์ กรุณาวิเคราะห์ฟอร์มใหม่ก่อนส่ง", None, None
            for index, page in enumerate(pages):
                fields: dict[str, Any] = {
                    key: value for key, value in payload.items()
                    if key.startswith("entry.") and actual_pages.get(key, 0) == page
                }
                fields.update({
                    "fbzx": state["fbzx"],
                    "fvv": state.get("fvv") or payload.get("fvv", "1"),
                    "pageHistory": state.get("pageHistory") or ",".join(map(str, pages[:index + 1])),
                })
                if state.get("partialResponse"):
                    fields["partialResponse"] = state["partialResponse"]
                elif index == 0:
                    fields["draftResponse"] = "[]"
                if index < len(pages) - 1:
                    fields["continue"] = "1"
                response = session.post(
                    submit_url, data=fields,
                    headers={**headers, "Referer": view_url}, timeout=timeout,
                )
                if index == len(pages) - 1:
                    success, error = check_submit_success(response.text, response.status_code, response.url)
                    if success:
                        return True, "ส่งข้อมูลสำเร็จ", response.text, response.url
                    return False, error or "Google Forms ยังไม่ยืนยันการบันทึก", None, None

                next_state = extract_form_page_state(response.text)
                next_history = next_state.get("pageHistory", "")
                expected = ",".join(map(str, pages[:index + 2]))
                if response.status_code != 200 or not next_state.get("fbzx") or next_history != expected:
                    return False, (
                        f"ฟอร์มหยุดที่หน้า {page + 1} ก่อนส่งจริง "
                        "อาจมีช่องบังคับหรือลำดับหน้าที่ต้องตรวจใน Google Forms"
                    ), None, None
                state = next_state
        except requests.exceptions.Timeout:
            return False, "ไม่ทราบผลการส่งเพราะการเชื่อมต่อหมดเวลา โปรดตรวจใน Google Forms ก่อนกดส่งอีกครั้ง", None, None
        except requests.exceptions.RequestException:
            return False, "เชื่อมต่อ Google Forms ไม่สำเร็จ โปรดลองเปิดฟอร์มพร้อมคำตอบในเบราว์เซอร์", None, None
    return False, "Google Forms ยังไม่ยืนยันการบันทึก", None, None
