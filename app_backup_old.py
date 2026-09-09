"""
app.py — EZEXAM Auto Form System (Final Fix v6)
=================================================
v1-v5: (ดู changelog เดิม — โมเดล/คีย์/โควตา/รูปภาพ)
v6: แก้ปัญหา "กดวิเคราะห์ข้อนี้ใหม่แล้วคำตอบไม่เปลี่ยน"
     -> Streamlit จะ "ยึด" ค่า widget ที่มี key ไว้ใน session_state เสมอ
        เมิน index=/value= ที่ส่งเข้าไปใหม่ทุกครั้งถ้า key เคย render มาก่อนแล้ว
        ต้องเซ็ต st.session_state[ans_key] ตรงๆก่อน rerun เท่านั้น ถึงจะอัปเดตค่าที่แสดงได้จริง
"""
from __future__ import annotations

import base64
import difflib
import html as html_lib
import io
import json
import logging
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
import streamlit as st
from google import genai
from google.genai import types

from style import inject_css, render_header

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ezexam")

st.set_page_config(page_title="EZEXAM | Auto Form System", page_icon="⚡", layout="centered")
inject_css()

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

TYPE_PAGE_BREAK = 8
TYPE_CHECKBOX = 4
TYPE_MULTIPLE_CHOICE = 2
TYPE_DROPDOWN = 3
TYPE_TEXT = 0
TYPE_PARAGRAPH = 1

CHUNK_SIZE = 3
MAX_PARALLEL_WORKERS = 2
MAX_MODEL_ATTEMPTS = 2
BACKOFF_SEC = [3, 6]
SUBMIT_TIMEOUT = 30
IMAGE_TIMEOUT = 10
MAX_IMAGE_DIM = 1024
MAX_IMAGE_DIM_TEXT = 1536
MAX_IMAGE_FILE_SIZE = 4 * 1024 * 1024
JPEG_QUALITY = 82

MODEL_CANDIDATES: List[str] = [
    "gemini-flash-latest",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.0-flash",
    "gemini-flash-lite-latest",
    "gemini-2.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

DEAD_KEY_SIGNALS = [
    "permission_denied",
    "403",
    "api_key_invalid",
    "invalid api key",
    "unregistered callers",
    "unauthenticated",
    "401",
    "denied access",
]

BASE64_IMG_RE = re.compile(r'data:image/(?P<mime>[\w+]+);base64,(?P<data>[A-Za-z0-9+/=]+)')

GOOGLE_IMG_URL_RE = re.compile(
    r'https?://[a-zA-Z0-9.-]*(?:googleusercontent|ggpht)\.com/[^\s"\'\\<>]+'
)

try:
    _ = types.ThinkingConfig
    THINKING_CONFIG_AVAILABLE = True
except Exception:
    THINKING_CONFIG_AVAILABLE = False


def _load_api_keys() -> List[str]:
    keys = []
    for k in st.secrets:
        if "GEMINI_API_KEY" in k:
            val = st.secrets[k]
            if isinstance(val, str) and val.strip():
                keys.append(val.strip())
            elif isinstance(val, list):
                keys.extend([str(v).strip() for v in val if str(v).strip()])
    return keys


api_keys = _load_api_keys()
if not api_keys:
    st.error("ระบบยังไม่ได้ตั้งค่า API Key (GEMINI_API_KEY)")
    st.stop()


@dataclass
class QuestionImage:
    source: str
    url: Optional[str]
    data: Optional[bytes]
    mime_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    status: str = "ok"
    error: Optional[str] = None

    def is_ready(self) -> bool:
        return self.data is not None and len(self.data) > 0


@dataclass
class Question:
    entry_id: str
    title: str
    description: str
    choices: List[str]
    is_multi: bool
    is_required: bool
    page_index: int
    images: List[QuestionImage] = field(default_factory=list)
    branch_map: Dict[str, int] = field(default_factory=dict)
    choice_images: Dict[int, List[QuestionImage]] = field(default_factory=dict)
    q_type: int = TYPE_TEXT


def safe_get(obj: Any, path: List[Union[int, str]], default: Any = None) -> Any:
    try:
        for p in path:
            if obj is None:
                return default
            obj = obj[p]
        return obj
    except Exception:
        return default


def clean_text(text: Any) -> str:
    if text is None:
        return ""
    s = str(text)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def extract_base64_images(text: str) -> List[Tuple[str, bytes]]:
    results = []
    for m in BASE64_IMG_RE.finditer(text):
        mime = m.group("mime")
        data_str = m.group("data")
        try:
            data = base64.b64decode(data_str)
            results.append((f"image/{mime}", data))
        except Exception:
            pass
    return results


def normalize_google_image_url(url: str) -> str:
    url = url.rstrip('\\').rstrip('/')
    base = re.sub(r'=(?:w\d+(?:-h\d+)?|h\d+|s\d+)(?:-[a-zA-Z]\w*)*$', '', url)
    return base + '=s1024'


def validate_image(raw_bytes: bytes) -> Tuple[bool, Optional[str], Optional[Tuple[int, int]]]:
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw_bytes))
        img.verify()
        img = Image.open(io.BytesIO(raw_bytes))
        return True, img.format, img.size
    except Exception:
        return False, None, None


