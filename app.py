import json
import re
import requests
import time
import html as html_lib
from google import genai
from google.genai import types
import streamlit as st

st.set_page_config(page_title="AutoForm AI", page_icon="✨", layout="centered")

# ==========================================
# 🔑 ระบบจัดการ API Key อัตโนมัติ (ซ่อนจากผู้ใช้)
# ==========================================
try:
    gemini_key = st.secrets["GEMINI_API_KEY"]
except:
    st.error("⚠️ ระบบยังไม่ได้ตั้งค่า API Key จากหลังบ้าน กรุณาเพิ่ม GEMINI_API_KEY ใน Streamlit Secrets")
    st.stop()

# ==========================================
# 🎨 CSS Overhaul
# ==========================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600&display=swap');
    html, body, [class*="css"] {
        font-family: 'Sarabun', sans-serif !important;
    }
    button[data-testid="baseButton-primary"] {
        background-color: #4F46E5 !important;
        border-color: #4F46E5 !important;
        color: white !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        padding: 0.5rem 1rem !important;
        transition: all 0.3s ease;
    }
    button[data-testid="baseButton-primary"]:hover {
        background-color: #4338CA !important;
        box-shadow: 0 4px 12px rgba(79, 70, 229, 0.3) !important;
        transform: translateY(-2px);
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border: 1px solid #E5E7EB !important;
        border-radius: 12px !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05) !important;
        background-color: #ffffff !important;
        padding: 1rem !important;
        border-top: 4px solid #4F46E5 !important;
    }
    .confidence-track {
        width: 100%;
        height: 5px;
        background-color: #F3F4F6;
        border-radius: 4px;
        margin: 10px 0;
        overflow: hidden;
    }
    .confidence-fill {
        height: 100%;
        border-radius: 4px;
        transition: width 0.8s ease-out;
    }
    .reasoning-text {
        color: #4B5563;
        font-size: 0.9rem;
        background-color: #EEF2FF;
        padding: 8px 12px;
        border-radius: 6px;
        border-left: 3px solid #6366F1;
        margin-bottom: 12px;
    }
    .score-box {
        background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
        color: white;
        padding: 15px;
        border-radius: 10px;
        text-align: center;
        font-size: 1.2rem;
        font-weight: 600;
        margin-top: 15px;
        margin-bottom: 15px;
        box-shadow: 0 4px 10px rgba(124, 58, 237, 0.3);
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ==========================================
# ⚙️ Core Functions
# ==========================================
def check_personal_info(q_title, choices, my_name, my_student_id, my_no, my_class):
    clean_title = re.sub(r'^\*?\*?(?:ข้อ\s*\d+[\s.:-]*)?', '', q_title.strip()).strip()
    clean_title = re.sub(r'\*+\s*$', '', clean_title).strip()
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

def extract_image_url(item):
    found_urls = []
    def find_urls(obj):
        if isinstance(obj, str) and (obj.startswith("http://") or obj.startswith("https://")):
            if "/viewform" not in obj and "/formResponse" not in obj and "forms.gle" not in obj: found_urls.append(obj)
        elif isinstance(obj, list):
            for sub in obj: find_urls(sub)
        elif isinstance(obj, dict):
            for v in obj.values(): find_urls(v)
    find_urls(item)
    return found_urls[0] if found_urls else None

# ==========================================
# 📱 Layout หลัก
# ==========================================
st.markdown("<h1 style='text-align: center; color: #1F2937; margin-bottom: 0;'>✨ AutoForm AI</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #6B7280; margin-top: 0; margin-bottom: 30px;'>ผู้ช่วยทำฟอร์มอัจฉริยะ (Vision AI Edition)</p>", unsafe_allow_html=True)

with st.container(border=True):
    st.markdown("#### ⚙️ 1. ตั้งค่าแบบฟอร์ม (Setup)")
    form_url = st.text_input("🔗 ลิงก์ Google Form (forms.gle/...)", placeholder="วางลิงก์ฟอร์มที่นี่...")

st.write("")

with st.expander("👤 2. ข้อมูลผู้สอบ & บริบท (พับเก็บได้)", expanded=True):
    exam_context = st.text_area("📚 บริบทข้อสอบ (แนะนำให้ใส่)", placeholder="เช่น วิทยาศาสตร์ ม.ปลาย...", height=68)
    st.write("---")
    col1, col2 = st.columns(2)
    with col1:
        my_name = st.text_input("ชื่อ-นามสกุล", placeholder="กรอกชื่อ...")
        my_no = st.text_input("เลขที่", placeholder="กรอกเลขที่...")
    with col2:
        my_student_id = st.text_input("เลขประจำตัว", placeholder="กรอกรหัส...")
        my_class = st.text_input("ชั้น/ห้อง", placeholder="เช่น ม.6/3...")

st.write("")

# ==========================================
# 🚀 Action: ปุ่มประมวลผล
# ==========================================
if st.button("🚀 เริ่มวิเคราะห์ข้อสอบ", type="primary", use_container_width=True):
    if not form_url:
        st.error("⚠️ กรุณากรอกลิงก์ฟอร์มให้ครบถ้วน")
    else:
        with st.status("🤖 กำลังวิเคราะห์ข้อมูล...", expanded=True) as status:
            try:
                st.write("📥 กำลังดึงโครงสร้าง...")
                client = genai.Client(api_key=gemini_key)
                res = requests.get(form_url, allow_redirects=True)
                html = res.text

                action_match = re.search(r'<form action="([^"]+)"', html)
                submit_url = action_match.group(1) if action_match else (
                    res.url.replace("/viewform", "/formResponse") if "/viewform" in res.url else res.url.rstrip("/") + "/formResponse"
                )

                match = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>', html, re.DOTALL)
                if not match:
                    status.update(label="❌ ไม่พบฟอร์ม", state="error")
                    st.stop()

                form_data = json.loads(match.group(1))
                questions_data = form_data[1][1] if len(form_data) > 1 and form_data[1] else []

                parsed_questions = []
                personal_data_map = {}
                
                page_count = 0
                
                fbzx = ""
                fbzx_match = re.search(r'name="fbzx" value="([^"]*)"', html)
                if fbzx_match: fbzx = fbzx_match.group(1)

                st.write("🔍 แยกโจทย์และคำนวณจำนวนหน้า...")
                for item in questions_data:
                    if not item or len(item) < 4: continue
                    
                    if item[3] == 8:
                        page_count += 1
                        continue

                    if len(item) < 5 or not item[4]: continue
                    
                    q_title = item[1]
                    entry_id = f"entry.{item[4][0][0]}"
                    choices_raw = item[4][0][1] if len(item[4][0]) > 1 else None
                    choices = [c[0] for c in choices_raw if c and len(c) > 0] if choices_raw else []

                    p_info = check_personal_info(q_title, choices, my_name, my_student_id, my_no, my_class)
                    if p_info:
                        personal_data_map[entry_id] = p_info
                        continue

                    img_url = extract_image_url(item)
                    parsed_questions.append({"entry_id": entry_id, "title": q_title, "choices": choices, "image_url": img_url})

                generated_page_history = ",".join([str(i) for i in range(page_count + 1)])

                if parsed_questions:
                    st.write("🧠 ให้ AI อ่านและคิดคำตอบ...")
                    contents_payload = []
                    prompt_data = []

                    for idx, q in enumerate(parsed_questions, 1):
                        q_info = f"ข้อ {idx} (ID: {q['entry_id']}): {q['title']}"
                        if q.get("image_url"): q_info += " [มีรูปภาพแนบ]"
                        if q['choices']: q_info += f"\nตัวเลือก: {json.dumps(q['choices'], ensure_ascii=False)}"
                        prompt_data.append(q_info)

                    full_prompt = f"""Context: {exam_context if exam_context else 'None'}
Questions:
{'\n'.join(prompt_data)}
Instructions: 
1. ตอบให้แม่นยำที่สุด
2. ข้อช้อยส์ ต้องเลือกตรงตามช้อยส์เป๊ะๆ
3. ตอบเป็น JSON: {{"entry.123": {{"answer": "...", "confidence": 90, "reasoning": "..."}}}}"""
                    contents_payload.append(full_prompt)

                    for q in parsed_questions:
                        if q.get("image_url"):
                            try:
                                img_res = requests.get(q["image_url"], timeout=5)
                                if img_res.status_code == 200:
                                    mime_type = img_res.headers.get("Content-Type", "image/jpeg")
                                    if "image" not in mime_type: mime_type = "image/jpeg"
                                    contents_payload.append(types.Part.from_bytes(data=img_res.content, mime_type=mime_type))
                            except: pass

                    models_to_try = ["gemini-3.6-flash", "gemini-2.5-flash"]
                    response = None
                    last_err = None

                    for model_name in models_to_try:
                        try:
                            response = client.models.generate_content(model=model_name, contents=contents_payload)
                            if response and response.text: break
                        except Exception as err:
                            last_err = err
                            time.sleep(2)

                    if not response: raise last_err

                    raw_ans = re.sub(r'\x60{3}(?:json)?', '', response.text.strip()).strip()
                    ai_answers = json.loads(raw_ans)
                else:
                    ai_answers = {}

                st.session_state.update({
                    "submit_url": submit_url, 
                    "parsed_questions": parsed_questions, 
                    "personal_data_map": personal_data_map, 
                    "ai_answers": ai_answers,
                    "pageHistory": generated_page_history,
                    "fbzx": fbzx
                })
                status.update(label="🎉 วิเคราะห์สำเร็จ!", state="complete", expanded=False)

            except Exception as e:
                status.update(label="❌ Error", state="error")
                st.error(f"รายละเอียด: {e}")

# ==========================================
# 📝 Review & Edit Section
# ==========================================
if "parsed_questions" in st.session_state:
    st.write("---")
    st.markdown("<h3 style='color: #1F2937;'>📋 ตรวจสอบก่อนส่ง</h3>", unsafe_allow_html=True)
    
    final_payload = {}

    if st.session_state["personal_data_map"]:
        with st.container(border=True):
            st.markdown("<b style='color:#4B5563;'>📌 ข้อมูลที่จะถูกส่ง</b>", unsafe_allow_html=True)
            cols = st.columns(len(st.session_state["personal_data_map"]))
            for idx, (entry_id, (title, val, cat)) in enumerate(st.session_state["personal_data_map"].items()):
                cols[idx].text_input(f"{title}", value=val, key=f"input_{entry_id}", disabled=True)
                final_payload[entry_id] = val

    for idx, q in enumerate(st.session_state["parsed_questions"], 1):
        entry_id = q["entry_id"]
        title = html_lib.escape(q["title"])
        choices = q["choices"]
        img_url = q.get("image_url")
        
        q_data = st.session_state["ai_answers"].get(entry_id, {})
        default_val = q_data.get("answer", "") if isinstance(q_data, dict) else q_data
        score = q_data.get("confidence", 70) if isinstance(q_data, dict) else 80
        reason = q_data.get("reasoning", "ประมวลผลอัตโนมัติ") if isinstance(q_data, dict) else ""

        color = "#10B981" if score >= 85 else "#F59E0B" if score >= 60 else "#EF4444"

        with st.container(border=True):
            st.markdown(f"<div style='font-size: 1.1rem; font-weight: 500; color: #1F2937;'>{idx}. {title}</div>", unsafe_allow_html=True)
            
            st.markdown(f"""
            <div class="confidence-track">
                <div class="confidence-fill" style="width: {score}%; background-color: {color};"></div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-size: 0.8rem; font-weight: 600; color: {color};">ความมั่นใจ: {score}%</span>
            </div>
            <div class="reasoning-text">💡 <b>AI คิดว่า:</b> {reason}</div>
            """, unsafe_allow_html=True)
            
            if img_url:
                st.image(img_url, use_column_width=True)

            if choices:
                default_idx = next((i for i, c in enumerate(choices) if c.strip() == str(default_val).strip() or c in str(default_val)), 0)
                final_payload[entry_id] = st.selectbox("คำตอบ", options=choices, index=default_idx, key=f"ans_{entry_id}", label_visibility="collapsed")
            else:
                final_payload[entry_id] = st.text_input("คำตอบ", value=str(default_val), key=f"ans_{entry_id}", label_visibility="collapsed")
    
    st.write("")
    
    final_payload["pageHistory"] = st.session_state.get("pageHistory", "0")
    if st.session_state.get("fbzx"):
        final_payload["fbzx"] = st.session_state["fbzx"]
    final_payload["fvv"] = "1"
    
    if st.button("✅ ยืนยันส่งข้อมูล", type="primary", use_container_width=True):
        with st.spinner("⏳ กำลังส่งข้อมูลและดึงผลคะแนน..."):
            res_submit = requests.post(st.session_state["submit_url"], data=final_payload)
            
            if res_submit.status_code == 200:
                st.balloons()
                st.success("🎉 ส่งคำตอบเข้า Google Form เรียบร้อยแล้ว!")
                
                html_response = res_submit.text
                link_match = re.search(r'href="([^"]*?viewscore\?[^"]*)"', html_response)
                
                if link_match:
                    raw_url = link_match.group(1)
                    score_url = html_lib.unescape(raw_url) 
                    
                    try:
                        score_page = requests.get(score_url, timeout=5).text
                        score_match = re.search(r'<span[^>]*>\s*([0-9]+)\s*</span>\s*<span[^>]*>\s*(?:/|&#47;|จาก)\s*([0-9]+)\s*</span>', score_page)
                        if not score_match: 
                            score_match = re.search(r'([0-9]+)\s*(?:/|&#47;|จาก)\s*([0-9]+)\s*(?:คะแนน|points)', score_page)
                        
                        if score_match:
                            my_score = score_match.group(1)
                            full_score = score_match.group(2)
                            st.markdown(f'<div class="score-box">🏆 คุณได้คะแนน: {my_score} / {full_score} คะแนน</div>', unsafe_allow_html=True)
                    except:
                        pass
                    
                    st.markdown(f'''
                    <a href="{score_url}" target="_blank" style="display: block; text-align: center; background-color: #4F46E5; color: white; padding: 12px; border-radius: 8px; text-decoration: none; font-weight: bold; margin-top: 10px; box-shadow: 0 4px 6px rgba(79, 70, 229, 0.2);">
                        🎯 คลิกลิงก์เพื่อเปิดหน้าคะแนน
                    </a>
                    ''', unsafe_allow_html=True)

                else:
                    st.warning("⚠️ ส่งคำตอบสำเร็จ! แต่ฟอร์มนี้ไม่ได้เปิดตั้งค่า 'ประกาศคะแนนทันที' จึงไม่สามารถดึงหน้าคะแนนได้ครับ")
            else:
                st.error(f"Error: เกิดข้อผิดพลาดรหัส {res_submit.status_code}")

