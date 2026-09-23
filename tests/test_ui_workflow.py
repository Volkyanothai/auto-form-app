from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).parents[1] / "app.py"


def build_app() -> AppTest:
    app = AppTest.from_file(APP_PATH, default_timeout=10)
    app.secrets["GEMINI_API_KEY"] = "test-only"
    return app


def test_landing_opens_setup_stage():
    app = build_app().run()

    assert not app.exception
    assert [button.label for button in app.button] == ["เริ่มต้นใช้งาน"]

    app.button[0].click().run()

    assert not app.exception
    assert [field.label for field in app.text_input] == [
        "ลิงก์แบบทดสอบ",
        "ชื่อ-นามสกุล",
        "เลขที่",
        "เลขประจำตัว",
        "ชั้น/ห้อง",
    ]
    assert [button.label for button in app.button] == [
        "กลับหน้าหลัก",
        "เริ่มวิเคราะห์",
    ]


def test_profile_values_survive_workspace_navigation():
    app = build_app().run()
    app.button[0].click().run()
    app.text_input(key="profile_name").set_value("โฟล์ค ทดสอบ")
    app.text_input(key="profile_class_number").set_value("12")
    app.text_input(key="profile_student_id").set_value("12345")
    app.text_input(key="profile_classroom").set_value("6/3").run()

    app.button[0].click().run()
    app.button[0].click().run()

    assert app.text_input(key="profile_name").value == "โฟล์ค ทดสอบ"
    assert app.text_input(key="profile_class_number").value == "12"
    assert app.text_input(key="profile_student_id").value == "12345"
    assert app.text_input(key="profile_classroom").value == "6/3"


def test_submitted_state_has_a_dedicated_result_stage():
    app = build_app()
    app.session_state["workspace_started"] = True
    app.session_state["questions"] = []
    app.session_state["personal_data_map"] = {}
    app.session_state["submitted"] = True
    app.run()

    assert not app.exception
    assert any("ส่งคำตอบเรียบร้อยแล้ว" in markdown.value for markdown in app.markdown)
    assert not app.text_input


def test_result_button_uses_view_score_link_from_confirmation_html():
    app = build_app()
    app.session_state["workspace_started"] = True
    app.session_state["questions"] = []
    app.session_state["personal_data_map"] = {}
    app.session_state["submitted"] = True
    app.session_state["confirmation_url"] = (
        "https://docs.google.com/forms/d/e/FORM_ID/formResponse"
    )
    app.session_state["confirmation_html"] = """
        <html><body>
          <a href="/forms/d/e/FORM_ID/viewscore?viewscore=AE0zAgD123">
            <span>View score</span>
          </a>
          <a href="/forms/d/e/FORM_ID/viewform">Submit another response</a>
        </body></html>
    """
    app.run()

    assert not app.exception
    link_buttons = app.get("link_button")
    assert len(link_buttons) == 1
    assert link_buttons[0].label == "เปิดหน้าคะแนนใน Google Forms"
    assert link_buttons[0].url == (
        "https://docs.google.com/forms/d/e/FORM_ID/viewscore?viewscore=AE0zAgD123"
    )


def test_result_does_not_expose_non_google_score_link():
    app = build_app()
    app.session_state["workspace_started"] = True
    app.session_state["questions"] = []
    app.session_state["personal_data_map"] = {}
    app.session_state["submitted"] = True
    app.session_state["confirmation_url"] = (
        "https://docs.google.com/forms/d/e/FORM_ID/formResponse"
    )
    app.session_state["confirmation_html"] = (
        '<html><body><a href="https://example.com/viewscore">View score</a></body></html>'
    )
    app.run()

    assert not app.exception
    assert not app.get("link_button")


def test_review_compares_answer_and_shows_final_overview_without_submitting():
    app = build_app()
    app.session_state["workspace_started"] = True
    app.session_state["questions"] = [SimpleNamespace(
        entry_id="entry.1", title="เลือกคำตอบที่ถูก", choices=["A", "B"],
        is_multi=False, is_required=True, page_index=0, images=[], choice_images={},
        branch_map={},
    )]
    app.session_state["ai_answers"] = {
        "entry.1": {"answer": "B", "confidence": 85, "reliability_score": 75,
                    "risk_level": "review", "reasoning": "ตรวจจากโจทย์"}
    }
    app.session_state["personal_data_map"] = {}
    app.session_state["fbzx"] = "token"
    app.session_state["fvv"] = "1"
    app.session_state["default_next"] = [-1]
    app.session_state["page_count"] = 1
    app.session_state["submit_url"] = "https://docs.google.com/forms/d/e/test/formResponse"
    app.run()

    assert not app.exception
    assert app.get("toggle")[0].label == "ดูโจทย์คู่กับคำตอบ AI"
    assert any("AI เสนอคำตอบ" in item.value for item in app.markdown)
    assert any('class="review-answer">B' in item.value for item in app.markdown)

    app.button(key="review_submit").click().run()
    assert not app.exception
    assert any("final-overview" in item.value for item in app.markdown)
    assert app.button(key="confirm_submit").label == "ยืนยันและส่งคำตอบ"
