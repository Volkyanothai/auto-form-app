import json
import re
import requests
from google import genai
import streamlit as st

st.set_page_config(page_title="Auto Google Form AI", page_icon="🤖")

st.title("🤖 ระบบช่วยตอบข้อสอบ Google Form")
st.write("วางลิงก์ฟอร์ม กรอกข้อมูลผู้ส่ง แล้วให้ Gemini AI ช่วยวิเคราะห์คำตอบ")

# ช่องกรอกข้อมูลหลัก
form_url = st.text_input("📌 ลิงก์ Google Form (forms.gle/...):")
gemini_key = st.text_input(
    "🔑 Gemini API Key:",
    type="password",
    help="กรอก API Key ของคุณที่ได้จาก Google AI Studio"
)

st.subheader("👤 ข้อมูลผู้ส่งข้อสอบ (กรอกเฉพาะข้อที่ฟอร์มนั้นๆ มี)")
col1, col2, col3 = st.columns(3)
with col1:
    my_name = st.text_input("ชื่อ-นามสกุล:")
with col2:
    my_no = st.text_input("เลขที่:")
with col3:
    my_class = st.text_input("ชั้น/ห้อง:")

if st.button("🔍 เริ่มวิเคราะห์ข้อสอบ", type="primary"):
    if not form_url or not gemini_key:
        st.error("⚠️ กรุณากรอกลิงก์ Google Form และ API Key ให้ครบถ้วน")
    else:
        with st.spinner("กำลังแกะข้อมูลและใช้ AI วิเคราะห์คำตอบ..."):
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

                    payload = {}
                    review_list = []

                    for item in questions_data:
                        if not item or len(item) < 5 or not item[4]:
                            continue
                        
                        q_title = item[1]
                        entry_id = f"entry.{item[4][0][0]}"
                        choices_raw = item[4][0][1] if len(item[4][0]) > 1 else None

                        if ("ชื่อ" in q_title or "นามสกุล" in q_title) and my_name:
                            payload[entry_id] = my_name
                            review_list.append((q_title, my_name, "ข้อมูลส่วนตัว"))
                            continue
                        elif "เลขที่" in q_title and my_no:
                            payload[entry_id] = my_no
                            review_list.append((q_title, my_no, "ข้อมูลส่วนตัว"))
                            continue
                        elif ("ชั้น" in q_title or "ห้อง" in q_title) and my_class:
                            payload[entry_id] = my_class
                            review_list.append((q_title, my_class, "ข้อมูลส่วนตัว"))
                            continue

                        if choices_raw:
                            choices = [c[0] for c in choices_raw if c and len(c) > 0]
                            prompt = f"คำถาม: {q_title}\nตัวเลือก: {json.dumps(choices, ensure_ascii=False)}\nคำสั่ง: เลือกตัวเลือกที่ถูกต้องที่สุดเพียง 1 ข้อ ตอบเฉพาะข้อความที่ตรงกับตัวเลือกเป๊ะๆ"
                            response = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
                            ai_ans = response.text.strip()
                            matched = next((ch for ch in choices if ch.strip() == ai_ans or ch in ai_ans or ai_ans in ch), choices[0])
                            payload[entry_id] = matched
                            review_list.append((q_title, matched, "ตัวเลือก"))
                        else:
                            prompt = f"คำถาม: {q_title}\nคำสั่ง: ตอบคำถามนี้อย่างถูกต้องและกระชับที่สุด"
                            response = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
                            ai_ans = response.text.strip()
                            payload[entry_id] = ai_ans
                            review_list.append((q_title, ai_ans, "เติมคำ"))

                    st.session_state["submit_url"] = submit_url
                    st.session_state["payload"] = payload
                    st.session_state["review_list"] = review_list
                    st.success("🎉 วิเคราะห์คำตอบเรียบร้อยแล้ว!")

            except Exception as e:
                st.error(f"เกิดข้อผิดพลาด: {e}")

if "review_list" in st.session_state:
    st.write("---")
    st.write("### 📋 ตรวจทานคำตอบทั้งหมดก่อนส่ง")
    for idx, (q, a, cat) in enumerate(st.session_state["review_list"], 1):
        st.info(f"**ข้อ {idx} [{cat}]:** {q}\n\n👉 **คำตอบ:** {a}")
    
    if st.button("🚀 ยืนยันส่งคำตอบเข้า Google Form", type="primary"):
        res_submit = requests.post(st.session_state["submit_url"], data=st.session_state["payload"])
        if res_submit.status_code == 200:
            st.balloons()
            st.success("🎉 ส่งคำตอบเข้า Google Form เรียบร้อยแล้วครับ!")
        else:
            st.error(f"เกิดข้อผิดพลาดในการส่ง Status Code: {res_submit.status_code}")
