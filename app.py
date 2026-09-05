import json
import re
import time
import html as html_lib

import requests
import streamlit as st
from google import genai
from google.genai import types

from style import inject_css, render_header

st.set_page_config(page_title="EZEXAM | Auto Form System", page_icon="⚡", layout="centered")
inject_css()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"}

try:
    gemini_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    st.error("ระบบยังไม่ได้ตั้งค่า API Key กรุณาเพิ่ม GEMINI_API_KEY ใน Streamlit Secrets")
    st.stop()


def check_personal_info(q_title, choices, my_name, my_student_id, my_no, my_class):
    clean_title = re.sub(r'^\*?\*?(?:ข้อ\s*\d+[\s.:-]*)?', '', q_title.strip()).strip()
    clean_title = clean_title.rstrip('*').strip()
    title_lower = clean_title.lower()

    if len(clean_title) > 25:
        return None

    exam_stopwords = ["สาร", "เคมี", "ดาว", "วิทยาศาสตร์", "โรค", "องค์กร", "กษัตริย์", "ธาตุ",
                      "เมือง", "ประเทศ", "วรรณคดี", "ผู้แต่ง", "หัวใจ", "บรรยากาศ", "ผิวหนัง",
                      "ปฏิบัติการ", "ดิน", "หิน", "เชื่อม", "เครือข่าย", "อินเทอร์เน็ต", "เว็บ",
                      "จัดเป็น", "คืออะไร", "ข้อใด", "หมายถึง", "ตัวอักษรย่อ"]
    if any(sw in title_lower for sw in exam_stopwords):
        return None

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


def extract_image_url(item):
    found_urls = []

    def find_urls(obj):
        if isinstance(obj, str) and obj.startswith(("http://", "https://")):
            if "/viewform" not in obj and "/formResponse" not in obj and "forms.gle" not in obj:
                found_urls.append(obj)
        elif isinstance(obj, list):
            for sub in obj:
                find_urls(sub)
        elif isinstance(obj, dict):
            for v in obj.values():
                find_urls(v)

    find_urls(item)
    return found_urls[0] if found_urls else None


render_header()

