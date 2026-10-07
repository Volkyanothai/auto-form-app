"""Exercise the generated Android engine with mocked network calls."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, str(ROOT / "scripts/export_android_core.py")], check=True)
sys.path.insert(0, str(ROOT / "android/app/generated/python"))
sys.path.insert(0, str(ROOT / "android/app/src/main/python"))
import android_core as core
import android_bridge as bridge
import android_transport as transport


def test_generated_core_loads_without_streamlit_or_google_sdk():
    assert bridge.self_test() == "ok"
    assert core.call_gemini_chunk_with_key.__module__ == "android_core"
    assert core.analyze_all.__module__ == "android_core"


def test_transport_sends_key_in_header_and_preserves_schema(monkeypatch):
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(ok=True, json=lambda: {
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{
                "text": '{"answers": []}'
            }]}}]
        })
    monkeypatch.setattr(transport.requests, "request", request)
    assert transport.generate("secret-key", "gemini-2.5-flash", "instruction",
                              [{"text": "question"}], core.AI_RESPONSE_SCHEMA) == {"answers": []}
    method, url, kwargs = calls[0]
    assert method == "POST" and "secret-key" not in url
    assert kwargs["headers"] == {"x-goog-api-key": "secret-key"}
    assert kwargs["json"]["generationConfig"]["responseSchema"] == core.AI_RESPONSE_SCHEMA


def test_transport_does_not_leak_keys_on_error(monkeypatch):
    monkeypatch.setattr(transport.requests, "request", lambda *a, **kw:
        SimpleNamespace(ok=False, status_code=403))
    import pytest
    with pytest.raises(RuntimeError) as caught:
        transport.api_request("secret-key", "models")
    assert "403" in str(caught.value) and "secret-key" not in str(caught.value)


def test_generated_analysis_preserves_validated_answers(monkeypatch):
    question = core.Question("entry.1", "2+2?", "", ["3", "4"], False, True, 0)
    monkeypatch.setattr(core, "generate", lambda *args: {"answers": [{
        "entry_id": "entry.1", "answer": ["4"], "confidence": 95, "reasoning": "2+2=4"
    }]})
    monkeypatch.setattr(core, "MODEL_CANDIDATES", ["gemini-2.5-flash"])
    answers, errors, logs = core.analyze_all([question], ["test"], "", verify_risky=True)
    assert not errors
    assert answers["entry.1"]["answer"] == "4"
    assert "reliability_score" in answers["entry.1"]


def test_workspace_submission_requires_valid_answer_and_blocks_duplicates(monkeypatch):
    q = core.Question("entry.1", "Question", "", ["A", "B"], False, True, 0)
    bridge.workspace = {
        "questions": [q], "personal": {}, "default_next": [-1], "page_count": 1,
        "fbzx": "123", "fvv": "1", "submit_url":
        "https://docs.google.com/forms/d/e/TEST/formResponse", "answers": {},
        "title": "Test", "submitted": False,
    }
    import pytest
    with pytest.raises(RuntimeError):
        bridge.dispatch("submit", '{"answers": {"entry.1": "invented"}}', "")
    calls = []
    def post(*args):
        calls.append(args)
        return True, "ok", "<html>confirmation</html>", args[0]
    monkeypatch.setattr(core, "post_form_response", post)
    result = json.loads(bridge.dispatch("submit", '{"answers": {"entry.1": "A"}}', ""))
    assert result["success"] and len(calls) == 1
    with pytest.raises(RuntimeError):
        bridge.dispatch("submit", '{"answers": {"entry.1": "B"}}', "")
    assert len(calls) == 1


def test_android_rejects_non_google_input_before_network(monkeypatch):
    def unexpected(*args):
        raise AssertionError("Should not make a network request")
    monkeypatch.setattr(core, "fetch_form", unexpected)
    import pytest
    for url in ["https://example.com/forms", "http://forms.gle/x",
                "https://docs.google.com:444/forms/x"]:
        with pytest.raises(RuntimeError):
            bridge.dispatch("load", json.dumps({"url": url}), "")