def compress_image(
    raw_bytes: bytes,
    max_dim: int = MAX_IMAGE_DIM,
    quality: int = JPEG_QUALITY,
    max_file_size: int = MAX_IMAGE_FILE_SIZE,
) -> Tuple[Optional[bytes], Optional[str], str]:
    try:
        from PIL import Image, ExifTags
    except ImportError:
        return None, None, "failed"

    if len(raw_bytes) < 100:
        return None, None, "failed"

    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception:
        return None, None, "failed"

    original_mode = img.mode

    try:
        if hasattr(img, '_getexif') and img._getexif():
            exif = dict(img._getexif().items())
            orientation = next((k for k, v in ExifTags.TAGS.items() if v == 'Orientation'), None)
            if orientation and orientation in exif:
                val = exif[orientation]
                if val == 3:
                    img = img.rotate(180, expand=True)
                elif val == 6:
                    img = img.rotate(270, expand=True)
                elif val == 8:
                    img = img.rotate(90, expand=True)
    except Exception:
        pass

    if original_mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGBA")

    if original_mode != "RGBA":
        img = img.convert("RGB")

    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)

    best_data = None
    best_mime = "image/jpeg"
    status = "ok"

    for q in [quality, max(60, quality - 10), max(50, quality - 20), 45]:
        buf = io.BytesIO()
        try:
            if original_mode == "RGBA":
                img.save(buf, "PNG", optimize=True)
                best_mime = "image/png"
            else:
                img.save(buf, "JPEG", quality=q, optimize=True)
                best_mime = "image/jpeg"
            data = buf.getvalue()
            if len(data) <= max_file_size:
                best_data = data
                if q < quality:
                    status = "compressed"
                break
        except Exception:
            continue

    if best_data is None:
        img.thumbnail((max_dim // 2, max_dim // 2), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=40, optimize=True)
        best_data = buf.getvalue()
        status = "compressed"

    return best_data, best_mime, status


def process_image_from_url(url: Optional[str], raw_bytes: Optional[bytes] = None) -> QuestionImage:
    if raw_bytes is None and url:
        try:
            r = requests.get(url, headers=UA, timeout=IMAGE_TIMEOUT)
            if r.status_code == 200 and len(r.content) > 100:
                raw_bytes = r.content
        except Exception:
            pass

    if raw_bytes is None:
        return QuestionImage(
            source="question", url=url, data=None, mime_type="image/jpeg",
            status="failed", error="ดาวน์โหลดรูปไม่ได้",
        )

    valid, fmt, size = validate_image(raw_bytes)
    if not valid:
        return QuestionImage(
            source="question", url=url, data=None, mime_type="image/jpeg",
            status="failed", error="ไฟล์ไม่ใช่รูปภาพ",
        )

    max_dim = MAX_IMAGE_DIM_TEXT if fmt in ("PNG", "GIF", "BMP") else MAX_IMAGE_DIM
    data, mime, status = compress_image(raw_bytes, max_dim=max_dim)

    if data is None:
        return QuestionImage(
            source="question", url=url, data=None, mime_type="image/jpeg",
            status="failed", error="บีบอัดรูปไม่ได้",
        )

    return QuestionImage(
        source="question", url=url, data=data, mime_type=mime,
        width=size[0] if size else None, height=size[1] if size else None,
        status=status,
    )


def _download_google_image_url(raw_url: str) -> QuestionImage:
    normalized = normalize_google_image_url(raw_url)
    for candidate in dict.fromkeys([normalized, raw_url]):
        img = process_image_from_url(candidate)
        if img.is_ready():
            return img
    return process_image_from_url(raw_url)


def extract_images_from_entry(
    entry: Any,
) -> Tuple[List[QuestionImage], Dict[int, List[QuestionImage]]]:
    question_images: List[QuestionImage] = []
    choice_images: Dict[int, List[QuestionImage]] = {}

    if not entry:
        return question_images, choice_images

    entry_json = json.dumps(entry, ensure_ascii=False)
    choices_raw = safe_get(entry, [4, 0, 1])

    choice_urls: set = set()
    if choices_raw and isinstance(choices_raw, list):
        for choice in choices_raw:
            if not choice:
                continue
            choice_json = json.dumps(choice, ensure_ascii=False)
            for raw_url in GOOGLE_IMG_URL_RE.findall(choice_json):
                choice_urls.add(raw_url)

    seen_urls: set = set()

    for mime, data in extract_base64_images(entry_json):
        valid, fmt, size = validate_image(data)
        if valid:
            processed, out_mime, status = compress_image(data)
            if processed:
                question_images.append(QuestionImage(
                    source="question", url=None, data=processed, mime_type=out_mime,
                    width=size[0] if size else None, height=size[1] if size else None,
                    status=status,
                ))

    for raw_url in GOOGLE_IMG_URL_RE.findall(entry_json):
        if raw_url in choice_urls or raw_url in seen_urls:
            continue
        seen_urls.add(raw_url)
        question_images.append(_download_google_image_url(raw_url))

    if choices_raw and isinstance(choices_raw, list):
        for ci, choice in enumerate(choices_raw):
            if not choice:
                continue
            choice_json = json.dumps(choice, ensure_ascii=False)

            for mime, data in extract_base64_images(choice_json):
                valid, fmt, size = validate_image(data)
                if valid:
                    processed, out_mime, status = compress_image(data)
                    if processed:
                        choice_images.setdefault(ci, []).append(QuestionImage(
                            source="choice", url=None, data=processed, mime_type=out_mime,
                            width=size[0] if size else None, height=size[1] if size else None,
                            status=status,
                        ))

            seen_choice_urls: set = set()
            for raw_url in GOOGLE_IMG_URL_RE.findall(choice_json):
                if raw_url in seen_choice_urls:
                    continue
                seen_choice_urls.add(raw_url)
                choice_images.setdefault(ci, []).append(_download_google_image_url(raw_url))

    return question_images, choice_images


def compute_image_stats(questions: List["Question"]) -> Tuple[int, int, int, int]:
    q_with_images = sum(1 for q in questions if q.images)
    q_with_ready = sum(1 for q in questions if any(img.is_ready() for img in q.images))
    total_found = sum(len(q.images) for q in questions)
    total_ready = sum(sum(1 for img in q.images if img.is_ready()) for q in questions)
    return q_with_images, q_with_ready, total_found, total_ready


def check_personal_info(
    q_title: str,
    choices: List[str],
    my_name: str,
    my_student_id: str,
    my_no: str,
    my_class: str,
) -> Optional[Tuple[str, str, str]]:
    clean_title = re.sub(r'^\*?\*?(?:ข้อ\s*\d+[\s.:-]*)?', '', q_title.strip()).strip().rstrip('*').strip()
    title_lower = clean_title.lower()
    if len(clean_title) > 35:
        return None

    exam_stopwords = [
        "สาร", "เคมี", "ดาว", "วิทยาศาสตร์", "โรค", "องค์กร", "กษัตริย์", "ธาตุ",
        "เมือง", "ประเทศ", "วรรณคดี", "ผู้แต่ง", "หัวใจ", "บรรยากาศ", "ผิวหนัง",
        "ปฏิบัติการ", "ดิน", "หิน", "เชื่อม", "เครือข่าย", "อินเทอร์เน็ต", "เว็บ",
        "จัดเป็น", "คืออะไร", "ข้อใด", "หมายถึง", "ตัวอักษรย่อ", "สมการ", "ปฏิกิริยา",
    ]
    if any(sw in title_lower for sw in exam_stopwords):
        return None

    if my_name and any(k in title_lower for k in ["ชื่อ", "นามสกุล", "สกุล", "name", "fullname"]):
        return (q_title, my_name, "ชื่อ-นามสกุล")

    if my_student_id and any(k in title_lower for k in ["เลขประจำตัว", "รหัสนักเรียน", "student id", "student_id", "id number"]):
        return (q_title, my_student_id, "เลขประจำตัว")

    if my_no and (any(k in title_lower for k in ["เลขที่", "ลำดับที่"]) or re.search(r'\bno\.?\s*\d*\b', title_lower)):
        return (q_title, my_no, "เลขที่")

    if my_class and any(k in title_lower for k in ["ชั้น", "ห้อง", "มัธยม", "classroom", "room"]):
        best_val = my_class
        if choices:
            for c in choices:
                c_str = str(c).strip()
                if c_str == my_class.strip() or c_str in my_class or my_class.endswith(c_str):
                    best_val = c_str
                    break
        return (q_title, best_val, "ชั้น/ห้อง")

    return None


def normalize_choice(text: str) -> str:
    s = str(text).strip()
    s = re.sub(r'^(?:ข้อ\s*)?[\(\[]?([ก-ฮa-zA-Z0-9]+)[\)\].]?\s*', r'\1 ', s)
    return s.strip()


def match_choice(ai_answer: Any, choices: List[str]) -> Tuple[int, bool]:
    if not choices:
        return -1, False

    clean_choices = [str(c).strip() for c in choices]
    ai_clean = str(ai_answer).strip()
    if not ai_clean:
        return -1, False

    for i, c in enumerate(clean_choices):
        if c == ai_clean:
            return i, True

    ai_lower = ai_clean.lower()
    for i, c in enumerate(clean_choices):
        if c.lower() == ai_lower:
            return i, True

    letter_match = re.match(r'^(?:ข้อ\s*)?[\(\[]?([ก-ฮa-zA-Z0-9]+)[\)\].]?\s*(.*)$', ai_clean)
    if letter_match:
        letter = letter_match.group(1)
        for i, c in enumerate(clean_choices):
            m = re.match(r'^(?:ข้อ\s*)?[\(\[]?(' + re.escape(letter) + r')[\)\].]?\s*', c)
            if m:
                return i, True

    for i, c in enumerate(clean_choices):
        c_norm = normalize_choice(c)
        ai_norm = normalize_choice(ai_clean)
        if c_norm and ai_norm and (c_norm == ai_norm or c_norm.startswith(ai_norm) or ai_norm.startswith(c_norm)):
            return i, True

    close = difflib.get_close_matches(ai_clean, clean_choices, n=1, cutoff=0.65)
    if close:
        return clean_choices.index(close[0]), True

    if letter_match:
        letter = letter_match.group(1)
        for i, c in enumerate(clean_choices):
            m = re.match(r'^(?:ข้อ\s*)?[\(\[]?([ก-ฮa-zA-Z0-9]+)[\)\].]?\s*', c)
            if m and m.group(1).lower() == letter.lower():
                return i, True

    return -1, False


def fetch_form(form_url: str) -> Tuple[dict, str, str, str, str]:
    if "docs.google.com/forms" not in form_url:
        raise RuntimeError("ลิงก์นี้ไม่ใช่ Google Form")

    res = requests.get(form_url, allow_redirects=True, headers=UA, timeout=20)
    raw_html = res.text

    m = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>', raw_html, re.DOTALL)
    if not m:
        m = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*?\]);', raw_html, re.DOTALL)
    if not m:
        raise RuntimeError("อ่านโครงสร้างฟอร์มไม่ได้ (ไม่พบ FB_PUBLIC_LOAD_DATA_)")

    try:
        form_data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"แปลงโครงสร้างฟอร์มไม่ได้: {e}")

    fbzx = ""
    fvv = "1"
    fbzx_m = re.search(r'name="fbzx"\s+value="(\d+)"', raw_html)
    fvv_m = re.search(r'name="fvv"\s+value="(\d+)"', raw_html)
    if fbzx_m:
        fbzx = fbzx_m.group(1)
    if fvv_m:
        fvv = fvv_m.group(1)

    submit_url = form_url.replace("viewform", "formResponse") if "viewform" in form_url else (
        form_url if "formResponse" in form_url else form_url.rstrip("/") + "/formResponse"
    )

    return form_data, fbzx, fvv, raw_html, submit_url


