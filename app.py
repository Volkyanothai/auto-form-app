"""
app.py — EZEXAM Auto Form System (Phase 0+1 Overhaul)
======================================================
- Image Pipeline ใหม่: ดึงรูปหลายโดเมน, base64, fallback, จัดการ limits
- Form Parser ที่ robust ขึ้น
- Choice Matching ที่แม่นยำขึ้น
- AI Prompt มี JSON Schema ชัดเจน
- Submit + pageHistory ที่ถูกต้องขึ้น
- Review UI แสดงคำตอบ AI, confidence, reasoning
"""
from __future__ import annotations

import base64
import difflib
import html as html_lib
import io
import json
import logging
import re
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

# ═══════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ezexam")


# ═══════════════════════════════════════════════════════════
# Streamlit Config
# ═══════════════════════════════════════════════════════════
st.set_page_config(page_title="EZEXAM | Auto Form System", page_icon="⚡", layout="centered")
inject_css()


# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

TYPE_PAGE_BREAK = 8
TYPE_CHECKBOX = 4
TYPE_TEXT = 0
TYPE_PARAGRAPH = 1
TYPE_GRID = 2
TYPE_SCALE = 3
TYPE_DATE = 5
TYPE_TIME = 6

MODELS_TO_TRY = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
CHUNK_SIZE = 2
MAX_PARALLEL_WORKERS = 2
MAX_MODEL_ATTEMPTS = 3
BACKOFF_SEC = [4, 8, 15]
SUBMIT_TIMEOUT = 30
IMAGE_TIMEOUT = 12
MAX_IMAGE_DIM = 1024
MAX_IMAGE_DIM_TEXT = 1536
MAX_IMAGE_FILE_SIZE = 4 * 1024 * 1024  # 4MB
JPEG_QUALITY = 82

# Regex รูปภาพหลายรูปแบบ
IMG_URL_PATTERNS = [
    re.compile(r'https?://lh\d?\.?googleusercontent\.com/[^\s"\'<>\\)]+', re.IGNORECASE),
    re.compile(r'https?://\w+\.googleusercontent\.com/[^\s"\'<>\\)]+', re.IGNORECASE),
    re.compile(r'https?://drive\.google\.com/uc\?export=view&id=[\w-]+', re.IGNORECASE),
    re.compile(r'https?://\w+\.googleapis\.com/[^\s"\'<>\\)]+', re.IGNORECASE),
]
BASE64_IMG_RE = re.compile(r'data:image/(?P<mime>[\w+]+);base64,(?P<data>[A-Za-z0-9+/=]+)')

# ตรวจสอบว่า google-genai รองรับ thinking_config หรือไม่
try:
    _ = types.ThinkingConfig
    THINKING_CONFIG_AVAILABLE = True
except Exception:
    THINKING_CONFIG_AVAILABLE = False


# ═══════════════════════════════════════════════════════════
# API Keys
# ═══════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════
@dataclass
class QuestionImage:
    source: str  # "question" | "choice" | "header" | "fallback"
    url: Optional[str]
    data: Optional[bytes]
    mime_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    status: str = "ok"  # ok | compressed | failed | url_only
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


@dataclass
class ParsedForm:
    questions: List[Question]
    personal_data_map: Dict[str, Tuple[str, str, str]]
    default_next: List[int]
    page_count: int
    fbzx: str
    fvv: str
    submit_url: str
    raw_html: str


# ═══════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════
def safe_get(obj: Any, path: List[Union[int, str]], default: Any = None) -> Any:
    """เข้าถึง nested object อย่างปลอดภัย"""
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
    """แยก base64 images จากข้อความ"""
    results = []
    for m in BASE64_IMG_RE.finditer(text):
        mime = m.group("mime")
        data_str = m.group("data")
        try:
            data = base64.b64decode(data_str)
            results.append((f"image/{mime}", data))
        except Exception as e:
            logger.warning(f"Base64 decode failed: {e}")
    return results


def find_all_image_urls(text: str) -> List[str]:
    """หา image URLs ทุกรูปแบบจากข้อความ"""
    found = []
    for pattern in IMG_URL_PATTERNS:
        found.extend(pattern.findall(text))
    # กรองซ้ำ รักษาลำดับ
    seen = set()
    unique = []
    for url in found:
        url = url.rstrip('"\'\\),;> ')
        if url not in seen and len(url) > 10:
            seen.add(url)
            unique.append(url)
    return unique


# ═══════════════════════════════════════════════════════════
# Image Pipeline
# ═══════════════════════════════════════════════════════════
def validate_image(raw_bytes: bytes) -> Tuple[bool, Optional[str], Optional[Tuple[int, int]]]:
    """ตรวจสอบว่าเป็นไฟล์รูปภาพจริง และคืนขนาด"""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw_bytes))
        img.verify()
        img = Image.open(io.BytesIO(raw_bytes))
        return True, img.format, img.size
    except Exception as e:
        return False, None, None


