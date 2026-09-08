"""
app.py — EZEXAM Auto Form System (Fixed - AI Response Issue)
"""
import json
import re
import time
import io
import difflib
import html as html_lib
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import streamlit as st
from google import genai
from google.genai import types

from style import inject_css, render_header

st.set_page_config(page_title="EZEXAM | Auto Form System", page_icon="⚡", layout="centered")
inject_css()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}

TYPE_PAGE_BREAK = 8
TYPE_CHECKBOX = 4

MODELS_TO_TRY = ["gemini-2.0-flash", "gemini-1.5-flash"]
CHUNK_SIZE = 3
MAX_PARALLEL_WORKERS = 1          # เปลี่ยนเป็น 1 ชั่วคราวเพื่อความเสถียร
MAX_MODEL_ATTEMPTS = 3
BACKOFF_SEC = [4, 8, 15]

IMG_URL_RE = re.compile(r'https://lh\d?\.?googleusercontent\.com/[^\s"\'<>\\]+')

api_keys = [st.secrets[k] for k in st.secrets if "GEMINI_API_KEY" in k]
if not api_keys:
    st.error("ระบบยังไม่ได้ตั้งค่า API Key")
    st.stop()


# ==================== ฟังก์ชันเดิม (คงไว้) ====================
def check_personal_info(q_title, choices, my_name, my_student_id, my_no, my_class):
    clean_title = re.sub(r'^\*?\*?(?:ข้อ\s*\d+[\s.:-]*)?', '', q_title.strip()).strip().rstrip('*').strip()
    title_lower = clean_title.lower()
    if len(clean_title) > 25: return None
    exam_stopwords = ["สาร", "เคมี", "ดาว", "วิทยาศาสตร์", "โรค", "องค์กร", "กษัตริย์", "ธาตุ",
                      "เมือง", "ประเทศ", "วรรณคดี", "ผู้แต่ง", "หัวใจ", "บรรยากาศ", "ผิวหนัง",
                      "ปฏิบัติการ", "ดิน", "หิน", "เชื่อม", "เครือข่าย", "อินเทอร์เน็ต", "เว็บ",
                      "จัดเป็น", "คืออะไร", "ข้อใด", "หมายถึง", "ตัวอักษรย่อ"]
    if any(sw in title_lower for sw in exam_stopwords): return None
    if my_name and any(k in title_lower for k in ["ชื่อ", "นามสกุล", "สกุล", "name"]): return (q_title, my_name, "ชื่อ-นามสกุล")
    if my_student_id and any(k in title_lower for k in ["เลขประจำตัว", "รหัส", "student id", "id"]): return (q_title, my_student_id, "เลขประจำตัว")
    if my_no and (any(k in title_lower for k in ["เลขที่", "no.", "number"]) or title_lower == "no"): return (q_title, my_no, "เลขที่")
    if my_class and any(k in title_lower for k in ["ชั้น", "ห้อง", "ม.", "มัธยม", "class", "grade", "room"]):
        best_val = my_class
        if choices:
            for c in choices:
                c_str = str(c).strip()
                if c_str == my_class.strip() or c_str in my_class or my_class.endswith(c_str):
                    best_val = c_str
                    break
        return (q_title, best_val, "ชั้น/ห้อง")
    return None


def match_choice(ai_answer, choices):
    ai_answer = str(ai_answer).strip()
    clean_choices = [str(c).strip() for c in choices]
    if not ai_answer or not clean_choices: return 0, False
    for i, c in enumerate(clean_choices):
        if c == ai_answer: return i, True
    for i, c in enumerate(clean_choices):
        if c and (c in ai_answer or ai_answer in c): return i, True
    for i, c in enumerate(clean_choices):
        if c.lower() == ai_answer.lower(): return i, True
    close = difflib.get_close_matches(ai_answer, clean_choices, n=1, cutoff=0.55)
    if close: return clean_choices.index(close[0]), True
    return 0, False


