import json
import re
import time
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

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
CHECKBOX_TYPE = 4

# --- ระบบกวาด API Key อัตโนมัติ ---
api_keys = [st.secrets[k] for k in st.secrets if "GEMINI_API_KEY" in k]
if not api_keys:
    st.error("ระบบยังไม่ได้ตั้งค่า API Key กรุณาเพิ่ม GEMINI_API_KEY (1, 2, 3...) ใน Streamlit Secrets")
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
        if len(raw_bytes) < 3000: return None, None
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        if max(img.size) > max_dim: img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception: return None, None

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
                # --- จัดการแปลงลิงก์สำหรับการ Submit ---
                if "viewform" in form_url:
                    st.session_state["submit_url"] = form_url.replace("viewform", "formResponse")
                elif "formResponse" not in form_url:
                    st.session_state["submit_url"] = form_url.rstrip("/") + "/formResponse"
                else:
                    st.session_state["submit_url"] = form_url

                st.write("กำลังอ่านโครงสร้างฟอร์มด้วยความเร็วสูง...")
                res = requests.get(form_url, allow_redirects=True, headers=UA, timeout=15)
                html = res.text
                html_no_meta = re.sub(r'<meta[^>]*property="og:image"[^>]*>', '', html)
                img_urls_found = re.findall(r'https://lh\d?\.?googleusercontent\.com/[^\s"\'<>]+', html_no_meta)
                img_counter = 0

                match = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>', html, re.DOTALL)
                if not match:
                    status.update(label="อ่านฟอร์มไม่ได้", state="error")
                    st.stop()

                form_data = json.loads(match.group(1))
                questions_data = form_data[1][1] if len(form_data) > 1 and form_data[1] else []

                parsed_questions = []
                personal_data_map = {}
                page_count = 0

                st.write("กำลังสกัดคำถามและค้นหารูปภาพ...")
                for item in questions_data:
                    if not item or len(item) < 4: continue
                    q_type = item[3]

                    if q_type == 8:
                        page_count += 1
                        continue

                    if q_type == 11 or len(item) < 5 or not item[4]:
                        continue

                    image_url = None
                    has_media = len(item) > 9 and item[9]
                    if has_media and img_counter < len(img_urls_found):
                        image_url = img_urls_found[img_counter]
                        img_counter += 1

                    q_title = item[1]
                    try: entry_id = "entry." + str(item[4][0][0])
                    except: continue

                    choices_raw = item[4][0][1] if len(item[4][0]) > 1 else None
                    choices = [c[0] for c in choices_raw if c and len(c) > 0] if choices_raw else []

                    p_info = check_personal_info(q_title, choices, my_name, my_student_id, my_no, my_class)
                    if p_info:
                        personal_data_map[entry_id] = p_info
                        continue

                    parsed_questions.append({
                        "entry_id": entry_id,
                        "title": q_title,
                        "choices": choices,
                        "is_multi": q_type == CHECKBOX_TYPE,
                        "image_url": image_url,
                    })

                if parsed_questions:
                    st.write("AI กำลังวิเคราะห์ข้อมูลข้อสอบ...")
                    contents_payload = []

                    main_prompt = (
                        f"Context: {exam_context if exam_context else 'None'}\n"
                        "Instructions:\n"
                        "1. คิดทบทวนคำตอบให้รอบคอบก่อนสรุป\n"
                        "2. ถ้ามีตัวเลือกให้ copy ข้อความตัวเลือกมาเป๊ะ ๆ ห้ามแต่งคำตอบขึ้นเอง\n"
                        "3. ถ้าข้อไหนมีป้าย [เลือกได้หลายข้อ] ให้ตอบ answer เป็น array\n"
                        "4. หากข้อใดมีรูปภาพแนบมาให้ ให้วิเคราะห์คำตอบจากรูปภาพนั้นเป็นหลัก\n"
                        "5. ตอบเป็น JSON รูปแบบ: {\"entry.123\": {\"answer\": \"...\", \"confidence\": 90, \"reasoning\": \"...\"}}\n"
                    )
                    contents_payload.append(types.Part.from_text(text=main_prompt))
                    contents_payload.append(types.Part.from_text(text="\nQuestions:\n"))

                    downloaded_preview = []

                    for idx, q in enumerate(parsed_questions, 1):
                        q_info = f"\nข้อ {idx} (ID: {q['entry_id']})"
                        if q.get("is_multi"): q_info += " [เลือกได้หลายข้อ]"
                        q_info += f": {q['title']}"
                        if q["choices"]: q_info += f"\nตัวเลือก: {json.dumps(q['choices'], ensure_ascii=False)}"

                        contents_payload.append(types.Part.from_text(text=q_info))

                        if q.get("image_url"):
                            try:
                                img_res = requests.get(q["image_url"], headers=UA, timeout=10)
                                if img_res.status_code == 200:
                                    valid_bytes, mime = compress_and_verify_image(img_res.content)
                                    if valid_bytes:
                                        contents_payload.append(types.Part.from_bytes(data=valid_bytes, mime_type=mime))
                                        downloaded_preview.append(valid_bytes)
                            except Exception:
                                pass

                    gen_config = types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(thinking_budget=2048),
                        temperature=0.1,
                        max_output_tokens=3072,
                    )

                    models_to_try = ["gemini-3.8-flash", "gemini-3.8-flash-8b", "gemini-3.8-pro", "gemini-flash-latest"]
                    MAX_RETRIES = 5
                    response = None
                    last_err = None

                    for current_key in api_keys:
                        if response: break
                        client = genai.Client(api_key=current_key, http_options=types.HttpOptions(timeout=30000))

                        for model_name in models_to_try:
                            if response: break
                            for attempt in range(MAX_RETRIES):
                                try:
                                    response = client.models.generate_content(model=model_name, contents=contents_payload, config=gen_config)
                                    if response and response.text: break
                                except Exception as err:
                                    last_err = err
                                    err_text = str(err)
                                    
                                    # ===== ส่วนที่ให้ระบบ "รอ" เมื่อโควต้าเต็ม (429) =====
                                    if "429" in err_text or "RESOURCE_EXHAUSTED" in err_text:
                                        st.write(f"⚠️ โควต้า API เต็มชั่วคราว (รอบที่ {attempt+1}/{MAX_RETRIES})... กำลังพักรอ 60 วินาทีเพื่อให้ระบบรีเซ็ต")
                                        time.sleep(60) # หน่วงเวลา 1 นาทีให้โควต้ารีเซ็ต
                                        continue # ลองส่งใหม่อีกครั้ง
                                    # ========================================================
                                    
                                    if ("503" in err_text or "504" in err_text) and attempt < MAX_RETRIES - 1:
                                        time.sleep(3)
                                        continue
                                    break


                    if not response: raise last_err if last_err else RuntimeError("API Key ทุกเส้นโควต้าเต็มหมดแล้ว หรือระบบ AI ขัดข้อง")

                    raw_ans = re.sub(r'`{3}(?:json)?', '', response.text.strip()).strip()
                    try: ai_answers = json.loads(raw_ans)
                    except json.JSONDecodeError:
                        m = re.search(r'\{.*\}', raw_ans, re.DOTALL)
                        ai_answers = json.loads(m.group(0)) if m else {}
                else:
                    ai_answers = {}
                    downloaded_preview = []

                st.session_state["parsed_questions"] = parsed_questions
                st.session_state["personal_data_map"] = personal_data_map
                st.session_state["ai_answers"] = ai_answers
                st.session_state["downloaded_preview"] = downloaded_preview

                status.update(label="ANALYSIS COMPLETE", state="complete", expanded=False)

            except Exception as e:
                status.update(label="ERROR", state="error")
                st.error("รายละเอียด: " + str(e))

