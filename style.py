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

# Product UI V2 overrides the original experimental skin without touching the
# application widgets. Keeping this as a second layer also makes rollback easy.
PRODUCT_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Noto+Sans+Thai:wght@400;500;600;700&display=swap');

:root{
  --p-bg:#070a12;
  --p-panel:#0d1220;
  --p-panel-2:#111827;
  --p-panel-3:#151d2e;
  --p-line:rgba(148,163,184,.16);
  --p-line-strong:rgba(148,163,184,.27);
  --p-text:#f4f7fb;
  --p-muted:#94a3b8;
  --p-blue:#74a7ff;
  --p-blue-strong:#4f8df7;
  --p-teal:#49d6bc;
  --p-amber:#f5bf5b;
  --p-red:#fb7185;
  --p-radius:18px;
  --p-shadow:0 24px 70px rgba(0,0,0,.34);
}

html,body,p,h1,h2,h3,h4,h5,h6,label,input,textarea,button,span,div{
  font-family:'Manrope','Noto Sans Thai',system-ui,sans-serif;
}
.stApp{
  color:var(--p-text);
  background:
    radial-gradient(900px 520px at 8% -10%,rgba(79,141,247,.14),transparent 64%),
    radial-gradient(700px 480px at 100% 10%,rgba(73,214,188,.08),transparent 65%),
    var(--p-bg);
  background-attachment:fixed;
}
[data-testid="stHeader"]{background:transparent;height:0;}
[data-testid="stToolbar"],#MainMenu,footer{display:none!important;}
.block-container{max-width:1180px;padding:1rem 1.25rem 5rem;}