def parse_form(
    form_data: Any,
    raw_html: str,
    my_name: str,
    my_student_id: str,
    my_no: str,
    my_class: str,
) -> Tuple[List[Question], Dict[str, Tuple[str, str, str]], List[int], int]:
    entries = safe_get(form_data, [1, 1], [])
    if not entries:
        if isinstance(form_data, list) and len(form_data) > 1 and isinstance(form_data[1], list) and len(form_data[1]) > 1:
            entries = form_data[1][1]
        elif isinstance(form_data, list) and len(form_data) > 1:
            entries = form_data[1]

    if not isinstance(entries, list):
        raise RuntimeError("ไม่พบรายการคำถามในฟอร์ม")

    questions: List[Question] = []
    personal_data_map: Dict[str, Tuple[str, str, str]] = {}

    pages_meta = [{"own_id": None, "next_raw": None}]
    page_id_to_index: Dict[Any, int] = {}
    current_page = 0

    for item in entries:
        if not item or len(item) < 4:
            continue

        q_type = item[3]
        if q_type == TYPE_PAGE_BREAK:
            current_page += 1
            own_id = item[0]
            next_raw = safe_get(item, [5])
            pages_meta.append({"own_id": own_id, "next_raw": next_raw})
            page_id_to_index[own_id] = current_page
            continue

        if q_type in (9, 10, 11):
            continue
        if len(item) < 5 or not item[4]:
            continue

        entry_id = safe_get(item, [4, 0, 0])
        if not entry_id:
            continue
        entry_id = "entry." + str(entry_id)

        q_title = clean_text(safe_get(item, [1], ""))
        q_desc = clean_text(safe_get(item, [2], ""))
        full_title = (q_title + " " + q_desc).strip()

        choices_raw = safe_get(item, [4, 0, 1])
        choices = []
        if choices_raw and isinstance(choices_raw, list):
            choices = [clean_text(c[0]) for c in choices_raw if c and len(c) > 0 and c[0]]

        is_multi = q_type == TYPE_CHECKBOX
        is_required = bool(safe_get(item, [4, 0, 2], False)) or bool(safe_get(item, [5], False))

        p_info = check_personal_info(full_title, choices, my_name, my_student_id, my_no, my_class)
        if p_info:
            personal_data_map[entry_id] = p_info
            continue

        q_images, c_images = extract_images_from_entry(item)

        branch_map: Dict[str, int] = {}
        if choices_raw and isinstance(choices_raw, list):
            for c in choices_raw:
                if c and len(c) > 2 and c[2] is not None:
                    if c[2] <= 0:
                        branch_map[str(c[0])] = -1
                    elif c[2] in page_id_to_index:
                        branch_map[str(c[0])] = page_id_to_index[c[2]]

        questions.append(Question(
            entry_id=entry_id,
            title=full_title,
            description=q_desc,
            choices=choices,
            is_multi=is_multi,
            is_required=is_required,
            page_index=current_page,
            images=q_images,
            branch_map=branch_map,
            choice_images=c_images,
            q_type=q_type,
        ))

    default_next: List[int] = []
    for i, meta in enumerate(pages_meta):
        nxt = i + 1 if i + 1 < len(pages_meta) else -1
        if meta["next_raw"] is not None:
            if meta["own_id"] is not None and meta["next_raw"] == meta["own_id"]:
                nxt = -1
            elif meta["next_raw"] in page_id_to_index:
                nxt = page_id_to_index[meta["next_raw"]]
        default_next.append(nxt)

    page_count = len(pages_meta)
    return questions, personal_data_map, default_next, page_count