with st.container(border=True):
    st.markdown('<div class="glass-header">TARGET FORM LINK</div>', unsafe_allow_html=True)
    form_url = st.text_input("Form URL", placeholder="วางลิงก์ Google Form ที่นี่...",
                             label_visibility="collapsed")

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
                client = genai.Client(api_key=gemini_key)
                res = requests.get(form_url, allow_redirects=True, headers=UA, timeout=20)
                html = res.text

                action_match = re.search(r'<form action="([^"]+)"', html)
                if action_match:
                    submit_url = action_match.group(1)
                elif "/viewform" in res.url:
                    submit_url = res.url.replace("/viewform", "/formResponse")
                else:
                    submit_url = res.url.rstrip("/") + "/formResponse"

                match = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>', html, re.DOTALL)
                if not match:
                    status.update(label="อ่านฟอร์มไม่ได้ (ฟอร์มอาจปิด หรือต้องล็อกอิน)", state="error")
                    st.stop()

                form_data = json.loads(match.group(1))
                questions_data = form_data[1][1] if len(form_data) > 1 and form_data[1] else []

                parsed_questions = []
                personal_data_map = {}
                page_count = 0

                fbzx = ""
                fbzx_match = re.search(r'name="fbzx" value="([^"]*)"', html)
                if fbzx_match:
                    fbzx = fbzx_match.group(1)

                st.write("กำลังแยกหน้าและรูปภาพ...")
                for item in questions_data:
                    if not item or len(item) < 4:
                        continue
                    if item[3] == 8:
                        page_count += 1
                        continue
                    if len(item) < 5 or not item[4]:
                        continue

                    q_title = item[1]
                    entry_id = "entry." + str(item[4][0][0])
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
                        "image_url": extract_image_url(item),
                    })

                generated_page_history = ",".join(str(i) for i in range(page_count + 1))

                if parsed_questions:
                    st.write("AI กำลังคิดคำตอบ...")
                    prompt_data = []
                    for idx, q in enumerate(parsed_questions, 1):
                        q_info = "ข้อ " + str(idx) + " (ID: " + q["entry_id"] + "): " + str(q["title"])
                        if q.get("image_url"):
                            q_info += " [มีรูปภาพแนบ]"
                        if q["choices"]:
                            q_info += "\nตัวเลือก: " + json.dumps(q["choices"], ensure_ascii=False)
                        prompt_data.append(q_info)

                    questions_block = "\n".join(prompt_data)
                    full_prompt = (
                        "Context: " + (exam_context if exam_context else "None") + "\n"
                        "Questions:\n" + questions_block + "\n"
                        "Instructions:\n"
                        "1. ตอบให้แม่นยำที่สุด\n"
                        "2. ข้อช้อยส์ ต้องเลือกตรงตามช้อยส์เป๊ะๆ\n"
                        '3. ตอบเป็น JSON เท่านั้น: '
                        '{"entry.123": {"answer": "...", "confidence": 90, "reasoning": "..."}}'
                    )

                    contents_payload = [full_prompt]
                    for q in parsed_questions:
                        if q.get("image_url"):
                            try:
                                img_res = requests.get(q["image_url"], headers=UA, timeout=8)
                                if img_res.status_code == 200:
                                    mime_type = img_res.headers.get("Content-Type", "image/jpeg")
                                    if "image" not in mime_type:
                                        mime_type = "image/jpeg"
                                    contents_payload.append(
                                        types.Part.from_bytes(data=img_res.content, mime_type=mime_type)
                                    )
                            except Exception:
                                pass

                    models_to_try = ["gemini-flash-latest", "gemini-3.6-flash"]
                    response = None
                    last_err = None
                    for model_name in models_to_try:
                        try:
                            response = client.models.generate_content(
                                model=model_name, contents=contents_payload
                            )
                            if response and response.text:
                                break
                        except Exception as err:
                            last_err = err
                            response = None
                            time.sleep(2)

                    if not response:
                        raise last_err if last_err else RuntimeError("AI ไม่ตอบกลับ")

                    raw_ans = re.sub(r'`{3}(?:json)?', '', response.text.strip()).strip()
                    try:
                        ai_answers = json.loads(raw_ans)
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
        img_url = q.get("image_url")

        q_data = st.session_state["ai_answers"].get(entry_id, {})
        if isinstance(q_data, dict):
            default_val = q_data.get("answer", "")
            score = q_data.get("confidence", 70)
            reason = q_data.get("reasoning", "ประมวลผลอัตโนมัติ")
        else:
            default_val = q_data
            score = 80
            reason = "ประมวลผลอัตโนมัติ"

        try:
            score = int(score)
        except Exception:
            score = 70

        if score >= 85:
            color = "#5fe3d0"
        elif score >= 60:
            color = "#e8c98a"
        else:
            color = "#ff7a8a"

        with st.container(border=True):
            st.markdown('<div class="q-title">' + str(idx) + '. ' + title + '</div>',
                        unsafe_allow_html=True)

            bar_html = (
                '<div class="confidence-track">'
                '<div class="confidence-fill" style="width:' + str(score) + '%;'
                'background:' + color + ';box-shadow:0 0 12px ' + color + ';"></div></div>'
                '<div style="font-size:.72rem;font-weight:700;color:' + color + ';'
                'letter-spacing:1px;margin-bottom:10px;">CONFIDENCE ' + str(score) + '%</div>'
                '<div class="reasoning-text"><b>AI REASON:</b> '
                + html_lib.escape(str(reason)) + '</div>'
            )
            st.markdown(bar_html, unsafe_allow_html=True)

            if img_url:
                st.image(img_url, use_container_width=True)

            if choices:
                default_idx = 0
                for i, c in enumerate(choices):
                    if str(c).strip() == str(default_val).strip() or str(c) in str(default_val):
                        default_idx = i
                        break
                final_payload[entry_id] = st.selectbox(
                    "ANSWER", options=choices, index=default_idx,
                    key="ans_" + entry_id, label_visibility="collapsed"
                )
            else:
                final_payload[entry_id] = st.text_input(
                    "ANSWER", value=str(default_val),
                    key="ans_" + entry_id, label_visibility="collapsed"
                )

    st.write("")

    final_payload["pageHistory"] = st.session_state.get("pageHistory", "0")
    if st.session_state.get("fbzx"):
        final_payload["fbzx"] = st.session_state["fbzx"]
    final_payload["fvv"] = "1"

    if st.button("TRANSMIT DATA", type="primary", use_container_width=True):
        with st.spinner("กำลังส่งข้อมูล..."):
            try:
                res_submit = requests.post(st.session_state["submit_url"],
                                           data=final_payload, headers=UA, timeout=25)
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
                    score_match = re.search(
                        r'<span[^>]*>\s*([0-9]+)\s*</span>\s*<span[^>]*>\s*(?:/|&#47;|จาก)\s*([0-9]+)\s*</span>',
                        score_page)
                    if not score_match:
                        score_match = re.search(
                            r'([0-9]+)\s*(?:/|&#47;|จาก)\s*([0-9]+)\s*(?:คะแนน|points)', score_page)
                    if score_match:
                        st.markdown(
                            '<div class="score-box"><div class="score-val">'
                            + score_match.group(1) + ' / ' + score_match.group(2)
                            + '</div><div class="score-lb">Score Secured</div></div>',
                            unsafe_allow_html=True)
                except Exception:
                    pass

                st.markdown(
                    '<a href="' + score_url + '" target="_blank" class="score-link">'
                    'เปิดหน้ายืนยันคะแนน</a>',
                    unsafe_allow_html=True)
            else:
                st.warning("ส่งสำเร็จแล้ว แต่ฟอร์มนี้ไม่ปล่อยคะแนนอัตโนมัติ")
        else:
            st.error("Error Code: " + str(res_submit.status_code))