def compress_image(
    raw_bytes: bytes,
    max_dim: int = MAX_IMAGE_DIM,
    quality: int = JPEG_QUALITY,
    max_file_size: int = MAX_IMAGE_FILE_SIZE,
) -> Tuple[Optional[bytes], Optional[str], str]:
    """
    บีบอัดรูปภาพให้เหมาะสมกับ Gemini
    คืน (data, mime_type, status)
    """
    try:
        from PIL import Image, ExifTags
    except ImportError:
        logger.error("PIL/Pillow ไม่ได้ติดตั้ง")
        return None, None, "failed"

    if len(raw_bytes) < 100:
        return None, None, "failed"

    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception as e:
        logger.warning(f"เปิดรูปไม่ได้: {e}")
        return None, None, "failed"

    original_format = img.format
    original_mode = img.mode

    # หมุนตาม EXIF
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

    # แปลงเป็น RGBA ก่อน แล้วค่อย RGB
    if original_mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGBA")

    # ตัดพื้นหลังขาวทึบออกเล็กน้อย (optional)
    if original_mode == "RGBA":
        # ไม่ทำอะไร เก็บโปร่งใส
        pass
    else:
        img = img.convert("RGB")

    # Resize
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)

    # บีบอัดวนลูปจนกว่าจะได้ขนาดที่เหมาะสม
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
        except Exception as e:
            logger.warning(f"บีบอัดรูปล้มเหลวที่ quality={q}: {e}")
            continue

    if best_data is None:
        # ลองลดขนาดลงอีก
        img.thumbnail((max_dim // 2, max_dim // 2), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=40, optimize=True)
        best_data = buf.getvalue()
        status = "compressed"

    return best_data, best_mime, status


def download_image(url: str, timeout: int = IMAGE_TIMEOUT) -> Optional[bytes]:
    """ดาวน์โหลดรูปภาพพร้อม fallback"""
    if not url or not url.startswith("http"):
        return None

    urls_to_try = [url]

    # แปลง Google Drive URL ถ้ามี
    if "drive.google.com" in url and "/file/d/" in url:
        m = re.search(r'/file/d/([\w-]+)', url)
        if m:
            urls_to_try.append(f"https://drive.google.com/uc?export=view&id={m.group(1)}")

    for try_url in urls_to_try:
        try:
            r = requests.get(try_url, headers=UA, timeout=timeout)
            if r.status_code == 200 and len(r.content) > 100:
                return r.content
        except Exception as e:
            logger.warning(f"ดาวน์โหลดรูปล้มเหลว {try_url}: {e}")
            continue
    return None


def process_image_from_url(url: Optional[str], raw_bytes: Optional[bytes] = None) -> QuestionImage:
    """ประมวลผลรูปภาพจาก URL หรือ bytes"""
    if raw_bytes is None and url:
        raw_bytes = download_image(url)

    if raw_bytes is None:
        return QuestionImage(
            source="question",
            url=url,
            data=None,
            mime_type="image/jpeg",
            status="url_only" if url else "failed",
            error="ดาวน์โหลดรูปไม่ได้",
        )

    valid, fmt, size = validate_image(raw_bytes)
    if not valid:
        return QuestionImage(
            source="question",
            url=url,
            data=None,
            mime_type="image/jpeg",
            status="failed",
            error="ไฟล์ที่ดาวน์โหลดไม่ใช่รูปภาพ",
        )

    # ถ้าเป็นรูปที่มีข้อความ ให้ใช้ความละเอียดสูงขึ้น
    max_dim = MAX_IMAGE_DIM_TEXT if fmt in ("PNG", "GIF", "BMP") else MAX_IMAGE_DIM

    data, mime, status = compress_image(raw_bytes, max_dim=max_dim)
    if data is None:
        return QuestionImage(
            source="question",
            url=url,
            data=None,
            mime_type="image/jpeg",
            status="failed",
            error="บีบอัดรูปไม่ได้",
        )

    return QuestionImage(
        source="question",
        url=url,
        data=data,
        mime_type=mime,
        width=size[0] if size else None,
        height=size[1] if size else None,
        status=status,
    )


def extract_images_from_entry(entry: Any, entry_index: int, global_urls: List[str]) -> Tuple[List[QuestionImage], Dict[int, List[QuestionImage]]]:
    """
    ดึงรูปภาพจาก entry หนึ่งรายการ
    คืน (question_images, choice_images)
    """
    question_images: List[QuestionImage] = []
    choice_images: Dict[int, List[QuestionImage]] = {}

    if not entry:
        return question_images, choice_images

    # 1. หา URL จาก subtree ของ entry
    entry_json = json.dumps(entry, ensure_ascii=False)
    entry_urls = find_all_image_urls(entry_json)
    base64_list = extract_base64_images(entry_json)

    # 2. หา base64 จาก nested structure
    for mime, data in base64_list:
        valid, fmt, size = validate_image(data)
        if valid:
            processed, out_mime, status = compress_image(data)
            if processed:
                question_images.append(QuestionImage(
                    source="question",
                    url=None,
                    data=processed,
                    mime_type=out_mipe,
                    width=size[0] if size else None,
                    height=size[1] if size else None,
                    status=status,
                ))

    # 3. หา URL จาก media field ถ้ามี (หลายตำแหน่งที่เป็นไปได้)
    media_fields = [9, 13, 8, 10, 11]
    for mf in media_fields:
        media = safe_get(entry, [mf])
        if media:
            media_json = json.dumps(media, ensure_ascii=False)
            media_urls = find_all_image_urls(media_json)
            for u in media_urls:
                if u not in [img.url for img in question_images]:
                    question_images.append(QuestionImage(
                        source="question",
                        url=u,
                        data=None,
                        mime_type="image/jpeg",
                        status="pending",
                    ))

    # 4. หา URL จาก title/description ถ้ามี
    for field_idx in [1, 2]:
        field_text = safe_get(entry, [field_idx], "")
        if isinstance(field_text, str):
            for u in find_all_image_urls(field_text):
                if u not in [img.url for img in question_images]:
                    question_images.append(QuestionImage(
                        source="question",
                        url=u,
                        data=None,
                        mime_type="image/jpeg",
                        status="pending",
                    ))

    # 5. หา URL จากตัวเลือก
    choices_raw = safe_get(entry, [4, 0, 1])
    if choices_raw and isinstance(choices_raw, list):
        for ci, choice in enumerate(choices_raw):
            if not choice:
                continue
            choice_json = json.dumps(choice, ensure_ascii=False)
            choice_urls = find_all_image_urls(choice_json)
            choice_base64 = extract_base64_images(choice_json)
            for u in choice_urls:
                choice_images.setdefault(ci, []).append(QuestionImage(
                    source="choice",
                    url=u,
                    data=None,
                    mime_type="image/jpeg",
                    status="pending",
                ))
            for mime, data in choice_base64:
                valid, fmt, size = validate_image(data)
                if valid:
                    processed, out_mime, status = compress_image(data)
                    if processed:
                        choice_images.setdefault(ci, []).append(QuestionImage(
                            source="choice",
                            url=None,
                            data=processed,
                            mime_type=out_mime,
                            width=size[0] if size else None,
                            height=size[1] if size else None,
                            status=status,
                        ))

    # 6. ถ้า entry ไม่มีรูปเลย แต่มี global URL ตามลำดับ ให้ fallback
    if not question_images and entry_index < len(global_urls):
        question_images.append(QuestionImage(
            source="fallback",
            url=global_urls[entry_index],
            data=None,
            mime_type="image/jpeg",
            status="pending",
        ))

    return question_images, choice_images


def fetch_and_process_images(questions: List[Question], progress_cb=None) -> None:
    """
    ดาวน์โหลดและประมวลผลรูปภาพทั้งหมดแบบ parallel
    """
    # รวบรวม tasks ทั้งหมด
    tasks = []  # (question_idx, image_idx, image, is_choice, choice_idx)

    for qi, q in enumerate(questions):
        for ii, img in enumerate(q.images):
            if img.status == "pending" and img.url:
                tasks.append((qi, ii, img, False, None))
        for ci, imgs in q.choice_images.items():
            for ii, img in enumerate(imgs):
                if img.status == "pending" and img.url:
                    tasks.append((qi, ii, img, True, ci))

    total = len(tasks)
    if total == 0:
        return

    def _process(task):
        qi, ii, img, is_choice, ci = task
        processed = process_image_from_url(img.url)
        return qi, ii, is_choice, ci, processed

    completed = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for result in pool.map(_process, tasks):
            qi, ii, is_choice, ci, processed = result
            if is_choice:
                questions[qi].choice_images[ci][ii] = processed
            else:
                questions[qi].images[ii] = processed

            completed += 1
            if progress_cb:
                progress_cb(completed, total)


# ═══════════════════════════════════════════════════════════
# Personal Info Detection
# ═══════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════
# Choice Matching
# ═══════════════════════════════════════════════════════════
def normalize_choice(text: str) -> str:
    s = str(text).strip()
    # ลบ prefix "ข้อ ", "(". ")", ช่องว่าง
    s = re.sub(r'^(?:ข้อ\s*)?[\(\[]?([ก-ฮa-zA-Z0-9]+)[\)\].]?\s*', r'\1 ', s)
    return s.strip()


def match_choice(ai_answer: Any, choices: List[str]) -> Tuple[int, bool]:
    """
    จับคู่คำตอบจาก AI กับตัวเลือก
    คืน (index, matched)
    """
    if not choices:
        return -1, False

    clean_choices = [str(c).strip() for c in choices]
    ai_clean = str(ai_answer).strip()
    if not ai_clean:
        return -1, False

    # 1. Exact match
    for i, c in enumerate(clean_choices):
        if c == ai_clean:
            return i, True

    # 2. Case-insensitive exact
    ai_lower = ai_clean.lower()
    for i, c in enumerate(clean_choices):
        if c.lower() == ai_lower:
            return i, True

    # 3. Match ตัวอักษรนำ (เช่น "ก." กับ "ข้อ ก. ...")
    letter_match = re.match(r'^(?:ข้อ\s*)?[\(\[]?([ก-ฮa-zA-Z0-9]+)[\)\].]?\s*(.*)$', ai_clean)
    if letter_match:
        letter = letter_match.group(1)
        for i, c in enumerate(clean_choices):
            m = re.match(r'^(?:ข้อ\s*)?[\(\[]?(' + re.escape(letter) + r')[\)\].]?\s*', c)
            if m:
                return i, True

    # 4. Substring ที่ชาญฉลาด (ไม่ให้ "ก." ตรงกับ "ข้อ ก.")
    for i, c in enumerate(clean_choices):
        c_norm = normalize_choice(c)
        ai_norm = normalize_choice(ai_clean)
        if c_norm and ai_norm and (c_norm == ai_norm or c_norm.startswith(ai_norm) or ai_norm.startswith(c_norm)):
            return i, True

    # 5. Fuzzy match
    close = difflib.get_close_matches(ai_clean, clean_choices, n=1, cutoff=0.65)
    if close:
        return clean_choices.index(close[0]), True

    # 6. Fuzzy บนตัวอักษรนำ
    if letter_match:
        letter = letter_match.group(1)
        for i, c in enumerate(clean_choices):
            m = re.match(r'^(?:ข้อ\s*)?[\(\[]?([ก-ฮa-zA-Z0-9]+)[\)\].]?\s*', c)
            if m and m.group(1).lower() == letter.lower():
                return i, True

    return -1, False


# ═══════════════════════════════════════════════════════════
# Form Fetching & Parsing
# ═══════════════════════════════════════════════════════════
def fetch_form(form_url: str) -> Tuple[dict, str, str, str, str]:
    """
    ดึงข้อมูลฟอร์มจาก Google Form
    คืน (form_data, fbzx, fvv, raw_html, submit_url)
    """
    if "docs.google.com/forms" not in form_url:
        raise RuntimeError("ลิงก์นี้ไม่ใช่ Google Form")

    res = requests.get(form_url, allow_redirects=True, headers=UA, timeout=20)
    raw_html = res.text

    m = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>', raw_html, re.DOTALL)
    if not m:
        # ลอง pattern สำรอง
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
    """
    แยกโครงสร้างฟอร์มออกมาเป็น questions
    """
    # หา entries
    entries = safe_get(form_data, [1, 1], [])
    if not entries:
        # ลอง path อื่น
        if isinstance(form_data, list) and len(form_data) > 1 and isinstance(form_data[1], list) and len(form_data[1]) > 1:
            entries = form_data[1][1]
        elif isinstance(form_data, list) and len(form_data) > 1:
            entries = form_data[1]

    if not isinstance(entries, list):
        raise RuntimeError("ไม่พบรายการคำถามในฟอร์ม")

    # ดึง global image URLs จาก HTML ทั้งหมด
    html_no_meta = re.sub(r'<meta[^>]*property="og:image"[^>]*>', '', raw_html)
    global_urls = find_all_image_urls(html_no_meta)

    questions: List[Question] = []
    personal_data_map: Dict[str, Tuple[str, str, str]] = {}

    pages_meta = [{"own_id": None, "next_raw": None}]
    page_id_to_index: Dict[Any, int] = {}
    current_page = 0

    # นับเฉพาะ entry ที่เป็นคำถามจริงๆ สำหรับ fallback global URLs
    question_entry_indices = []

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

        # ข้าม types ที่ไม่รองรับ
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

        # ตรวจข้อมูลส่วนตัว
        p_info = check_personal_info(full_title, choices, my_name, my_student_id, my_no, my_class)
        if p_info:
            personal_data_map[entry_id] = p_info
            continue

        # ดึงรูปภาพ
        entry_index = len(question_entry_indices)
        question_entry_indices.append(entry_index)
        q_images, c_images = extract_images_from_entry(item, entry_index, global_urls)

        # Branching map
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

    # คำนวณ default_next
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


# ═══════════════════════════════════════════════════════════
# Page History Simulation
# ═══════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════
# AI Analysis
# ═══════════════════════════════════════════════════════════
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string"},
                    "answer": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "reasoning": {"type": "string"},
                },
                "required": ["entry_id", "answer", "confidence", "reasoning"],
            },
        }
    },
    "required": ["answers"],
}