def simulate_page_history(
    questions: List[Question],
    final_answers: Dict[str, Any],
    default_next: List[int],
    page_count: int,
) -> str:
    by_page: Dict[int, List[Question]] = {}
    for q in questions:
        by_page.setdefault(q.page_index, []).append(q)

    visited = [0]
    current = 0
    guard = 0

    while guard < page_count + 5:
        guard += 1
        nxt = default_next[current] if current < len(default_next) else -1

        for q in by_page.get(current, []):
            if q.branch_map:
                ans = final_answers.get(q.entry_id)
                if isinstance(ans, list):
                    ans = ans[0] if ans else None
                if ans is not None and str(ans) in q.branch_map:
                    nxt = q.branch_map[str(ans)]
                    break

        if nxt < 0 or nxt in visited:
            break
        visited.append(nxt)
        current = nxt

    return ",".join(str(p) for p in visited)


def is_dead_key_error(msg: str) -> bool:
    msg_l = msg.lower()
    return any(s in msg_l for s in DEAD_KEY_SIGNALS)


def is_daily_quota_error(msg: str) -> bool:
    msg_l = msg.lower()
    if "429" not in msg_l and "resource_exhausted" not in msg_l:
        return False
    compact = msg_l.replace("_", "").replace("-", "")
    return "perday" in compact


def is_quota_or_transient_error(msg: str) -> bool:
    msg_l = msg.lower()
    if "429" in msg_l or "resource_exhausted" in msg_l or "quota" in msg_l:
        return True
    if any(code in msg_l for code in ["503", "504", "502", "500", "deadline"]):
        return True
    return False


def verify_model_works(api_key: str, model_name: str) -> Tuple[bool, str]:
    try:
        client = genai.Client(api_key=api_key)
        client.models.generate_content(
            model=model_name,
            contents=[types.Part.from_text(text="ping")],
            config=types.GenerateContentConfig(max_output_tokens=5),
        )
        return True, "ok"
    except Exception as e:
        msg = str(e)
        msg_l = msg.lower()
        model_bad_signals = [
            "404", "not_found", "no longer available", "not supported",
            "does not exist", "is not found", "unsupported model",
        ]
        if is_dead_key_error(msg_l):
            return False, "key_dead"
        if any(s in msg_l for s in model_bad_signals):
            return False, "model_bad"
        return True, "transient_error"


@st.cache_resource(ttl=1800, show_spinner=False)
def pick_model_and_healthy_keys(keys: Tuple[str, ...]) -> Tuple[Optional[str], List[str], List[str]]:
    logs: List[str] = []
    if not keys:
        return None, [], ["❌ ไม่มี API Key"]

    chosen_model: Optional[str] = None

    for model in MODEL_CANDIDATES:
        ok, reason = verify_model_works(keys[0], model)
        if ok:
            chosen_model = model
            break
        if reason == "key_dead":
            for alt_key in keys[1:]:
                ok2, reason2 = verify_model_works(alt_key, model)
                if ok2:
                    chosen_model = model
                    break
            if chosen_model:
                break

    if not chosen_model:
        logs.append("❌ ไม่พบโมเดลที่ใช้งานได้เลยกับคีย์ใดๆ")
        return None, [], logs

    logs.append(f"✅ ใช้โมเดลหลัก: {chosen_model} (จะสลับโมเดลอื่นอัตโนมัติถ้าโควตาต่อวันหมด)")

    healthy_keys: List[str] = []
    for i, key in enumerate(keys):
        ok, reason = verify_model_works(key, chosen_model)
        masked = key[:6] + "..." + key[-4:] if len(key) > 12 else "***"
        if ok:
            healthy_keys.append(key)
            logs.append(f"✅ Key #{i+1} ({masked}): ใช้งานได้")
        else:
            if reason == "key_dead":
                logs.append(f"⛔ Key #{i+1} ({masked}): ถูกปฏิเสธการเข้าถึง — ตัดออกจากการใช้งาน")
            else:
                logs.append(f"⚠️ Key #{i+1} ({masked}): ตรวจไม่ผ่าน ({reason})")

    if not healthy_keys:
        logs.append("❌ ไม่มีคีย์ใดใช้งานได้เลย")
        return chosen_model, [], logs

    return chosen_model, healthy_keys, logs


def build_system_instruction(exam_context: str) -> str:
    ctx = exam_context.strip() if exam_context else "ไม่มีบริบทเพิ่มเติม"
    return f"""คุณคือผู้ช่วยตอบข้อสอบอัตโนมัติที่แม่นยำและระมัดระวัง

บริบทข้อสอบ: {ctx}

กฎที่ต้องปฏิบัติ:
1. อ่านคำถามและรูปประกอบให้ละเอียด
2. ถ้าคำถามมีตัวเลือก ให้ตอบเป็นข้อความของตัวเลือกนั้นเป๊ะๆ (เช่น "ก. แมว" ไม่ใช่แค่ "ก")
3. ถ้าเป็นคำถามเติมคำ/ข้อความ ให้ตอบเป็นข้อความสั้นที่ถูกต้อง
4. ถ้าเป็นคำถามหลายคำตอบ (เลือกได้หลายข้อ / checkbox) ให้ตอบเป็น array ของข้อความ เช่น ["ก. แมว", "ข. หมา"]
5. ให้ confidence 0-100
6. อธิบาย reasoning สั้นๆ (ภาษาไทย)
7. ตอบเป็น JSON ตามรูปแบบนี้เท่านั้น:
{{
  "answers": [
    {{"entry_id": "entry.123456", "answer": "คำตอบ", "confidence": 85, "reasoning": "..."}},
    {{"entry_id": "entry.789012", "answer": ["ตัวเลือก1", "ตัวเลือก2"], "confidence": 70, "reasoning": "..."}}
  ]
}}
8. หากไม่แน่ใจ ให้ตอบตัวเลือกที่น่าจะถูกที่สุดพร้อม confidence ต่ำ
"""


def build_question_parts(idx: int, q: Question) -> List[types.Part]:
    parts: List[types.Part] = []

    text = f"\n--- ข้อ {idx} (ID: {q.entry_id}) ---\n"
    text += f"คำถาม: {q.title}\n"
    if q.is_multi:
        text += "ประเภท: เลือกได้หลายคำตอบ (ตอบเป็น array)\n"
    elif q.choices:
        text += "ประเภท: เลือกคำตอบเดียว\n"
    else:
        text += "ประเภท: คำตอบอิสระ\n"

    if q.choices:
        text += "ตัวเลือก:\n"
        for ci, choice in enumerate(q.choices, 1):
            text += f"  {ci}. {choice}\n"

    if q.images and not any(img.is_ready() for img in q.images):
        text += "(หมายเหตุ: คำถามนี้มีรูปภาพประกอบ แต่ระบบดึงรูปไม่สำเร็จ)\n"

    parts.append(types.Part.from_text(text=text))

    for img in q.images:
        if img.is_ready():
            parts.append(types.Part.from_bytes(data=img.data, mime_type=img.mime_type))

    return parts


