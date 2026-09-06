import json
import re
import requests
import streamlit as st

st.set_page_config(page_title="EZEXAM Debugger", layout="centered")

st.markdown("### 🛠️ เครื่องมือเอกซเรย์โครงสร้างข้อสอบ (X-Ray Mode)")
form_url = st.text_input("วางลิงก์ Google Form ที่นี่:")

if st.button("สแกนหาที่ซ่อนรูปภาพ", type="primary"):
    with st.spinner("กำลังเจาะข้อมูลดิบ..."):
        res = requests.get(form_url)
        match = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*</script>', res.text, re.DOTALL)
        
        if match:
            form_data = json.loads(match.group(1))
            questions_data = form_data[1][1] if len(form_data) > 1 and form_data[1] else []
            
            st.success("เจาะโครงสร้างสำเร็จ! เปิดดูข้อมูลด้านล่างได้เลย")
            for item in questions_data:
                if not item or len(item) < 4: continue
                q_title = item[1] if len(item) > 1 else "ไม่มีชื่อ"
                
                with st.expander(f"โจทย์: {q_title}", expanded=("จากรูป" in str(q_title))):
                    st.json(item)
        else:
            st.error("ไม่สามารถดึงข้อมูล FB_PUBLIC_LOAD_DATA_ ได้")