def compress_and_verify_image(raw_bytes, max_dim=1024, quality=82):
    try:
        from PIL import Image
        if len(raw_bytes) < 3000: return None, None
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        if max(img.size) > max_dim: img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except: return None, None


def fetch_form(form_url):
    if "docs.google.com/forms" not in form_url: raise RuntimeError("ลิงก์นี้ไม่ใช่ Google Form")
    res = requests.get(form_url, allow_redirects=True, headers=UA, timeout=15)
    raw_html = res.text
    m = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>', raw_html, re.DOTALL)
    if not m: raise RuntimeError("อ่านโครงสร้างฟอร์มไม่ได้")
    form_data = json.loads(m.group(1))
    fbzx = re.search(r'name="fbzx"\s+value="(\d+)"', raw_html)
    fvv = re.search(r'name="fvv"\s+value="(\d+)"', raw_html)
    fbzx = fbzx.group(1) if fbzx else ""
    fvv = fvv.group(1) if fvv else "1"
    html_no_meta = re.sub(r'<meta[^>]*property="og:image"[^>]*>', '', raw_html)
    return form_data, fbzx, fvv, IMG_URL_RE.findall(html_no_meta)


def parse_form(form_data, img_urls_found, my_name, my_student_id, my_no, my_class):
    entries = form_data[1][1] if len(form_data) > 1 and form_data[1] else []
    parsed_questions, personal_data_map = [], {}
    pages_meta = [{"own_id": None, "next_raw": None}]
    page_id_to_index = {}
    current_page = 0
    img_counter = 0

    for item in entries:
        if not item or len(item) < 4: continue
        q_type = item[3]
        if q_type == TYPE_PAGE_BREAK:
            current_page += 1
            own_id = item[0]
            next_raw = item[5] if len(item) > 5 else None
            pages_meta.append({"own_id": own_id, "next_raw": next_raw})
            page_id_to_index[own_id] = current_page
            continue
        if q_type == 11 or len(item) < 5 or not item[4]: continue
        try:
            entry_id = "entry." + str(item[4][0][0])
        except: continue
        q_title = item[1]
        choices_raw = item[4][0][1] if len(item[4][0]) > 1 else None
        choices = [c[0] for c in choices_raw if c and len(c) > 0] if choices_raw else []

        image_urls = list(dict.fromkeys(IMG_URL_RE.findall(json.dumps(item, ensure_ascii=False)))) if item else []
        has_media = len(item) > 9 and bool(item[9])
        if not image_urls and has_media and img_counter < len(img_urls_found):
            image_urls = [img_urls_found[img_counter]]
        if has_media or image_urls: img_counter += 1

        p_info = check_personal_info(q_title, choices, my_name, my_student_id, my_no, my_class)
        if p_info:
            personal_data_map[entry_id] = p_info
            continue

        branch_map = {}
        if choices_raw:
            for c in choices_raw:
                if c and len(c) > 2 and c[2] is not None:
                    if c[2] <= 0: branch_map[c[0]] = -1
                    elif c[2] in page_id_to_index: branch_map[c[0]] = page_id_to_index[c[2]]

        parsed_questions.append({
            "entry_id": entry_id, "title": q_title, "choices": choices,
            "is_multi": q_type == TYPE_CHECKBOX, "image_urls": image_urls,
            "page_index": current_page, "branch_map": branch_map,
        })

    default_next = []
    for i, meta in enumerate(pages_meta):
        nxt = i + 1 if i + 1 < len(pages_meta) else -1
        if meta["next_raw"] is not None:
            if meta["own_id"] is not None and meta["next_raw"] == meta["own_id"]: nxt = -1
            elif meta["next_raw"] in page_id_to_index: nxt = page_id_to_index[meta["next_raw"]]
        default_next.append(nxt)
    return parsed_questions, personal_data_map, default_next, len(pages_meta)


