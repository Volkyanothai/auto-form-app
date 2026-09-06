import json
import re
import time
import random
import io
import difflib
import html as html_lib

import requests
import streamlit as st
from PIL import Image
from google import genai
from google.genai import types

from style import inject_css, render_header

st.set_page_config(page_title="EZEXAM | Auto Form System", page_icon="⚡", layout="centered")
inject_css()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"}

CHECKBOX_TYPE = 4

try:
    gemini_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    st.error("ระบบยังไม่ได้ตั้งค่า API Key กรุณาเพิ่ม GEMINI_API_KEY ใน Streamlit Secrets")
    st.stop()


def check_personal_info(q_title, choices, my_name, my_student_id, my_no, my_class):
    clean_title = re.sub(r'^\*?\*?(?:ข้อ\s*\d+[\s.:-]*)?', '', q_title.strip()).strip()
    clean_title = clean_title.rstrip('*').strip()
    title_lower = clean_title.lower()

    if len(clean_title) > 25: return None

    exam_stopwords = ["สาร", "เคมี", "ดาว", "วิทยาศาสตร์", "โรค", "องค์กร", "กษัตริย์", "ธาตุ",
                      "เมือง", "ประเทศ", "วรรณคดี", "ผู้แต่ง", "หัวใจ", "บรรยากาศ", "ผิวหนัง",
                      "ปฏิบัติการ", "ดิน", "หิน", "เชื่อม", "เครือข่าย", "อินเทอร์เน็ต", "เว็บ",
                      "จัดเป็น", "คืออะไร", "ข้อใด", "หมายถึง", "ตัวอักษรย่อ"]
    if any(sw in title_lower for sw in exam_stopwords): return None

    if my_name and any(k in title_lower for k in ["ชื่อ", "นามสกุล", "สกุล", "name"]):
        return (q_title, my_name, "ชื่อ-นามสกุล")
    if my_student_id and any(k in title_lower for k in ["เลขประจำตัว", "รหัส", "student id", "id"]):
        return (q_title, my_student_id, "เลขประจำตัว")
    if my_no and (any(k in title_lower for k in ["เลขที่", "no.", "number"]) or title_lower == "no"):
        return (q_title, my_no, "เลขที่")

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


def extract_all_potential_images(item):
    """
    พลังถึก: กวาดทุก URL ในข้อมูลของข้อสอบข้อนี้โดยไม่สนโดเมน
    และใช้การแปลงอักขระให้ถูกต้องทั้งหมด
    """
    s = json.dumps(item, ensure_ascii=False).replace('\\/', '/').replace('\\u003d', '=').replace('\\u0026', '&')
    
    # ดึงทุกอย่างที่อยู่ในเครื่องหมาย " " และขึ้นต้นด้วย http
    urls = re.findall(r'"(https?://[^"\\]+)"', s)
    
    # เผื่อ Google ใช้ลิงก์แบบ //
    for u in re.findall(r'"(//[^"\\]+)"', s):
        urls.append("https:" + u)
        
    valid = []
    for u in urls:
        ul = u.lower()
        # กรองเฉพาะของที่รู้แน่ๆ ว่าไม่ใช่รูปภาพทิ้ง
        if any(bad in ul for bad in ['gstatic.com', 'youtube', 'youtu.be', 'schema.org']):
            continue
        if u not in valid:
            valid.append(u)
            
    return valid


def compress_image(raw_bytes, max_dim=1024, quality=82):
    """
    ตัวคัดกรองขั้นเด็ดขาด: โหลดมาแล้วลองเปิดดู ถ้าไม่ใช่รูปภาพ (เช่นเป็นลิงก์เว็บ)
    มันจะพังและ return None ทันที ทำให้เราได้เฉพาะรูปภาพของแท้!
    """
    try:
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return None, None


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


render_header()

with st.container(border=True):
    st.markdown('<div class="glass-header">TARGET FORM LINK</div>', unsafe_allow_html=True)
    form_url = st.text_input("Form URL", placeholder="วางลิงก์ Google Form ที่นี่...", label_visibility="collapsed")

st.write("")

with st.container(border=True):
    st.markdown('<div class="glass-header">PERSONAL DATA & CONTEXT</div>', unsafe_allow_html=True)
    exam_context = st.text_area("EXAM CONTEXT", placeholder="เช่น ฟิสิกส์ ม.6 บทคลื่น...", height=68)
    st.write("")
    col1, col2 = st.columns(2)
    with col1:
        my_name = st.text_input("FULL NAME", placeholder="ชื่อ-นามสกุล")
        my_no = st.text_input("CLASS NUMBER", placeholder="เลขที่")
    with col2:
        my_student_id = st.text_input("STUDENT ID", placeholder="เลขประจำตัว")
        my_class = st.text_input("CLASSROOM", placeholder="เช่น 6/3")

