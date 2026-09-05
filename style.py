"""
style.py — EZEXAM UI (drop-in replacement, ทับไฟล์เดิมได้เลย)
ต้องมี Pillow ใน requirements.txt:  pillow
"""
import base64
import io
from pathlib import Path

import streamlit as st

# ═══════════ ปรับได้ตรงนี้ ═══════════
LOGO_FILES  = ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp", "logo.svg")
LOGO_COLOR  = "auto"     # "auto" = ตรวจเอง | "white" = บังคับขาว | "original" = สีเดิม
STRIP_WHITE = True       # ลบพื้นหลังขาวทึบออกอัตโนมัติ
# ════════════════════════════════════


def _find_logo():
    for name in LOGO_FILES:
        p = Path(name)
        if p.exists():
            return p
    return None


def _strip_white_bg(img, tol=34):
    """ลบพื้นหลังขาวทึบ -> โปร่งใส (เช็คจาก 4 มุมก่อน ถ้าไม่ขาวจะไม่แตะ)"""
    w, h = img.size
    px = img.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    solid = [c for c in corners if c[3] > 8]
    if not solid:
        return img
    r0 = sum(c[0] for c in solid) // len(solid)
    g0 = sum(c[1] for c in solid) // len(solid)
    b0 = sum(c[2] for c in solid) // len(solid)
    if not (r0 > 224 and g0 > 224 and b0 > 224):
        return img
    out = img.copy()
    o = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            d = max(abs(r - r0), abs(g - g0), abs(b - b0))
            if d <= tol:
                o[x, y] = (r, g, b, 0)
            elif d <= tol * 2:
                o[x, y] = (r, g, b, int(a * (d - tol) / tol))
    return out


def _is_dark(img):
    data = [p for p in img.getdata() if p[3] > 40]
    if not data:
        return False
    lum = sum(0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2] for p in data) / len(data)
    return lum < 135


def _to_white(img):
    return img.point(lambda _: 255, mode=None) if False else \
        __import__("PIL.Image", fromlist=["Image"]).merge(
            "RGBA",
            (img.split()[0].point(lambda _: 255),
             img.split()[1].point(lambda _: 255),
             img.split()[2].point(lambda _: 255),
             img.split()[3]))


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
        box = img.getbbox()                 # ◄ หัวใจ: ตัดขอบว่างทิ้ง
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
.stApp::before{content:"";position:fixed;inset:-25%;z-index:0;pointer-events:none;background:radial-gradient(34% 27% at 20% 26%,rgba(58,104,255,.22),transparent 70%),radial-gradient(30% 24% at 80% 66%,rgba(95,227,208,.11),transparent 70%),radial-gradient(26% 22% at 58% 10%,rgba(132,90,255,.15),transparent 70%);filter:blur(84px);animation:aurora 32s ease-in-out infinite alternate;}
@keyframes aurora{0%{transform:translate3d(0,0,0) scale(1);opacity:.7}50%{transform:translate3d(-3%,3%,0) scale(1.1);opacity:.92}100%{transform:translate3d(3%,-2%,0) scale(1.04);opacity:.78}}
[data-testid="stAppViewContainer"]>.main{position:relative;z-index:1;}
[data-testid="stHeader"]{background:transparent;}
#MainMenu,footer{visibility:hidden;}
[data-testid="stToolbar"]{visibility:hidden;height:0;}
[data-testid="stDecoration"]{display:none;}
.block-container{padding:1.2rem 1rem 4rem;max-width:860px;}

