from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import requests

from submission_flow import build_prefilled_form_url, check_submit_success, post_form_response


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


def test_returned_form_and_timeout_never_trigger_automatic_second_post():
    calls = []

    def returns_form(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(text="FB_PUBLIC_LOAD_DATA_ = [];", status_code=200, url=FORM_RESPONSE)

    success, message, html, url = post_form_response(FORM_RESPONSE, {"entry.1": "A"}, {}, 5, returns_form)
    assert not success and "หน้าฟอร์มกลับมา" in message
    assert html is None and url is None and len(calls) == 1

    def times_out(*args, **kwargs):
        calls.append((args, kwargs))
        raise requests.exceptions.Timeout()

    success, message, html, url = post_form_response(FORM_RESPONSE, {"entry.1": "A"}, {}, 5, times_out)
    assert not success and "ไม่ทราบผล" in message
    assert html is None and url is None and len(calls) == 2
