from pathlib import Path

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
