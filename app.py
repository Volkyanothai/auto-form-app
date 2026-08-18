import json
import re
import requests
import time
import html as html_lib
from google import genai
from google.genai import types
import streamlit as st

# ตั้งค่าหน้าเว็บแบบ Clean & Minimal
st.set_page_config(page_title="AutoForm AI", page_icon="⚪", layout="centered")

# ==========================================
# 🎨 CSS Overhaul (ล้างคราบ Streamlit ให้ดูแพง)
# ==========================================
st.markdown("""
<style>
    /* นำเข้าฟอนต์ Google Fonts เพื่อความโมเดิร์น */
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600&display=swap');
    html, body, [class*="css"] {
        font-family: 'Sarabun', sans-serif !important;
    }

    /* เปลี่ยน Container ให้เป็น Soft Card (มีเงาบางๆ มุมโค้ง) */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border: 1px solid #f1f3f5 !important;
        border-radius: 12px !important;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.03) !important;
        background-color: #ffffff !important;
        padding: 0.5rem !important;
        transition: all 0.2s ease-in-out;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:hover {
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06) !important;
        border-color: #e9ecef !important;
    }

    /* Minimalist Slim Progress Bar */
    .confidence-track {
        width: 100%;
        height: 4px;
        background-color: #f1f3f5;
        border-radius: 4px;
        margin: 12px 0;
        overflow: hidden;
    }
    .confidence-fill {
        height: 100%;
        border-radius: 4px;
        transition: width 0.8s ease-out;
    }
    
    /* สไตล์สำหรับกล่องเหตุผลของ AI */
    .reasoning-text {
        color: #868e96;
        font-size: 0.85rem;
        line-height: 1.5;
        margin-bottom: 12px;
        padding-left: 12px;
        border-left: 2px solid #dee2e6;
    }

    /* ซ่อนแถบเมนูที่ไม่จำเป็นของ Streamlit */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ==========================================
# ⚙️ Core Functions (ระบบอัจฉริยะ คงเดิม 100%)
# ==========================================
def check_personal_info(q_title, choices, my_name, my_student_id, my_no, my_class):
    clean_title = re.sub(r'^\*?\*?(?:ข้อ\s*\d+[\s.:-]*)?', '', q_title.strip()).strip()
    clean_title = re.sub(r'\*+\s*$', '', clean_title).strip()
    title_lower = clean_title.lower()

    exam_stopwords = ["สาร", "เคมี", "ดาว", "วิทยาศาสตร์", "โรค", "องค์กร", "กษัตริย์", "ธาตุ", "เมือง", "ประเทศ", "วรรณคดี", "ผู้แต่ง", "หัวใจ", "บรรยากาศ", "ผิวหนัง", "ปฏิบัติการ", "ดิน", "หิน"]
    if any(sw in title_lower for sw in exam_stopwords) or len(clean_title) > 40:
        return None

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
            if "/viewform" not in obj and "/formResponse" not in obj and "forms.gle" not in obj:
                found_urls.append(obj)
        elif isinstance(obj, list):
            for sub in obj: find_urls(sub)
        elif isinstance(obj, dict):
            for v in obj.values(): find_urls(v)
    find_urls(item)
    return found_urls[0] if found_urls else None

# ==========================================
# 📐 Layout: Sidebar & Configuration
# ==========================================
with st.sidebar:
    st.markdown("<h2 style='color: #111;'>Configuration</h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #666; font-size: 0.9rem;'>ตั้งค่าระบบและบริบทข้อสอบ</p>", unsafe_allow_html=True)
    st.write("---")
    
    gemini_key = st.text_input("Gemini API Key", type="password")
    exam_context = st.text_area("Context (ขอบเขตเนื้อหา)", placeholder="เช่น วิทยาศาสตร์ ม.ปลาย...", height=100)
    
    if not gemini_key:
        st.caption("ระบบต้องการ API Key ในการประมวลผล")

# ==========================================
# 📐 Layout: Main Hero & Setup
# ==========================================
st.markdown("<h1 style='text-align: center; color: #111; font-weight: 600; margin-bottom: 0;'>AutoForm AI</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #868e96; margin-top: 0; font-size: 1.1rem;'>Intelligent Google Form Assistant</p>", unsafe_allow_html=True)
st.write("")

with st.container(border=True):
    st.markdown("<div style='font-weight: 600; font-size: 1.1rem; color: #343a40; margin-bottom: 10px;'>Form Details</div>", unsafe_allow_html=True)
    form_url = st.text_input("Google Form URL", placeholder="https://forms.gle/...", label_visibility="collapsed")
    
    st.write("")
    st.markdown("<div style='font-weight: 600; font-size: 1.1rem; color: #343a40; margin-bottom: 10px;'>Personal Information</div>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        my_name = st.text_input("ชื่อ-นามสกุล", placeholder="Name")
        my_no = st.text_input("เลขที่", placeholder="No.")
    with col2:
        my_student_id = st.text_input("เลขประจำตัว", placeholder="Student ID")
        my_class = st.text_input("ชั้น/ห้อง", placeholder="Class/Room")

st.write("")

# ==========================================
# 🚀 Action: Analyze Form
# ==========================================
if st.button("Analyze Form", type="primary", use_container_width=True):
    if not form_url or not gemini_key:
        st.error("Please provide both Google Form URL and API Key.")
    else:
        with st.status("Processing form data...", expanded=True) as status:
            try:
                st.write("Extracting structure...")
                client = genai.Client(api_key=gemini_key)
                res = requests.get(form_url, allow_redirects=True)
                html = res.text

                action_match = re.search(r'<form action="([^"]+)"', html)
                submit_url = action_match.group(1) if action_match else (
                    res.url.replace("/viewform", "/formResponse") if "/viewform" in res.url else res.url.rstrip("/") + "/formResponse"
                )

                match = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>', html, re.DOTALL)
                if not match:
                    status.update(label="Failed to parse form", state="error")
                    st.stop()

                form_data = json.loads(match.group(1))
                questions_data = form_data[1][1] if len(form_data) > 1 and form_data[1] else []

                parsed_questions = []
                personal_data_map = {}

                st.write("Identifying questions and images...")
                for item in questions_data:
                    if not item or len(item) < 5 or not item[4]: continue
                    
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

                if parsed_questions:
                    st.write("Generating answers via AI...")
                    contents_payload = []
                    prompt_data = []

                    for idx, q in enumerate(parsed_questions, 1):
                        q_info = f"Question {idx} (ID: {q['entry_id']}): {q['title']}"
                        if q.get("image_url"): q_info += " [Contains Image]"
                        if q['choices']: q_info += f"\nChoices: {json.dumps(q['choices'], ensure_ascii=False)}"
                        prompt_data.append(q_info)

                    full_prompt = f"""Expert Mode:
Context: {exam_context if exam_context else 'None'}
Questions:
{'\n'.join(prompt_data)}

Instructions:
1. Provide the most accurate answer (analyze images if present).
2. For multiple choice, output the exact string from the choices.
3. Reply ONLY in JSON format: {{"entry.123": {{"answer": "...", "confidence": 95, "reasoning": "..."}}}}"""
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
                    "submit_url": submit_url, "parsed_questions": parsed_questions,
                    "personal_data_map": personal_data_map, "ai_answers": ai_answers
                })
                status.update(label="Analysis Complete", state="complete", expanded=False)

            except Exception as e:
                status.update(label="Error Occurred", state="error")
                st.error(f"Details: {e}")

# ==========================================
# 📝 Review & Edit Section (Minimalist Cards)
# ==========================================
if "parsed_questions" in st.session_state:
    st.write("---")
    st.markdown("<h2 style='color: #111; font-weight: 500; font-size: 1.5rem;'>Review & Submit</h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #868e96; font-size: 0.95rem; margin-bottom: 20px;'>ตรวจสอบคำตอบและแก้ไขได้ก่อนส่งเข้าระบบ</p>", unsafe_allow_html=True)
    
    final_payload = {}

    # โชว์ข้อมูลส่วนตัวแบบเนียนๆ
    if st.session_state["personal_data_map"]:
        with st.container(border=True):
            st.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: #adb5bd; text-transform: uppercase; margin-bottom: 10px;'>Auto-filled Data</div>", unsafe_allow_html=True)
            cols = st.columns(len(st.session_state["personal_data_map"]))
            for idx, (entry_id, (title, val, cat)) in enumerate(st.session_state["personal_data_map"].items()):
                cols[idx].text_input(f"{title}", value=val, key=f"input_{entry_id}", disabled=True)
                final_payload[entry_id] = val

    # ข้อสอบแสดงทีละ Card
    for idx, q in enumerate(st.session_state["parsed_questions"], 1):
        entry_id = q["entry_id"]
        title = html_lib.escape(q["title"]) # ป้องกัน Error จาก HTML tags
        choices = q["choices"]
        img_url = q.get("image_url")
        
        q_data = st.session_state["ai_answers"].get(entry_id, {})
        default_val = q_data.get("answer", "") if isinstance(q_data, dict) else q_data
        score = q_data.get("confidence", 70) if isinstance(q_data, dict) else 80
        reason = q_data.get("reasoning", "ประมวลผลอัตโนมัติ") if isinstance(q_data, dict) else ""

        # การกำหนดสีพาสเทลตามระดับความมั่นใจ
        if score >= 85:
            color = "#40c057" # Soft Green
        elif score >= 60:
            color = "#fab005" # Soft Yellow
        else:
            color = "#fa5252" # Soft Red

        with st.container(border=True):
            # โครงสร้างหัวข้อและแถบสีสไตล์ Minimal
            st.markdown(f"""
            <div style="font-size: 1.05rem; font-weight: 500; color: #212529; margin-bottom: 5px;">{idx}. {title}</div>
            <div class="confidence-track">
                <div class="confidence-fill" style="width: {score}%; background-color: {color};"></div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                <div class="reasoning-text">{reason}</div>
                <div style="font-size: 0.75rem; color: {color}; font-weight: 600; white-space: nowrap; margin-left: 15px; margin-top: 2px;">{score}% MATCH</div>
            </div>
            """, unsafe_allow_html=True)
            
            if img_url:
                st.image(img_url, use_column_width=True)

            if choices:
                default_idx = next((i for i, c in enumerate(choices) if c.strip() == str(default_val).strip() or c in str(default_val)), 0)
                final_payload[entry_id] = st.selectbox("Answer", options=choices, index=default_idx, key=f"ans_{entry_id}", label_visibility="collapsed")
            else:
                final_payload[entry_id] = st.text_input("Answer", value=str(default_val), key=f"ans_{entry_id}", label_visibility="collapsed")
    
    st.write("")
    
    if st.button("Submit to Google Form", type="primary", use_container_width=True):
        res_submit = requests.post(st.session_state["submit_url"], data=final_payload)
        if res_submit.status_code == 200:
            st.success("Form submitted successfully.")
        else:
            st.error(f"Error Code: {res_submit.status_code}")

