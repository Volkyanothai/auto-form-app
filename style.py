import base64
from pathlib import Path
import streamlit as st


@st.cache_data
def _logo_b64() -> str:
    for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp"):
        p = Path(name)
        if p.exists():
            return base64.b64encode(p.read_bytes()).decode()
    return ""


def inject_css() -> None:
    st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@300;400;600;700;800&family=Noto+Sans+Thai:wght@300;400;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --navy-900:#050a18; --navy-800:#0a1228;
  --ice:#7fb3ff; --aqua:#5fe3d0; --gold:#e8c98a;
  --text:#eaf0ff; --muted:#93a7cc;
  --line:rgba(140,175,255,.16);
}

html,body,p,h1,h2,h3,h4,h5,h6,label,input,textarea,li,button,span,div{
  font-family:'Sora','Noto Sans Thai',sans-serif;
}
.material-symbols-rounded{font-family:'Material Symbols Rounded'!important;}

.stApp{
  background:
    radial-gradient(1100px 700px at 12% -10%, rgba(58,102,255,.30), transparent 60%),
    radial-gradient(900px 650px at 88% 8%, rgba(95,227,208,.15), transparent 62%),
    radial-gradient(800px 600px at 50% 110%, rgba(122,92,255,.20), transparent 65%),
    linear-gradient(170deg,var(--navy-900) 0%,var(--navy-800) 48%,#060c1c 100%);
  background-attachment:fixed; color:var(--text);
}
.stApp::before{
  content:"";position:fixed;inset:-20%;z-index:0;pointer-events:none;
  background:
    radial-gradient(38% 30% at 25% 30%, rgba(70,120,255,.30), transparent 70%),
    radial-gradient(34% 28% at 75% 62%, rgba(95,227,208,.17), transparent 70%),
    radial-gradient(30% 26% at 55% 15%, rgba(150,100,255,.22), transparent 70%);
  filter:blur(60px); animation:aurora 26s ease-in-out infinite alternate;
}
@keyframes aurora{
  0%{transform:translate3d(0,0,0) scale(1);opacity:.85}
  50%{transform:translate3d(-3%,3%,0) scale(1.12);opacity:1}
  100%{transform:translate3d(3%,-2%,0) scale(1.05);opacity:.9}
}
[data-testid="stAppViewContainer"]>.main{position:relative;z-index:1;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding:1.6rem 1.1rem 4rem;max-width:920px;}

/* ===== HERO ===== */
.hero{
  text-align:center;padding:2.3rem 1.2rem;margin-bottom:1.5rem;
  background:linear-gradient(145deg,rgba(30,52,102,.55),rgba(10,18,40,.32));
  border:1px solid var(--line);border-radius:28px;
  backdrop-filter:blur(22px) saturate(160%);
  -webkit-backdrop-filter:blur(22px) saturate(160%);
  box-shadow:0 20px 60px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.10);
  animation:rise .8s cubic-bezier(.2,.8,.2,1) both;
}
.hero-logo{width:96px;height:96px;object-fit:contain;margin-bottom:1rem;
  filter:drop-shadow(0 0 22px rgba(127,179,255,.55));animation:float 5s ease-in-out infinite;}
.hero-mark{width:88px;height:88px;margin:0 auto 1rem;border-radius:26px;
  display:flex;align-items:center;justify-content:center;font-size:2.3rem;
  background:linear-gradient(135deg,rgba(127,179,255,.28),rgba(95,227,208,.16));
  border:1px solid rgba(127,179,255,.35);box-shadow:0 0 34px rgba(127,179,255,.30);
  animation:float 5s ease-in-out infinite;}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-9px)}}