def build_system_instruction(exam_context: str) -> str:
    ctx = exam_context.strip() if exam_context else "ไม่มีบริบทเพิ่มเติม"
    return f"""คุณคือผู้ช่วยตอบข้อสอบอัตโนมัติที่แม่นยำและระมัดระวัง

บริบทข้อสอบ: {ctx}

กฎที่ต้องปฏิบัติ:
1. อ่านคำถามและรูปประกอบให้ละเอียด
2. ถ้าคำถามมีตัวเลือก ให้ตอบเป็นข้อความของตัวเลือกนั้นเป๊ะๆ (เช่น "ก. แมว" ไม่ใช่แค่ "ก")
3. ถ้าเป็นคำถามเติมคำ/ข้อความ ให้ตอบเป็นข้อความสั้นที่ถูกต้อง
4. ถ้าเป็นคำถามหลายคำตอบ ให้ตอบเป็น array ของข้อความ
5. ให้ confidence 0-100 โดยพิจารณาจากความชัดเจนของโจทย์
6. อธิบาย reasoning สั้นๆ ว่าทำไมถึงเลือกคำตอบนี้ (ภาษาไทย)
7. ตอบเป็น JSON ตาม schema ที่กำหนดเท่านั้น ห้ามมีข้อความนอก JSON
8. หากไม่แน่ใจ ให้ตอบตัวเลือกที่น่าจะถูกที่สุดพร้อม confidence ต่ำ
"""


