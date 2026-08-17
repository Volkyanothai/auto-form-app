import json
import re
import requests
from google import genai
import streamlit as st

st.set_page_config(page_title="Auto Google Form AI V2", page_icon="🤖")

st.title("🤖 ระบบช่วยตอบข้อสอบ Google Form (V2)")
st.write("วิเคราะห์ข้อสอบรวดเดียวประหยัดโควต้า + แก้ไขคำตอบได้ตามใจชอบก่อนกดส่ง")

# 1. ช่องกรอกข้อมูลหลัก
form_url = st.text_input("📌 ลิงก์ Google Form (forms.gle/...):")
gemini_key = st.text_input(
    "🔑 Gemini API Key:",
    type="password",
    help="กรอก API Key ของคุณจาก Google AI Studio"
)

st.write("---")
st.subheader("🧠 บริบทเพิ่มเติมสำหรับ AI")
exam_context = st.text_area(
    "📚 บริบทของข้อสอบ:",
    placeholder="เช่น วิชาฟิสิกส์เรื่องแม่เหล็กไฟฟ้า ม.ปลาย, ข้อสอบเตรียมเข้าค่ายสัตวแพทย์..."
)

st.write("---")
st.subheader("👤 ข้อมูลผู้ส่งข้อสอบ (กรอกเฉพาะข้อที่ฟอร์มนั้นๆ มี)")
col1, col2, col3 = st.columns(3)
with col1:
    my_name = st.text_input("ชื่อ-นามสกุล:")
with col2:
    my_no = st.text_input("เลขที่:")
with col3:
    my_class = st.text_input("ชั้น/ห้อง:")

# 2. เริ่มแกะฟอร์มและใช้ AI คิดรวบยอด
if st.button("🔍 เริ่มวิเคราะห์ข้อสอบทั้งหมด", type="primary"):
    if not form_url or not gemini_key:
        st.error("⚠️ กรุณากรอกลิงก์ Google Form และ API Key ให้ครบถ้วน")
    else:
        with st.spinner("กำลังแกะโครงสร้างฟอร์มและใช้ AI วิเคราะห์คำตอบ..."):
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

                        # ดักจับข้อมูลส่วนตัว
                        if ("ชื่อ" in q_title or "นามสกุล" in q_title) and my_name:
                            personal_data_map[entry_id] = (q_title, my_name, "ข้อมูลส่วนตัว")
                            continue
                        elif "เลขที่" in q_title and my_no:
                            personal_data_map[entry_id] = (q_title, my_no, "ข้อมูลส่วนตัว")
                            continue
                        elif ("ชั้น" in q_title or "ห้อง" in q_title) and my_class:
                            personal_data_map[entry_id] = (q_title, my_class, "ข้อมูลส่วนตัว")
                            continue

                        choices = [c[0] for c in choices_raw if c and len(c) > 0] if choices_raw else []
                        parsed_questions.append({
                            "entry_id": entry_id,
                            "title": q_title,
                            "choices": choices
                        })

                    # มัดรวมคำถามส่ง AI ครั้งเดียวแก้ปัญหา Rate Limit (Error 429)
                    if parsed_questions:
                        prompt_data = []
                        for idx, q in enumerate(parsed_questions, 1):
                            q_info = f"ข้อ {idx} (ID: {q['entry_id']}): {q['title']}"
                            if q['choices']:
                                q_info += f"\nตัวเลือก: {json.dumps(q['choices'], ensure_ascii=False)}"
                            prompt_data.append(q_info)

                        full_prompt = f"""คุณคือผู้เชี่ยวชาญที่กำลังทำข้อสอบ
บริบทเพิ่มเติม: {exam_context if exam_context else 'ไม่มี'}

คำถามทั้งหมด:
{'\n\n'.join(prompt_data)}

คำสั่ง:
1. วิเคราะห์และหาคำตอบที่ถูกต้องที่สุดสำหรับทุกข้อ
2. หากเป็นข้อที่มีตัวเลือก ต้องเลือกคำตอบที่ตรงกับตัวเลือกในลิสต์เป๊ะๆ 100%
3. ตอบกลับในรูปแบบ JSON dictionary เท่านั้น ใช้ key เป็น entry_id และ value เป็นคำตอบที่เลือก เช่น:
{{"entry.123456": "ข้อความคำตอบ", "entry.789012": "ข้อความเติมคำ"}}"""

                        response = client.models.generate_content(
                            model="gemini-3.6-flash", 
                            contents=full_prompt
                        )
                        
                        raw_ans = response.text.strip()
                        raw_ans = re.sub(r'```json\s*|\s*```', '', raw_ans).strip()
                        ai_answers = json.loads(raw_ans)
                    else:
                        ai_answers = {}

                    st.session_state["submit_url"] = submit_url
                    st.session_state["parsed_questions"] = parsed_questions
                    st.session_state["personal_data_map"] = personal_data_map
                    st.session_state["ai_answers"] = ai_answers
                    st.success("🎉 ดึงและวิเคราะห์ข้อสอบสำเร็จ! ตรวจสอบและแก้ไขคำตอบด้านล่างได้เลย")

            except Exception as e:
                st.error(f"เกิดข้อผิดพลาดในการประมวลผล: {e}")

