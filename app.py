import json
import re
import requests
import time
from google import genai
from google.genai import types
import streamlit as st

st.set_page_config(page_title="Auto Google Form AI Pro", page_icon="🤖")

st.title("🤖 ระบบผู้ช่วยตอบข้อสอบ (Pro Edition + Vision AI)")
st.write("วิเคราะห์แม่นยำ อ่านรูปภาพประกอบข้อสอบได้ พร้อมคะแนนความมั่นใจและเหตุผล")

# --- ฟังก์ชันตรวจจับข้อมูลส่วนตัวแบบแม่นยำและยืดหยุ่นสูง ---
def check_personal_info(q_title, choices, my_name, my_student_id, my_no, my_class):
    # ตัดสัญลักษณ์ Markdown และเลขข้อออกเพื่อเช็กข้อความจริง
    clean_title = re.sub(r'^\*?\*?(?:ข้อ\s*\d+[\s.:-]*)?', '', q_title.strip()).strip()
    clean_title = re.sub(r'\*+\s*$', '', clean_title).strip()
    title_lower = clean_title.lower()

    # คำต้องห้ามที่เป็นโจทย์วิชาการ (ป้องกันการเข้าใจผิด)
    exam_stopwords = [
        "สาร", "เคมี", "ดาว", "วิทยาศาสตร์", "โรค", "องค์กร", 
        "กษัตริย์", "ธาตุ", "เมือง", "ประเทศ", "วรรณคดี", "ผู้แต่ง",
        "หัวใจ", "บรรยากาศ", "ผิวหนัง", "ปฏิบัติการ", "ดิน", "หิน"
    ]
    if any(sw in title_lower for sw in exam_stopwords):
        return None

    # 1. เช็ก ชื่อ-นามสกุล
    if my_name and any(k in title_lower for k in ["ชื่อ", "นามสกุล", "สกุล", "name"]):
        return (q_title, my_name, "ชื่อ-นามสกุล")

    # 2. เช็ก เลขประจำตัวนักเรียน
    if my_student_id and any(k in title_lower for k in ["เลขประจำตัว", "รหัส", "student id", "id"]):
        return (q_title, my_student_id, "เลขประจำตัว")

    # 3. เช็ก เลขที่
    if my_no and (any(k in title_lower for k in ["เลขที่", "no.", "number"]) or title_lower == "no"):
        return (q_title, my_no, "เลขที่")

    # 4. เช็ก ชั้น/ห้อง (จับคู่กับตัวเลือกถ้ามี)
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

# --- ฟังก์ชันค้นหารูปภาพในโจทย์แบบลึกทุกจุด ---
def extract_image_url(item):
    found_urls = []
    def find_urls(obj):
        if isinstance(obj, str):
            if (obj.startswith("http://") or obj.startswith("https://")):
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

# --- CSS สำหรับแถบไล่เฉดสี ---
st.markdown("""
<style>
.gradient-bar-container {
    width: 100%;
    height: 12px;
    background-color: #eee;
    border-radius: 10px;
    overflow: hidden;
    margin: 5px 0;
}
.gradient-bar {
    height: 100%;
    border-radius: 10px;
    transition: width 1s ease-in-out;
    background: linear-gradient(90deg, #ff4b4b 0%, #ffdb4b 50%, #00cc66 100%);
}
</style>
""", unsafe_allow_html=True)

# 1. ช่องกรอกข้อมูลหลัก
form_url = st.text_input("📌 ลิงก์ Google Form (forms.gle/...):")
gemini_key = st.text_input("🔑 Gemini API Key:", type="password")

st.write("---")
st.subheader("🧠 ข้อมูลขอบเขตเนื้อหา / บริบทเพิ่มเติม")
exam_context = st.text_area(
    "📚 บริบทของข้อสอบ:",
    placeholder="เช่น วิชาฟิสิกส์เรื่องแม่เหล็กไฟฟ้า ม.ปลาย, ข้อสอบเตรียมเข้าค่ายสัตวแพทย์..."
)

st.write("---")
st.subheader("👤 ข้อมูลผู้ส่งข้อสอบ (กรอกเฉพาะข้อที่ฟอร์มนั้นๆ มี)")
col1, col2, col3, col4 = st.columns(4)
with col1:
    my_name = st.text_input("ชื่อ-นามสกุล:")
with col2:
    my_student_id = st.text_input("เลขประจำตัวนักเรียน:")
with col3:
    my_no = st.text_input("เลขที่:")
with col4:
    my_class = st.text_input("ชั้น/ห้อง:")

