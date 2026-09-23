from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import requests

from submission_flow import (
    MAX_PREFILL_URL_LENGTH,
    build_original_form_url,
    build_prefilled_form_url,
    check_submit_success,
    post_form_response,
    build_entry_page_map,
    post_form_response_with_pages,
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


def test_multi_page_submission_uses_live_state_and_posts_final_page_only_once():
    form_data = [None, [None, [
        [1, "Name", None, 0, [[101, None, 1]]],
        [2, "Next", None, 8, None],
        [3, "Question", None, 2, [[102, [["A"], ["B"]], 1]]],
    ]]]
    import json

    def page_html(history, token, partial=""):
        return (
            f'<input name="fbzx" value="{token}">'
            f'<input name="fvv" value="1">'
            f'<input name="pageHistory" value="{history}">'
            f'<input name="partialResponse" value="{partial}">'
            f'<script>var FB_PUBLIC_LOAD_DATA_ = {json.dumps(form_data)};</script>'
        )

    class FakeSession:
        def __init__(self):
            self.posts = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, text=page_html("0", "fresh"))

        def post(self, url, data, **kwargs):
            self.posts.append(dict(data))
            if len(self.posts) == 1:
                return SimpleNamespace(status_code=200,
                                       text=page_html("0,1", "next", "[[101, 'Name']]") , url=url)
            return SimpleNamespace(status_code=200,
                                   text='<div class="freebirdFormviewerViewResponseConfirmationMessage">OK</div>',
                                   url=url)

    session = FakeSession()
    payload = {"entry.101": "Folk", "entry.102": "B", "pageHistory": "0,1", "fbzx": "old"}
    assert build_entry_page_map(form_data) == {"entry.101": 0, "entry.102": 1}
    success, _, _, _ = post_form_response_with_pages(
        FORM_RESPONSE, payload, {}, {}, 5, session_factory=lambda: session,
    )
    assert success
    assert len(session.posts) == 2
    assert session.posts[0]["entry.101"] == "Folk"
    assert "entry.102" not in session.posts[0]
    assert session.posts[0]["fbzx"] == "fresh"
    assert session.posts[0]["continue"] == "1"
    assert session.posts[1]["entry.102"] == "B"
    assert "entry.101" not in session.posts[1]
    assert session.posts[1]["fbzx"] == "next"
    assert session.posts[1]["partialResponse"] == "[[101, 'Name']]"
    assert "continue" not in session.posts[1]


def test_page_validation_stops_before_final_submit_when_google_rejects_navigation():
    form_data = [None, [None, [[1, "Q", None, 0, [[101, None, 1]]],
                               [2, "Next", None, 8, None],
                               [3, "Q2", None, 0, [[102, None, 1]]]]]]
    import json
    html = (
        '<input name="fbzx" value="fresh"><input name="pageHistory" value="0">'
        f'<script>var FB_PUBLIC_LOAD_DATA_ = {json.dumps(form_data)};</script>'
    )

    class RejectedSession:
        posts = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, text=html)

        def post(self, *args, **kwargs):
            self.posts += 1
            return SimpleNamespace(status_code=200, text=html, url=FORM_RESPONSE)

    session = RejectedSession()
    success, message, _, _ = post_form_response_with_pages(
        FORM_RESPONSE, {"entry.101": "A", "entry.102": "B", "pageHistory": "0,1"},
        {}, {}, 5, session_factory=lambda: session,
    )
    assert not success and "หยุดที่หน้า" in message
    assert session.posts == 1