def build_question_parts(idx: int, q: Question) -> List[types.Part]:
    parts: List[types.Part] = []

    # ข้อความคำถาม
    text = f"\n--- ข้อ {idx} (ID: {q.entry_id}) ---\n"
    text += f"คำถาม: {q.title}\n"
    if q.description:
        text += f"คำอธิบาย: {q.description}\n"
    if q.is_multi:
        text += "ประเภท: เลือกได้หลายคำตอบ\n"
    else:
        text += "ประเภท: เลือกคำตอบเดียว\n"
    if q.choices:
        text += "ตัวเลือก:\n"
        for ci, choice in enumerate(q.choices, 1):
            text += f"  {ci}. {choice}\n"
    else:
        text += "ประเภท: คำตอบอิสระ (เติมคำตอบ)\n"

    parts.append(types.Part.from_text(text=text))

    # รูปประกอบคำถาม
    for img in q.images:
        if img.is_ready():
            parts.append(types.Part.from_bytes(data=img.data, mime_type=img.mime_type))
        elif img.url:
            parts.append(types.Part.from_text(text=f"[รูปประกอบคำถาม: {img.url}]"))

    # รูปประกอบตัวเลือก
    for ci, imgs in q.choice_images.items():
        if ci < len(q.choices):
            for img in imgs:
                if img.is_ready():
                    parts.append(types.Part.from_text(text=f"[รูปประกอบตัวเลือก {q.choices[ci]}]"))
                    parts.append(types.Part.from_bytes(data=img.data, mime_type=img.mime_type))
                elif img.url:
                    parts.append(types.Part.from_text(text=f"[รูปประกอบตัวเลือก {q.choices[ci]}: {img.url}]"))

    return parts