def parse_ai_response(resp_text: str) -> Dict[str, Any]:
    raw = resp_text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    matches = re.findall(r'\{.*\}', raw, re.DOTALL)
    if matches:
        for m in sorted(matches, key=len, reverse=True):
            try:
                data = json.loads(m)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue

    matches = re.findall(r'\[.*\]', raw, re.DOTALL)
    if matches:
        for m in sorted(matches, key=len, reverse=True):
            try:
                arr = json.loads(m)
                if isinstance(arr, list):
                    return {"answers": arr}
            except Exception:
                continue

    raise RuntimeError(f"ไม่สามารถแปลงคำตอบ AI ได้: {raw[:200]}")


def call_gemini_chunk_with_key(
    api_key: str,
    exam_context: str,
    chunk: List[Tuple[int, Question]],
    model_name: str,
) -> Dict[str, Any]:
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=120000))

    contents: List[types.Part] = [types.Part.from_text(text=build_system_instruction(exam_context))]
    for idx, q in chunk:
        contents.extend(build_question_parts(idx, q))

    gen_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        max_output_tokens=4096,
        temperature=0.1,
        top_p=0.95,
    )

    if THINKING_CONFIG_AVAILABLE:
        try:
            gen_config.thinking_config = types.ThinkingConfig(thinking_level="low")
        except Exception:
            pass

    resp = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=gen_config,
    )

    if not resp or not resp.text:
        raise RuntimeError("โมเดลตอบกลับเป็นค่าว่าง")

    data = parse_ai_response(resp.text)

    if "answers" not in data:
        raise RuntimeError("คำตอบไม่มี key 'answers'")

    result: Dict[str, Any] = {}
    for ans in data.get("answers", []):
        eid = ans.get("entry_id")
        if eid:
            result[eid] = {
                "answer": ans.get("answer", ""),
                "confidence": max(0, min(100, int(ans.get("confidence", 70)))),
                "reasoning": ans.get("reasoning", "ไม่มีคำอธิบาย"),
            }
    return result


def try_key_model(
    api_key: str,
    exam_context: str,
    chunk: List[Tuple[int, Question]],
    model_name: str,
) -> Tuple[str, Any]:
    last_err: Optional[Exception] = None
    for attempt in range(MAX_MODEL_ATTEMPTS):
        try:
            data = call_gemini_chunk_with_key(api_key, exam_context, chunk, model_name)
            return "ok", data
        except Exception as err:
            msg = str(err)
            last_err = err

            if is_dead_key_error(msg):
                return "key_dead", err

            if is_daily_quota_error(msg):
                return "daily_exhausted", err

            if is_quota_or_transient_error(msg):
                if attempt < MAX_MODEL_ATTEMPTS - 1:
                    time.sleep(BACKOFF_SEC[min(attempt, len(BACKOFF_SEC) - 1)])
                    continue
                return "transient_fail", err

            return "other_fail", err

    return "transient_fail", last_err


def call_gemini_chunk(
    keys: List[str],
    start_key_idx: int,
    exam_context: str,
    chunk: List[Tuple[int, Question]],
    model_candidates: List[str],
    bad_keys: set,
    bad_keys_lock: threading.Lock,
    exhausted: set,
    exhausted_lock: threading.Lock,
) -> Tuple[Dict[str, Any], str]:
    n = len(keys)
    last_err: Optional[Exception] = None

    for offset in range(n):
        key_idx = (start_key_idx + offset) % n
        key = keys[key_idx]

        with bad_keys_lock:
            if key in bad_keys:
                continue

        for model_name in model_candidates:
            with exhausted_lock:
                if (key, model_name) in exhausted:
                    continue

            status, result = try_key_model(key, exam_context, chunk, model_name)

            if status == "ok":
                return result, model_name

            if status == "key_dead":
                with bad_keys_lock:
                    bad_keys.add(key)
                last_err = result
                break

            if status == "daily_exhausted":
                with exhausted_lock:
                    exhausted.add((key, model_name))
                last_err = result
                continue

            last_err = result
            continue

    raise last_err or RuntimeError("ไม่มีคีย์/โมเดลใดใช้งานได้เลย (โควตาอาจหมดหมดทุกทางแล้ว)")


def analyze_all(
    questions: List[Question],
    keys: List[str],
    exam_context: str,
    progress_cb=None,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    indexed = list(enumerate(questions, 1))
    chunks = [indexed[i:i + CHUNK_SIZE] for i in range(0, len(indexed), CHUNK_SIZE)]
    results: Dict[str, Any] = {}
    errors: List[str] = []
    debug_logs: List[str] = []

    if not chunks:
        return results, errors, debug_logs

    model_name, healthy_keys, health_logs = pick_model_and_healthy_keys(tuple(keys))
    debug_logs.extend(health_logs)

    if not model_name or not healthy_keys:
        errors.append("ไม่พบโมเดล/คีย์ที่ใช้งานได้เลย (API Key ถูกปฏิเสธการเข้าถึง)")
        return results, errors, debug_logs

    model_order = [model_name] + [m for m in MODEL_CANDIDATES if m != model_name]

    bad_keys: set = set()
    bad_keys_lock = threading.Lock()
    exhausted: set = set()
    exhausted_lock = threading.Lock()

    workers = min(MAX_PARALLEL_WORKERS, len(healthy_keys), len(chunks))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                call_gemini_chunk,
                healthy_keys,
                i % len(healthy_keys),
                exam_context,
                chunk,
                model_order,
                bad_keys,
                bad_keys_lock,
                exhausted,
                exhausted_lock,
            ): i
            for i, chunk in enumerate(chunks)
        }

        done = 0
        for fut in as_completed(futures):
            chunk_idx = futures[fut]
            done += 1
            if progress_cb:
                progress_cb(done, len(chunks))

            try:
                chunk_result, used_model = fut.result()
                if isinstance(chunk_result, dict):
                    results.update(chunk_result)
                    tag = f" (โมเดล: {used_model})" if used_model != model_name else ""
                    debug_logs.append(f"✅ Chunk {chunk_idx+1}/{len(chunks)}: ได้ {len(chunk_result)} ข้อ{tag}")
                else:
                    errors.append("ผลลัพธ์จาก AI ไม่ถูกต้อง")
                    debug_logs.append(f"❌ Chunk {chunk_idx+1}/{len(chunks)}: ผลลัพธ์ไม่ใช่ dict")
            except Exception as e:
                err_msg = f"Chunk {chunk_idx+1}/{len(chunks)} error: {str(e)}"
                errors.append(str(e))
                debug_logs.append(f"❌ {err_msg}")

    if bad_keys:
        debug_logs.append(f"⛔ พบคีย์ตายระหว่างทำงานเพิ่ม {len(bad_keys)} ตัว (ถูกตัดออกจากการใช้งานแล้ว)")

    if exhausted:
        exhausted_models = sorted(set(m for _, m in exhausted))
        debug_logs.append(f"🔁 โควตาต่อวันหมดสำหรับบางคู่ (คีย์,โมเดล) — สลับไปโมเดลอื่นแล้ว ({', '.join(exhausted_models)})")

    all_combo_exhausted = len(exhausted) >= len(healthy_keys) * len(model_order)
    if all_combo_exhausted and results == {}:
        debug_logs.append(
            "🛑 โควตาฟรีต่อวันหมดสำหรับ 'ทุกคีย์ x ทุกโมเดล' แล้ว "
            "ต้องรอถึงเที่ยงคืนตามเวลา Pacific Time หรือเพิ่ม API Key ที่ใช้งานได้ หรือเปิด Billing"
        )

    return results, errors, debug_logs


