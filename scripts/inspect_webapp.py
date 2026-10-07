"""Inspect/wake the hosted UI without AI calls or form submissions."""
import json
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

def path(url):
    p = urlsplit(url)
    return p.scheme + "://" + p.netloc + p.path

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 412, "height": 915})
    page.on("pageerror", lambda error: print("PAGE_ERROR", str(error), flush=True))
    page.on("requestfailed", lambda req: print("REQUEST_FAILED", path(req.url), req.failure, flush=True))
    page.on("response", lambda res: print("HTTP_ERROR", res.status, path(res.url), flush=True) if res.status >= 400 else None)
    page.on("websocket", lambda ws: print("WEBSOCKET", path(ws.url), flush=True))
    try:
        response = page.goto("https://ezexam.streamlit.app/?client=android",
                             wait_until="domcontentloaded", timeout=60000)
        ui = page.main_frame
        for attempt in range(90):
            ui = next((frame for frame in page.frames if urlsplit(frame.url).path.startswith("/~/+/")), page.main_frame)
            if ui.locator('input[placeholder="https://forms.gle/..."]').count():
                break
            for label in ("Yes, get this app back up!", "เริ่มต้นใช้งาน"):
                button = ui.get_by_role("button", name=label, exact=True)
                if button.count() and button.first.is_visible():
                    button.first.click()
            if attempt % 10 == 0:
                print("PAGE_STATE", json.dumps({
                    "origin_path": path(page.url), "title": page.title(),
                    "body": ui.locator("body").inner_text()[:2200],
                    "html": page.locator("#root").inner_html()[:1800] if page.locator("#root").count() else "",
                    "frames": [path(frame.url) for frame in page.frames],
                }, ensure_ascii=False), flush=True)
            page.wait_for_timeout(2000)
        print(json.dumps({
            "status": response.status if response else None,
            "origin_path": path(page.url), "title": page.title(),
            "visible_text": ui.locator("body").inner_text()[:2200],
            "buttons": ui.get_by_role("button").all_text_contents()[:20],
            "inputs": ui.locator("input").evaluate_all(
                "(items)=>items.map(i=>({type:i.type,placeholder:i.placeholder}))"),
        }, ensure_ascii=False), flush=True)
        assert ui.locator('input[placeholder="https://forms.gle/..."]').count(), "Original form input did not load"
        assert not ui.locator('input[type="password"]').count(), "Unexpected key/password field"
    finally:
        browser.close()