def call_gemini_chunk(
    api_key: str,
    exam_context: str,
    chunk: List[Tuple[int, Question]],
    thinking_level: str = "low",
) -> Dict[str, Any]:
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=120000))

    contents: List[types.Part] = [types.Part.from_text(text=build_system_instruction(exam_context))]
    for idx, q in chunk:
        contents.extend(build_question_parts(idx, q))

    # นับจำนวนรูปใน chunk
    image_count = sum(
        1 for p in contents
        if hasattr(p, "inline_data") and p.inline_data is not None
    )
    if image_count > 16:
        logger.warning(f"Chunk มีรูปมาก ({image_count} รูป) อาจเกิน limit ของ Gemini")

    gen_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ANSWER_SCHEMA,
        max_output_tokens=8192,
        temperature=0.15,
        top_p=0.95,
    )

    if THINKING_CONFIG_AVAILABLE:
        try:
            gen_config.thinking_config = types.ThinkingConfig(thinking_level=thinking_level)
        except Exception:
            pass

    last_err: Optional[Exception] = None

    for model_name in MODELS_TO_TRY:
        for attempt in range(MAX_MODEL_ATTEMPTS):
            try:
                logger.info(f"Calling {model_name} (attempt {attempt + 1}) for {len(chunk)} questions")
                resp = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=gen_config,
                )

                if not resp or not resp.text:
                    raise RuntimeError("โมเดลตอบกลับเป็นค่าว่าง")

                raw = resp.text.strip()
                raw = re.sub(r'^```(?:json)?\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw)

                data = json.loads(raw)
                if not isinstance(data, dict) or "answers" not in data:
                    raise RuntimeError("รูปแบบ JSON ไม่ถูกต้อง")

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

            except Exception as err:
                last_err = err
                msg = str(err).lower()
                logger.warning(f"{model_name} attempt {attempt + 1} failed: {err}")

                if "429" in msg or "resource_exhausted" in msg or "quota" in msg:
                    sleep_time = BACKOFF_SEC[min(attempt, len(BACKOFF_SEC) - 1)]
                    logger.info(f"Rate limited, sleeping {sleep_time}s")
                    time.sleep(sleep_time)
                    continue

                if any(code in msg for code in ["503", "504", "502", "500", "deadline"]) and attempt < MAX_MODEL_ATTEMPTS - 1:
                    time.sleep(5)
                    continue

                # ถ้าเป็น JSON parse error ลอง model ถัดไป
                break

    raise last_err or RuntimeError("โมเดลไม่ตอบสนองหลังจากลองทุกตัวเลือก")


def analyze_all(
    questions: List[Question],
    keys: List[str],
    exam_context: str,
    thinking_level: str,
    progress_cb=None,
) -> Tuple[Dict[str, Any], List[str]]:
    indexed = list(enumerate(questions, 1))
    chunks = [indexed[i:i + CHUNK_SIZE] for i in range(0, len(indexed), CHUNK_SIZE)]
    results: Dict[str, Any] = {}
    errors: List[str] = []

    if not chunks:
        return results, errors

    # จำกัด parallelism ตามจำนวน keys
    workers = min(MAX_PARALLEL_WORKERS, len(keys), len(chunks))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(call_gemini_chunk, keys[i % len(keys)], exam_context, chunk, thinking_level): chunk
            for i, chunk in enumerate(chunks)
        }

        done = 0
        for fut in as_completed(futures):
            done += 1
            if progress_cb:
                progress_cb(done, len(chunks))

            try:
                chunk_result = fut.result()
                if isinstance(chunk_result, dict):
                    results.update(chunk_result)
                else:
                    errors.append("ผลลัพธ์จาก AI ไม่ถูกต้อง")
            except Exception as e:
                err_msg = f"Chunk error: {str(e)}\n{traceback.format_exc()}"
                logger.error(err_msg)
                errors.append(str(e))

    return results, errors