def build_submit_payload(
    personal_data_map: Dict[str, Tuple[str, str, str]],
    questions: List[Question],
    final_answers: Dict[str, Any],
    fbzx: str,
    fvv: str,
    page_history: str,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fbzx": fbzx,
        "fvv": fvv,
        "pageHistory": page_history,
    }

    for entry_id, info in personal_data_map.items():
        payload[entry_id] = info[1]

    for q in questions:
        entry_id = q.entry_id
        ans = final_answers.get(entry_id, "")

        if q.choices:
            if q.is_multi:
                if isinstance(ans, list):
                    valid = []
                    for a in ans:
                        idx, matched = match_choice(a, q.choices)
                        if matched:
                            valid.append(q.choices[idx])
                        elif a in q.choices:
                            valid.append(a)
                    payload[entry_id] = valid
                else:
                    idx, matched = match_choice(ans, q.choices)
                    payload[entry_id] = [q.choices[idx]] if matched else []
            else:
                idx, matched = match_choice(ans, q.choices)
                payload[entry_id] = q.choices[idx] if matched else ans
        else:
            payload[entry_id] = ans

    return payload


def check_submit_success(response_text: str, status_code: int) -> Tuple[bool, Optional[str]]:
    if status_code != 200:
        return False, f"HTTP {status_code}"

    success_markers = [
        "freebirdformviewerviewresponseconfirmationmessage",
        "บันทึกคำตอบ",
        "response received",
        "thank you",
        "ขอบคุณ",
        "สำเร็จ",
    ]
    if any(marker in response_text.lower() for marker in success_markers):
        return True, None

    if "FB_PUBLIC_LOAD_DATA_" in response_text or 'role="form"' in response_text:
        return False, "ฟอร์มยังแสดงผลอยู่ (อาจมีข้อผิดพลาด)"

    return True, None


def submit_form(submit_url: str, payload: Dict[str, Any], max_retries: int = 2) -> Tuple[bool, str]:
    for attempt in range(max_retries + 1):
        try:
            res = requests.post(submit_url, data=payload, headers=UA, timeout=SUBMIT_TIMEOUT)
            success, err = check_submit_success(res.text, res.status_code)
            if success:
                return True, "ส่งข้อมูลสำเร็จ"
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            return False, err or f"ส่งไม่สำเร็จ (HTTP {res.status_code})"
        except requests.exceptions.Timeout:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            return False, "หมดเวลาการเชื่อมต่อ"
        except Exception as e:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            return False, f"ข้อผิดพลาด: {str(e)}"

    return False, "ไม่สามารถส่งข้อมูลได้"


def get_ai_answer(ai_answers: Dict[str, Any], entry_id: str) -> Dict[str, Any]:
    data = ai_answers.get(entry_id, {})
    if isinstance(data, dict):
        return data
    return {"answer": str(data) if data else "", "confidence": 0, "reasoning": "AI ไม่ได้ตอบข้อนี้"}


def apply_ai_answer_to_state(q: Question, ans_data: Dict[str, Any]) -> None:
    """
    เซ็ตค่าใน st.session_state ของ widget คำตอบโดยตรง

    สำคัญมาก: Streamlit จะ 'ยึด' ค่า widget ที่มี key ไว้ใน session_state เสมอ
    เมื่อ widget เคยถูก render มาก่อนแล้วครั้งหนึ่ง ทุกครั้งที่ render ซ้ำ (rerun)
    Streamlit จะ *เมิน* ค่า index=/value= ที่เราส่งเข้าไปใหม่ทันที แล้วใช้ค่าที่
    ค้างอยู่ใน session_state[key] แสดงแทนเสมอ — ต่อให้ ai_answers เปลี่ยนไปแล้วก็ตาม
    (นี่คือสาเหตุที่กด "วิเคราะห์ข้อนี้ใหม่" แล้วคำตอบบนจอไม่เปลี่ยน)

    วิธีแก้คือต้องเซ็ต st.session_state[key] ตรงๆ ก่อน rerun เท่านั้น
    """
    ans_key = f"ans_{q.entry_id}"
    ans = ans_data.get("answer", "")

    if q.choices:
        if q.is_multi:
            ans_list = ans if isinstance(ans, list) else ([ans] if ans else [])
            resolved: List[str] = []
            for a in ans_list:
                idx_m, matched = match_choice(a, q.choices)
                if matched:
                    resolved.append(q.choices[idx_m])
                elif a in q.choices:
                    resolved.append(a)
            st.session_state[ans_key] = resolved
        else:
            idx_m, matched = match_choice(ans, q.choices)
            st.session_state[ans_key] = q.choices[idx_m] if matched else None
    else:
        st.session_state[ans_key] = str(ans) if ans else ""


def confidence_color(score: int) -> str:
    if score >= 80:
        return "#5fe3d0"
    elif score >= 50:
        return "#e8c98a"
    else:
        return "#ff6b6b"


def render_image_status(img: QuestionImage):
    if img.status == "ok":
        return "✅"
    elif img.status == "compressed":
        return "⚡"
    elif img.status == "failed":
        return "❌"
    return "⏳"


render_header()

with st.container(border=True):
    st.markdown('<div class="glass-header">TARGET FORM LINK</div>', unsafe_allow_html=True)
    form_url = st.text_input("Form URL", placeholder="วางลิงก์ Google Form ที่นี่...", label_visibility="collapsed")

with st.container(border=True):
    st.markdown('<div class="glass-header">PERSONAL DATA & CONTEXT</div>', unsafe_allow_html=True)
    exam_context = st.text_area("EXAM CONTEXT", placeholder="เช่น ฟิสิกส์ ม.6 บทคลื่น...", height=68)
    debug_mode = st.checkbox("โหมด debug", value=False)

    col1, col2 = st.columns(2)
    with col1:
        my_name = st.text_input("FULL NAME", placeholder="ชื่อ-นามสกุล")
        my_no = st.text_input("CLASS NUMBER", placeholder="เลขที่")
    with col2:
        my_student_id = st.text_input("STUDENT ID", placeholder="เลขประจำตัว")
        my_class = st.text_input("CLASSROOM", placeholder="เช่น 6/3")

if "manual_images" not in st.session_state:
    st.session_state["manual_images"] = {}

