"""Workspace confined to this Android process; no server and no bundled keys."""
import base64
import hashlib
import json
from urllib.parse import urlsplit
import android_core as core
from android_transport import available_models

workspace = None


def _encode(value):
    return json.dumps(value, ensure_ascii=False)


def _image(image):
    return {"source": image.source, "status": image.status,
            "data": ("data:" + image.mime_type + ";base64," +
                     base64.b64encode(image.data).decode("ascii")) if image.is_ready() else ""}


def _question(q):
    return {
        "entry_id": q.entry_id, "title": q.title, "choices": q.choices,
        "is_multi": q.is_multi, "required": q.is_required, "page": q.page_index,
        "images": [_image(img) for img in q.images],
        "choice_images": {str(i): [_image(img) for img in imgs]
                          for i, imgs in q.choice_images.items()},
        "section": q.section_title, "context_notes": q.context_notes,
    }


def _view():
    w = workspace
    return {
        "title": w["title"], "questions": [_question(q) for q in w["questions"]],
        "personal": {eid: {"title": info[0], "value": info[1], "required": info[3]}
                     for eid, info in w["personal"].items()},
        "answers": w["answers"], "errors": w.get("errors", []),
        "submitted": w.get("submitted", False),
        "original_url": core.build_original_form_url(w["submit_url"]),
    }


def _notify(callback, message):
    if callback is not None:
        callback.progress(message)


def dispatch(action, argument_json, key, callback=None):
    global workspace
    args = json.loads(argument_json)
    if action == "load":
        # Limit network targets to Google's form services, including short links.
        url = args.get("url", "").strip()
        if "://" not in url:
            url = "https://" + url
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname not in
                {"forms.gle", "docs.google.com", "forms.google.com"}
                or parts.username or parts.password or parts.port not in (None, 443)):
            raise RuntimeError("กรุณาใช้ลิงก์ HTTPS ของ Google Forms หรือ forms.gle")
        _notify(callback, "กำลังอ่านฟอร์มและรูปประกอบ…")
        data, fbzx, fvv, raw_html, submit_url = core.fetch_form(url)
        questions, personal, default_next, page_count = core.parse_form(
            data, raw_html, args.get("name", ""), args.get("student_id", ""),
            args.get("number", ""), args.get("classroom", ""),
        )
        if not questions and not personal:
            raise RuntimeError("ฟอร์มนี้ไม่มีคำถามที่รองรับ")
        # Avoid presenting an incomplete review for grids, date/time, or file uploads.
        items = core.safe_get(data, [1, 1], [])
        supported = {0, 1, 2, 3, 4, 8, 9, 10, 11}
        if any(item and len(item) > 4 and item[4] and item[3] not in supported
               for item in items):
            raise RuntimeError("ฟอร์มนี้มีตาราง วันที่ เวลา หรืออัปโหลดไฟล์ กรุณาเปิดใน Google Forms")
        workspace = {
            "title": core.clean_text(core.safe_get(data, [1, 8], "")) or "Google Forms",
            "questions": questions, "personal": personal,
            "default_next": default_next, "page_count": page_count,
            "fbzx": fbzx, "fvv": fvv, "submit_url": submit_url, "answers": {},
            "context": args.get("context", ""), "errors": [], "submitted": False,
        }
        return _encode(_view())
    if action == "reset":
        workspace = None
        return "{}"
    if workspace is None:
        raise RuntimeError("กรุณาเปิดฟอร์มก่อน")
    if action == "analyze":
        if workspace.get("submitted"):
            raise RuntimeError("ฟอร์มนี้ส่งแล้ว กรุณาเริ่มฟอร์มใหม่")
        _notify(callback, "กำลังตรวจโมเดลที่พร้อมใช้งาน…")
        core.MODEL_CANDIDATES = available_models(key, core.MODEL_CANDIDATES)
        eid = args.get("entry_id")
        questions = [q for q in workspace["questions"] if not eid or q.entry_id == eid]
        if not questions:
            raise RuntimeError("ไม่พบคำถาม")
        def progress(done, total):
            _notify(callback, f"วิเคราะห์ {done}/{total} ชุด — กำลังตรวจทานคำตอบ")
        def live(phase, result):
            _notify(callback, phase + " — ได้คำตอบ " + str(len(result)) + " ข้อ")
        answers, errors, logs = core.analyze_all(
            questions, [key], workspace["context"],
            progress_cb=progress, verify_risky=True, live_cb=live,
        )
        # On reanalysis failure, keep usable old answers.
        workspace["answers"].update({k: v for k, v in answers.items() if v.get("answer")})
        workspace["errors"] = errors
        return _encode(_view())
    if action in {"prefill", "submit"}:
        answers = args.get("answers", {})
        if not isinstance(answers, dict):
            raise RuntimeError("รูปแบบคำตอบไม่ถูกต้อง")
        history = core.simulate_page_history(
            workspace["questions"], answers, workspace["default_next"], workspace["page_count"])
        visited = {int(page) for page in history.split(",")}
        questions = [q for q in workspace["questions"] if q.page_index in visited]
        for q in questions:
            answer = answers.get(q.entry_id)
            if q.is_required and not answer:
                raise RuntimeError("กรุณาตอบคำถามที่จำเป็น: " + q.title[:100])
            if q.choices and answer:
                values = answer if isinstance(answer, list) else [answer]
                if any(value not in q.choices for value in values):
                    raise RuntimeError("คำตอบไม่ตรงกับตัวเลือก: " + q.title[:100])
                if not q.is_multi and len(values) != 1:
                    raise RuntimeError("กรุณาเลือกคำตอบเดียว")
        for eid, info in workspace["personal"].items():
            if info[3] and not str(answers.get(eid, info[1]) or "").strip():
                raise RuntimeError("กรุณากรอก " + info[0])
        payload = core.build_submit_payload(
            workspace["personal"], questions, answers, workspace["fbzx"],
            workspace["fvv"], history)
        original_url = core.build_original_form_url(workspace["submit_url"])
        prefill_url = core.build_prefilled_form_url(workspace["submit_url"], payload)
        if action == "prefill":
            return _encode({"url": prefill_url or original_url,
                            "truncated": not bool(prefill_url)})
        fingerprint = hashlib.sha256(_encode(payload).encode()).hexdigest()
        if workspace.get("submitted") or workspace.get("submitted_fingerprint") == fingerprint:
            raise RuntimeError("คำตอบฟอร์มนี้ส่งสำเร็จแล้ว ระบบจะไม่ส่งซ้ำ")
        _notify(callback, "กำลังส่งคำตอบที่คุณยืนยัน…")
        success, message, html, response_url = core.post_form_response(
            workspace["submit_url"], payload, core.UA, core.SUBMIT_TIMEOUT)
        if success:
            workspace["submitted"] = True
            workspace["submitted_fingerprint"] = fingerprint
        return _encode({"success": success, "message": message,
                        "url": prefill_url or original_url,
                        "truncated": not bool(prefill_url)})
    raise RuntimeError("คำสั่งไม่ถูกต้อง")


def self_test():
    assert core.build_form_view_url(
        "https://docs.google.com/forms/d/e/TEST/formResponse").endswith("/viewform")
    assert core.normalize_model_answers(
        {"answers": [{"entry_id": "entry.1", "answer": ["A"], "confidence": 90,
                      "reasoning": "test"}]},
        {"entry.1": {"choices": ["A", "B"], "is_multi": False}}
    )["entry.1"]["answer"] == "A"
    from PIL import Image
    import io
    image = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(image, "PNG")
    assert core.validate_image(image.getvalue())[0]
    return "ok"
