"""
style.py — EZEXAM UI (Prismatic Glass & Terminal Decryption Edition)
====================================================================
v3 — เปลี่ยนหน้าจอ Loading จาก Blueprint Sketching เป็น "Terminal
     ถอดรหัส" (hacker console): กรอบ terminal ปลอม + เส้นสแกนวิ่งไล่จาก
     บนลงล่าง + ตัวหนังสือ status เป็น monospace เรืองแสงมี ">" นำหน้า
     ทุกบรรทัด + progress bar เป็นบล็อกข้อมูลเรืองแสงแทนเส้นเรียบ +
     เอฟเฟกต์ไฟกระพริบเบาๆ (flicker) ให้ความรู้สึกเหมือนเครื่องกำลัง
     ทำงานหนักจริงๆ (ปิดอัตโนมัติถ้าเครื่องตั้ง reduce motion ไว้)
v2 — ปรับปรุงจากเวอร์ชันเดิม:
  1. ดึงสีที่ใช้ซ้ำๆ มาไว้เป็น CSS variables (--*) ที่เดียว แก้สีทีเดียวจบ
  2. การ์ดคำถามไม่ต้อง animate gradient border ตลอดเวลาแล้ว (เดิมถ้ามีคำถาม
     เยอะๆ การ์ดทุกใบจะ animate พร้อมกันตลอด ทำให้ iPad ค้าง/ร้อน/กินแบต) —
     ตอนนี้ border นิ่ง ๆ โดย default แล้วค่อย "วิ่ง" ตอนแตะ (tap) เท่านั้น
  3. เพิ่ม prefers-reduced-motion ปิดแอนิเมชันทั้งหมดให้อัตโนมัติสำหรับ
     คนที่ตั้งค่าเครื่องไว้แบบนั้น (ทั้งเพื่อ accessibility และประหยัดแบต)
  4. เพิ่ม safe-area padding กันเนื้อหาโดน notch/home-indicator ของ iPad/iPhone บัง
  5. แคชโลโก้อิงจาก mtime+size ของไฟล์ ถ้าเปลี่ยนไฟล์โลโก้แล้วไม่ต้อง restart app
     เพื่อให้เห็นผลใหม่ (เดิมแคชค้างตลอดอายุ process)
  6. ลด backdrop-filter blur ลงเล็กน้อยบนมือถือ/iPad เพื่อ performance
- รองรับ iPad เต็มรูปแบบ (Tap-to-flare แทน Hover)
- ปรับแต่งหน้าจอ Loading เป็นสไตล์ Blueprint Sketching
"""
import base64
import io
from pathlib import Path

import streamlit as st

# ═══════════ ปรับได้ตรงนี้ ═══════════
LOGO_FILES = ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp", "logo.svg")
LOGO_COLOR = "auto"     # "auto" = ตรวจเอง | "white" = บังคับขาว | "original" = สีเดิม
STRIP_WHITE = True      # ลบพื้นหลังขาวทึบออกอัตโนมัติ
# ════════════════════════════════════

def _find_logo():
    for name in LOGO_FILES:
        p = Path(name)
        if p.exists():
            return p
    return None

def _strip_white_bg(img, tol=34):
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return img
    w, h = img.size
    if w < 2 or h < 2:
        return img
    arr = np.array(img)
    if arr.shape[-1] != 4:
        return img
    corners = [arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1]]
    solid = [c for c in corners if c[3] > 8]
    if not solid:
        return img
    r0 = int(np.mean([c[0] for c in solid]))
    g0 = int(np.mean([c[1] for c in solid]))
    b0 = int(np.mean([c[2] for c in solid]))
    if not (r0 > 224 and g0 > 224 and b0 > 224):
        return img
    diff = np.max(np.abs(arr[:, :, :3].astype(np.int16) - [r0, g0, b0]), axis=2)
    alpha = arr[:, :, 3].astype(np.float32)
    mask_bg = diff <= tol
    alpha[mask_bg] = 0
    mask_edge = (diff > tol) & (diff <= tol * 2)
    ratio = (diff[mask_edge] - tol) / tol
    alpha[mask_edge] = alpha[mask_edge] * ratio
    arr[:, :, 3] = alpha.astype(np.uint8)
    return Image.fromarray(arr)

