# EZEXAM Android

แอป Android ที่รวม Python engine จากโปรเจกต์เดิมไว้ใน APK
หน้าจอมือถือทำงานในเครื่อง ไม่ต้องมี Streamlit server
รองรับ Android 7.0 ขึ้นไป (arm64-v8a, armeabi-v7a, x86_64)

## ติดตั้ง

ดาวน์โหลด EZEXAM.apk จาก GitHub Releases แล้วเปิดไฟล์บน Android
อนุญาตติดตั้งแอปจากแหล่งนี้เมื่อ Android ขอสิทธิ์
รุ่นนี้เป็น APK สำหรับติดตั้งโดยตรง ลงนามด้วย debug certificate
การติดตั้ง build ใหม่ที่ลายเซ็นต่างกันต้องถอนรุ่นเก่าก่อน
ไม่ใช่รุ่นสำหรับเผยแพร่ใน Google Play

## ใช้งาน

1. เปิดแอปและใส่ลิงก์ Google Forms พร้อมข้อมูลผู้ตอบ
2. เปิดฟอร์มเพื่อตรวจคำถาม
3. ตั้งค่า Gemini API Key ในเมนูตั้งค่า บันทึกคีย์แบบเข้ารหัสได้
4. กดวิเคราะห์และตรวจทาน แล้วแก้คำตอบได้ทุกข้อ
5. ตรวจข้อมูลและคำตอบ ติ๊กว่าตรวจแล้ว และยืนยันส่ง

API Key ไม่อยู่ใน APK และไม่อ่านจาก Streamlit secrets
คีย์ที่บันทึกใช้ AES-GCM กับ Android Keystore และปิด Android backup
ข้อมูลผู้ตอบและคำตอบอยู่ในหน่วยความจำระหว่างใช้งาน
การออกจาก process อาจทำให้คำตอบหาย
การเรียก Gemini และ Google Forms ต้องใช้อินเทอร์เน็ต
การใช้ Gemini อาจมีโควตาหรือค่าใช้จ่ายตามบัญชีของคุณ

รองรับคำตอบสั้น ย่อหน้า ตัวเลือกเดียว dropdown และ checkbox รวมรูปประกอบ
ฟอร์มที่ต้องลงชื่อเข้าใช้ ตาราง วันที่ เวลา หรืออัปโหลดไฟล์ต้องเปิดใน Google Forms
หากส่งในแอปไม่สำเร็จ ให้เปิดฟอร์มพร้อมคำตอบ ตรวจอีกครั้งแล้วส่งผ่านเบราว์เซอร์
หากหมดเวลาส่ง ต้องตรวจว่า Google บันทึกคำตอบแล้วหรือยังก่อนส่งซ้ำ

## สร้างและทดสอบ

ใช้ JDK 17, Python 3.11, Android SDK 35 และ Gradle 8.11.1

```sh
python scripts/export_android_core.py
cd android
gradle assembleDebug lintDebug
gradle connectedDebugAndroidTest
```

GitHub Actions สร้าง APK รัน Python tests และทดสอบเปิดแอปบน Android emulator
เมื่อผ่านทั้งหมดจะอัปโหลด APK ไปยัง Artifacts และ GitHub prerelease

## การใช้โค้ดร่วมกัน

scripts/export_android_core.py เลือก Python functions และ constants จาก app.py ด้วย AST
ไม่ import Streamlit UI ไม่รวม secrets
ใช้ form_media.py, analysis_validation.py และ submission_flow.py เดิม
Android เปลี่ยนเฉพาะตัวเรียก Gemini SDK เป็น HTTPS REST
ตรรกะการอ่านฟอร์ม รูปภาพ การแบ่งชุด retry ตรวจคำตอบและตรวจทานยังใช้โค้ดเดิม
Chaquopy ใช้ Python runtime ใน Android: https://chaquo.com/chaquopy/doc/current/android.html
