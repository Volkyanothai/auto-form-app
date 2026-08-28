import json
import re
import requests
import time
import html as html_lib
from google import genai
from google.genai import types
import streamlit as st

st.set_page_config(page_title="EZEXAM | Auto Form System", page_icon="⚡", layout="centered")

# ==========================================
# 🔑 ระบบจัดการ API Key อัตโนมัติ
# ==========================================
try:
    gemini_key = st.secrets["GEMINI_API_KEY"]
except:
    st.error("⚠️ ระบบยังไม่ได้ตั้งค่า API Key จากหลังบ้าน กรุณาเพิ่ม GEMINI_API_KEY ใน Streamlit Secrets")
    st.stop()

# ==========================================
# 🎨 CSS Overhaul (Bug Fixes & Layout)
# ==========================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Orbitron:wght@700;900&family=Sarabun:wght@300;400;500&display=swap');

    .stApp {
        background-color: #0b1120 !important;
        background-image: 
            radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.4) 0px, transparent 50%),
            radial-gradient(at 100% 100%, rgba(16, 185, 129, 0.2) 0px, transparent 50%) !important;
        background-attachment: fixed !important;
    }

    p, h1, h2, h3, h4, h5, h6, label, span {
        font-family: 'Inter', 'Sarabun', sans-serif !important;
        color: #f8fafc;
    }

    /* กล่องกระจกสมจริง (Glass Cards) */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(15, 23, 42, 0.6) !important;
        backdrop-filter: blur(12px) !important;
        -webkit-backdrop-filter: blur(12px) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 16px !important;
        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.3) !important;
        padding: 1.5rem !important;
    }

    /* บังคับช่องกรอกข้อมูลให้เป็นสีเข้ม (แก้ปัญหาช่องสีขาว) */
    .stTextInput input, .stSelectbox div[data-baseweb="select"], .stTextArea textarea {
        background-color: #1e293b !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        border-radius: 8px !important;
        color: #ffffff !important;
        font-family: 'Inter', 'Sarabun', sans-serif !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus, .stSelectbox div[data-baseweb="select"]:focus-within {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 8px rgba(59, 130, 246, 0.5) !important;
    }
    
    .stTextInput label p, .stSelectbox label p, .stTextArea label p {
        color: #94a3b8 !important;
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.5px;
    }

    /* ปุ่มกด */
    div.stButton > button {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
        border: none !important;
        color: #ffffff !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        letter-spacing: 1px;
        box-shadow: 0 4px 15px rgba(37, 99, 235, 0.3) !important;
        transition: all 0.3s ease !important;
    }
    div.stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(37, 99, 235, 0.6) !important;
    }

    /* AI Score & Reasoning */
    .reasoning-text {
        color: #cbd5e1;
        font-size: 0.85rem;
        background: rgba(59, 130, 246, 0.15);
        padding: 10px 15px;
        border-radius: 8px;
        border-left: 3px solid #3b82f6;
        margin-bottom: 12px;
    }
    .confidence-track {
        width: 100%;
        height: 5px;
        background-color: rgba(255, 255, 255, 0.1);
        border-radius: 4px;
        margin: 10px 0;
    }
    .confidence-fill {
        height: 100%;
        border-radius: 4px;
    }
    .score-box {
        background: rgba(16, 185, 129, 0.1);
        border: 1px solid rgba(16, 185, 129, 0.3);
        color: #34d399;
        padding: 15px;
        border-radius: 12px;
        text-align: center;
        font-size: 1.2rem;
        font-weight: 600;
        margin-top: 15px;
        margin-bottom: 15px;
    }
    
    .glass-header {
        font-size: 1.1rem;
        font-weight: 600;
        color: #f8fafc;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
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
st.markdown("""
<div style="text-align: center; width: 100%; margin-bottom: 40px;">
    <h1 style='color: #ffffff; font-family: "Orbitron", sans-serif; letter-spacing: 3px; font-size: 3rem; margin: 0; text-shadow: 0 0 20px rgba(59,130,246,0.8);'>EZEXAM</h1>
    <p style='color: #60a5fa; font-family: "Orbitron", sans-serif; letter-spacing: 2px; font-weight: 700; font-size: 0.9rem; margin: 5px 0 0 0;'>AUTO FORM SYSTEM</p>
</div>
""", unsafe_allow_html=True)

with st.container(border=True):
    st.markdown('<div class="glass-header"><span style="color:#3b82f6;">🔗</span> TARGET FORM LINK</div>', unsafe_allow_html=True)
    form_url = st.text_input("Form URL", placeholder="Paste Google Form link here...", label_visibility="collapsed")

st.write("")

# เปลี่ยน Expander เป็น Container แบบธรรมดา
with st.container(border=True):
    st.markdown('<div class="glass-header"><span style="color:#3b82f6;">👤</span> PERSONAL DATA & CONTEXT</div>', unsafe_allow_html=True)
    exam_context = st.text_area("EXAM CONTEXT", placeholder="e.g. High school physics...", height=68)
    st.write("")
    col1, col2 = st.columns(2)
    with col1:
        my_name = st.text_input("FULL NAME", placeholder="Your name...")
        my_no = st.text_input("CLASS NUMBER", placeholder="Your number...")
    with col2:
        my_student_id = st.text_input("STUDENT ID", placeholder="Your ID...")
        my_class = st.text_input("CLASSROOM", placeholder="e.g. 6/3...")

st.write("")

# ==========================================
# 🚀 Action: ปุ่มประมวลผล
# ==========================================
if st.button("🚀 INITIATE ANALYSIS", type="primary", use_container_width=True):
    if not form_url:
        st.error("⚠️ Please insert Google Form link.")
    else:
        with st.status("🤖 SYSTEM PROCESSING...", expanded=True) as status:
            try:
                st.write("📥 Extracting form structure...")
                client = genai.Client(api_key=gemini_key)
                res = requests.get(form_url, allow_redirects=True)
                html = res.text

                action_match = re.search(r'<form action="([^"]+)"', html)
                submit_url = action_match.group(1) if action_match else (
                    res.url.replace("/viewform", "/formResponse") if "/viewform" in res.url else res.url.rstrip("/") + "/formResponse"
                )

                match = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>', html, re.DOTALL)
                if not match:
                    status.update(label="❌ Form not found", state="error")
                    st.stop()

                form_data = json.loads(match.group(1))
                questions_data = form_data[1][1] if len(form_data) > 1 and form_data[1] else []

                parsed_questions = []
                personal_data_map = {}
                page_count = 0
                fbzx = ""
                fbzx_match = re.search(r'name="fbzx" value="([^"]*)"', html)
                if fbzx_match: fbzx = fbzx_match.group(1)

                st.write("🔍 Identifying pages and images...")
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
                    st.write("🧠 AI is computing answers...")
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
                status.update(label="🎉 ANALYSIS COMPLETE!", state="complete", expanded=False)

            except Exception as e:
                status.update(label="❌ ERROR", state="error")
                st.error(f"Details: {e}")

# ==========================================
# 📝 Review & Edit Section
# ==========================================
if "parsed_questions" in st.session_state:
    st.write("---")
    st.markdown("<h2 style='color: #f8fafc; font-weight: 600; font-size: 1.5rem;'>📋 REVIEW & SUBMIT</h2>", unsafe_allow_html=True)
    
    final_payload = {}

    if st.session_state["personal_data_map"]:
        with st.container(border=True):
            st.markdown('<div class="glass-header"><span style="color:#10b981;">✓</span> AUTO-FILLED DATA</div>', unsafe_allow_html=True)
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

        color = "#10b981" if score >= 85 else "#f59e0b" if score >= 60 else "#ef4444"

        with st.container(border=True):
            st.markdown(f"<div style='font-size: 1.1rem; font-weight: 500; color: #f8fafc; margin-bottom: 10px;'>{idx}. {title}</div>", unsafe_allow_html=True)
            
            st.markdown(f"""
            <div class="confidence-track">
                <div class="confidence-fill" style="width: {score}%; background-color: {color}; box-shadow: 0 0 8px {color};"></div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <span style="font-size: 0.75rem; font-weight: 600; color: {color}; letter-spacing: 0.5px;">CONFIDENCE: {score}%</span>
            </div>
            <div class="reasoning-text">✨ <b>AI REASON:</b> {reason}</div>
            """, unsafe_allow_html=True)
            
            if img_url:
                st.image(img_url, use_column_width=True)

            if choices:
                default_idx = next((i for i, c in enumerate(choices) if c.strip() == str(default_val).strip() or c in str(default_val)), 0)
                final_payload[entry_id] = st.selectbox("ANSWER", options=choices, index=default_idx, key=f"ans_{entry_id}", label_visibility="collapsed")
            else:
                final_payload[entry_id] = st.text_input("ANSWER", value=str(default_val), key=f"ans_{entry_id}", label_visibility="collapsed")
    
    st.write("")
    
    final_payload["pageHistory"] = st.session_state.get("pageHistory", "0")
    if st.session_state.get("fbzx"):
        final_payload["fbzx"] = st.session_state["fbzx"]
    final_payload["fvv"] = "1"
    
    if st.button("✅ TRANSMIT DATA", type="primary", use_container_width=True):
        with st.spinner("⏳ Transmitting data securely..."):
            res_submit = requests.post(st.session_state["submit_url"], data=final_payload)
            
            if res_submit.status_code == 200:
                st.balloons()
                st.success("🎉 Transmission Complete!")
                
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
                            st.markdown(f'<div class="score-box">🏆 SCORE SECURED: {my_score} / {full_score}</div>', unsafe_allow_html=True)
                    except:
                        pass
                    
                    st.markdown(f'''
                    <a href="{score_url}" target="_blank" style="display: block; text-align: center; background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.4); color: #60a5fa; padding: 12px; border-radius: 8px; text-decoration: none; font-weight: 600; letter-spacing: 0.5px; margin-top: 10px; transition: all 0.3s ease;">
                        📄 OPEN SCORE CONFIRMATION
                    </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.warning("⚠️ Data sent! This form does not release scores automatically.")
            else:
                st.error(f"Error Code: {res_submit.status_code}")