def _is_dark(img):
    try:
        import numpy as np
        arr = np.array(img)
        if arr.shape[-1] == 4:
            mask = arr[:, :, 3] > 40
            if not np.any(mask):
                return False
            rgb = arr[:, :, :3][mask]
            lum = 0.299 * rgb[:, 0] + 0.587 * rgb[:, 1] + 0.114 * rgb[:, 2]
            return float(np.mean(lum)) < 135
        else:
            lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
            return float(np.mean(lum)) < 135
    except Exception:
        return False

def _to_white(img):
    try:
        from PIL import Image
        r, g, b, a = img.split()
        white_r = r.point(lambda _: 255)
        white_g = g.point(lambda _: 255)
        white_b = b.point(lambda _: 255)
        return Image.merge("RGBA", (white_r, white_g, white_b, a))
    except Exception:
        return img

def _logo_cache_key(p: Path) -> str:
    """ใช้ mtime+size เป็น key กันแคชค้างเวลาเปลี่ยนไฟล์โลโก้"""
    try:
        stat = p.stat()
        return f"{p.name}:{stat.st_mtime_ns}:{stat.st_size}"
    except Exception:
        return p.name

@st.cache_data(show_spinner=False)
def _logo_uri_cached(cache_key: str, path_str: str) -> str:
    p = Path(path_str)
    raw = p.read_bytes()
    if p.suffix.lower() == ".svg":
        return "data:image/svg+xml;base64," + base64.b64encode(raw).decode()
    try:
        from PIL import Image
    except Exception:
        return "data:image/png;base64," + base64.b64encode(raw).decode()
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        if max(img.size) > 1000:
            img.thumbnail((1000, 1000), Image.LANCZOS)
        if STRIP_WHITE:
            img = _strip_white_bg(img)
        box = img.getbbox()
        if box:
            img = img.crop(box)
        if LOGO_COLOR == "white" or (LOGO_COLOR == "auto" and _is_dark(img)):
            img = _to_white(img)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return "data:image/png;base64," + base64.b64encode(raw).decode()

def _logo_uri() -> str:
    p = _find_logo()
    if p is None:
        return ""
    return _logo_uri_cached(_logo_cache_key(p), str(p))

def _raw(html_code: str) -> None:
    try:
        st.html(html_code)
    except Exception:
        st.markdown(html_code, unsafe_allow_html=True)

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700;800&family=Noto+Sans+Thai:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');

:root{
  --bg-1:#03060f; --bg-2:#070d22; --bg-3:#04081a;
  --ink:#e7edfb; --ink-dim:#8698bd; --ink-dim2:#7c8db3;
  --blue:#7fb3ff;      --blue-rgb:127,179,255;
  --blue-soft:#8fbcff; --blue-soft-rgb:143,188,255;
  --teal:#5fe3d0;       --teal-rgb:95,227,208;
  --gold:#e8c98a;       --gold-rgb:232,201,138;
  --violet:#845aff;     --violet-rgb:132,90,255;
  --glass-border: rgba(var(--blue-rgb),.14);
  --blur-strong: blur(24px) saturate(150%);
  --blur-soft: blur(16px) saturate(140%);
  --mono: 'JetBrains Mono','Fira Code',Consolas,Monaco,monospace;
}

html,body,p,h1,h2,h3,h4,h5,h6,label,input,textarea,li,button,span,div{font-family:'Sora','Noto Sans Thai',sans-serif;}

/* ปิดแอนิเมชันทั้งหมดอัตโนมัติถ้าเครื่องผู้ใช้ตั้งค่า reduce motion ไว้
   (ช่วยทั้งเรื่อง accessibility และประหยัดแบตบน iPad) */