.hero h1{font-size:2.7rem;font-weight:800;letter-spacing:4px;margin:0 0 .45rem;
  background:linear-gradient(100deg,#fff 10%,var(--ice) 45%,var(--gold) 92%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.hero p{color:var(--muted);font-size:.82rem;letter-spacing:3px;font-weight:600;margin:0;}
.hero-line{width:110px;height:2px;margin:1.1rem auto 0;border-radius:2px;
  background:linear-gradient(90deg,transparent,var(--gold),transparent);}

/* ===== การ์ดกระจก (st.container(border=True)) ===== */
div[data-testid="stVerticalBlockBorderWrapper"]{
  background:rgba(18,32,64,.55)!important;
  border:1px solid var(--line)!important;border-radius:22px!important;
  padding:1.4rem!important;
  backdrop-filter:blur(18px) saturate(150%)!important;
  -webkit-backdrop-filter:blur(18px) saturate(150%)!important;
  box-shadow:0 14px 44px rgba(0,0,0,.42), inset 0 1px 0 rgba(255,255,255,.08)!important;
  transition:transform .35s cubic-bezier(.2,.8,.2,1),box-shadow .35s,border-color .35s;
  animation:rise .6s ease both;
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover{
  transform:translateY(-4px);border-color:rgba(127,179,255,.38)!important;
  box-shadow:0 22px 60px rgba(0,0,0,.55),0 0 26px rgba(127,179,255,.14)!important;
}
@keyframes rise{from{opacity:0;transform:translateY(22px)}to{opacity:1;transform:none}}

.glass-header{
  font-size:.78rem;font-weight:700;letter-spacing:1.4px;color:var(--ice);
  margin-bottom:1rem;display:flex;align-items:center;gap:9px;text-transform:uppercase;
}
.q-title{font-size:1.06rem;font-weight:600;line-height:1.65;color:var(--text);margin-bottom:.8rem;}

/* ===== ปุ่ม ===== */
div.stButton>button{
  width:100%;border-radius:16px;padding:.85rem 1.2rem;
  font-weight:700;font-size:1rem;letter-spacing:1px;
  color:#061024!important;border:none!important;
  background:linear-gradient(135deg,var(--ice),#a9cdff 45%,var(--gold))!important;
  box-shadow:0 10px 30px rgba(127,179,255,.30)!important;
  transition:transform .2s,box-shadow .3s,filter .3s;
}
div.stButton>button:hover{transform:translateY(-2px);filter:brightness(1.07);
  box-shadow:0 16px 40px rgba(127,179,255,.45)!important;}
div.stButton>button:active{transform:translateY(1px) scale(.99);}

/* ===== ช่องกรอก ===== */
.stTextInput input,.stTextArea textarea,
.stSelectbox div[data-baseweb="select"]>div{
  background:rgba(10,20,44,.62)!important;
  border:1px solid var(--line)!important;border-radius:14px!important;
  color:var(--text)!important;
}
.stTextInput input:focus,.stTextArea textarea:focus,
.stSelectbox div[data-baseweb="select"]:focus-within{
  border-color:var(--ice)!important;box-shadow:0 0 0 3px rgba(127,179,255,.18)!important;
}
.stTextInput label p,.stSelectbox label p,.stTextArea label p{
  color:var(--muted)!important;font-size:.72rem!important;
  font-weight:700!important;letter-spacing:1px;text-transform:uppercase;
}
.stTextInput input:disabled{
  color:var(--text)!important;-webkit-text-fill-color:var(--text)!important;opacity:1!important;
}

/* ===== ความมั่นใจ ===== */
.confidence-track{width:100%;height:6px;background:rgba(255,255,255,.07);
  border-radius:99px;overflow:hidden;margin:.6rem 0 .5rem;}
.confidence-fill{height:100%;border-radius:99px;animation:grow 1.1s cubic-bezier(.2,.8,.2,1) both;}
@keyframes grow{from{width:0}}
.reasoning-text{
  color:#c7d5f0;font-size:.85rem;line-height:1.6;
  background:rgba(127,179,255,.10);padding:11px 15px;border-radius:12px;
  border-left:3px solid var(--ice);margin-bottom:12px;
}

/* ===== คะแนน ===== */
.score-box{
  text-align:center;padding:2rem 1.2rem;border-radius:26px;margin:1.2rem 0;
  background:linear-gradient(145deg,rgba(232,201,138,.16),rgba(127,179,255,.10));
  border:1px solid rgba(232,201,138,.34);backdrop-filter:blur(20px);
  box-shadow:0 20px 60px rgba(0,0,0,.5),0 0 46px rgba(232,201,138,.14);
  animation:pop .7s cubic-bezier(.2,1.2,.3,1) both;
}
.score-val{font-size:3.4rem;font-weight:800;line-height:1;
  background:linear-gradient(120deg,var(--gold),#fff,var(--ice));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.score-lb{color:var(--muted);font-size:.78rem;letter-spacing:2.5px;
  text-transform:uppercase;margin-top:.55rem;}
@keyframes pop{from{opacity:0;transform:scale(.9)}to{opacity:1;transform:none}}

.score-link{
  display:block;text-align:center;padding:13px;border-radius:14px;
  background:rgba(127,179,255,.10);border:1px solid rgba(127,179,255,.35);
  color:var(--ice)!important;text-decoration:none;font-weight:700;letter-spacing:.8px;
  margin-top:10px;transition:all .3s ease;
}
.score-link:hover{background:rgba(127,179,255,.20);transform:translateY(-2px);}

.section-title{font-size:1.35rem;font-weight:700;color:var(--text);
  margin:2rem 0 1rem;letter-spacing:.5px;}
[data-testid="stStatusWidget"]{
  background:rgba(14,26,54,.75)!important;border:1px solid var(--line)!important;
  border-radius:16px!important;backdrop-filter:blur(12px)!important;
}
[data-testid="stStatusWidget"] summary{color:#dbe6ff!important;font-weight:600!important;}
[data-testid="stExpander"]{background:rgba(14,26,54,.5);
  border:1px solid var(--line)!important;border-radius:16px!important;}
.stProgress>div>div>div>div{background:linear-gradient(90deg,var(--ice),var(--aqua))!important;}
hr{border-color:var(--line)!important;}

/* ===== มือถือ ===== */
@media (max-width:640px){
  .block-container{padding:1rem .7rem 3rem;}
  .hero{padding:1.7rem .9rem;border-radius:22px;}
  .hero h1{font-size:1.9rem;letter-spacing:2.5px;}
  .hero p{font-size:.7rem;letter-spacing:2px;}
  .hero-logo,.hero-mark{width:70px;height:70px;font-size:1.8rem;}
  div[data-testid="stVerticalBlockBorderWrapper"]{padding:1.05rem!important;border-radius:18px!important;}
  div[data-testid="stVerticalBlockBorderWrapper"]:hover{transform:none;}
  .q-title{font-size:.99rem;}
  .score-val{font-size:2.6rem;}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;}}
</style>
""", unsafe_allow_html=True)


def render_header(title: str = "EZEXAM", subtitle: str = "AUTO FORM SYSTEM") -> None:
    b64 = _logo_b64()
    mark = (f'<img src="data:image/png;base64,{b64}" class="hero-logo">'
            if b64 else '<div class="hero-mark">⚡</div>')
    st.markdown(
        f'<div class="hero">{mark}<h1>{title}</h1><p>{subtitle}</p>'
        f'<div class="hero-line"></div></div>',
        unsafe_allow_html=True,
    )