# 2. เริ่มแกะฟอร์ม
if st.button("🔍 เริ่มวิเคราะห์ข้อสอบ", type="primary"):
    if not form_url or not gemini_key:
        st.error("⚠️ กรุณากรอกลิงก์ Google Form และ API Key ให้ครบถ้วน")
    else:
        with st.spinner("AI กำลังวิเคราะห์ข้อสอบและอ่านรูปภาพประกอบ..."):
            try:
                client = genai.Client(api_key=gemini_key)
                res = requests.get(form_url, allow_redirects=True)
                html = res.text

                action_match = re.search(r'<form action="([^"]+)"', html)
                submit_url = action_match.group(1) if action_match else (
                    res.url.replace("/viewform", "/formResponse") if "/viewform" in res.url else res.url.rstrip("/") + "/formResponse"
                )

                match = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>', html, re.DOTALL)
                if not match:
                    st.error("❌ ไม่พบโครงสร้างฟอร์ม กรุณาตรวจสอบว่าฟอร์มเปิดสาธารณะหรือไม่")
                else:
                    form_data = json.loads(match.group(1))
                    questions_data = form_data[1][1] if len(form_data) > 1 and form_data[1] else []

                    parsed_questions = []
                    personal_data_map = {}

                    for item in questions_data:
                        if not item or len(item) < 5 or not item[4]:
                            continue
                        
                        q_title = item[1]
                        entry_id = f"entry.{item[4][0][0]}"
                        choices_raw = item[4][0][1] if len(item[4][0]) > 1 else None
                        choices = [c[0] for c in choices_raw if c and len(c) > 0] if choices_raw else []

                        # ดักจับข้อมูลส่วนตัวด้วยฟังก์ชันใหม่
                        p_info = check_personal_info(q_title, choices, my_name, my_student_id, my_no, my_class)
                        if p_info:
                            personal_data_map[entry_id] = p_info
                            continue

                        img_url = extract_image_url(item)

                        parsed_questions.append({
                            "entry_id": entry_id,
                            "title": q_title,
                            "choices": choices,
                            "image_url": img_url
                        })

                    # มัดรวมส่ง AI (พร้อมรูปภาพประกอบ Vision AI)
                    if parsed_questions:
                        contents_payload = []
                        prompt_data = []

                        for idx, q in enumerate(parsed_questions, 1):
                            q_info = f"ข้อ {idx} (ID: {q['entry_id']}): {q['title']}"
                            if q.get("image_url"):
                                q_info += " [ข้อนี้มีรูปภาพประกอบแนบมาด้วย]"
                            if q['choices']:
                                q_info += f"\nตัวเลือก: {json.dumps(q['choices'], ensure_ascii=False)}"
                            prompt_data.append(q_info)

                        full_prompt = f"""คุณคือผู้เชี่ยวชาญที่กำลังทำข้อสอบ
ขอบเขตเนื้อหา / บริบทเพิ่มเติม: {exam_context if exam_context else 'ไม่มี'}

คำถามทั้งหมด:
{'\n\n'.join(prompt_data)}

คำสั่ง:
1. วิเคราะห์และหาคำตอบที่ถูกต้องที่สุดสำหรับทุกข้อ (หากข้อใดมีรูปภาพแนบ ให้ดูรูปภาพประกอบการวิเคราะห์ด้วย)
2. ข้อที่มีตัวเลือก ต้องเลือกคำตอบที่ตรงกับตัวเลือกในลิสต์เป๊ะๆ 100%
3. ประเมินระดับความมั่นใจ (confidence) เป็นตัวเลข 0-100% และเขียนเหตุผลสั้นๆ (reasoning)
4. ตอบกลับในรูปแบบ JSON dictionary เท่านั้น ตัวอย่าง:
{{
  "entry.123456": {{
    "answer": "ข้อความคำตอบที่เลือก",
    "confidence": 95,
    "reasoning": "เหตุผลสั้นๆ ที่เลือกข้อนี้"
  }}
}}"""
                        contents_payload.append(full_prompt)

                        # ดึงไฟล์ภาพส่งให้ Gemini Vision
                        for q in parsed_questions:
                            if q.get("image_url"):
                                try:
                                    img_res = requests.get(q["image_url"], timeout=5)
                                    if img_res.status_code == 200:
                                        mime_type = img_res.headers.get("Content-Type", "image/jpeg")
                                        if "image" not in mime_type:
                                            mime_type = "image/jpeg"
                                        img_part = types.Part.from_bytes(data=img_res.content, mime_type=mime_type)
                                        contents_payload.append(img_part)
                                except Exception:
                                    pass

                        # รายชื่อโมเดลเรียงตามลำดับหลัก-สำรอง
                        models_to_try = ["gemini-3.6-flash", "gemini-2.5-flash"]
                        response = None
                        last_err = None

                        for model_name in models_to_try:
                            try:
                                response = client.models.generate_content(
                                    model=model_name, 
                                    contents=contents_payload
                                )
                                if response and response.text:
                                    break
                            except Exception as err:
                                last_err = err
                                time.sleep(2)

                        if not response or not response.text:
                            raise last_err

                        raw_ans = response.text.strip()
                        raw_ans = re.sub(r'\x60{3}(?:json)?', '', raw_ans).strip()
                        ai_answers = json.loads(raw_ans)
                    else:
                        ai_answers = {}

                    st.session_state["submit_url"] = submit_url
                    st.session_state["parsed_questions"] = parsed_questions
                    st.session_state["personal_data_map"] = personal_data_map
                    st.session_state["ai_answers"] = ai_answers
                    st.success("🎉 ดึงและวิเคราะห์ข้อสอบสำเร็จ!")

            except Exception as e:
                st.error(f"เกิดข้อผิดพลาดในการประมวลผล: {e}")