@media (prefers-reduced-motion: reduce){
  *,*::before,*::after{animation-duration:.001ms !important;animation-iteration-count:1 !important;transition-duration:.001ms !important;}
}

/* ═══ BACKGROUND ═══ */
.stApp{background:radial-gradient(1200px 760px at 8% -14%,rgba(var(--blue-rgb),.24),transparent 62%),radial-gradient(940px 680px at 94% 4%,rgba(var(--teal-rgb),.10),transparent 64%),radial-gradient(800px 600px at 50% 114%,rgba(var(--violet-rgb),.16),transparent 66%),linear-gradient(172deg,var(--bg-1) 0%,var(--bg-2) 44%,var(--bg-3) 100%);background-attachment:fixed;color:var(--ink);}
[data-testid="stAppViewContainer"]>.main{position:relative;z-index:1;}
[data-testid="stHeader"]{background:transparent;}
#MainMenu,footer{visibility:hidden;}
[data-testid="stToolbar"]{visibility:hidden;height:0;}
[data-testid="stDecoration"]{display:none;}
.block-container{padding:calc(1.2rem + env(safe-area-inset-top)) calc(1rem + env(safe-area-inset-right)) calc(4rem + env(safe-area-inset-bottom)) calc(1rem + env(safe-area-inset-left));max-width:900px;}

