"""Gemini HTTPS transport; keys are headers, never embedded in URLs or logs."""
import base64
import json
import re
from types import SimpleNamespace
import requests


class Part:
    @staticmethod
    def from_text(*, text):
        return {"text": text}

    @staticmethod
    def from_bytes(*, data, mime_type):
        return {"inlineData": {"mimeType": mime_type,
                               "data": base64.b64encode(data).decode("ascii")}}


types = SimpleNamespace(Part=Part)


def api_request(key, path, payload=None):
    if not key.strip():
        raise RuntimeError("กรุณาตั้งค่า Gemini API Key")
    url = "https://generativelanguage.googleapis.com/v1beta/" + path
    response = requests.request(
        "POST" if payload is not None else "GET", url,
        headers={"x-goog-api-key": key.strip()}, json=payload, timeout=(15, 90),
    )
    if not response.ok:
        # Do not expose raw request URLs, response bodies or credential values.
        messages = {
            400: "API Key หรือรูปแบบคำขอไม่ถูกต้อง",
            401: "API Key ไม่ถูกต้อง", 403: "API Key ไม่มีสิทธิ์ใช้งาน",
            404: "โมเดลนี้ยังไม่พร้อมใช้งาน",
            429: "โควตา Gemini หมดหรือเรียกใช้ถี่เกินไป",
        }
        raise RuntimeError(f"HTTP {response.status_code}: " + messages.get(
            response.status_code, "Gemini ไม่พร้อมใช้งาน กรุณาลองอีกครั้ง"))
    return response.json()


def available_models(key, preferred):
    data = api_request(key, "models?pageSize=1000")
    models = [
        item["name"].removeprefix("models/") for item in data.get("models", [])
        if "generateContent" in item.get("supportedGenerationMethods", [])
        and re.fullmatch(r"models/gemini-[a-zA-Z0-9._-]+", item.get("name", ""))
        and "flash" in item["name"]
        and not any(x in item["name"] for x in ("image", "tts", "audio", "live", "robotics"))
    ]
    chosen = [m for m in preferred if m in models]
    # Prefer production text/vision Flash models over previews and Flash Lite.
    chosen += sorted((m for m in models if m not in chosen),
                     key=lambda m: ("lite" in m, "preview" in m, m), reverse=False)
    if not chosen:
        raise RuntimeError("API Key นี้ไม่มีโมเดล Gemini Flash ที่ใช้วิเคราะห์ได้")
    return chosen[:4]


def generate(key, model, instruction, parts, schema):
    if not re.fullmatch(r"gemini-[a-zA-Z0-9._-]+", model):
        raise RuntimeError("ชื่อโมเดลไม่ถูกต้อง")
    body = {
        "systemInstruction": {"parts": [{"text": instruction}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema,
            "maxOutputTokens": 4096, "temperature": 0.1, "topP": 0.95,
        },
    }
    data = api_request(key, f"models/{model}:generateContent", body)
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini ไม่ส่งคำตอบกลับมา")
    candidate = candidates[0]
    if candidate.get("finishReason") not in (None, "STOP"):
        raise RuntimeError("Gemini ตอบไม่ครบหรือไม่สามารถวิเคราะห์คำถามชุดนี้ได้")
    text = "".join(part.get("text", "") for part in
                   candidate.get("content", {}).get("parts", []) if not part.get("thought"))
    if not text:
        raise RuntimeError("Gemini ตอบกลับเป็นค่าว่าง")
    return json.loads(text)