def simulate_page_history(parsed_questions, final_answers, default_next, page_count):
    by_page = {}
    for q in parsed_questions: by_page.setdefault(q["page_index"], []).append(q)
    visited, current, guard = [0], 0, 0
    while guard < page_count + 2:
        guard += 1
        nxt = default_next[current] if current < len(default_next) else -1
        for q in by_page.get(current, []):
            if q["branch_map"]:
                ans = final_answers.get(q["entry_id"])
                if isinstance(ans, list): ans = ans[0] if ans else None
                if ans in q["branch_map"]: nxt = q["branch_map"][ans]; break
        if nxt < 0 or nxt in visited: break
        visited.append(nxt)
        current = nxt
    return ",".join(str(p) for p in visited)


def prefetch_images(parsed_questions):
    pairs = [(q["entry_id"], u) for q in parsed_questions for u in q.get("image_urls", [])]
    bytes_map = {}
    def _dl(pair):
        eid, url = pair
        try:
            r = requests.get(url, headers=UA, timeout=10)
            if r.status_code == 200:
                data, mime = compress_and_verify_image(r.content)
                if data: return eid, data, mime
        except: pass
        return None
    if pairs:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for res in pool.map(_dl, pairs):
                if res:
                    eid, data, mime = res
                    bytes_map.setdefault(eid, []).append((data, mime))
    for q in parsed_questions:
        q["image_data"] = bytes_map.get(q["entry_id"], [])
    return [d for lst in bytes_map.values() for d, _ in lst]


# ==================== ส่วนที่แก้ไขใหม่ ====================
def build_prompt_header(exam_context):
    text = f"Context: {exam_context or 'None'}\nInstructions:\n1. คิดทบทวนคำตอบให้รอบคอบ\n2. คัดลอกตัวเลือกมาเป๊ะ\n3. ตอบเป็น JSON เท่านั้น\n\nQuestions:\n"
    return types.Part.from_text(text=text)


def build_question_block(idx, q):
    parts = [types.Part.from_text(text=f"\nข้อ {idx} (ID: {q['entry_id']}): {q['title']}\nตัวเลือก: {json.dumps(q['choices'], ensure_ascii=False)}" if q["choices"] else f"\nข้อ {idx}: {q['title']}")]
    for data, mime in q.get("image_data", []):
        parts.append(types.Part.from_bytes(data=data, mime_type=mime))
    return parts


def call_gemini_chunk(api_key, exam_context, chunk, thinking_level="low"):
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=60000))
    contents = [build_prompt_header(exam_context)]
    for idx, q in chunk:
        contents.extend(build_question_block(idx, q))

    gen_config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
        response_mime_type="application/json",
        max_output_tokens=4096,
    )

    last_err = None
    for model_name in MODELS_TO_TRY:
        for attempt in range(MAX_MODEL_ATTEMPTS):
            try:
                resp = client.models.generate_content(model=model_name, contents=contents, config=gen_config)
                if resp and resp.text:
                    raw = re.sub(r'^```(?:json)?\s*', '', resp.text.strip())
                    raw = re.sub(r'\s*```$', '', raw)
                    try:
                        return json.loads(raw)
                    except:
                        m = re.search(r'\{.*\}', raw, re.DOTALL)
                        if m: return json.loads(m.group(0))
                        raise
            except Exception as err:
                last_err = err
                msg = str(err).lower()
                if "429" in msg or "resource_exhausted" in msg:
                    time.sleep(BACKOFF_SEC[min(attempt, len(BACKOFF_SEC)-1)])
                    continue
                if ("503" in msg or "504" in msg) and attempt < MAX_MODEL_ATTEMPTS - 1:
                    time.sleep(5)
                    continue
                break
    raise last_err or RuntimeError("โมเดลไม่ตอบสนอง")