/* ═══ HERO ═══ */
.hero{position:relative;overflow:hidden;border-radius:24px;padding:1.75rem 1.4rem 1.4rem;margin:0 0 1.35rem;background:linear-gradient(158deg,rgba(22,42,90,.52),rgba(6,12,30,.44));border:1px solid var(--glass-border);backdrop-filter:var(--blur-strong);-webkit-backdrop-filter:var(--blur-strong);box-shadow:0 24px 64px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.075);}
.hero-inner{position:relative;z-index:2;display:flex;flex-direction:column;align-items:center;gap:.95rem;}
.hero-logo-wrap{position:relative;overflow:hidden;width:100%;display:flex;justify-content:center;padding:.15rem 0;}
.hero-logo{width:min(76%,300px);height:auto;display:block;filter:drop-shadow(0 5px 22px rgba(var(--blue-rgb),.34));animation:float 7s ease-in-out infinite;}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
.wordmark{display:flex;align-items:baseline;gap:.12em;font-size:2.5rem;font-weight:800;letter-spacing:-1px;line-height:1;}
.wordmark .a{color:#fff;}
.wordmark .b{background:linear-gradient(110deg,var(--blue-soft),var(--gold));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.hero-meta{display:flex;align-items:center;justify-content:center;gap:.65rem;flex-wrap:wrap;}
.hero-pill{display:inline-flex;align-items:center;gap:.45rem;padding:.33rem .72rem;border-radius:99px;background:rgba(var(--teal-rgb),.08);border:1px solid rgba(var(--teal-rgb),.24);color:#8ff0e0;font-size:.6rem;font-weight:700;letter-spacing:1.5px;}
.hero-pill i{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--teal);box-shadow:0 0 8px rgba(var(--teal-rgb),.9);}
.hero-tag{font-size:.6rem;font-weight:600;letter-spacing:2.1px;color:var(--ink-dim2);text-transform:uppercase;}

/* ═══ PRISMATIC GLASS CARDS (IPAD OPTIMIZED) ═══
   หมายเหตุ: เดิม border ไล่สี animate ตลอดเวลาทุกการ์ด ถ้าฟอร์มมีคำถาม
   เยอะๆ จะกลายเป็นหลายสิบ animation วิ่งพร้อมกัน ทำให้ scroll กระตุก/เครื่องร้อน
   ตอนนี้ border นิ่งโดย default (ยังคงลาย prismatic ไว้) แล้วค่อยไล่สีตอนแตะเท่านั้น */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background:
        linear-gradient(155deg, rgba(16,28,60,.75), rgba(6,12,30,.65)) padding-box,
        linear-gradient(120deg, rgba(var(--blue-soft-rgb),.35), rgba(var(--teal-rgb),.55), rgba(var(--gold-rgb),.55), rgba(var(--violet-rgb),.55), rgba(var(--blue-soft-rgb),.35)) border-box;
    border: 1.5px solid transparent;
    border-radius: 20px;
    padding: 1.4rem;
    backdrop-filter: var(--blur-soft);
    -webkit-backdrop-filter: var(--blur-soft);
    box-shadow: 0 16px 44px rgba(0,0,0,.5);
    transition: transform .2s cubic-bezier(.2,.8,.2,1), box-shadow .3s;
}
/* Tap-to-Flare for iPad: ไล่สี border เฉพาะตอนแตะ/กดค้าง ประหยัด GPU มาก */
div[data-testid="stVerticalBlockBorderWrapper"]:active {
    transform: scale(0.99);
    background-size: 200% 200%;
    background:
        linear-gradient(155deg, rgba(16,28,60,.85), rgba(6,12,30,.80)) padding-box,
        linear-gradient(120deg, rgba(var(--blue-soft-rgb),.9), var(--teal), var(--gold), var(--violet), rgba(var(--blue-soft-rgb),.9)) border-box;
    animation: gradientBorder 1.1s linear infinite;
}
@keyframes gradientBorder {
    0% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}

.glass-header{display:flex;align-items:center;gap:.55rem;font-size:.72rem;font-weight:700;letter-spacing:1.5px;color:var(--blue);margin-bottom:1.05rem;text-transform:uppercase;}
.glass-header::before{content:"";flex:0 0 auto;width:5px;height:5px;border-radius:50%;background:var(--blue);box-shadow:0 0 9px rgba(var(--blue-rgb),.9);}
.q-title{font-size:1.04rem;font-weight:600;line-height:1.68;color:var(--ink);margin-bottom:.8rem;}

/* ═══ TERMINAL DECRYPTION (LOADING STATE) ═══
   หน้าจอ st.status() ถูกแปลงร่างเป็น terminal ปลอมทั้งกรอบ:
   - ::before วาดแถบหัว terminal (จุดไฟ 3 ดวง + ชื่อไฟล์ปลอม)
   - ::after วาดเส้นสแกนเรืองแสงไล่จากใต้แถบหัวลงล่างวนซ้ำ
   - ข้อความ status ทุกบรรทัดเปลี่ยนเป็น monospace เรืองแสงมี "> " นำหน้า
   - progress bar กลายเป็นบล็อกข้อมูลเรืองแสงแทนเส้นเรียบ
   แก้บั๊กจากรอบก่อน: st.status() ของ Streamlit จริงๆ render ด้วย
   data-testid="stExpander" (มันสร้างจากคอมโพเนนต์ expander ข้างใน) ส่วน
   testid="stStatusWidget" ที่ใช้ผิดไปคือแถบ "กำลังรันสคริปต์" มุมขวาบน
   ของแอป Streamlit เอง คนละตัวกันเลย เลยไม่มีอะไรเปลี่ยนสักจุด — ด้านล่าง
   นี้แก้เป็น stExpander แล้ว แต่ถ้าแอปมี st.expander() จุดอื่นด้วย มันจะ
   โดนสไตล์ terminal นี้ไปด้วย บอกได้ถ้าอยากให้แยกสไตล์เฉพาะจุดนี้จุดเดียว */
[data-testid="stExpander"] {
    background: linear-gradient(160deg, #05080f 0%, #071019 100%) !important;
    border: 1px solid rgba(var(--teal-rgb),.35) !important;
    border-radius: 14px !important;
    position: relative;
    overflow: hidden;
    padding-top: 2.5rem !important;
    box-shadow: 0 0 0 1px rgba(var(--teal-rgb),.08), 0 0 34px rgba(var(--teal-rgb),.18), 0 20px 50px rgba(0,0,0,.55);
    animation: termFlicker 5s infinite;
}
[data-testid="stExpander"]::before {
    content: "◉ ◉ ◉   ezexam_core.sys — decrypting";
    position: absolute;
    top: 0; left: 0; right: 0; height: 2rem;
    display: flex;
    align-items: center;
    padding: 0 .9rem;
    font-family: var(--mono);
    font-size: .58rem;
    letter-spacing: .12em;
    color: var(--ink-dim);
    background: rgba(255,255,255,.025);
    border-bottom: 1px solid rgba(var(--teal-rgb),.18);
    z-index: 2;
}
[data-testid="stExpander"]::after {
    content: "";
    position: absolute;
    left: 0; right: 0;
    height: 2px;
    top: 2.5rem;
    background: linear-gradient(90deg, transparent, rgba(var(--teal-rgb),.95), transparent);
    box-shadow: 0 0 14px 2px rgba(var(--teal-rgb),.85);
    animation: scanline 2.6s linear infinite;
    z-index: 1;
    pointer-events: none;
}
@keyframes scanline {
    0%   { top: 2.5rem; opacity: 0; }
    6%   { opacity: 1; }
    94%  { opacity: 1; }
    100% { top: 100%; opacity: 0; }
}
@keyframes termFlicker {
    0%, 96%, 100% { filter: brightness(1); }
    96.5% { filter: brightness(1.18); }
    97%   { filter: brightness(.88); }
    97.5% { filter: brightness(1.08); }
}
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p,
[data-testid="stExpander"] label p,
[data-testid="stExpander"] summary p {
    font-family: var(--mono) !important;
    font-size: .82rem;
    letter-spacing: .01em;
    color: rgba(var(--teal-rgb),.94);
    text-shadow: 0 0 8px rgba(var(--teal-rgb),.35);
    margin: .18rem 0 !important;
    position: relative;
    z-index: 1;
}
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p::before {
    content: "> ";
    color: var(--gold);
    font-weight: 700;
    text-shadow: 0 0 8px rgba(var(--gold-rgb),.5);
}
[data-testid="stExpander"] svg {
    color: var(--teal) !important;
    filter: drop-shadow(0 0 6px rgba(var(--teal-rgb),.85));
}
.stProgress > div > div > div > div {
    background:
        repeating-linear-gradient(90deg, rgba(5,8,15,.92) 0 3px, transparent 3px 9px),
        linear-gradient(90deg, rgba(var(--teal-rgb),.9) 0%, var(--gold) 70%, #ffffff 100%) !important;
    border-radius: 3px;
    height: 8px;
    box-shadow: 0 0 14px rgba(var(--teal-rgb),.7), 0 0 26px rgba(var(--gold-rgb),.5);
    position: relative;
    overflow: visible !important;
}
.stProgress > div > div > div > div::after {
    content: "";
    position: absolute;
    right: -6px;
    top: -3px;
    width: 14px;
    height: 14px;
    background: #ffffff;
    border-radius: 50%;
    box-shadow: 0 0 15px 4px rgba(var(--gold-rgb),.9), 0 0 25px 6px rgba(255,255,255,.8);
    animation: laserPulse .35s ease-in-out infinite alternate;
}
@keyframes laserPulse {
    0% { transform: scale(.7); opacity: .8; }
    100% { transform: scale(1.4); opacity: 1; }
}

/* ═══ BUTTONS ═══ */
div.stButton>button{width:100%;border-radius:13px;padding:.88rem 1.2rem;font-weight:700;font-size:.96rem;letter-spacing:1px;color:#04101e;border:none;background:linear-gradient(120deg,var(--blue-soft) 0%,#b8d6ff 44%,var(--gold) 100%);box-shadow:0 12px 30px rgba(var(--blue-rgb),.26);transition:transform .2s,box-shadow .3s,filter .3s;}
div.stButton>button:active{transform:translateY(2px) scale(.98); filter:brightness(1.15);}
div.stButton>button:focus-visible{outline:2px solid var(--blue-soft);outline-offset:2px;}

/* ═══ INPUTS ═══ */
.stTextInput input,.stTextArea textarea,.stSelectbox div[data-baseweb="select"]>div{background:rgba(7,14,34,.66);border:1px solid var(--glass-border);border-radius:12px;color:var(--ink);transition:border-color .25s,box-shadow .25s,background .25s;}
.stTextInput input:focus,.stTextArea textarea:focus{border-color:var(--blue);background:rgba(9,18,44,.86);box-shadow:0 0 0 3px rgba(var(--blue-rgb),.15);}
.stTextInput label p,.stSelectbox label p,.stTextArea label p{color:var(--ink-dim);font-size:.68rem;font-weight:700;letter-spacing:1.1px;text-transform:uppercase;}
.stTextInput input:disabled{-webkit-appearance:none;appearance:none;background-color:rgba(7,14,34,.8)!important;color:var(--ink)!important;-webkit-text-fill-color:var(--ink)!important;opacity:1!important;border:1px solid rgba(140,175,255,.17)!important;}

/* ═══ CONFIDENCE & REASONING ═══ */
.confidence-track{width:100%;height:6px;background:rgba(255,255,255,.055);border-radius:99px;overflow:hidden;margin:.4rem 0 .25rem;}
.confidence-fill{height:100%;border-radius:99px;animation:grow 1.1s cubic-bezier(.2,.8,.2,1) both;box-shadow:0 0 10px currentColor;}
@keyframes grow{from{width:0}}
.confidence-label{font-size:.72rem;color:var(--ink-dim);margin-bottom:.6rem;}
.reasoning-text{color:#c2d0ee;font-size:.85rem;line-height:1.65;background:rgba(var(--blue-rgb),.085);padding:11px 15px;border-radius:11px;border-left:3px solid var(--blue);margin-bottom:12px;}

/* ═══ OTHERS ═══ */
[data-testid="stMetric"]{background:rgba(var(--blue-rgb),.06);border:1px solid var(--glass-border);border-radius:12px;padding:.6rem;}
.section-title{position:relative;padding-left:14px;font-size:1.28rem;font-weight:700;color:var(--ink);margin:2rem 0 1rem;}
.section-title::before{content:"";position:absolute;left:0;top:.2em;bottom:.2em;width:4px;border-radius:99px;background:linear-gradient(180deg,var(--blue),var(--gold));box-shadow:0 0 11px rgba(var(--blue-rgb),.5);}
.stRadio label span{color:var(--ink);}
.stMultiSelect [data-baseweb="tag"]{background:rgba(var(--blue-rgb),.2)!important;border-color:rgba(var(--blue-rgb),.4)!important;color:var(--ink)!important;}

@media (max-width:640px){
.block-container{padding-top:calc(.8rem + env(safe-area-inset-top));padding-left:calc(.65rem + env(safe-area-inset-left));padding-right:calc(.65rem + env(safe-area-inset-right));padding-bottom:calc(3rem + env(safe-area-inset-bottom));}
.hero{padding:1.35rem .95rem 1.15rem;border-radius:20px;}
.wordmark{font-size:1.95rem;}
div[data-testid="stVerticalBlockBorderWrapper"]{padding:1.05rem;border-radius:16px;backdrop-filter:none;-webkit-backdrop-filter:none;}
}
</style>"""

def inject_css() -> None:
    _raw(CSS)

def render_header(title: str = "EZEXAM",
                  subtitle: str = "AUTO FORM SYSTEM",
                  status: str = "SYSTEM ONLINE") -> None:
    uri = _logo_uri()
    if uri:
        mark = ('<div class="hero-logo-wrap">'
                f'<img src="{uri}" class="hero-logo" alt="{title}">'
                '</div>')
    else:
        mark = ('<div class="wordmark">'
                '<span class="a">EZ</span><span class="b">EXAM</span></div>')
    _raw(
        '<div class="hero"><div class="hero-inner">'
        + mark +
        '<div class="hero-meta">'
        f'<span class="hero-pill"><i></i>{status}</span>'
        f'<span class="hero-tag">{subtitle}</span>'
        '</div></div></div>'
    )
