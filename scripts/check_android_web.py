"""Validate the public app URL; never read server credentials."""
import os
from pathlib import Path
from urllib.parse import urlsplit

root = Path(__file__).resolve().parents[1]
config = root / "android/webapp.properties"
url = ""
if config.exists():
    for line in config.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("url="):
            url = line[4:].strip()
if url:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment or any(c.isspace() for c in url)):
        raise SystemExit("android/webapp.properties must contain a public HTTPS app URL")
configured = bool(url)
if not configured:
    # Reserved non-routable domain, used only with intercepted instrumented
    # test pages. An APK built this way must never be published.
    url = "https://example.invalid/"
output = os.environ.get("GITHUB_OUTPUT")
env = os.environ.get("GITHUB_ENV")
if output:
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"configured={str(configured).lower()}\n")
if env:
    with open(env, "a", encoding="utf-8") as handle:
        handle.write(f"EZEXAM_WEB_URL={url}\n")
print("Hosted app URL configured" if configured else
      "No hosted app URL: validation only, APK publication disabled")
