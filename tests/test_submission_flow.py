from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import requests

from submission_flow import (
    MAX_PREFILL_URL_LENGTH,
    build_original_form_url,
    build_form_view_url,
    build_prefilled_form_url,
    check_submit_success,
    post_form_response,
)


FORM_RESPONSE = "https://docs.google.com/forms/d/e/FORM_ID/formResponse"


def test_only_google_confirmation_page_proves_submission():
    assert check_submit_success(
        '<div class="freebirdFormviewerViewResponseConfirmationMessage">Thanks</div>',
        200,
    ) == (True, None)
    for html in ("Thanks!", '<div role="form">Thank you</div>', "FB_PUBLIC_LOAD_DATA_ = [];"):
        success, message = check_submit_success(html, 200, FORM_RESPONSE)
        assert not success
        assert message
    success, message = check_submit_success("", 200, "https://accounts.google.com/signin")
    assert not success
    assert "ลงชื่อเข้าใช้" in message


def test_modern_visible_confirmation_is_accepted_without_legacy_css_marker():
    for message in ("Your response has been recorded.", "บันทึกคำตอบของคุณแล้ว"):
        html = f"<html><body><main><p>{message}</p></main></body></html>"
        assert check_submit_success(html, 200, FORM_RESPONSE) == (True, None)
        success, _, returned_html, _ = post_form_response(
            FORM_RESPONSE, {"entry.1": "A"}, {}, 5,
            lambda *args, **kwargs: SimpleNamespace(text=html, status_code=200, url=FORM_RESPONSE),
        )
        assert success and returned_html == html


def test_confirmation_with_google_page_data_and_decorative_form_is_not_called_unanswered():
    html = ('<script>FB_PUBLIC_LOAD_DATA_ = [];</script>'
            '<form action="/search"></form><p>Submit another response</p>')
    assert check_submit_success(html, 200, FORM_RESPONSE) == (True, None)


def test_form_or_script_text_cannot_masquerade_as_confirmation():
    for html in (
        '<form action="formResponse"><p>Your response has been recorded.</p><input name="entry.1"></form>',
        '<script>const message = "Your response has been recorded.";</script>',
    ):
        assert not check_submit_success(html, 200, FORM_RESPONSE)[0]


def test_prefill_uses_only_answer_fields_and_keeps_checkbox_values():
    url = build_prefilled_form_url(FORM_RESPONSE, {
        "entry.123": "ภาษาไทย & วิทย์",
        "entry.456": ["ก", "ข"],
        "fbzx": "private-token",
        "pageHistory": "0,1",
    })
    assert url is not None
    parsed = urlsplit(url)
    assert parsed.path.endswith("/viewform")
    assert parse_qs(parsed.query) == {
        "usp": ["pp_url"], "entry.123": ["ภาษาไทย & วิทย์"], "entry.456": ["ก", "ข"],
    }
    assert build_prefilled_form_url("https://evil.example/forms/d/e/id/formResponse", {"entry.1": "a"}) is None


def test_long_thai_answers_fall_back_to_clean_original_form():
    long_answers = {f"entry.{index}": "ภาษาไทย" * 50 for index in range(30)}
    assert build_prefilled_form_url(FORM_RESPONSE, long_answers) is None
    original = build_original_form_url(FORM_RESPONSE + "?usp=pp_url&entry.1=private")
    assert original == "https://docs.google.com/forms/d/e/FORM_ID/viewform"
    short_url = build_prefilled_form_url(FORM_RESPONSE, {"entry.1": "ภาษาไทย"})
    assert short_url is not None and len(short_url) <= MAX_PREFILL_URL_LENGTH


def test_returned_form_and_timeout_never_trigger_automatic_second_post():
    calls = []

    def returns_form(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(text='<form action="formResponse"><input name="entry.1"></form>', status_code=200, url=FORM_RESPONSE)

    success, message, html, url = post_form_response(FORM_RESPONSE, {"entry.1": "A"}, {}, 5, returns_form)
    assert not success and "หน้าฟอร์มกลับมา" in message
    assert html is None and url is None and len(calls) == 1

    def times_out(*args, **kwargs):
        calls.append((args, kwargs))
        raise requests.exceptions.Timeout()

    success, message, html, url = post_form_response(FORM_RESPONSE, {"entry.1": "A"}, {}, 5, times_out)
    assert not success and "ไม่ทราบผล" in message
    assert html is None and url is None and len(calls) == 2

def test_submission_link_is_opened_as_respondent_page():
    response_url = FORM_RESPONSE + "?usp=pp_url"
    assert build_form_view_url(response_url) == (
        "https://docs.google.com/forms/d/e/FORM_ID/viewform?usp=pp_url"
    )
    assert build_form_view_url("https://forms.gle/short") == "https://forms.gle/short"
    assert build_form_view_url(
        "https://evil.example/forms/d/e/FORM_ID/formResponse"
    ).endswith("/formResponse")
    assert build_form_view_url(FORM_RESPONSE.replace("formResponse", "viewform")) == (
        FORM_RESPONSE.replace("formResponse", "viewform")
    )
