"""Export shared logic without importing or packaging the Streamlit UI.

AST selection retains the tested form reader, images, branching, answer
normalisation, retries and verification. Only the SDK transport is replaced
by a small HTTPS REST adapter, avoiding unsupported Android SDK dependencies.
"""
from pathlib import Path
import ast
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "android/app/generated/python"
OUT.mkdir(parents=True, exist_ok=True)
source = (ROOT / "app.py").read_text(encoding="utf-8")
tree = ast.parse(source)
first = next(n.lineno for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "safe_get")
last = next(n.end_lineno for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_submit_payload")
constants = {
    "UA", "TYPE_PAGE_BREAK", "TYPE_CHECKBOX", "TYPE_MULTIPLE_CHOICE", "TYPE_DROPDOWN",
    "TYPE_TEXT", "TYPE_PARAGRAPH", "TYPE_IMAGE", "MAX_PARALLEL_WORKERS",
    "MAX_REPAIR_ATTEMPTS", "MAX_ROUTE_ATTEMPTS", "MAX_VERIFICATION_ITEMS",
    "MAX_ADJUDICATION_ITEMS", "MAX_IMAGE_WORKERS", "ANALYSIS_TIMEOUT_MS",
    "SUBMIT_TIMEOUT", "IMAGE_TIMEOUT", "MAX_IMAGE_DIM", "MAX_IMAGE_DIM_TEXT",
    "MAX_IMAGE_FILE_SIZE", "JPEG_QUALITY", "MODEL_CANDIDATES", "DEAD_KEY_SIGNALS",
    "BASE64_IMG_RE", "GOOGLE_IMG_URL_RE",
}
selected = []
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name in {"Question", "QuestionImage"}:
        selected.append(node)
    elif isinstance(node, ast.FunctionDef) and first <= node.lineno <= last:
        # Cache on desktop is process-wide. Android uses a workspace with its
        # own lifetime and downloads each image at most once per load.
        node.decorator_list = []
        selected.append(node)
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(t, ast.Name) and t.id in constants for t in targets):
            selected.append(node)
header = """from __future__ import annotations
import base64, difflib, hashlib, html as html_lib, io, json, logging, re, threading, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TypeVar, Union
from urllib.parse import urljoin, urlsplit
import requests
from form_media import *
from analysis_validation import *
from submission_flow import build_form_view_url, build_original_form_url, build_prefilled_form_url, post_form_response
from android_transport import types
THINKING_CONFIG_AVAILABLE = False
logger = logging.getLogger("ezexam.android")
"""
body = ast.unparse(ast.Module(body=selected, type_ignores=[]))
footer = """
# Replace only the transport; retry/verification logic remains shared.
from android_transport import generate
def call_gemini_chunk_with_key(api_key, exam_context, chunk, model_name):
    parts = []
    for index, question in chunk:
        parts.extend(build_question_parts(index, question))
    data = generate(api_key, model_name, build_system_instruction(exam_context), parts, AI_RESPONSE_SCHEMA)
    expected = {q.entry_id: {"choices": q.choices, "is_multi": q.is_multi} for _, q in chunk}
    return normalize_model_answers(data, expected)
"""
text = header + "\n" + body + "\n" + footer
compile(text, "android_core.py", "exec")
(OUT / "android_core.py").write_text(text, encoding="utf-8")
for name in ("analysis_validation.py", "form_media.py", "submission_flow.py"):
    shutil.copyfile(ROOT / name, OUT / name)
print("Android core exported: shared parsing, images, analysis and verification")

shutil.copyfile(ROOT / "logo.png", ROOT / "android/app/src/main/assets/logo.png")