# 3. หน้าจำลองตรวจทานและแก้ไขคำตอบ (Human-in-the-Loop)
if "parsed_questions" in st.session_state:
    st.write("---")
    st.write("### ✏️ จำลองคำตอบ (คุณสามารถกดแก้คำตอบได้ที่ช่องด้านล่าง)")
    
    final_payload = {}

    # ล็อกข้อมูลส่วนตัวไว้
    for entry_id, (title, val, cat) in st.session_state["personal_data_map"].items():
        st.text_input(f"📌 {title} [{cat}]", value=val, key=f"input_{entry_id}", disabled=True)
        final_payload[entry_id] = val

    st.write("---")
    
    parsed_q = st.session_state["parsed_questions"]
    ai_ans = st.session_state["ai_answers"]

    # สร้าง UI ให้ผู้ใช้ตรวจและกดเปลี่ยนคำตอบ
    for idx, q in enumerate(parsed_q, 1):
        entry_id = q["entry_id"]
        title = q["title"]
        choices = q["choices"]
        default_ai_val = ai_ans.get(entry_id, "")

        st.markdown(f"**ข้อ {idx}: {title}**")
        
        # ข้อเลือกตอบ (Dropdown)
        if choices:
            default_idx = 0
            for c_idx, choice_str in enumerate(choices):
                if choice_str.strip() == str(default_ai_val).strip() or choice_str in str(default_ai_val):
                    default_idx = c_idx
                    break
            
            selected_choice = st.selectbox(
                f"คำตอบข้อ {idx} (เลือกใหม่ได้หาก AI เลือกผิด):",
                options=choices,
                index=default_idx,
                key=f"user_choice_{entry_id}"
            )
            final_payload[entry_id] = selected_choice
        
        # ข้อเติมคำ (Text Box)
        else:
            user_text = st.text_input(
                f"คำตอบข้อ {idx} (พิมพ์แก้ได้ตามชอบ):",
                value=str(default_ai_val),
                key=f"user_text_{entry_id}"
            )
            final_payload[entry_id] = user_text
        
        st.write("")

    st.write("---")
    if st.button("🚀 ยืนยันส่งคำตอบเข้า Google Form", type="primary"):
        res_submit = requests.post(st.session_state["submit_url"], data=final_payload)
        if res_submit.status_code == 200:
            st.balloons()
            st.success("🎉 ส่งคำตอบเข้า Google Form เรียบร้อยแล้วครับ!")
        else:
            st.error(f"เกิดข้อผิดพลาดในการส่ง Status Code: {res_submit.status_code}")