def analyze_all(parsed_questions, keys, exam_context, thinking_level, progress_cb=None):
    indexed = list(enumerate(parsed_questions, 1))
    chunks = [indexed[i:i + CHUNK_SIZE] for i in range(0, len(indexed), CHUNK_SIZE)]
    results, errors = {}, []

    if not chunks: return results, errors

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as pool:
        futures = {
            pool.submit(call_gemini_chunk, keys[i % len(keys)], exam_context, chunk, thinking_level): chunk
            for i, chunk in enumerate(chunks)
        }
        done = 0
        for fut in as_completed(futures):
            done += 1
            if progress_cb: progress_cb(done, len(chunks))
            try:
                chunk_result = fut.result()
                if isinstance(chunk_result, dict):
                    results.update(chunk_result)
                else:
                    errors.append("ผลลัพธ์จาก AI ไม่ถูกต้อง")
            except Exception as e:
                errors.append(str(e))
    return results, errors


# ==================== Submit ====================
def build_submit_payload(personal_data_map, parsed_questions, final_answers, fbzx, fvv, page_history):
    payload = {"fbzx": fbzx, "fvv": fvv, "pageHistory": page_history}
    for entry_id, info in personal_data_map.items(): payload[entry_id] = info[1]
    for q in parsed_questions:
        entry_id = q["entry_id"]
        ans = final_answers.get(entry_id, "")
        if q["choices"]:
            if q["is_multi"] and isinstance(ans, list):
                valid = [q["choices"][match_choice(a, q["choices"])[0]] if match_choice(a, q["choices"])[1] else a for a in ans]
                payload[entry_id] = valid
            else:
                idx, matched = match_choice(ans, q["choices"])
                payload[entry_id] = q["choices"][idx] if matched else ans
        else:
            payload[entry_id] = ans
    return payload


def check_submit_success(response_text):
    if re.search(r'freebirdFormviewerViewResponseConfirmationMessage|บันทึกคำตอบ', response_text, re.IGNORECASE): return True
    if "FB_PUBLIC_LOAD_DATA_" in response_text: return False
    return None


# ==================== UI ====================
render_header()

with st.container(border=True):
    st.markdown('<div class="glass-header">TARGET FORM LINK</div>', unsafe_allow_html=True)
    form_url = st.text_input("Form URL", placeholder="วางลิงก์ Google Form ที่นี่...", label_visibility="collapsed")

with st.container(border=True):
    st.markdown('<div class="glass-header">PERSONAL DATA & CONTEXT</div>', unsafe_allow_html=True)
    exam_context = st.text_area("EXAM CONTEXT", placeholder="เช่น ฟิสิกส์ ม.6 บทคลื่น...", height=68)
    fast_mode = st.checkbox("โหมดเร็ว", value=True)
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
                st.session_state["submit_url"] = form_url.replace("viewform", "formResponse") if "viewform" in form_url else (form_url if "formResponse" in form_url else form_url.rstrip("/") + "/formResponse")

                st.write("กำลังอ่านโครงสร้างฟอร์ม...")
                form_data, fbzx, fvv, img_urls_found = fetch_form(form_url)

                st.write("กำลังสกัดคำถาม...")
                parsed_questions, personal_data_map, default_next, page_count = parse_form(form_data, img_urls_found, my_name, my_student_id, my_no, my_class)

                st.write("กำลังดาวน์โหลดรูปภาพ...")
                preview_images = prefetch_images(parsed_questions)

                ai_answers, ai_errors = {}, []
                if parsed_questions:
                    st.write(f"AI กำลังวิเคราะห์ {len(parsed_questions)} ข้อ...")
                    bar = st.progress(0.0)
                    def _cb(done, total): bar.progress(done / total)
                    ai_answers, ai_errors = analyze_all(parsed_questions, api_keys, exam_context, "low" if fast_mode else "medium", _cb)

                    if ai_errors:
                        st.warning(f"มี {len(ai_errors)} ข้อที่วิเคราะห์ไม่สำเร็จ")
                        with st.expander("ดูรายละเอียด"):
                            for err in ai_errors: st.code(err)
                    else:
                        st.success(f"AI วิเคราะห์สำเร็จ {len(ai_answers)} ข้อ")

                st.session_state.update({
                    "parsed_questions": parsed_questions, "personal_data_map": personal_data_map,
                    "ai_answers": ai_answers, "preview_images": preview_images,
                    "fbzx": fbzx, "fvv": fvv, "default_next": default_next,
                    "page_count": page_count, "exam_context": exam_context
                })
                status.update(label="ANALYSIS COMPLETE", state="complete", expanded=False)
            except Exception as e:
                status.update(label="ERROR", state="error")
                st.error(str(e))

