"""
style.py — EZEXAM UI (Prismatic Glass & Blueprint Sketching Edition)
====================================================================
- อัปเกรดดีไซน์ขอบกระจกสีรุ้ง (Prismatic Glass) วิ่งอัตโนมัติ
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

@st.cache_data(show_spinner=False)
def _logo_uri() -> str:
    p = _find_logo()
    if p is None:
        return ""
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

def _raw(html_code: str) -> None:
    try:
        st.html(html_code)
    except Exception:
        st.markdown(html_code, unsafe_allow_html=True)

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700;800&family=Noto+Sans+Thai:wght@300;400;500;600;700&display=swap');
html,body,p,h1,h2,h3,h4,h5,h6,label,input,textarea,li,button,span,div{font-family:'Sora','Noto Sans Thai',sans-serif;}

/* ═══ BACKGROUND ═══ */
.stApp{background:radial-gradient(1200px 760px at 8% -14%,rgba(44,84,230,.24),transparent 62%),radial-gradient(940px 680px at 94% 4%,rgba(95,227,208,.10),transparent 64%),radial-gradient(800px 600px at 50% 114%,rgba(108,80,242,.16),transparent 66%),linear-gradient(172deg,#03060f 0%,#070d22 44%,#04081a 100%);background-attachment:fixed;color:#e7edfb;}
[data-testid="stAppViewContainer"]>.main{position:relative;z-index:1;}
[data-testid="stHeader"]{background:transparent;}
#MainMenu,footer{visibility:hidden;}
[data-testid="stToolbar"]{visibility:hidden;height:0;}
[data-testid="stDecoration"]{display:none;}
.block-container{padding:1.2rem 1rem 4rem;max-width:900px;}

/* ═══ HERO ═══ */
.hero{position:relative;overflow:hidden;border-radius:24px;padding:1.75rem 1.4rem 1.4rem;margin:0 0 1.35rem;background:linear-gradient(158deg,rgba(22,42,90,.52),rgba(6,12,30,.44));border:1px solid rgba(140,175,255,.12);backdrop-filter:blur(24px) saturate(150%);-webkit-backdrop-filter:blur(24px) saturate(150%);box-shadow:0 24px 64px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.075);}
.hero-inner{position:relative;z-index:2;display:flex;flex-direction:column;align-items:center;gap:.95rem;}
.hero-logo-wrap{position:relative;overflow:hidden;width:100%;display:flex;justify-content:center;padding:.15rem 0;}
.hero-logo{width:min(76%,300px);height:auto;display:block;filter:drop-shadow(0 5px 22px rgba(120,170,255,.34));animation:float 7s ease-in-out infinite;}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
.wordmark{display:flex;align-items:baseline;gap:.12em;font-size:2.5rem;font-weight:800;letter-spacing:-1px;line-height:1;}
.wordmark .a{color:#fff;}
.wordmark .b{background:linear-gradient(110deg,#8fbcff,#e8c98a);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.hero-meta{display:flex;align-items:center;justify-content:center;gap:.65rem;flex-wrap:wrap;}
.hero-pill{display:inline-flex;align-items:center;gap:.45rem;padding:.33rem .72rem;border-radius:99px;background:rgba(95,227,208,.08);border:1px solid rgba(95,227,208,.24);color:#8ff0e0;font-size:.6rem;font-weight:700;letter-spacing:1.5px;}
.hero-tag{font-size:.6rem;font-weight:600;letter-spacing:2.1px;color:#7c8db3;text-transform:uppercase;}

/* ═══ PRISMATIC GLASS CARDS (IPAD OPTIMIZED) ═══ */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: 
        linear-gradient(155deg, rgba(16,28,60,.75), rgba(6,12,30,.65)) padding-box,
        linear-gradient(120deg, rgba(127,179,255,0.25), rgba(95,227,208,0.5), rgba(232,201,138,0.5), rgba(132,90,255,0.5), rgba(127,179,255,0.25)) border-box;
    border: 1.5px solid transparent;
    border-radius: 20px;
    padding: 1.4rem;
    backdrop-filter: blur(24px) saturate(150%);
    -webkit-backdrop-filter: blur(24px) saturate(150%);
    background-size: 200% 200%;
    animation: gradientBorder 6s linear infinite;
    box-shadow: 0 16px 44px rgba(0,0,0,.5);
    transition: transform 0.2s cubic-bezier(.2,.8,.2,1);
}
@keyframes gradientBorder {
    0% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}
/* Tap-to-Flare for iPad */
div[data-testid="stVerticalBlockBorderWrapper"]:active {
    transform: scale(0.99);
    background: 
        linear-gradient(155deg, rgba(16,28,60,.85), rgba(6,12,30,.80)) padding-box,
        linear-gradient(120deg, rgba(127,179,255,0.9), rgba(95,227,208,1), rgba(232,201,138,1), rgba(132,90,255,1), rgba(127,179,255,0.9)) border-box;
    animation: gradientBorder 1s linear infinite;
}

.glass-header{display:flex;align-items:center;gap:.55rem;font-size:.72rem;font-weight:700;letter-spacing:1.5px;color:#7fb3ff;margin-bottom:1.05rem;text-transform:uppercase;}
.glass-header::before{content:"";flex:0 0 auto;width:5px;height:5px;border-radius:50%;background:#7fb3ff;box-shadow:0 0 9px rgba(127,179,255,.9);}
.q-title{font-size:1.04rem;font-weight:600;line-height:1.68;color:#e7edfb;margin-bottom:.8rem;}

/* ═══ BLUEPRINT SKETCHING (LOADING STATE) ═══ */
[data-testid="stStatusWidget"] {
    background: linear-gradient(135deg, rgba(6, 12, 30, 0.95), rgba(10, 20, 44, 0.98)) !important;
    border: 1px solid rgba(127, 179, 255, 0.4) !important;
    border-radius: 16px !important;
    position: relative;
    overflow: hidden;
    box-shadow: 0 0 30px rgba(127, 179, 255, 0.15);
}
/* Grid Overlay */
[data-testid="stStatusWidget"]::before {
    content: "";
    position: absolute;
    inset: 0;
    background-image: 
        linear-gradient(rgba(127, 179, 255, 0.15) 1px, transparent 1px),
        linear-gradient(90deg, rgba(127, 179, 255, 0.15) 1px, transparent 1px);
    background-size: 24px 24px;
    z-index: 0;
    pointer-events: none;
    animation: gridPan 15s linear infinite;
}
@keyframes gridPan {
    0% { background-position: 0 0; }
    100% { background-position: 48px 48px; }
}
/* Ensure Text is above grid */
[data-testid="stStatusWidget"] * {
    position: relative;
    z-index: 1;
}
/* Sketching Laser (Progress Bar) */
.stProgress > div > div > div > div {
    background: linear-gradient(90deg, transparent 0%, rgba(95,227,208,0.7) 40%, rgba(232,201,138,1) 85%, #ffffff 100%) !important;
    border-radius: 99px;
    height: 4px;
    box-shadow: 0 0 12px rgba(95,227,208,0.8), 0 0 24px rgba(232,201,138,0.6);
    position: relative;
    overflow: visible !important;
}
/* The Laser Head */
.stProgress > div > div > div > div::after {
    content: "";
    position: absolute;
    right: -6px;
    top: -5px;
    width: 14px;
    height: 14px;
    background: #ffffff;
    border-radius: 50%;
    box-shadow: 0 0 15px 4px rgba(232,201,138,0.9), 0 0 25px 6px rgba(255,255,255,0.8);
    animation: laserPulse 0.35s ease-in-out infinite alternate;
}
@keyframes laserPulse {
    0% { transform: scale(0.7); opacity: 0.8; }
    100% { transform: scale(1.4); opacity: 1; }
}

/* ═══ BUTTONS ═══ */
div.stButton>button{width:100%;border-radius:13px;padding:.88rem 1.2rem;font-weight:700;font-size:.96rem;letter-spacing:1px;color:#04101e;border:none;background:linear-gradient(120deg,#8fbcff 0%,#b8d6ff 44%,#e8c98a 100%);box-shadow:0 12px 30px rgba(127,179,255,.26);transition:transform .2s,box-shadow .3s,filter .3s;}
div.stButton>button:active{transform:translateY(2px) scale(.98); filter:brightness(1.15);}

/* ═══ INPUTS ═══ */
.stTextInput input,.stTextArea textarea,.stSelectbox div[data-baseweb="select"]>div{background:rgba(7,14,34,.66);border:1px solid rgba(140,175,255,.14);border-radius:12px;color:#e7edfb;transition:border-color .25s,box-shadow .25s,background .25s;}
.stTextInput input:focus,.stTextArea textarea:focus{border-color:#7fb3ff;background:rgba(9,18,44,.86);box-shadow:0 0 0 3px rgba(127,179,255,.15);}
.stTextInput label p,.stSelectbox label p,.stTextArea label p{color:#8698bd;font-size:.68rem;font-weight:700;letter-spacing:1.1px;text-transform:uppercase;}
.stTextInput input:disabled{-webkit-appearance:none;appearance:none;background-color:rgba(7,14,34,.8)!important;color:#e7edfb!important;-webkit-text-fill-color:#e7edfb!important;opacity:1!important;border:1px solid rgba(140,175,255,.17)!important;}

/* ═══ CONFIDENCE & REASONING ═══ */
.confidence-track{width:100%;height:6px;background:rgba(255,255,255,.055);border-radius:99px;overflow:hidden;margin:.4rem 0 .25rem;}
.confidence-fill{height:100%;border-radius:99px;animation:grow 1.1s cubic-bezier(.2,.8,.2,1) both;box-shadow:0 0 10px currentColor;}
@keyframes grow{from{width:0}}
.confidence-label{font-size:.72rem;color:#8698bd;margin-bottom:.6rem;}
.reasoning-text{color:#c2d0ee;font-size:.85rem;line-height:1.65;background:rgba(127,179,255,.085);padding:11px 15px;border-radius:11px;border-left:3px solid #7fb3ff;margin-bottom:12px;}

/* ═══ OTHERS ═══ */
[data-testid="stMetric"]{background:rgba(127,179,255,.06);border:1px solid rgba(140,175,255,.12);border-radius:12px;padding:.6rem;}
[data-testid="stExpander"]{background:rgba(10,20,44,.5);border:1px solid rgba(140,175,255,.13);border-radius:13px;}
.section-title{position:relative;padding-left:14px;font-size:1.28rem;font-weight:700;color:#e7edfb;margin:2rem 0 1rem;}
.section-title::before{content:"";position:absolute;left:0;top:.2em;bottom:.2em;width:4px;border-radius:99px;background:linear-gradient(180deg,#7fb3ff,#e8c98a);box-shadow:0 0 11px rgba(127,179,255,.5);}
.stRadio label span{color:#e7edfb;}
.stMultiSelect [data-baseweb="tag"]{background:rgba(127,179,255,.2)!important;border-color:rgba(127,179,255,.4)!important;color:#e7edfb!important;}

@media (max-width:640px){
.block-container{padding:.8rem .65rem 3rem;}
.hero{padding:1.35rem .95rem 1.15rem;border-radius:20px;}
.wordmark{font-size:1.95rem;}
div[data-testid="stVerticalBlockBorderWrapper"]{padding:1.05rem;border-radius:16px;}
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