# ═══════════════════════════════════════════════════════════
# Submit
# ═══════════════════════════════════════════════════════════
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

    # ข้อมูลส่วนตัว
    for entry_id, info in personal_data_map.items():
        payload[entry_id] = info[1]

    # คำตอบแต่ละข้อ
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
        "freebirdFormviewerViewResponseConfirmationMessage",
        "บันทึกคำตอบ",
        "response received",
        "thank you",
        "ขอบคุณ",
        "สำเร็จ",
    ]
    if any(marker in response_text.lower() for marker in success_markers):
        return True, None

    # ถ้ายังมีฟอร์มอยู่ แสดงว่าอาจส่งไม่สำเร็จ
    if "FB_PUBLIC_LOAD_DATA_" in response_text or 'role="form"' in response_text:
        return False, "ฟอร์มยังแสดงผลอยู่ (อาจมีข้อผิดพลาด)"

    # ไม่แน่ใจ ให้ถือว่าสำเร็จถ้า status 200
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


# ═══════════════════════════════════════════════════════════
# UI Helpers
# ═══════════════════════════════════════════════════════════
def get_ai_answer(ai_answers: Dict[str, Any], entry_id: str) -> Dict[str, Any]:
    data = ai_answers.get(entry_id, {})
    if isinstance(data, dict):
        return data
    return {"answer": str(data) if data else "", "confidence": 70, "reasoning": "ประมวลผลอัตโนมัติ"}


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
    elif img.status == "url_only":
        return "🔗"
    elif img.status == "failed":
        return "❌"
    return "⏳"


# ═══════════════════════════════════════════════════════════
# Main UI
# ═══════════════════════════════════════════════════════════
render_header()