# Review Section
if "parsed_questions" in st.session_state:
    st.markdown('<div class="section-title">REVIEW</div>', unsafe_allow_html=True)

    if st.session_state.get("preview_images"):
        with st.container(border=True):
            st.markdown('<div class="glass-header">📸 รูปภาพที่ดึงมาจากโจทย์</div>', unsafe_allow_html=True)
            imgs = st.session_state["preview_images"]
            cols = st.columns(min(len(imgs), 4))
            for idx, img_bytes in enumerate(imgs):
                cols[idx % 4].image(img_bytes, use_container_width=True, caption=f"รูปที่ {idx+1}")

    if st.session_state["personal_data_map"]:
        with st.container(border=True):
            st.markdown('<div class="glass-header">AUTO-FILLED DATA</div>', unsafe_allow_html=True)
            items = list(st.session_state["personal_data_map"].items())
            cols = st.columns(min(len(items), 2))
            for idx, (entry_id, info) in enumerate(items):
                cols[idx % len(cols)].text_input(info[0], value=info[1], key="input_"+entry_id, disabled=True)

    for idx, q in enumerate(st.session_state["parsed_questions"], 1):
        entry_id = q["entry_id"]
        q_data = st.session_state["ai_answers"].get(entry_id, {})
        default_val = q_data.get("answer", "") if isinstance(q_data, dict) else q_data
        score = int(q_data.get("confidence", 70)) if isinstance(q_data, dict) else 70
        reason = q_data.get("reasoning", "ประมวลผลอัตโนมัติ") if isinstance(q_data, dict) else "ประมวลผลอัตโนมัติ"

        with st.container(border=True):
            st.markdown(f'<div class="q-title">{idx}. {html_lib.escape(q["title"])}</div>', unsafe_allow_html=True)
            if q.get("image_data"):
                icols = st.columns(min(len(q["image_data"]), 3))
                for i, (data, _) in enumerate(q["image_data"]):
                    icols[i % 3].image(data, use_container_width=True)

            ans_key = f"ans_{entry_id}"
            if q["choices"]:
                if q["is_multi"]:
                    st.multiselect("คำตอบ", q["choices"], default=[], key=ans_key)
                else:
                    st.radio("คำตอบ", q["choices"], key=ans_key)
            else:
                st.text_input("คำตอบ", value=str(default_val), key=ans_key)

    if st.button("TRANSMIT DATA", type="primary", use_container_width=True):
        with st.spinner("กำลังส่งข้อมูล..."):
            final_answers = {eid: info[1] for eid, info in st.session_state["personal_data_map"].items()}
            for q in st.session_state["parsed_questions"]:
                final_answers[q["entry_id"]] = st.session_state.get(f"ans_{q['entry_id']}", "")
            page_history = simulate_page_history(st.session_state["parsed_questions"], final_answers, st.session_state["default_next"], st.session_state["page_count"])
            payload = build_submit_payload(st.session_state["personal_data_map"], st.session_state["parsed_questions"], final_answers, st.session_state["fbzx"], st.session_state["fvv"], page_history)
            try:
                res = requests.post(st.session_state["submit_url"], data=payload, headers=UA, timeout=25)
                if res.status_code == 200:
                    st.success("ส่งข้อมูลสำเร็จ")
                else:
                    st.error(f"ส่งไม่สำเร็จ (Error: {res.status_code})")
            except Exception as e:
                st.error(str(e))