st.write("")

if st.button("INITIATE ANALYSIS", type="primary", use_container_width=True):
    if not form_url:
        st.error("กรุณาใส่ลิงก์ Google Form ก่อน")
    else:
        with st.status("SYSTEM PROCESSING...", expanded=True) as status:
            try:
                st.write("กำลังอ่านโครงสร้างฟอร์ม...")
                client = genai.Client(api_key=gemini_key, http_options=types.HttpOptions(timeout=30000))
                res = requests.get(form_url, allow_redirects=True, headers=UA, timeout=20)
                html = res.text

                action_match = re.search(r'<form action="([^"]+)"', html)
                if action_match: submit_url = action_match.group(1)
                elif "/viewform" in res.url: submit_url = res.url.replace("/viewform", "/formResponse")
                else: submit_url = res.url.rstrip("/") + "/formResponse"

                match = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>', html, re.DOTALL)
                if not match:
                    status.update(label="อ่านฟอร์มไม่ได้", state="error")
                    st.stop()

                form_data = json.loads(match.group(1))
                questions_data = form_data[1][1] if len(form_data) > 1 and form_data[1] else []

                parsed_questions = []
                personal_data_map = {}
                page_count = 0
                last_standalone_imgs = []

                fbzx = ""
                fbzx_match = re.search(r'name="fbzx" value="([^"]*)"', html)
                if fbzx_match: fbzx = fbzx_match.group(1)

                st.write("กำลังกวาดล้างลิงก์รูปภาพทั้งหมดในข้อสอบ...")
                for item in questions_data:
                    if not item or len(item) < 4: continue
                    q_type = item[3]
                    
                    if q_type == 8: 
                        page_count += 1
                        continue
                        
                    # ถ้าเป็นรูปภาพลอยๆ กวาด URL เก็บไว้ก่อน
                    if q_type == 11 or len(item) < 5 or not item[4]:
                        last_standalone_imgs = extract_all_potential_images(item)
                        continue

                    q_title = item[1]
                    try: entry_id = "entry." + str(item[4][0][0])
                    except: continue
                    
                    choices_raw = item[4][0][1] if len(item[4][0]) > 1 else None
                    choices = [c[0] for c in choices_raw if c and len(c) > 0] if choices_raw else []

                    p_info = check_personal_info(q_title, choices, my_name, my_student_id, my_no, my_class)
                    if p_info:
                        personal_data_map[entry_id] = p_info
                        continue
                        
                    # กวาด URL ทุกเส้นที่อยู่ในข้อนี้
                    q_imgs = extract_all_potential_images(item)
                    if not q_imgs and last_standalone_imgs:
                        q_imgs = last_standalone_imgs
                        
                    last_standalone_imgs = [] 

                    parsed_questions.append({
                        "entry_id": entry_id,
                        "title": q_title,
                        "choices": choices,
                        "image_urls": q_imgs, # เก็บรายชื่อ URL ทั้งหมดไว้
                        "is_multi": q_type == CHECKBOX_TYPE,
                    })

                generated_page_history = ",".join(str(i) for i in range(page_count + 1))

                if parsed_questions:
                    st.write("กำลังดาวน์โหลดรูปภาพและส่งให้ AI วิเคราะห์...")
                    contents_payload = [
                        "Context: " + (exam_context if exam_context else "None") + "\n"
                        "Instructions:\n"
                        "1. คิดทบทวนคำตอบให้รอบคอบก่อนสรุป\n"
                        "2. ถ้ามีตัวเลือกให้ copy ข้อความตัวเลือกมาเป๊ะ ๆ ห้ามแต่งคำตอบขึ้นเอง\n"
                        "3. ถ้าข้อไหนมีป้าย [เลือกได้หลายข้อ] ให้ตอบ answer เป็น array\n"
                        "4. หากโจทย์ระบุว่า 'จากรูป' แต่มี [SYSTEM NOTE] กำกับว่าค้นหารูปไม่พบ ให้ตอบว่า 'ไม่พบรูปภาพ' และตั้ง confidence เป็น 0\n"
                        "5. ตอบเป็น JSON รูปแบบ: {\"entry.123\": {\"answer\": \"...\", \"confidence\": 90, \"reasoning\": \"...\"}}\n\n"
                        "Questions:"
                    ]

                    for idx, q in enumerate(parsed_questions, 1):
                        q_info = "\nข้อ " + str(idx) + " (ID: " + q["entry_id"] + ")"
                        if q.get("is_multi"): q_info += " [เลือกได้หลายข้อ]"
                        q_info += ": " + str(q["title"])
                        if q["choices"]: q_info += "\nตัวเลือก: " + json.dumps(q["choices"], ensure_ascii=False)
                        
                        contents_payload.append(q_info)

                        q_valid_images = []
                        if q.get("image_urls"):
                            for img_url in q["image_urls"]:
                                try:
                                    # ลองดาวน์โหลดทุก URL ที่หาเจอ
                                    img_res = requests.get(img_url, headers=UA, timeout=10)
                                    if img_res.status_code == 200:
                                        # ส่งเข้าเครื่องคัดกรอง ถ้าเป็นรูปภาพจริงๆ จะได้ไฟล์กลับมา
                                        small_bytes, mime_type = compress_image(img_res.content)
                                        if small_bytes:
                                            contents_payload.append(types.Part.from_bytes(data=small_bytes, mime_type=mime_type))
                                            q_valid_images.append(small_bytes) # เก็บรูปไว้โชว์ในแอป
                                except Exception:
                                    pass
                        
                        q["valid_images"] = q_valid_images # บันทึกรูปของจริงที่โหลดได้

                        if not q_valid_images:
                            if any(kw in str(q["title"]) for kw in ["รูป", "ภาพ"]):
                                contents_payload.append("\n[SYSTEM NOTE: ค้นหารูปภาพไม่พบในระบบ]\n")

                    gen_config = types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(thinking_budget=2048),
                        temperature=0.1,
                        max_output_tokens=3072,
                    )

                    models_to_try = ["gemini-flash-latest", "gemini-3.6-flash", "gemini-3.1-flash-lite"]
                    MAX_RETRIES_PER_MODEL = 2
                    response = None
                    last_err = None
                    for model_name in models_to_try:
                        for attempt in range(MAX_RETRIES_PER_MODEL):
                            try:
                                response = client.models.generate_content(model=model_name, contents=contents_payload, config=gen_config)
                                if response and response.text: break
                            except Exception as err:
                                last_err = err
                                response = None
                                err_text = str(err)
                                is_overload = ("503" in err_text or "UNAVAILABLE" in err_text or "429" in err_text or "RESOURCE_EXHAUSTED" in err_text or "504" in err_text)
                                if is_overload and attempt < MAX_RETRIES_PER_MODEL - 1:
                                    wait_time = (2 ** attempt) * 2 + random.uniform(0, 1)
                                    st.write(f"โมเดลหน่วง กำลังลองใหม่ใน {round(wait_time, 1)} วิ...")
                                    time.sleep(wait_time)
                                    continue
                                else: break
                        if response and response.text: break

                    if not response: raise last_err if last_err else RuntimeError("AI ไม่ตอบกลับ")

                    raw_ans = re.sub(r'`{3}(?:json)?', '', response.text.strip()).strip()
                    try: ai_answers = json.loads(raw_ans)
                    except json.JSONDecodeError:
                        m = re.search(r'\{.*\}', raw_ans, re.DOTALL)
                        ai_answers = json.loads(m.group(0)) if m else {}
                else:
                    ai_answers = {}

                st.session_state["submit_url"] = submit_url
                st.session_state["parsed_questions"] = parsed_questions
                st.session_state["personal_data_map"] = personal_data_map
                st.session_state["ai_answers"] = ai_answers
                st.session_state["pageHistory"] = generated_page_history
                st.session_state["fbzx"] = fbzx

                status.update(label="ANALYSIS COMPLETE", state="complete", expanded=False)

            except Exception as e:
                status.update(label="ERROR", state="error")
                st.error("รายละเอียด: " + str(e))

