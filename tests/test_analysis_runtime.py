"""Exercise production routing without API credentials or network calls."""
import ast
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from types import SimpleNamespace

import analysis_validation as validation
from google.genai import types

APP = Path(__file__).parents[1] / "app.py"
FUNCTIONS = {
    "call_gemini_chunk_with_key", "try_key_model", "call_gemini_chunk",
    "analyze_all", "_ready_image_count", "is_dead_key_error",
    "is_daily_quota_error", "is_model_unavailable_error",
    "is_quota_or_transient_error",
}
CONSTANTS = {
    "MAX_PARALLEL_WORKERS", "MAX_REPAIR_ATTEMPTS", "MAX_ROUTE_ATTEMPTS",
    "MAX_VERIFICATION_ITEMS", "MAX_ADJUDICATION_ITEMS", "ANALYSIS_TIMEOUT_MS",
    "ANALYSIS_BUDGET_SECONDS", "MODEL_CANDIDATES", "DEAD_KEY_SIGNALS",
}

def engine():
    selected = []
    for node in ast.parse(APP.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            selected.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id in CONSTANTS for target in targets):
                selected.append(node)
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *selected,
    ], type_ignores=[])
    scope = {name: getattr(validation, name) for name in dir(validation)}
    scope.update(threading=threading, time=time, ThreadPoolExecutor=ThreadPoolExecutor,
                 wait=wait, FIRST_COMPLETED=FIRST_COMPLETED, types=types)
    exec(compile(ast.fix_missing_locations(module), str(APP), "exec"), scope)
    return scope

def questions(count):
    return [SimpleNamespace(entry_id=f"entry.{i}", title=f"Question {i}",
        images=[], choice_images={}, choices=["A", "B"], is_multi=False)
        for i in range(count)]

def route(scope, deadline=None, exhausted=None):
    return scope["call_gemini_chunk"](
        ["test-only"], 0, "", [], ["first", "fallback"],
        set(), threading.Lock(), exhausted if exhausted is not None else set(),
        threading.Lock(), deadline=deadline)

def test_expired_budget_never_starts_another_request():
    scope = engine()
    scope["time"] = SimpleNamespace(monotonic=lambda: 10)
    calls = []
    scope["try_key_model"] = lambda *args: calls.append(args)
    import pytest
    with pytest.raises(TimeoutError):
        route(scope, deadline=10)
    assert calls == []

def test_fallback_request_uses_only_remaining_budget():
    scope = engine()
    now = [10]
    scope["time"] = SimpleNamespace(monotonic=lambda: now[0])
    timeouts = []
    def attempt(*args):
        timeouts.append(args[-1])
        now[0] += 0.4
        return ("transient_fail", RuntimeError("503 unavailable")) if len(timeouts) == 1 else ("ok", {})
    scope["try_key_model"] = attempt
    route(scope, deadline=11)
    assert timeouts[0] == 1000
    assert 599 <= timeouts[1] <= 600

def test_unavailable_models_are_not_retried_for_every_chunk():
    scope = engine()
    calls = []
    def attempt(*args):
        calls.append(args)
        return "model_bad", RuntimeError("404 model not found")
    scope["try_key_model"] = attempt
    exhausted = set()
    import pytest
    for _ in range(3):
        with pytest.raises(RuntimeError):
            route(scope, exhausted=exhausted)
    assert len(calls) == 2

def test_quota_failure_does_not_trigger_pair_and_single_repair_passes():
    scope = engine()
    calls = []
    def attempt(*args):
        calls.append(args)
        return "transient_fail", RuntimeError("429 RESOURCE_EXHAUSTED per-minute quota")
    scope["try_key_model"] = attempt
    items = questions(30)
    results, errors, logs = scope["analyze_all"](items, ["test-only"], "", verify_risky=False)
    assert not results and errors
    batches = validation.build_balanced_batches(list(enumerate(items, 1)), lambda _: 0)
    assert len(calls) == len(batches) * scope["MAX_ROUTE_ATTEMPTS"]
    assert any("หยุดลองซ้ำ" in log for log in logs)

def test_budget_keeps_completed_answers_and_skips_later_repairs():
    scope = engine()
    now = [0]
    scope["time"] = SimpleNamespace(monotonic=lambda: now[0])
    scope["MAX_PARALLEL_WORKERS"] = 1
    calls = []
    def analyze(*args):
        if now[0] >= args[-1]:
            raise TimeoutError("ครบเวลาวิเคราะห์")
        calls.append(args)
        now[0] += 60
        return {q.entry_id: {"answer": "A", "confidence": 90} for _, q in args[3]}, args[4][0]
    scope["call_gemini_chunk"] = analyze
    results, errors, _ = scope["analyze_all"](questions(20), ["test-only"], "", verify_risky=False)
    assert len(results) == 16 and errors
    assert len(calls) == 2
    assert all(answer["answer"] == "A" for answer in results.values())

def test_overdue_network_call_does_not_block_return_of_partial_results():
    scope = engine()
    scope["ANALYSIS_BUDGET_SECONDS"] = 0.1
    release = threading.Event()
    exited = threading.Event()
    def analyze(*args):
        if args[3][0][0] > 8:
            try:
                release.wait(3)
                return {}, args[4][0]
            finally:
                exited.set()
        return {q.entry_id: {"answer": "A", "confidence": 90} for _, q in args[3]}, args[4][0]
    scope["call_gemini_chunk"] = analyze
    start = time.monotonic()
    try:
        results, errors, _ = scope["analyze_all"](questions(9), ["test-only"], "", verify_risky=False)
        assert time.monotonic() - start < 0.7
        assert len(results) == 8 and errors
    finally:
        release.set()
        assert exited.wait(1)

def test_status_updates_on_main_thread_before_result_arrives():
    scope = engine()
    release = threading.Event()
    ticks = []
    main_thread = threading.get_ident()
    def analyze(*args):
        assert release.wait(3)
        return {"entry.0": {"answer": "A", "confidence": 90}}, args[4][0]
    def status(*args):
        assert threading.get_ident() == main_thread
        ticks.append(args)
        if len(ticks) >= 2:
            release.set()
    scope["call_gemini_chunk"] = analyze
    results, errors, _ = scope["analyze_all"](
        questions(1), ["test-only"], "", verify_risky=False, status_cb=status)
    assert len(ticks) >= 2
    assert results["entry.0"]["answer"] == "A" and not errors

def test_sdk_has_one_attempt_and_capped_timeout_and_closes_client():
    scope = engine()
    captured = {}
    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.models = SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(text='{"answers": []}'))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            captured["closed"] = True
    scope.update(genai=SimpleNamespace(Client=Client), THINKING_CONFIG_AVAILABLE=False,
                 build_system_instruction=lambda _: "", build_question_parts=lambda *args: [],
                 parse_ai_response=json.loads)
    assert scope["call_gemini_chunk_with_key"]("test-only", "", [], "model", 500) == {}
    assert captured["http_options"].timeout == 500
    assert captured["http_options"].retry_options.attempts == 1
    assert captured["closed"]