# --- ส่วนทบทวนและปุ่ม Submit ถูกนำมารวมไว้ด้วยกัน ---
if "parsed_questions" in st.session_state:
    st.markdown('<div class="section-title">REVIEW (สำหรับทบทวนก่อนสอบเท่านั้น)</div>', unsafe_allow_html=True)

    if st.session_state.get("downloaded_preview"):
        with st.container(border=True):
            st.markdown('<div class="glass-header">📸 รูปภาพที่ดึงมาจากโจทย์</div>', unsafe_allow_html=True)
            cols = st.columns(min(len(st.session_state["downloaded_preview"]), 4))
            for idx, img_bytes in enumerate(st.session_state["downloaded_preview"]):
                cols[idx % 4].image(img_bytes, use_container_width=True, caption=f"รูปที่ {idx+1}")

    if st.session_state["personal_data_map"]:
        with st.container(border=True):
            st.markdown('<div class="glass-header">AUTO-FILLED DATA</div>', unsafe_allow_html=True)
            items = list(st.session_state["personal_data_map"].items())
            cols = st.columns(min(len(items), 2))
            for idx, (entry_id, info) in enumerate(items):
                title, val, cat = info
                cols[idx % len(cols)].text_input(title, value=val, key="input_" + entry_id, disabled=True)

    for idx, q in enumerate(st.session_state["parsed_questions"], 1):
        entry_id = q["entry_id"]
        title = html_lib.escape(str(q["title"]))
        choices = q["choices"]

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
                '<div style="margin-top:10px;font-weight:700;">เฉลยที่ AI แนะนำ: ' + html_lib.escape(str(default_val)) + '</div>'
            )
            st.markdown(bar_html, unsafe_allow_html=True)

            if choices:
                st.caption("ตัวเลือกทั้งหมด: " + ", ".join(str(c) for c in choices))

    st.write("")
    
    # --- ปุ่มส่งข้อมูล (รวมร่าง) ---
    if st.button("TRANSMIT DATA", type="primary", use_container_width=True):
        with st.spinner("กำลังประกอบข้อมูลและจัดส่ง..."):
            
            # --- สร้าง Payload สำหรับส่งฟอร์ม ---
            final_payload = {}
            
            # 1. ใส่ข้อมูลส่วนตัว
            for entry_id, info in st.session_state["personal_data_map"].items():
                title, val, cat = info
                final_payload[entry_id] = val
                
            # 2. ใส่คำตอบ AI
            for q in st.session_state["parsed_questions"]:
                entry_id = q["entry_id"]
                q_data = st.session_state["ai_answers"].get(entry_id, {})
                ai_ans = q_data.get("answer", "") if isinstance(q_data, dict) else q_data
                
                # เช็คคำตอบให้ตรงกับ Choices เพื่อป้องกัน Error ตอน POST
                if q["choices"]:
                    if q["is_multi"] and isinstance(ai_ans, list):
                        valid_ans = []
                        for ans_item in ai_ans:
                            idx, matched = match_choice(ans_item, q["choices"])
                            valid_ans.append(q["choices"][idx] if matched else ans_item)
                        final_payload[entry_id] = valid_ans
                    else:
                        idx, matched = match_choice(ai_ans, q["choices"])
                        final_payload[entry_id] = q["choices"][idx] if matched else ai_ans
                else:
                    final_payload[entry_id] = ai_ans

            try:
                # ทำการส่ง POST Request ไปยัง submit_url
                res_submit = requests.post(st.session_state["submit_url"], data=final_payload, headers=UA, timeout=25)
            except Exception as e:
                st.error("ส่งไม่สำเร็จ: " + str(e))
                st.stop()

        # --- ตรวจสอบผลลัพธ์ ---
        if res_submit.status_code == 200:
            st.balloons()
            st.success("ส่งข้อมูลสำเร็จ")
            
            # ค้นหาลิงก์ดูคะแนน (หากระบบตั้งให้แสดงอัตโนมัติ)
            link_match = re.search(r'href="([^"]*?viewscore\?[^"]*)"', res_submit.text)
            if link_match:
                score_url = html_lib.unescape(link_match.group(1))
                try:
                    score_page = requests.get(score_url, headers=UA, timeout=8).text
                    score_match = re.search(r'<span[^>]*>\s*([0-9]+)\s*</span>\s*<span[^>]*>\s*(?:/|&#47;|จาก)\s*([0-9]+)\s*</span>', score_page)
                    if not score_match: 
                        score_match = re.search(r'([0-9]+)\s*(?:/|&#47;|จาก)\s*([0-9]+)\s*(?:คะแนน|points)', score_page)
                    if score_match: 
                        st.markdown('<div class="score-box"><div class="score-val">' + score_match.group(1) + ' / ' + score_match.group(2) + '</div><div class="score-lb">Score Secured</div></div>', unsafe_allow_html=True)
                except Exception: 
                    pass
                st.markdown('<a href="' + score_url + '" target="_blank" class="score-link">เปิดหน้ายืนยันคะแนน</a>', unsafe_allow_html=True)
            else:
                st.warning("ส่งสำเร็จแล้ว แต่ฟอร์มนี้ไม่ปล่อยคะแนนอัตโนมัติ")
        else:
            st.error("Error Code: " + str(res_submit.status_code))
