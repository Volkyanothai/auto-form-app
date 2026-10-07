# EZEXAM Auto Form App

เว็บแอป Python/Streamlit สำหรับอ่าน Google Forms วิเคราะห์และตรวจทานคำตอบด้วย Gemini

## Android APK

เพิ่มแอป Android ที่รวม Python engine เดิมในเครื่องและมีหน้าจอสำหรับมือถือ
ดู [วิธีติดตั้งและใช้งาน](android/README.md)
ดาวน์โหลด APK ที่ผ่านการทดสอบจาก [GitHub Releases](https://github.com/Volkyanothai/auto-form-app/releases)
ระบบสร้าง APK อยู่ใน [GitHub Actions](https://github.com/Volkyanothai/auto-form-app/actions/workflows/android-apk.yml)

## เว็บแอป

```sh
pip install -r requirements.txt
streamlit run app.py
```

ตั้งค่า GEMINI_API_KEY ใน Streamlit secrets ของ deployment
คีย์ในเว็บไม่ถูกนำไปใส่ใน APK ผู้ใช้ Android ตั้งค่าคีย์ในแอปและเก็บแบบเข้ารหัสได้