with st.container(border=True):
    st.markdown('<div class="glass-header">TARGET FORM LINK</div>', unsafe_allow_html=True)
    form_url = st.text_input("Form URL", placeholder="วางลิงก์ Google Form ที่นี่...", label_visibility="collapsed")

with st.container(border=True):
    st.markdown('<div class="glass-header">PERSONAL DATA & CONTEXT</div>', unsafe_allow_html=True)
    exam_context = st.text_area("EXAM CONTEXT", placeholder="เช่น ฟิสิกส์ ม.6 บทคลื่น...", height=68)
    fast_mode = st.checkbox("โหมดเร็ว", value=True)
    image_quality = st.selectbox(
        "คุณภาพรูปภาพ",
        ["auto", "high", "normal", "low"],
        index=0,
        help="auto = ปรับตามประเภทรูป, high = ละเอียดสูง (ช้า), normal = 1024px, low = 512px (เร็ว)"
    )

    col1, col2 = st.columns(2)
    with col1:
        my_name = st.text_input("FULL NAME", placeholder="ชื่อ-นามสกุล")
        my_no = st.text_input("CLASS NUMBER", placeholder="เลขที่")
    with col2:
        my_student_id = st.text_input("STUDENT ID", placeholder="เลขประจำตัว")
        my_class = st.text_input("CLASSROOM", placeholder="เช่น 6/3")

if st.button("INITIATE ANALYSIS", type="primary", use_container_width=True):
    if not form_url:
        st.error("กรุณาใส่ลิงก์ Google Form ก่อน")
    else:
        with st.status("SYSTEM PROCESSING...", expanded=True) as status:
            try:
                # Reset state
                for key in list(st.session_state.keys()):
                    if key.startswith("ans_"):
                        del st.session_state[key]

                st.write("🔍 กำลังอ่านโครงสร้างฟอร์ม...")
                form_data, fbzx, fvv, raw_html, submit_url = fetch_form(form_url)

                st.write("🧩 กำลังสกัดคำถาม...")
                questions, personal_data_map, default_next, page_count = parse_form(
                    form_data, raw_html, my_name, my_student_id, my_no, my_class
                )

                st.write(f"🖼️ กำลังดาวน์โหลดรูปภาพ ({sum(len(q.images) + sum(len(v) for v in q.choice_images.values()) for q in questions)} รูป)...")
                img_progress = st.empty()

                def img_cb(done, total):
                    img_progress.progress(done / total, text=f"ดาวน์โหลดรูป {done}/{total}")

                fetch_and_process_images(questions, img_cb)
                img_progress.empty()

                ai_answers, ai_errors = {}, []
                if questions:
                    st.write(f"🤖 AI กำลังวิเคราะห์ {len(questions)} ข้อ...")
                    bar = st.progress(0.0)
                    def ai_cb(done, total): bar.progress(done / total, text=f"วิเคราะห์ {done}/{total}")

                    ai_answers, ai_errors = analyze_all(
                        questions, api_keys, exam_context,
                        "low" if fast_mode else "medium",
                        ai_cb,
                    )
                    bar.empty()

                    if ai_errors:
                        st.warning(f"มี {len(ai_errors)} ข้อที่วิเคราะห์ไม่สำเร็จ")
                        with st.expander("ดูรายละเอียดข้อผิดพลาด"):
                            for err in ai_errors:
                                st.code(err)
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
                })
                status.update(label="ANALYSIS COMPLETE", state="complete", expanded=False)

            except Exception as e:
                status.update(label="ERROR", state="error")
                logger.error(traceback.format_exc())
                st.error(f"เกิดข้อผิดพลาด: {str(e)}")