if "parsed_questions" in st.session_state:
    st.markdown('<div class="section-title">REVIEW & SUBMIT</div>', unsafe_allow_html=True)
    final_payload = {}

    if st.session_state["personal_data_map"]:
        with st.container(border=True):
            st.markdown('<div class="glass-header">AUTO-FILLED DATA</div>', unsafe_allow_html=True)
            items = list(st.session_state["personal_data_map"].items())
            cols = st.columns(min(len(items), 2))
            for idx, (entry_id, info) in enumerate(items):
                title, val, cat = info
                cols[idx % len(cols)].text_input(title, value=val, key="input_" + entry_id, disabled=True)
                final_payload[entry_id] = val

    for idx, q in enumerate(st.session_state["parsed_questions"], 1):
        entry_id = q["entry_id"]
        title = html_lib.escape(str(q["title"]))
        choices = q["choices"]
        valid_images = q.get("valid_images", [])
        is_multi = q.get("is_multi", False)

        q_data = st.session_state["ai_answers"].get(entry_id, {})
        if isinstance(q_data, dict):
            default_val = q_data.get("answer", "")
            score = q_data.get("confidence", 70)
            reason = q_data.get("reasoning", "ประมวลผลอัตโนมัติ")
        else:
            default_val = q_data
            score = 80
            reason = "ประมวลผลอัตโนมัติ"

        try: score = int(score)
        except Exception: score = 70

        color = "#5fe3d0" if score >= 85 else "#e8c98a" if score >= 60 else "#ff7a8a"

        with st.container(border=True):
            st.markdown('<div class="q-title">' + str(idx) + '. ' + title + '</div>', unsafe_allow_html=True)

            bar_html = (
                '<div class="confidence-track">'
                '<div class="confidence-fill" style="width:' + str(score) + '%;background:' + color + ';box-shadow:0 0 12px ' + color + ';"></div></div>'
                '<div style="font-size:.72rem;font-weight:700;color:' + color + ';letter-spacing:1px;margin-bottom:10px;">CONFIDENCE ' + str(score) + '%</div>'
                '<div class="reasoning-text"><b>AI REASON:</b> ' + html_lib.escape(str(reason)) + '</div>'
            )
            st.markdown(bar_html, unsafe_allow_html=True)

            # โชว์รูปภาพของจริงที่ดึงและคัดกรองมาแล้ว
            if valid_images:
                for img_bytes in valid_images:
                    st.image(img_bytes, use_container_width=True)
                    st.caption("✅ ดึงไฟล์รูปภาพที่แนบสำเร็จ")

            if is_multi and choices:
                default_list = [str(v).strip().lower() for v in default_val] if isinstance(default_val, list) else [str(default_val).strip().lower()] if default_val else []
                default_selected = [c for c in choices if str(c).strip().lower() in default_list]
                final_payload[entry_id] = st.multiselect("ANSWER", options=choices, default=default_selected, key="ans_" + entry_id, label_visibility="collapsed")
            elif choices:
                default_idx, matched_ok = match_choice(default_val, choices)
                if not matched_ok: st.warning("⚠️ คำตอบ AI ไม่ตรงกับตัวเลือกเป๊ะ ๆ กรุณาตรวจสอบข้อนี้เอง")
                final_payload[entry_id] = st.selectbox("ANSWER", options=choices, index=default_idx, key="ans_" + entry_id, label_visibility="collapsed")
            else:
                final_payload[entry_id] = st.text_input("ANSWER", value=str(default_val), key="ans_" + entry_id, label_visibility="collapsed")

    st.write("")
    final_payload["pageHistory"] = st.session_state.get("pageHistory", "0")
    if st.session_state.get("fbzx"): final_payload["fbzx"] = st.session_state["fbzx"]
    final_payload["fvv"] = "1"

    if st.button("TRANSMIT DATA", type="primary", use_container_width=True):
        with st.spinner("กำลังส่งข้อมูล..."):
            try:
                res_submit = requests.post(st.session_state["submit_url"], data=final_payload, headers=UA, timeout=25)
            except Exception as e:
                st.error("ส่งไม่สำเร็จ: " + str(e))
                st.stop()

        if res_submit.status_code == 200:
            st.balloons()
            st.success("ส่งข้อมูลสำเร็จ")
            link_match = re.search(r'href="([^"]*?viewscore\?[^"]*)"', res_submit.text)
            if link_match:
                score_url = html_lib.unescape(link_match.group(1))
                try:
                    score_page = requests.get(score_url, headers=UA, timeout=8).text
                    score_match = re.search(r'<span[^>]*>\s*([0-9]+)\s*</span>\s*<span[^>]*>\s*(?:/|&#47;|จาก)\s*([0-9]+)\s*</span>', score_page)
                    if not score_match: score_match = re.search(r'([0-9]+)\s*(?:/|&#47;|จาก)\s*([0-9]+)\s*(?:คะแนน|points)', score_page)
                    if score_match: st.markdown('<div class="score-box"><div class="score-val">' + score_match.group(1) + ' / ' + score_match.group(2) + '</div><div class="score-lb">Score Secured</div></div>', unsafe_allow_html=True)
                except Exception: pass
                st.markdown('<a href="' + score_url + '" target="_blank" class="score-link">เปิดหน้ายืนยันคะแนน</a>', unsafe_allow_html=True)
            else:
                st.warning("ส่งสำเร็จแล้ว แต่ฟอร์มนี้ไม่ปล่อยคะแนนอัตโนมัติ")
        else:
            st.error("Error Code: " + str(res_submit.status_code))
