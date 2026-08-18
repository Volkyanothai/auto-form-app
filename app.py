import json
import re
import requests
import time
from google import genai
from google.genai import types
import streamlit as st

# ตั้งค่าหน้าเว็บให้กว้างขึ้นและตั้งชื่อให้ดูโปร
st.set_page_config(page_title="AutoForm AI | Pro", page_icon="⚡", layout="centered")

# --- CSS ตกแต่ง UI ขั้นสูง ---
st.markdown("""
<style>
    /* ปรับแต่งปุ่มและฟอนต์ให้ดูโมเดิร์น */
    .stButton>button {
        border-radius: 8px;
        font-weight: bold;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 10px rgba(0,0,0,0.15);
    }
    /* แถบ Gradient ความมั่นใจ */
    .gradient-bar-container {
        width: 100%;
        height: 10px;
        background-color: #f0f2f6;
        border-radius: 10px;
        overflow: hidden;
        margin: 8px 0;
    }
    .gradient-bar {
        height: 100%;
        border-radius: 10px;
        transition: width 1s ease-in-out;
        background: linear-gradient(90deg, #ff4b4b 0%, #ffdb4b 50%, #00cc66 100%);
    }
    /* ข้อความเหตุผล AI */
    .ai-reason {
        color: #555;
        font-size: 0.85rem;
        background-color: #f8f9fa;
        padding: 8px 12px;
        border-radius: 6px;
        border-left: 3px solid #00cc66;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# --- ฟังก์ชันตรวจจับข้อมูลส่วนตัว และรูปภาพ (คงเดิม) ---
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
# 🎨 ส่วนจัดเลย์เอาต์ UI (Layout)
# ==========================================

# 📌 เมนูด้านข้าง (Sidebar) สำหรับตั้งค่าระบบ
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/8633/8633180.png", width=60) # ใส่โลโก้เล็กๆ
    st.title("ตั้งค่าระบบ")
    st.caption("⚙️ System Configuration")
    st.divider()
    
    gemini_key = st.text_input("🔑 Gemini API Key:", type="password", help="ใส่ API Key จาก Google AI Studio")
    if not gemini_key:
        st.warning("⚠️ กรุณาใส่ API Key เพื่อใช้งานระบบ")
    
    st.divider()
    st.markdown("💡 **Tip:** การใส่บริบทข้อสอบให้ชัดเจน จะช่วยให้ AI ตอบได้แม่นยำขึ้นมาก")

# 📌 ส่วนหัวของหน้าเว็บ (Hero Section)
st.title("⚡ AutoForm AI")
st.markdown("<p style='font-size: 1.1rem; color: #666;'>ระบบผู้ช่วยทำแบบทดสอบอัจฉริยะ พร้อมระบบ Vision AI และการจำลองตรวจทานคำตอบ</p>", unsafe_allow_html=True)
st.write("")

# 📌 ส่วนตั้งค่าฟอร์มและข้อมูลส่วนตัว (Card Layout)
with st.container(border=True):
    st.subheader("📋 1. ตั้งค่าแบบฟอร์ม")
    form_url = st.text_input("🔗 ลิงก์ Google Form (forms.gle/...):", placeholder="วางลิงก์ฟอร์มที่นี่...")
    exam_context = st.text_area("📚 บริบทของข้อสอบ (Optional):", placeholder="เช่น วิชาฟิสิกส์ เรื่องแม่เหล็กไฟฟ้า ม.6...", height=68)

# 📌 ส่วนข้อมูลส่วนตัว (พับเก็บได้ เพื่อความสะอาดตา)
with st.expander("👤 2. ข้อมูลผู้ทำข้อสอบ (ตั้งค่าล่วงหน้า)", expanded=True):
    st.info("ระบบจะกรอกข้อมูลเหล่านี้ให้อัตโนมัติ หากพบช่องถามข้อมูลในฟอร์ม")
    col1, col2 = st.columns(2)
    with col1:
        my_name = st.text_input("ชื่อ-นามสกุล:")
        my_no = st.text_input("เลขที่:")
    with col2:
        my_student_id = st.text_input("เลขประจำตัวนักเรียน:")
        my_class = st.text_input("ชั้น/ห้อง:")

st.write("")

# ==========================================
# 🚀 ระบบวิเคราะห์ข้อสอบ
# ==========================================
if st.button("🚀 เริ่มดึงข้อมูลและวิเคราะห์ข้อสอบ", type="primary", use_container_width=True):
    if not form_url or not gemini_key:
        st.error("⚠️ กรุณากรอกลิงก์ Google Form และ API Key (ในเมนูด้านซ้าย) ให้ครบถ้วน")
    else:
        with st.status("🤖 กำลังทำงาน...", expanded=True) as status:
            try:
                st.write("📥 กำลังดึงโครงสร้าง Google Form...")
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
                    st.error("ไม่พบโครงสร้างฟอร์ม กรุณาตรวจสอบว่าฟอร์มเปิดเป็นสาธารณะหรือไม่")
                else:
                    form_data = json.loads(match.group(1))
                    questions_data = form_data[1][1] if len(form_data) > 1 and form_data[1] else []

                    parsed_questions = []
                    personal_data_map = {}

                    st.write("🔍 กำลังคัดกรองข้อมูลส่วนตัวและรูปภาพ...")
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
                        st.write("🧠 กำลังส่งข้อมูลให้ AI วิเคราะห์ (อาจใช้เวลาสักครู่)...")
                        contents_payload = []
                        prompt_data = []

                        for idx, q in enumerate(parsed_questions, 1):
                            q_info = f"ข้อ {idx} (ID: {q['entry_id']}): {q['title']}"
                            if q.get("image_url"): q_info += " [มีรูปภาพ]"
                            if q['choices']: q_info += f"\nตัวเลือก: {json.dumps(q['choices'], ensure_ascii=False)}"
                            prompt_data.append(q_info)

                        full_prompt = f"""คุณคือผู้เชี่ยวชาญทำข้อสอบ
บริบท: {exam_context if exam_context else 'ไม่มี'}
คำถาม:
{'\n'.join(prompt_data)}

คำสั่ง:
1. หาคำตอบที่ถูกต้องที่สุด (ดูรูปภาพประกอบด้วยถ้ามี)
2. ตอบกลับเป็น JSON: {{"entry.123": {{"answer": "...", "confidence": 90, "reasoning": "..."}}}}"""
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
                    status.update(label="🎉 วิเคราะห์สำเร็จเรียบร้อย!", state="complete", expanded=False)

            except Exception as e:
                status.update(label="❌ เกิดข้อผิดพลาด", state="error")
                st.error(f"รายละเอียด Error: {e}")


# ==========================================
# ✏️ ส่วนตรวจสอบและแก้ไข (Review & Submit)
# ==========================================
if "parsed_questions" in st.session_state:
    st.divider()
    st.subheader("🎯 ตรวจสอบและยืนยันคำตอบ")
    st.caption("ตรวจสอบเหตุผลของ AI แก้ไขคำตอบหากจำเป็น แล้วกดส่งด้านล่างสุด")
    
    final_payload = {}

    # ข้อมูลส่วนตัว (โชว์แบบสรุปใน Card เดียว)
    if st.session_state["personal_data_map"]:
        with st.container(border=True):
            st.markdown("##### 📌 ข้อมูลส่วนตัวที่จะถูกส่ง")
            cols = st.columns(len(st.session_state["personal_data_map"]))
            for idx, (entry_id, (title, val, cat)) in enumerate(st.session_state["personal_data_map"].items()):
                cols[idx].text_input(f"{title}", value=val, key=f"input_{entry_id}", disabled=True)
                final_payload[entry_id] = val

    # ข้อสอบ (แยกข้อละ 1 Card ให้ดูสะอาดตา)
    for idx, q in enumerate(st.session_state["parsed_questions"], 1):
        entry_id = q["entry_id"]
        title = q["title"]
        choices = q["choices"]
        img_url = q.get("image_url")
        
        q_data = st.session_state["ai_answers"].get(entry_id, {})
        default_val = q_data.get("answer", "") if isinstance(q_data, dict) else q_data
        score = q_data.get("confidence", 70) if isinstance(q_data, dict) else 80
        reason = q_data.get("reasoning", "ประมวลผลอัตโนมัติ") if isinstance(q_data, dict) else ""

        # สร้างกรอบ (Card) ล้อมรอบแต่ละข้อ
        with st.container(border=True):
            st.markdown(f"**ข้อ {idx}: {title}**")
            
            if img_url:
                st.image(img_url, width=400) # จำกัดขนาดรูปไม่ให้ใหญ่ทะลุจอ

            # แถบสีและเหตุผลดีไซน์ใหม่
            st.markdown(f"""
            <div class="gradient-bar-container"><div class="gradient-bar" style="width: {score}%"></div></div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                <span style="font-size: 0.85rem; font-weight: bold; color: {'#00cc66' if score >= 80 else '#ffdb4b' if score >= 50 else '#ff4b4b'};">
                    ความมั่นใจ: {score}%
                </span>
            </div>
            <div class="ai-reason">💡 <b>เหตุผล:</b> {reason}</div>
            """, unsafe_allow_html=True)

            # ช่องแก้คำตอบ
            if choices:
                default_idx = next((i for i, c in enumerate(choices) if c.strip() == str(default_val).strip() or c in str(default_val)), 0)
                final_payload[entry_id] = st.selectbox("เลือกคำตอบ:", options=choices, index=default_idx, key=f"ans_{entry_id}", label_visibility="collapsed")
            else:
                final_payload[entry_id] = st.text_input("คำตอบ:", value=str(default_val), key=f"ans_{entry_id}", label_visibility="collapsed")
    
    st.write("")
    
    # ปุ่มกดส่งขนาดใหญ่ ดีไซน์สะดุดตา
    col_space1, col_btn, col_space2 = st.columns([1, 2, 1])
    with col_btn:
        if st.button("✅ ยืนยันส่งข้อมูลเข้า Google Form", type="primary", use_container_width=True):
            res_submit = requests.post(st.session_state["submit_url"], data=final_payload)
            if res_submit.status_code == 200:
                st.balloons()
                st.success("🎉 ส่งคำตอบสำเร็จเรียบร้อยแล้ว!")
            else:
                st.error(f"เกิดข้อผิดพลาดรหัส: {res_submit.status_code}")