/* ═══ HERO ═══ */
.hero{position:relative;overflow:hidden;border-radius:24px;padding:1.75rem 1.4rem 1.4rem;margin:0 0 1.35rem;background:linear-gradient(158deg,rgba(22,42,90,.52),rgba(6,12,30,.44));border:1px solid rgba(140,175,255,.12);backdrop-filter:blur(24px) saturate(150%);-webkit-backdrop-filter:blur(24px) saturate(150%);box-shadow:0 24px 64px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.075);animation:rise .7s cubic-bezier(.2,.8,.2,1) both;}
.hero::before{content:"";position:absolute;inset:0;pointer-events:none;background-image:linear-gradient(rgba(140,175,255,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(140,175,255,.05) 1px,transparent 1px);background-size:30px 30px;-webkit-mask-image:radial-gradient(ellipse 70% 65% at 50% 42%,#000 0%,transparent 78%);mask-image:radial-gradient(ellipse 70% 65% at 50% 42%,#000 0%,transparent 78%);}
.hero::after{content:"";position:absolute;top:0;left:18%;right:18%;height:1px;background:linear-gradient(90deg,transparent,rgba(127,179,255,.85),rgba(232,201,138,.7),transparent);}
.hero-aura{position:absolute;left:50%;top:-46%;width:118%;height:150%;transform:translateX(-50%);pointer-events:none;background:radial-gradient(48% 42% at 50% 50%,rgba(88,138,255,.20),transparent 72%);filter:blur(24px);}
.hero-inner{position:relative;z-index:2;display:flex;flex-direction:column;align-items:center;gap:.95rem;}

.hero-logo-wrap{position:relative;overflow:hidden;width:100%;display:flex;justify-content:center;padding:.15rem 0;}
.hero-logo-wrap::after{content:"";position:absolute;top:-40%;bottom:-40%;left:-45%;width:30%;transform:skewX(-18deg);background:linear-gradient(100deg,transparent,rgba(255,255,255,.16),transparent);animation:sheen 9s ease-in-out infinite;pointer-events:none;}
@keyframes sheen{0%,76%{left:-45%}100%{left:115%}}
.hero-logo{width:min(76%,300px);height:auto;display:block;filter:drop-shadow(0 5px 22px rgba(120,170,255,.34));animation:float 7s ease-in-out infinite;}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}

.wordmark{display:flex;align-items:baseline;gap:.12em;font-size:2.5rem;font-weight:800;letter-spacing:-1px;line-height:1;}
.wordmark .a{color:#fff;}
.wordmark .b{background:linear-gradient(110deg,#8fbcff,#e8c98a);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}

.hero-meta{display:flex;align-items:center;justify-content:center;gap:.65rem;flex-wrap:wrap;}
.hero-pill{display:inline-flex;align-items:center;gap:.45rem;padding:.33rem .72rem;border-radius:99px;background:rgba(95,227,208,.08);border:1px solid rgba(95,227,208,.24);color:#8ff0e0;font-size:.6rem;font-weight:700;letter-spacing:1.5px;}
.hero-pill i{width:6px;height:6px;border-radius:50%;background:#5fe3d0;box-shadow:0 0 9px #5fe3d0;animation:pulse 2.2s ease-in-out infinite;}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
.hero-sep{width:3px;height:3px;border-radius:50%;background:rgba(140,175,255,.35);}
.hero-tag{font-size:.6rem;font-weight:600;letter-spacing:2.1px;color:#7c8db3;text-transform:uppercase;}
.hero-line{width:54px;height:2px;border-radius:99px;background:linear-gradient(90deg,#7fb3ff,#e8c98a);box-shadow:0 0 14px rgba(232,201,138,.42);}

/* ═══ CARDS ═══ */
div[data-testid="stVerticalBlockBorderWrapper"]{background:linear-gradient(155deg,rgba(18,33,68,.6),rgba(8,15,38,.46));border:1px solid rgba(140,175,255,.12);border-radius:19px;padding:1.4rem;backdrop-filter:blur(18px) saturate(145%);-webkit-backdrop-filter:blur(18px) saturate(145%);box-shadow:0 16px 44px rgba(0,0,0,.4),inset 0 1px 0 rgba(255,255,255,.065);transition:transform .35s cubic-bezier(.2,.8,.2,1),box-shadow .35s,border-color .35s;animation:rise .6s ease both;}
div[data-testid="stVerticalBlockBorderWrapper"]:hover{transform:translateY(-3px);border-color:rgba(127,179,255,.32);box-shadow:0 24px 60px rgba(0,0,0,.55),0 0 22px rgba(127,179,255,.11);}
@keyframes rise{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}

.glass-header{display:flex;align-items:center;gap:.55rem;font-size:.72rem;font-weight:700;letter-spacing:1.5px;color:#7fb3ff;margin-bottom:1.05rem;text-transform:uppercase;}
.glass-header::before{content:"";flex:0 0 auto;width:5px;height:5px;border-radius:50%;background:#7fb3ff;box-shadow:0 0 9px rgba(127,179,255,.9);}
.glass-header::after{content:"";flex:1 1 auto;height:1px;background:linear-gradient(90deg,rgba(127,179,255,.26),transparent);}
.q-title{font-size:1.04rem;font-weight:600;line-height:1.68;color:#e7edfb;margin-bottom:.8rem;}

/* ═══ BUTTON ═══ */
div.stButton>button{width:100%;border-radius:13px;padding:.88rem 1.2rem;font-weight:700;font-size:.96rem;letter-spacing:1px;color:#04101e;border:none;background:linear-gradient(120deg,#8fbcff 0%,#b8d6ff 44%,#e8c98a 100%);box-shadow:0 12px 30px rgba(127,179,255,.26);transition:transform .2s,box-shadow .3s,filter .3s;}
div.stButton>button:hover{transform:translateY(-2px);filter:brightness(1.06);box-shadow:0 18px 42px rgba(127,179,255,.4);}
div.stButton>button:active{transform:translateY(1px) scale(.99);}

/* ═══ INPUTS ═══ */
.stTextInput input,.stTextArea textarea,.stSelectbox div[data-baseweb="select"]>div{background:rgba(7,14,34,.66);border:1px solid rgba(140,175,255,.14);border-radius:12px;color:#e7edfb;transition:border-color .25s,box-shadow .25s,background .25s;}
.stTextInput input:hover,.stTextArea textarea:hover{border-color:rgba(140,175,255,.28);}
.stTextInput input:focus,.stTextArea textarea:focus{border-color:#7fb3ff;background:rgba(9,18,44,.86);box-shadow:0 0 0 3px rgba(127,179,255,.15);}
.stTextInput label p,.stSelectbox label p,.stTextArea label p{color:#8698bd;font-size:.68rem;font-weight:700;letter-spacing:1.1px;text-transform:uppercase;}
.stTextInput input:disabled{-webkit-appearance:none;appearance:none;background-color:rgba(7,14,34,.8)!important;color:#e7edfb!important;-webkit-text-fill-color:#e7edfb!important;opacity:1!important;border:1px solid rgba(140,175,255,.17)!important;}

/* ═══ RESULT ═══ */
.confidence-track{width:100%;height:6px;background:rgba(255,255,255,.055);border-radius:99px;overflow:hidden;margin:.6rem 0 .5rem;}
.confidence-fill{height:100%;border-radius:99px;animation:grow 1.1s cubic-bezier(.2,.8,.2,1) both;}
@keyframes grow{from{width:0}}
.reasoning-text{color:#c2d0ee;font-size:.85rem;line-height:1.65;background:rgba(127,179,255,.085);padding:11px 15px;border-radius:11px;border-left:3px solid #7fb3ff;margin-bottom:12px;}
.score-box{position:relative;overflow:hidden;text-align:center;padding:2rem 1.2rem;border-radius:22px;margin:1.2rem 0;background:linear-gradient(150deg,rgba(232,201,138,.13),rgba(127,179,255,.08));border:1px solid rgba(232,201,138,.28);backdrop-filter:blur(20px);box-shadow:0 22px 58px rgba(0,0,0,.48),0 0 42px rgba(232,201,138,.11);animation:pop .7s cubic-bezier(.2,1.2,.3,1) both;}
.score-box::after{content:"";position:absolute;top:0;left:22%;right:22%;height:1px;background:linear-gradient(90deg,transparent,rgba(232,201,138,.8),transparent);}
.score-val{font-size:3.3rem;font-weight:800;line-height:1;background:linear-gradient(120deg,#e8c98a,#fff 48%,#7fb3ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.score-lb{color:#8698bd;font-size:.72rem;letter-spacing:2.5px;text-transform:uppercase;margin-top:.6rem;}
@keyframes pop{from{opacity:0;transform:scale(.9)}to{opacity:1;transform:none}}
.score-link{display:block;text-align:center;padding:13px;border-radius:12px;background:rgba(127,179,255,.085);border:1px solid rgba(127,179,255,.28);color:#9cc6ff;text-decoration:none;font-weight:700;letter-spacing:.8px;margin-top:10px;transition:all .3s ease;}
.score-link:hover{background:rgba(127,179,255,.17);border-color:rgba(127,179,255,.52);transform:translateY(-2px);}
.section-title{position:relative;padding-left:14px;font-size:1.28rem;font-weight:700;color:#e7edfb;margin:2rem 0 1rem;}
.section-title::before{content:"";position:absolute;left:0;top:.2em;bottom:.2em;width:4px;border-radius:99px;background:linear-gradient(180deg,#7fb3ff,#e8c98a);box-shadow:0 0 11px rgba(127,179,255,.5);}
[data-testid="stStatusWidget"]{background:rgba(10,20,44,.78);border:1px solid rgba(140,175,255,.13);border-radius:13px;}
[data-testid="stExpander"]{background:rgba(10,20,44,.5);border:1px solid rgba(140,175,255,.13);border-radius:13px;}
.stProgress>div>div>div>div{background:linear-gradient(90deg,#7fb3ff,#5fe3d0);}
hr{border-color:rgba(140,175,255,.13);}
::-webkit-scrollbar{width:9px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:rgba(127,179,255,.2);border-radius:99px;}
::-webkit-scrollbar-thumb:hover{background:rgba(127,179,255,.36);}

@media (max-width:640px){
.block-container{padding:.8rem .65rem 3rem;}
.hero{padding:1.35rem .95rem 1.15rem;border-radius:20px;}
.hero::before{background-size:24px 24px;}
.hero-inner{gap:.8rem;}
.hero-logo{width:min(84%,255px);}
.wordmark{font-size:1.95rem;}
.hero-tag,.hero-pill{font-size:.55rem;letter-spacing:1.3px;}
div[data-testid="stVerticalBlockBorderWrapper"]{padding:1.05rem;border-radius:16px;}
div[data-testid="stVerticalBlockBorderWrapper"]:hover{transform:none;}
.q-title{font-size:.97rem;}
.score-val{font-size:2.6rem;}
.section-title{font-size:1.14rem;}
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
        '<div class="hero"><div class="hero-aura"></div><div class="hero-inner">'
        + mark +
        '<div class="hero-meta">'
        f'<span class="hero-pill"><i></i>{status}</span>'
        '<span class="hero-sep"></span>'
        f'<span class="hero-tag">{subtitle}</span>'
        '</div>'
        '<div class="hero-line"></div>'
        '</div></div>'
    )
