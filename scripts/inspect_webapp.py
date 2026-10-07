"""Read-only browser diagnostics: no AI calls or form submissions."""
import json
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 412, "height": 915})
    try:
        response = page.goto("https://ezexam.streamlit.app/?client=android",
                             wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(20000)
        parsed = urlsplit(page.url)
        print(json.dumps({
            "status": response.status if response else None,
            "origin_path": parsed.scheme + "://" + parsed.netloc + parsed.path,
            "title": page.title(),
            "visible_text": page.locator("body").inner_text()[:2200],
            "buttons": page.get_by_role("button").all_text_contents()[:20],
            "inputs": page.locator("input").evaluate_all(
                "(items)=>items.map(i=>({type:i.type,placeholder:i.placeholder}))"),
        }, ensure_ascii=False))
    finally:
        browser.close()