if st.button("INITIATE ANALYSIS", type="primary", use_container_width=True):
    if not form_url:
        st.error("กรุณาใส่ลิงก์ Google Form ก่อน")
    else:
        with st.status("SYSTEM PROCESSING...", expanded=True) as status:
            try:
                for key in list(st.session_state.keys()):
                    if key.startswith("ans_"):
                        del st.session_state[key]

                st.write("🔍 กำลังอ่านโครงสร้างฟอร์ม...")
                form_data, fbzx, fvv, raw_html, submit_url = fetch_form(form_url)

                st.write("🧩 กำลังสกัดคำถามและดาวน์โหลดรูปภาพ...")
                questions, personal_data_map, default_next, page_count = parse_form(
                    form_data, raw_html, my_name, my_student_id, my_no, my_class
                )

                manual_images = st.session_state["manual_images"]
                for q in questions:
                    if q.entry_id in manual_images:
                        if not any(img.source == "manual_upload" for img in q.images):
                            q.images.append(manual_images[q.entry_id])

                parse_logs: List[str] = []
                qi_stat, qr_stat, ti_stat, tr_stat = compute_image_stats(questions)
                if qi_stat > 0:
                    parse_logs.append(
                        f"🖼️ พบคำถามที่มีรูปภาพ {qi_stat} ข้อ (รวม {ti_stat} รูป) — "
                        f"ดาวน์โหลด/ประมวลผลสำเร็จ {tr_stat}/{ti_stat} รูป (พร้อมใช้งาน {qr_stat} ข้อ)"
                    )
                    st.write(parse_logs[0])
                    if qr_stat < qi_stat:
                        warn_msg = f"⚠️ มี {qi_stat - qr_stat} ข้อที่ดึงรูปอัตโนมัติไม่ได้ — เลื่อนลงไปอัปโหลดรูปเองได้ที่ด้านล่างหลังวิเคราะห์เสร็จ"
                        parse_logs.append(warn_msg)
                        st.warning(warn_msg)

                st.write(f"🤖 AI กำลังวิเคราะห์ {len(questions)} ข้อ...")
                bar = st.progress(0.0)

                def ai_cb(done, total):
                    bar.progress(done / total, text=f"วิเคราะห์ {done}/{total}")

                ai_answers, ai_errors, debug_logs = analyze_all(
                    questions, api_keys, exam_context, ai_cb
                )
                debug_logs = parse_logs + debug_logs
                bar.empty()

                answered_count = sum(1 for q in questions if get_ai_answer(ai_answers, q.entry_id).get("answer"))
                unanswered_count = len(questions) - answered_count

                if ai_errors:
                    st.warning(f"มีปัญหาบางส่วน — AI ตอบได้ {answered_count}/{len(questions)} ข้อ")
                    with st.expander("ดูรายละเอียดข้อผิดพลาด", expanded=True):
                        for err in ai_errors:
                            st.code(err)
                    if unanswered_count > 0:
                        st.error(
                            f"⚠️ มี {unanswered_count} ข้อที่ AI ไม่ได้ตอบเลย "
                            "ถ้า Debug Logs บอกว่าโควตาต่อวันหมดทุกโมเดล/คีย์แล้ว "
                            "กรุณารอถึงเที่ยงคืน (เวลา Pacific Time) หรือเพิ่ม API Key ใหม่ หรือเปิด Billing"
                        )
                else:
                    st.success(f"✅ AI วิเคราะห์สำเร็จ {len(ai_answers)} ข้อ")

                st.session_state.update({
                    "questions": questions,
                    "personal_data_map": personal_data_map,
                    "ai_answers": ai_answers,
                    "fbzx": fbzx,
                    "fvv": fvv,
                    "default_next": default_next,
                    "page_count": page_count,
                    "exam_context": exam_context,
                    "submit_url": submit_url,
                    "debug_logs": debug_logs,
                })
                status.update(label="ANALYSIS COMPLETE", state="complete", expanded=False)

            except Exception as e:
                status.update(label="ERROR", state="error")
                logger.error(traceback.format_exc())
                st.error(f"เกิดข้อผิดพลาด: {str(e)}")