/* Top application shell */
.product-topbar{
  display:flex;align-items:center;justify-content:space-between;gap:1rem;
  min-height:68px;padding:12px 16px;margin:0 0 26px;
  border:1px solid var(--p-line);border-radius:16px;
  background:rgba(13,18,32,.76);backdrop-filter:blur(18px);
  box-shadow:0 10px 34px rgba(0,0,0,.24);
}
.product-brand{display:flex;align-items:center;gap:12px;min-width:0;}
.product-logo{display:block;max-width:132px;max-height:34px;object-fit:contain;}
.product-wordmark{font-weight:800;font-size:1.08rem;letter-spacing:-.02em;color:var(--p-text);}
.product-wordmark span{color:var(--p-blue);}
.product-sub{font-size:.72rem;color:var(--p-muted);margin-top:2px;}
.product-status{display:flex;align-items:center;gap:8px;padding:7px 11px;border:1px solid rgba(73,214,188,.2);border-radius:999px;background:rgba(73,214,188,.07);font-size:.72rem;font-weight:700;color:#8be8d7;white-space:nowrap;}
.product-status i{width:7px;height:7px;border-radius:50%;background:var(--p-teal);box-shadow:0 0 0 4px rgba(73,214,188,.1);}

/* Landing */
.landing-hero{position:relative;overflow:hidden;padding:clamp(2rem,5vw,4.5rem);border:1px solid var(--p-line);border-radius:26px;background:linear-gradient(145deg,rgba(17,24,39,.96),rgba(9,14,26,.98));box-shadow:var(--p-shadow);}
.landing-hero::after{content:"";position:absolute;width:460px;height:460px;border-radius:50%;right:-160px;top:-220px;background:radial-gradient(circle,rgba(79,141,247,.24),transparent 68%);pointer-events:none;}
.eyebrow{display:inline-flex;align-items:center;gap:8px;padding:7px 11px;border:1px solid rgba(116,167,255,.22);border-radius:999px;background:rgba(116,167,255,.07);font-size:.7rem;font-weight:800;letter-spacing:.08em;color:#a9c8ff;text-transform:uppercase;}
.landing-title{max-width:790px;margin:24px 0 14px;font-size:clamp(2.1rem,5.6vw,4.2rem);line-height:1.08;letter-spacing:-.055em;font-weight:800;color:var(--p-text);}
.landing-title em{font-style:normal;background:linear-gradient(100deg,#92b9ff,#65dfc9);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.landing-copy{max-width:690px;color:#aab7ca;font-size:clamp(.95rem,1.8vw,1.08rem);line-height:1.8;margin:0 0 18px;}
.trust-row{display:flex;gap:10px;flex-wrap:wrap;margin-top:20px;}
.trust-chip{display:inline-flex;align-items:center;gap:7px;color:#b7c2d3;font-size:.76rem;padding:8px 10px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid var(--p-line);}
.feature-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:18px 0 8px;}
.feature-card{padding:19px;border:1px solid var(--p-line);border-radius:16px;background:rgba(13,18,32,.72);}
.feature-icon{display:grid;place-items:center;width:36px;height:36px;border-radius:11px;background:rgba(116,167,255,.1);border:1px solid rgba(116,167,255,.18);font-size:1rem;margin-bottom:15px;}
.feature-card h3{margin:0 0 7px;font-size:.93rem;color:var(--p-text);}
.feature-card p{margin:0;color:var(--p-muted);font-size:.78rem;line-height:1.65;}

/* Workspace hierarchy */
.workspace-head{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin:6px 2px 18px;}
.workspace-kicker{font-size:.69rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--p-blue);}
.workspace-title{font-size:clamp(1.55rem,3vw,2.2rem);font-weight:800;letter-spacing:-.035em;margin:5px 0 4px;color:var(--p-text);}
.workspace-copy{font-size:.85rem;color:var(--p-muted);margin:0;}
.workflow{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:0 0 22px;padding:8px;border:1px solid var(--p-line);border-radius:15px;background:rgba(13,18,32,.72);}
.workflow-step{display:flex;align-items:center;gap:10px;min-width:0;padding:11px 12px;border-radius:10px;color:#738198;}
.workflow-step.active{background:rgba(116,167,255,.1);color:#c9dcff;}
.workflow-step.done{color:#8be8d7;}
.workflow-index{display:grid;place-items:center;width:26px;height:26px;flex:0 0 auto;border-radius:8px;border:1px solid currentColor;font-size:.68rem;font-weight:800;}
.workflow-label{font-size:.76rem;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.section-title{font-size:1.35rem;letter-spacing:-.025em;margin:28px 0 14px;padding:0;color:var(--p-text);}
.section-title::before{display:none;}
.glass-header{font-size:.69rem;letter-spacing:.08em;margin-bottom:16px;color:#9ebfff;}
.glass-header::before{width:7px;height:7px;background:var(--p-blue);box-shadow:none;}

/* Cards and widgets */
div[data-testid="stVerticalBlockBorderWrapper"]{
  padding:1.25rem!important;border:1px solid var(--p-line)!important;border-radius:var(--p-radius)!important;
  background:linear-gradient(145deg,rgba(17,24,39,.86),rgba(12,17,30,.86))!important;
  box-shadow:0 12px 40px rgba(0,0,0,.2)!important;backdrop-filter:blur(12px)!important;
  animation:none!important;transition:border-color .2s ease,transform .2s ease!important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover{border-color:var(--p-line-strong)!important;}
[data-testid="stExpander"]{padding-top:0!important;border:1px solid var(--p-line)!important;border-radius:14px!important;background:rgba(12,17,30,.86)!important;box-shadow:none!important;animation:none!important;filter:none!important;overflow:hidden!important;}
[data-testid="stExpander"]::before,[data-testid="stExpander"]::after{display:none!important;content:none!important;animation:none!important;}
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p,[data-testid="stExpander"] label p,[data-testid="stExpander"] summary p{font-family:'Manrope','Noto Sans Thai',sans-serif!important;font-size:.82rem!important;color:#cbd5e1!important;text-shadow:none!important;letter-spacing:0!important;}
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p::before{display:none!important;content:none!important;}
[data-testid="stMetric"]{padding:16px;border:1px solid var(--p-line);border-radius:14px;background:rgba(116,167,255,.045);}
[data-testid="stMetricLabel"]{color:var(--p-muted);}
[data-testid="stMetricValue"]{font-weight:750;letter-spacing:-.04em;}
.q-title{font-size:1.03rem;font-weight:700;line-height:1.65;color:var(--p-text);}

.stTextInput input,.stTextArea textarea,.stSelectbox div[data-baseweb="select"]>div{
  min-height:46px;background:rgba(7,10,18,.72)!important;border:1px solid var(--p-line)!important;border-radius:11px!important;color:var(--p-text)!important;box-shadow:none!important;
}
.stTextInput input:focus,.stTextArea textarea:focus{border-color:var(--p-blue)!important;box-shadow:0 0 0 3px rgba(116,167,255,.12)!important;}
.stTextInput label p,.stSelectbox label p,.stTextArea label p{font-size:.72rem;color:#a7b3c6;text-transform:none;letter-spacing:0;}
div.stButton>button{min-height:44px;padding:.68rem 1rem;border:1px solid rgba(116,167,255,.3);border-radius:11px;background:linear-gradient(180deg,#6ea2fb,#4f86e8);color:white;font-size:.82rem;font-weight:750;letter-spacing:0;box-shadow:0 8px 22px rgba(79,141,247,.18);transition:transform .15s ease,filter .15s ease,border-color .15s ease;}
div.stButton>button:hover{filter:brightness(1.08);border-color:#9cc2ff;}
div.stButton>button:active{transform:translateY(1px) scale(.99);}
div.stButton>button[kind="secondary"]{background:rgba(255,255,255,.045);border-color:var(--p-line);box-shadow:none;color:#d5deeb;}
[data-testid="stAlert"]{border-radius:12px;border-width:1px;}
.stProgress>div>div>div>div{height:7px;border-radius:999px;background:linear-gradient(90deg,var(--p-blue-strong),var(--p-teal))!important;box-shadow:none;}
.stProgress>div>div>div>div::after{display:none;}
.confidence-track{height:7px;background:rgba(148,163,184,.12);box-shadow:none;}
.confidence-fill{box-shadow:none;}
.reasoning-text{background:rgba(116,167,255,.055);border:1px solid rgba(116,167,255,.13);border-left:3px solid var(--p-blue);color:#c7d2e3;}

/* Status and empty/result surfaces */
.empty-state{text-align:center;padding:42px 20px;border:1px dashed var(--p-line-strong);border-radius:18px;background:rgba(13,18,32,.45);}
.empty-icon{display:grid;place-items:center;width:52px;height:52px;margin:0 auto 16px;border-radius:15px;background:rgba(116,167,255,.09);font-size:1.35rem;}
.empty-state h3{font-size:1.05rem;margin:0 0 7px;}
.empty-state p{max-width:480px;margin:0 auto;color:var(--p-muted);font-size:.82rem;line-height:1.65;}
.result-hero{text-align:center;padding:38px 22px;border:1px solid rgba(73,214,188,.2);border-radius:22px;background:linear-gradient(145deg,rgba(73,214,188,.08),rgba(13,18,32,.9));}
.result-icon{display:grid;place-items:center;width:58px;height:58px;margin:0 auto 16px;border-radius:18px;background:rgba(73,214,188,.12);border:1px solid rgba(73,214,188,.22);font-size:1.5rem;}
.result-hero h2{margin:0 0 8px;font-size:1.65rem;}
.result-hero p{margin:0;color:var(--p-muted);font-size:.86rem;}

@media(max-width:760px){
  .block-container{padding:.65rem .72rem 4rem;}
  .product-topbar{min-height:58px;padding:9px 11px;margin-bottom:15px;border-radius:13px;}
  .product-logo{max-width:104px;max-height:28px;}.product-sub{display:none;}.product-status{font-size:.62rem;padding:6px 8px;}
  .landing-hero{padding:2rem 1.15rem;border-radius:20px;}.landing-title{letter-spacing:-.04em;}
  .feature-grid{grid-template-columns:1fr;gap:9px}.feature-card{padding:15px;}
  .workflow{grid-template-columns:1fr;padding:6px}.workflow-step{padding:8px 10px}.workflow-step:not(.active){display:none;}
  .workspace-head{align-items:flex-start;flex-direction:column;}
  div[data-testid="stVerticalBlockBorderWrapper"]{padding:1rem!important;border-radius:15px!important;backdrop-filter:none!important;}
  [data-testid="stMetric"]{padding:12px;}
}
</style>"""

def inject_css() -> None:
    _raw(CSS + PRODUCT_CSS)

def render_header(title: str = "EZEXAM",
                  subtitle: str = "AUTO FORM SYSTEM",
                  status: str = "SYSTEM ONLINE") -> None:
    uri = _logo_uri()
    if uri:
        mark = f'<img src="{uri}" class="product-logo" alt="{title}">'
        identity = f'<div class="product-sub">{subtitle}</div>'
    else:
        mark = '<div class="product-wordmark">EZ<span>EXAM</span></div>'
        identity = f'<div><div class="product-wordmark">{title}</div><div class="product-sub">{subtitle}</div></div>'
    _raw(
        '<div class="product-topbar">'
        '<div class="product-brand">' + mark +
        identity + '</div>'
        f'<div class="product-status"><i></i>{status}</div></div>'
    )