# 3. แสดงผล UI แบบแก้ไขได้ พร้อมแถบสีความมั่นใจและรูปภาพประกอบ
if "parsed_questions" in st.session_state:
    st.write("---")
    st.write("### ✏️ จำลองคำตอบ (ตรวจสอบ/ปรับแก้ได้ก่อนส่งจริง)")
    
    final_payload = {}

    # โชว์ข้อมูลส่วนตัวที่ถูกล็อกไว้ถูกต้อง
    for entry_id, (title, val, cat) in st.session_state["personal_data_map"].items():
        st.text_input(f"📌 {title} [{cat}]", value=val, key=f"input_{entry_id}", disabled=True)
        final_payload[entry_id] = val

    if st.session_state["personal_data_map"]:
        st.write("---")
    
    parsed_q = st.session_state["parsed_questions"]
    ai_ans = st.session_state["ai_answers"]

    for idx, q in enumerate(parsed_q, 1):
        entry_id = q["entry_id"]
        title = q["title"]
        choices = q["choices"]
        img_url = q.get("image_url")
        
        # ดึงข้อมูลจาก AI
        q_data = ai_ans.get(entry_id, {})
        if isinstance(q_data, str):
            default_val = q_data
            score = 80
            reason = "ประมวลผลคำตอบอัตโนมัติ"
        else:
            default_val = q_data.get("answer", "")
            score = q_data.get("confidence", 70)
            reason = q_data.get("reasoning", "ไม่ระบุเหตุผล")

        st.markdown(f"**ข้อ {idx}: {title}**")
        
        # แสดงรูปภาพประกอบข้อสอบบนหน้าเว็บ (ถ้ามี)
        if img_url:
            st.image(img_url, caption=f"📷 รูปภาพประกอบข้อ {idx}", use_column_width=True)

        # แสดงแถบสีความมั่นใจแบบ Gradient
        st.markdown(f"""
        <div class="gradient-bar-container">
            <div class="gradient-bar" style="width: {score}%"></div>
        </div>
        <small style="color: #555;">🎯 ความมั่นใจ: <b>{score}%</b> | 💡 <i>เหตุผล: {reason}</i></small>
        """, unsafe_allow_html=True)
        
        st.write("")

        # ข้อเลือกตอบ (Dropdown)
        if choices:
            default_idx = 0
            for c_idx, choice_str in enumerate(choices):
                if choice_str.strip() == str(default_val).strip() or choice_str in str(default_val):
                    default_idx = c_idx
                    break
            
            selected_choice = st.selectbox(
                f"คำตอบข้อ {idx}:",
                options=choices,
                index=default_idx,
                key=f"user_choice_{entry_id}"
            )
            final_payload[entry_id] = selected_choice
        
        # ข้อเติมคำ (Text Box)
        else:
            user_text = st.text_input(
                f"คำตอบข้อ {idx}:",
                value=str(default_val),
                key=f"user_text_{entry_id}"
            )
            final_payload[entry_id] = user_text
        
        st.write("---")

    if st.button("🚀 ยืนยันส่งคำตอบเข้า Google Form", type="primary"):
        res_submit = requests.post(st.session_state["submit_url"], data=final_payload)
        if res_submit.status_code == 200:
            st.balloons()
            st.success("🎉 ส่งคำตอบเข้า Google Form เรียบร้อยแล้วครับ!")
        else:
            st.error(f"เกิดข้อผิดพลาดในการส่ง Status Code: {res_submit.status_code}")
