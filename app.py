import json
import re
import requests
from google import genai
import streamlit as st

st.set_page_config(page_title="Auto Google Form AI Pro", page_icon="🤖")

st.title("🤖 ระบบผู้ช่วยตอบข้อสอบ (Pro Edition)")
st.write("ระบบวิเคราะห์แม่นยำ พร้อมโชว์คะแนนความมั่นใจและเหตุผลของ AI")

# --- CSS สำหรับแถบไล่เฉดสีสวยๆ ---
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

# ช่องกรอกข้อมูลพื้นฐาน
form_url = st.text_input("📌 ลิงก์ Google Form:")
gemini_key = st.text_input("🔑 Gemini API Key:", type="password")

# --- โค้ดหลัก ---
if st.button("🔍 เริ่มวิเคราะห์ข้อสอบ", type="primary"):
    if not form_url or not gemini_key:
        st.error("⚠️ กรุณากรอกข้อมูลให้ครบ")
    else:
        with st.spinner("AI กำลังวิเคราะห์ข้อสอบ..."):
            try:
                client = genai.Client(api_key=gemini_key)
                res = requests.get(form_url, allow_redirects=True)
                html = res.text
                
                # ดึงข้อมูลคำถาม
                match = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>', html, re.DOTALL)
                form_data = json.loads(match.group(1))
                questions_data = form_data[1][1] if len(form_data) > 1 and form_data[1] else []
                
                # มัดรวมส่ง AI
                parsed_questions = []
                for item in questions_data:
                    if not item or len(item) < 5 or not item[4]: continue
                    parsed_questions.append({
                        "entry_id": f"entry.{item[4][0][0]}",
                        "title": item[1],
                        "choices": [c[0] for c in item[4][0][1]] if len(item[4][0]) > 1 else []
                    })

                # ส่งคำสั่งให้ตอบแบบ JSON (พร้อม confidence และ reasoning)
                prompt = f"""วิเคราะห์ข้อสอบเหล่านี้: {json.dumps(parsed_questions, ensure_ascii=False)}
ตอบเป็น JSON เท่านั้น format: 
{{"entry.123": {{"answer": "...", "confidence": 95, "reasoning": "..."}}}}"""
                
                response = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
                ai_data = json.loads(re.sub(r'```json|```', '', response.text))
                
                st.session_state["ai_results"] = ai_data
                st.session_state["parsed_questions"] = parsed_questions
                st.session_state["submit_url"] = res.url.replace("/viewform", "/formResponse")
                st.success("🎉 วิเคราะห์เสร็จสิ้น!")
            except Exception as e:
                st.error(f"Error: {e}")

# --- แสดงผล UI แบบแก้ไขได้ ---
if "ai_results" in st.session_state:
    st.write("---")
    final_payload = {}
    for q in st.session_state["parsed_questions"]:
        eid = q['entry_id']
        data = st.session_state["ai_results"].get(eid, {"answer": "", "confidence": 0, "reasoning": "ไม่ระบุ"})
        
        st.markdown(f"**{q['title']}**")
        
        # แสดงแถบสีความมั่นใจ
        score = data['confidence']
        st.markdown(f"""
        <div class="gradient-bar-container">
            <div class="gradient-bar" style="width: {score}%"></div>
        </div>
        <small>ความมั่นใจ: {score}% | 💡 {data['reasoning']}</small>
        """, unsafe_allow_html=True)
        
        # ส่วนแก้ไขคำตอบ
        if q['choices']:
            final_payload[eid] = st.selectbox("เลือกคำตอบ:", options=q['choices'], index=q['choices'].index(data['answer']) if data['answer'] in q['choices'] else 0, key=f"sel_{eid}")
        else:
            final_payload[eid] = st.text_input("คำตอบ:", value=data['answer'], key=f"txt_{eid}")
        st.write("---")

    if st.button("🚀 ส่งคำตอบเข้า Google Form"):
        requests.post(st.session_state["submit_url"], data=final_payload)
        st.balloons()
        st.success("ส่งเรียบร้อยแล้ว!")