# ═══════════════════════════════════════════════════════════
# Review Section
# ═══════════════════════════════════════════════════════════
if "questions" in st.session_state:
    st.markdown('<div class="section-title">REVIEW & EDIT</div>', unsafe_allow_html=True)

    questions = st.session_state["questions"]
    ai_answers = st.session_state.get("ai_answers", {})
    personal_data_map = st.session_state.get("personal_data_map", {})

    # สรุปภาพรวม
    total_q = len(questions)
    answered = sum(1 for q in questions if get_ai_answer(ai_answers, q.entry_id).get("answer"))
    avg_conf = 0
    if answered > 0:
        avg_conf = sum(get_ai_answer(ai_answers, q.entry_id).get("confidence", 0) for q in questions) / total_q

    with st.container(border=True):
        st.markdown('<div class="glass-header">ANALYSIS SUMMARY</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("คำถามทั้งหมด", total_q)
        c2.metric("AI ตอบแล้ว", answered)
        c3.metric("ความมั่นใจเฉลี่ย", f"{avg_conf:.0f}%")

    # ข้อมูลส่วนตัว
    if personal_data_map:
        with st.container(border=True):
            st.markdown('<div class="glass-header">AUTO-FILLED DATA</div>', unsafe_allow_html=True)
            items = list(personal_data_map.items())
            cols = st.columns(min(len(items), 2))
            for idx, (entry_id, info) in enumerate(items):
                cols[idx % len(cols)].text_input(info[2], value=info[1], key="input_" + entry_id, disabled=True)

    # Bulk actions
    col_accept, col_reset = st.columns(2)
    with col_accept:
        if st.button("✅ ยอมรับคำตอบ AI ทั้งหมด", use_container_width=True):
            for q in questions:
                ans_data = get_ai_answer(ai_answers, q.entry_id)
                ans = ans_data.get("answer", "")
                if q.is_multi and not isinstance(ans, list):
                    ans = [ans] if ans else []
                st.session_state[f"ans_{q.entry_id}"] = ans
            st.rerun()
    with col_reset:
        if st.button("🔄 รีเซ็ตคำตอบทั้งหมด", use_container_width=True):
            for q in questions:
                if f"ans_{q.entry_id}" in st.session_state:
                    del st.session_state[f"ans_{q.entry_id}"]
            st.rerun()

    # แสดงคำถามแต่ละข้อ
    for idx, q in enumerate(questions, 1):
        entry_id = q.entry_id
        ans_data = get_ai_answer(ai_answers, entry_id)
        default_val = ans_data.get("answer", "")
        confidence = ans_data.get("confidence", 0)
        reasoning = ans_data.get("reasoning", "")

        with st.container(border=True):
            # Header
            header_html = f'<div class="q-title">{idx}. {html_lib.escape(q.title)}</div>'
            st.markdown(header_html, unsafe_allow_html=True)

            # รูปประกอบคำถาม
            if q.images:
                st.markdown('<div class="image-gallery">', unsafe_allow_html=True)
                img_cols = st.columns(min(len(q.images), 3))
                for i, img in enumerate(q.images):
                    with img_cols[i % 3]:
                        if img.is_ready():
                            st.image(img.data, use_container_width=True, caption=f"รูป {i+1} {render_image_status(img)}")
                        elif img.url:
                            st.markdown(f'<div class="image-fallback">🔗 รูปที่ {i+1}: <a href="{img.url}" target="_blank">ดูรูปต้นฉบับ</a></div>', unsafe_allow_html=True)
                        else:
                            st.markdown(f'<div class="image-fallback">❌ โหลดรูปที่ {i+1} ไม่ได้</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            # Confidence + Reasoning
            if confidence > 0:
                color = confidence_color(confidence)
                st.markdown(
                    f'<div class="confidence-track"><div class="confidence-fill" style="width:{confidence}%;background:{color};"></div></div>',
                    unsafe_allow_html=True
                )
                st.markdown(f'<div class="confidence-label">ความมั่นใจ: {confidence}%</div>', unsafe_allow_html=True)
            if reasoning:
                st.markdown(f'<div class="reasoning-text">💡 {html_lib.escape(reasoning)}</div>', unsafe_allow_html=True)

            # Input
            ans_key = f"ans_{entry_id}"

            if q.choices:
                # แปลง default ให้ตรงกับตัวเลือก
                if q.is_multi:
                    default_list = default_val if isinstance(default_val, list) else ([default_val] if default_val else [])
                    # กรองเฉพาะที่มีในตัวเลือก
                    default_list = [d for d in default_list if d in q.choices]
                    st.multiselect("คำตอบ", q.choices, default=default_list, key=ans_key)
                else:
                    default_str = str(default_val) if default_val else None
                    if default_str not in q.choices:
                        # ลอง match กับตัวเลือก
                        matched_idx, matched = match_choice(default_str, q.choices)
                        if matched:
                            default_str = q.choices[matched_idx]
                        else:
                            default_str = None
                    st.radio("คำตอบ", q.choices, index=q.choices.index(default_str) if default_str in q.choices else 0, key=ans_key)
            else:
                st.text_input("คำตอบ", value=str(default_val), key=ans_key)

    # Submit button
    if st.button("TRANSMIT DATA", type="primary", use_container_width=True):
        with st.spinner("กำลังส่งข้อมูล..."):
            final_answers = {eid: info[1] for eid, info in personal_data_map.items()}
            missing_required = []

            for q in questions:
                val = st.session_state.get(f"ans_{q.entry_id}", "")
                final_answers[q.entry_id] = val
                if q.is_required and (not val or (isinstance(val, list) and not val)):
                    missing_required.append(f"ข้อ {q.entry_id}")

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