if "questions" in st.session_state:
    st.markdown('<div class="section-title">REVIEW & EDIT</div>', unsafe_allow_html=True)

    questions = st.session_state["questions"]
    ai_answers = st.session_state.get("ai_answers", {})
    personal_data_map = st.session_state.get("personal_data_map", {})
    debug_logs = st.session_state.get("debug_logs", [])
    manual_images = st.session_state["manual_images"]

    for q in questions:
        if q.entry_id in manual_images and not any(img.source == "manual_upload" for img in q.images):
            q.images.append(manual_images[q.entry_id])

    if st.session_state.get("debug_mode") or debug_mode:
        with st.expander("🔧 Debug Logs", expanded=True):
            for log in debug_logs:
                st.text(log)

    total_q = len(questions)
    answered = sum(1 for q in questions if get_ai_answer(ai_answers, q.entry_id).get("answer"))
    not_answered = total_q - answered
    avg_conf = 0
    if total_q > 0:
        avg_conf = sum(get_ai_answer(ai_answers, q.entry_id).get("confidence", 0) for q in questions) / total_q

    with st.container(border=True):
        st.markdown('<div class="glass-header">ANALYSIS SUMMARY</div>', unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("คำถามทั้งหมด", total_q)
        c2.metric("AI ตอบแล้ว", answered)
        c3.metric("AI ไม่ตอบ ⚠️", not_answered)
        c4.metric("ความมั่นใจเฉลี่ย", f"{avg_conf:.0f}%")
        if not_answered > 0:
            st.warning(f"⚠️ มี {not_answered} ข้อที่ AI ไม่ได้ตอบ กรุณาตอบเองในข้อที่มีเครื่องหมายเตือนสีแดง")

    if personal_data_map:
        with st.container(border=True):
            st.markdown('<div class="glass-header">AUTO-FILLED DATA</div>', unsafe_allow_html=True)
            items = list(personal_data_map.items())
            cols = st.columns(min(len(items), 2))
            for idx, (entry_id, info) in enumerate(items):
                cols[idx % len(cols)].text_input(info[2], value=info[1], key="input_" + entry_id, disabled=True)

    col_accept, col_reset = st.columns(2)
    with col_accept:
        if st.button("✅ ยอมรับคำตอบ AI ทั้งหมด", use_container_width=True):
            for q in questions:
                ans_data = get_ai_answer(ai_answers, q.entry_id)
                apply_ai_answer_to_state(q, ans_data)
            st.rerun()
    with col_reset:
        if st.button("🔄 รีเซ็ตคำตอบทั้งหมด", use_container_width=True):
            for q in questions:
                if f"ans_{q.entry_id}" in st.session_state:
                    del st.session_state[f"ans_{q.entry_id}"]
            st.rerun()

    for qi, q in enumerate(questions, 1):
        if not any(img.is_ready() for img in q.images):
            has_attempted = len(q.images) > 0
            looks_like_image_q = has_attempted or ("รูป" in q.title or "ภาพ" in q.title)
            if not looks_like_image_q:
                continue

            uploaded = st.file_uploader(
                f"📎 ข้อ {qi}: อัปโหลดรูปเอง (ระบบดึงรูปอัตโนมัติไม่สำเร็จสำหรับข้อนี้)",
                type=["jpg", "jpeg", "png", "webp"],
                key=f"upload_{q.entry_id}"
            )
            if uploaded:
                file_marker = getattr(uploaded, "file_id", None) or f"{uploaded.name}_{uploaded.size}"
                marker_key = f"_upload_marker_{q.entry_id}"
                if st.session_state.get(marker_key) != file_marker:
                    st.session_state[marker_key] = file_marker
                    new_img = QuestionImage(
                        source="manual_upload",
                        url=None,
                        data=uploaded.getvalue(),
                        mime_type=uploaded.type or "image/jpeg",
                        status="ok",
                    )
                    manual_images[q.entry_id] = new_img
                    st.session_state["manual_images"] = manual_images
                    q.images.append(new_img)
                    st.success(f"✅ อัปโหลดรูปข้อ {qi} สำเร็จ! กดปุ่ม '🔄 วิเคราะห์ข้อนี้ใหม่' ที่ข้อนั้นด้านล่าง")
                    st.rerun()

    for idx, q in enumerate(questions, 1):
        entry_id = q.entry_id
        ans_data = get_ai_answer(ai_answers, entry_id)
        default_val = ans_data.get("answer", "")
        confidence = ans_data.get("confidence", 0)
        reasoning = ans_data.get("reasoning", "")
        ai_has_answer = bool(default_val) and (not isinstance(default_val, list) or len(default_val) > 0)

        with st.container(border=True):
            header_html = f'<div class="q-title">{idx}. {html_lib.escape(q.title)}</div>'
            st.markdown(header_html, unsafe_allow_html=True)

            if q.images:
                st.markdown('<div class="image-gallery">', unsafe_allow_html=True)
                img_cols = st.columns(min(len(q.images), 3))
                for i, img in enumerate(q.images):
                    with img_cols[i % 3]:
                        if img.is_ready():
                            st.image(img.data, use_container_width=True, caption=f"รูป {i+1} {render_image_status(img)}")
                        else:
                            st.markdown(f'<div class="image-fallback">❌ โหลดรูปที่ {i+1} ไม่ได้ ({img.error or "ไม่ทราบสาเหตุ"})</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

                if any(img.is_ready() for img in q.images):
                    if st.button(f"🔄 วิเคราะห์ข้อ {idx} นี้ใหม่ (ใช้รูปล่าสุด)", key=f"reanalyze_{entry_id}"):
                        with st.spinner("AI กำลังวิเคราะห์ข้อนี้..."):
                            model_name, healthy_keys, _logs = pick_model_and_healthy_keys(tuple(api_keys))
                            if not model_name or not healthy_keys:
                                st.error("ไม่มีโมเดล/คีย์ที่ใช้งานได้ในขณะนี้")
                            else:
                                model_order = [model_name] + [m for m in MODEL_CANDIDATES if m != model_name]
                                bad_keys_local: set = set()
                                exhausted_local: set = set()
                                lock_local = threading.Lock()
                                try:
                                    result, used_model = call_gemini_chunk(
                                        healthy_keys, 0,
                                        st.session_state.get("exam_context", exam_context),
                                        [(idx, q)], model_order,
                                        bad_keys_local, lock_local,
                                        exhausted_local, lock_local,
                                    )
                                    if entry_id in result:
                                        ai_answers[entry_id] = result[entry_id]
                                        st.session_state["ai_answers"] = ai_answers
                                        # สำคัญ: ต้องเซ็ต widget state ตรงๆ ไม่งั้นหน้าจอจะไม่อัปเดต
                                        # (ดูคำอธิบายเต็มในฟังก์ชัน apply_ai_answer_to_state)
                                        apply_ai_answer_to_state(q, result[entry_id])
                                        st.success(f"✅ วิเคราะห์สำเร็จ (โมเดล: {used_model}) — คำตอบอัปเดตแล้ว")
                                    else:
                                        st.warning("AI ไม่ได้ตอบข้อนี้ ลองใหม่อีกครั้ง")
                                except Exception as e:
                                    st.error(f"เกิดข้อผิดพลาด: {e}")
                        st.rerun()

            if not ai_has_answer:
                st.markdown(
                    '<div style="background:#3a1414;border:1px solid #ff6b6b;border-radius:8px;'
                    'padding:8px 12px;margin-bottom:8px;color:#ff9b9b;font-size:0.9em;">'
                    '⚠️ AI ยังไม่ตอบข้อนี้ — กรุณาเลือก/พิมพ์คำตอบเอง'
                    '</div>',
                    unsafe_allow_html=True,
                )
            elif confidence > 0:
                color = confidence_color(confidence)
                st.markdown(
                    f'<div class="confidence-track"><div class="confidence-fill" style="width:{confidence}%;background:{color};"></div></div>',
                    unsafe_allow_html=True
                )
                st.markdown(f'<div class="confidence-label">ความมั่นใจ: {confidence}%</div>', unsafe_allow_html=True)
            if reasoning and ai_has_answer:
                st.markdown(f'<div class="reasoning-text">💡 {html_lib.escape(reasoning)}</div>', unsafe_allow_html=True)

            ans_key = f"ans_{entry_id}"

            if q.choices:
                if q.is_multi:
                    st.multiselect("คำตอบ (เลือกได้หลายข้อ)", q.choices, key=ans_key)
                else:
                    st.radio("คำตอบ", q.choices, key=ans_key)
            else:
                st.text_input("คำตอบ", key=ans_key)

    if st.button("TRANSMIT DATA", type="primary", use_container_width=True):
        with st.spinner("กำลังส่งข้อมูล..."):
            final_answers = {eid: info[1] for eid, info in personal_data_map.items()}
            missing_required = []

            for qidx, q in enumerate(questions, 1):
                val = st.session_state.get(f"ans_{q.entry_id}", "")
                final_answers[q.entry_id] = val
                if q.is_required and (not val or (isinstance(val, list) and not val)):
                    missing_required.append(f"ข้อ {qidx}")

            if missing_required:
                st.error(f"กรุณากรอกข้อบังคับให้ครบ: {', '.join(missing_required[:5])}{'...' if len(missing_required) > 5 else ''}")
            else:
                page_history = simulate_page_history(
                    questions, final_answers,
                    st.session_state["default_next"],
                    st.session_state["page_count"],
                )
                payload = build_submit_payload(
                    personal_data_map, questions, final_answers,
                    st.session_state["fbzx"],
                    st.session_state["fvv"],
                    page_history,
                )

                success, msg = submit_form(st.session_state["submit_url"], payload)
                if success:
                    st.success("🎉 " + msg)
                    st.balloons()
                else:
                    st.error("❌ " + msg)
                    with st.expander("ดู payload ที่ส่ง"):
                        st.json(payload)
