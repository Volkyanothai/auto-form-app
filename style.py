import base64
from pathlib import Path
import streamlit as st

# โลโก้สีเข้ม -> แปลงเป็นขาวล้วนอัตโนมัติ (ถ้าโลโก้เป็นสีอ่อน/ขาวอยู่แล้ว เปลี่ยนเป็น False)
INVERT_LOGO = True


@st.cache_data
def _logo_b64() -> str:
    for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp"):
        p = Path(name)
        if p.exists():
            return base64.b64encode(p.read_bytes()).decode()
    return ""


def _raw(html_code: str) -> None:
    try:
        st.html(html_code)
    except Exception:
        st.markdown(html_code, unsafe_allow_html=True)


CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;600;700;800&family=Noto+Sans+Thai:wght@300;400;600;700&display=swap');
html,body,p,h1,h2,h3,h4,h5,h6,label,input,textarea,li,button,span,div{font-family:'Sora','Noto Sans Thai',sans-serif;}

.stApp{background:radial-gradient(1200px 780px at 10% -12%,rgba(48,88,235,.26),transparent 62%),radial-gradient(950px 700px at 92% 6%,rgba(95,227,208,.11),transparent 64%),radial-gradient(820px 620px at 50% 112%,rgba(112,84,245,.17),transparent 66%),linear-gradient(170deg,#04081a 0%,#08102a 46%,#050a1c 100%);background-attachment:fixed;color:#e8eeff;}
.stApp::before{content:"";position:fixed;inset:-25%;z-index:0;pointer-events:none;background:radial-gradient(36% 28% at 22% 28%,rgba(64,110,255,.24),transparent 70%),radial-gradient(32% 26% at 78% 64%,rgba(95,227,208,.12),transparent 70%),radial-gradient(28% 24% at 56% 12%,rgba(140,95,255,.17),transparent 70%);filter:blur(80px);animation:aurora 30s ease-in-out infinite alternate;}
@keyframes aurora{0%{transform:translate3d(0,0,0) scale(1);opacity:.75}50%{transform:translate3d(-3%,3%,0) scale(1.1);opacity:.95}100%{transform:translate3d(3%,-2%,0) scale(1.04);opacity:.82}}

[data-testid="stAppViewContainer"]>.main{position:relative;z-index:1;}
[data-testid="stHeader"]{background:transparent;}
#MainMenu{visibility:hidden;}
footer{visibility:hidden;}
[data-testid="stToolbar"]{visibility:hidden;height:0;}
[data-testid="stDecoration"]{display:none;}

.block-container{padding:1.5rem 1.1rem 4rem;max-width:880px;}

/* ══ HERO ══ */
.hero{position:relative;overflow:hidden;text-align:center;padding:2.3rem 1.5rem 1.8rem;margin-bottom:1.5rem;border-radius:26px;background:linear-gradient(160deg,rgba(26,46,94,.58),rgba(7,13,32,.40));border:1px solid rgba(140,175,255,.14);backdrop-filter:blur(26px) saturate(150%);-webkit-backdrop-filter:blur(26px) saturate(150%);box-shadow:0 26px 72px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.09);animation:rise .8s cubic-bezier(.2,.8,.2,1) both;}
.hero::before{content:"";position:absolute;inset:0;pointer-events:none;background-image:linear-gradient(rgba(140,175,255,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(140,175,255,.055) 1px,transparent 1px);background-size:34px 34px;-webkit-mask-image:radial-gradient(circle at 50% 44%,#000 0%,transparent 74%);mask-image:radial-gradient(circle at 50% 44%,#000 0%,transparent 74%);}
.hero::after{content:"";position:absolute;top:0;left:16%;right:16%;height:1px;background:linear-gradient(90deg,transparent,rgba(127,179,255,.9),rgba(232,201,138,.75),transparent);}

.hero-logo-wrap{position:relative;z-index:2;overflow:hidden;display:flex;align-items:center;justify-content:center;margin:0 auto;padding:.2rem 0;}
.hero-logo-wrap::after{content:"";position:absolute;top:-30%;bottom:-30%;left:-50%;width:34%;transform:skewX(-18deg);background:linear-gradient(100deg,transparent,rgba(255,255,255,.14),transparent);animation:sheen 8s ease-in-out infinite;pointer-events:none;}
@keyframes sheen{0%,74%{left:-50%}100%{left:118%}}
.hero-logo{width:min(80%,330px);max-height:118px;height:auto;object-fit:contain;display:block;animation:float 6s ease-in-out infinite;}
.logo-knockout{filter:brightness(0) invert(1) drop-shadow(0 3px 18px rgba(127,179,255,.40));opacity:.97;}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}

.hero-mark{width:118px;height:118px;margin:0 auto;border-radius:28px;display:flex;align-items:center;justify-content:center;font-size:3rem;background:linear-gradient(135deg,rgba(127,179,255,.24),rgba(95,227,208,.12));border:1px solid rgba(127,179,255,.32);box-shadow:0 0 30px rgba(127,179,255,.24);animation:float 6s ease-in-out infinite;position:relative;z-index:2;}

.hero h1,.hero p{display:none;}
.hero-line{position:relative;z-index:2;width:62px;height:3px;margin:1.4rem auto 0;border-radius:99px;background:linear-gradient(90deg,#7fb3ff,#e8c98a);box-shadow:0 0 16px rgba(232,201,138,.45);}

/* ══ CARDS ══ */
div[data-testid="stVerticalBlockBorderWrapper"]{background:linear-gradient(155deg,rgba(20,36,72,.62),rgba(10,18,42,.46));border:1px solid rgba(140,175,255,.13);border-radius:20px;padding:1.5rem;backdrop-filter:blur(18px) saturate(145%);-webkit-backdrop-filter:blur(18px) saturate(145%);box-shadow:0 16px 46px rgba(0,0,0,.42),inset 0 1px 0 rgba(255,255,255,.07);transition:transform .35s cubic-bezier(.2,.8,.2,1),box-shadow .35s,border-color .35s;animation:rise .6s ease both;}
div[data-testid="stVerticalBlockBorderWrapper"]:hover{transform:translateY(-3px);border-color:rgba(127,179,255,.34);box-shadow:0 24px 62px rgba(0,0,0,.55),0 0 24px rgba(127,179,255,.12);}
@keyframes rise{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:none}}

.glass-header{display:flex;align-items:center;gap:.6rem;font-size:.74rem;font-weight:700;letter-spacing:1.6px;color:#7fb3ff;margin-bottom:1.1rem;text-transform:uppercase;}
.glass-header::before{content:"";flex:0 0 auto;width:6px;height:6px;border-radius:50%;background:#7fb3ff;box-shadow:0 0 10px rgba(127,179,255,.9);}
.glass-header::after{content:"";flex:1 1 auto;height:1px;background:linear-gradient(90deg,rgba(127,179,255,.28),transparent);}

.q-title{font-size:1.05rem;font-weight:600;line-height:1.68;color:#e8eeff;margin-bottom:.85rem;}

/* ══ BUTTON ══ */
div.stButton>button{position:relative;overflow:hidden;width:100%;border-radius:14px;padding:.9rem 1.2rem;font-weight:700;font-size:.98rem;letter-spacing:1.1px;color:#05101f;border:none;background:linear-gradient(120deg,#8fbcff 0%,#b6d5ff 42%,#e8c98a 100%);box-shadow:0 12px 32px rgba(127,179,255,.28);transition:transform .2s,box-shadow .3s,filter .3s;}
div.stButton>button:hover{transform:translateY(-2px);filter:brightness(1.06) saturate(1.05);box-shadow:0 18px 44px rgba(127,179,255,.42);}
div.stButton>button:active{transform:translateY(1px) scale(.99);}

/* ══ INPUTS ══ */
.stTextInput input,.stTextArea textarea,.stSelectbox div[data-baseweb="select"]>div{background:rgba(8,16,38,.66);border:1px solid rgba(140,175,255,.15);border-radius:13px;color:#e8eeff;transition:border-color .25s,box-shadow .25s,background .25s;}
.stTextInput input:hover,.stTextArea textarea:hover{border-color:rgba(140,175,255,.30);}
.stTextInput input:focus,.stTextArea textarea:focus{border-color:#7fb3ff;background:rgba(10,20,46,.85);box-shadow:0 0 0 3px rgba(127,179,255,.16);}
.stTextInput label p,.stSelectbox label p,.stTextArea label p{color:#8fa3c9;font-size:.7rem;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;}
.stTextInput input:disabled{-webkit-appearance:none;appearance:none;background-color:rgba(8,16,38,.8) !important;color:#e8eeff !important;-webkit-text-fill-color:#e8eeff !important;opacity:1 !important;border:1px solid rgba(140,175,255,.18) !important;}

/* ══ RESULT ══ */
.confidence-track{width:100%;height:6px;background:rgba(255,255,255,.06);border-radius:99px;overflow:hidden;margin:.6rem 0 .5rem;}
.confidence-fill{height:100%;border-radius:99px;animation:grow 1.1s cubic-bezier(.2,.8,.2,1) both;}
@keyframes grow{from{width:0}}
.reasoning-text{color:#c4d2ef;font-size:.85rem;line-height:1.65;background:rgba(127,179,255,.09);padding:11px 15px;border-radius:11px;border-left:3px solid #7fb3ff;margin-bottom:12px;}

.score-box{position:relative;overflow:hidden;text-align:center;padding:2.1rem 1.2rem;border-radius:24px;margin:1.2rem 0;background:linear-gradient(150deg,rgba(232,201,138,.14),rgba(127,179,255,.09));border:1px solid rgba(232,201,138,.30);backdrop-filter:blur(20px);box-shadow:0 22px 62px rgba(0,0,0,.5),0 0 44px rgba(232,201,138,.12);animation:pop .7s cubic-bezier(.2,1.2,.3,1) both;}
.score-box::after{content:"";position:absolute;top:0;left:20%;right:20%;height:1px;background:linear-gradient(90deg,transparent,rgba(232,201,138,.8),transparent);}
.score-val{font-size:3.4rem;font-weight:800;line-height:1;background:linear-gradient(120deg,#e8c98a,#fff 48%,#7fb3ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.score-lb{color:#8fa3c9;font-size:.74rem;letter-spacing:2.6px;text-transform:uppercase;margin-top:.6rem;}
@keyframes pop{from{opacity:0;transform:scale(.9)}to{opacity:1;transform:none}}
.score-link{display:block;text-align:center;padding:13px;border-radius:13px;background:rgba(127,179,255,.09);border:1px solid rgba(127,179,255,.30);color:#9cc6ff;text-decoration:none;font-weight:700;letter-spacing:.8px;margin-top:10px;transition:all .3s ease;}
.score-link:hover{background:rgba(127,179,255,.18);border-color:rgba(127,179,255,.55);transform:translateY(-2px);}

.section-title{position:relative;padding-left:15px;font-size:1.3rem;font-weight:700;color:#e8eeff;margin:2rem 0 1rem;letter-spacing:.3px;}
.section-title::before{content:"";position:absolute;left:0;top:.2em;bottom:.2em;width:4px;border-radius:99px;background:linear-gradient(180deg,#7fb3ff,#e8c98a);box-shadow:0 0 12px rgba(127,179,255,.5);}

[data-testid="stStatusWidget"]{background:rgba(12,22,48,.78);border:1px solid rgba(140,175,255,.14);border-radius:14px;}
[data-testid="stExpander"]{background:rgba(12,22,48,.5);border:1px solid rgba(140,175,255,.14);border-radius:14px;}
.stProgress>div>div>div>div{background:linear-gradient(90deg,#7fb3ff,#5fe3d0);}
hr{border-color:rgba(140,175,255,.14);}

::-webkit-scrollbar{width:9px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:rgba(127,179,255,.22);border-radius:99px;}
::-webkit-scrollbar-thumb:hover{background:rgba(127,179,255,.38);}

@media (max-width:640px){
.block-container{padding:.9rem .7rem 3rem;}
.hero{padding:1.7rem 1rem 1.35rem;border-radius:22px;}
.hero::before{background-size:26px 26px;}
.hero-logo{width:min(86%,260px);max-height:88px;}
.hero-line{margin-top:1.1rem;width:52px;}
.hero-mark{width:92px;height:92px;font-size:2.4rem;border-radius:24px;}
div[data-testid="stVerticalBlockBorderWrapper"]{padding:1.1rem;border-radius:17px;}
div[data-testid="stVerticalBlockBorderWrapper"]:hover{transform:none;}
.q-title{font-size:.98rem;}
.score-val{font-size:2.7rem;}
.section-title{font-size:1.15rem;}
}
</style>"""


def inject_css() -> None:
    _raw(CSS)


def render_header(title: str = "EZEXAM", subtitle: str = "AUTO FORM SYSTEM") -> None:
    b64 = _logo_b64()
    if b64:
        cls = "hero-logo logo-knockout" if INVERT_LOGO else "hero-logo"
        mark = ('<div class="hero-logo-wrap">'
                '<img src="data:image/png;base64,' + b64 + '" class="' + cls + '">'
                '</div>')
    else:
        mark = '<div class="hero-mark">&#9889;</div>'
    _raw('<div class="hero">' + mark +
         '<h1>' + title + '</h1><p>' + subtitle + '</p>'
         '<div class="hero-line"></div></div>')
