# EZEXAM Auto Form App

เว็บแอป Python/Streamlit สำหรับอ่าน Google Forms วิเคราะห์และตรวจทานคำตอบด้วย Gemini

## Android

แอป Android 2 เปิดเว็บ EZEXAM จริงในแอป
จึงได้หน้าตาและฟังก์ชันเดียวกับเว็บ และใช้ Gemini API Key ที่ตั้งไว้ฝั่งเซิร์ฟเวอร์
เปิดแอป วางลิงก์ Google Forms แล้วกดเริ่มวิเคราะห์ได้เลย

ดู [วิธีติดตั้งและตั้งค่าที่อยู่เว็บ](android/README.md)
ดาวน์โหลด [APK จาก GitHub Releases](https://github.com/Volkyanothai/auto-form-app/releases)

## เว็บแอป

```sh
pip install -r requirements.txt
streamlit run app.py
```

ตั้งค่า GEMINI_API_KEY ใน Streamlit secrets ของ deployment
URL ที่มี `?client=android` จะเปิดเข้าหน้าวางลิงก์โดยตรง
