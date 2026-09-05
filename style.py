import base64
from pathlib import Path
import streamlit as st


@st.cache_data
def _logo_b64() -> str:
    """อ่านไฟล์ logo.png ถ้ามี แปลงเป็น base64 ถ้าไม่มีคืนค่าว่าง"""
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
  --navy-900:#050a18;
  --navy-800:#0a1228;
  --navy-700:#101c3d;
  --ice:#7fb3ff;
  --aqua:#5fe3d0;
  --gold:#e8c98a;
  --text:#eaf0ff;
  --muted:#8fa3c8;
  --line:rgba(140,175,255,.16);
  --glass:rgba(18,32,64,.55);
}

*{font-family:'Sora','Noto Sans Thai',sans-serif;}

.stApp{
  background:
    radial-gradient(1100px 700px at 12% -10%, rgba(58,102,255,.28), transparent 60%),
    radial-gradient(900px 650px at 88% 8%, rgba(95,227,208,.16), transparent 62%),
    radial-gradient(800px 600px at 50% 110%, rgba(122,92,255,.20), transparent 65%),
    linear-gradient(170deg,var(--navy-900) 0%,var(--navy-800) 48%,#060c1c 100%);
  background-attachment:fixed;
  color:var(--text);
}

/* ===== ออโรร่าเคลื่อนไหวด้านหลัง ===== */
.stApp::before{
  content:"";position:fixed;inset:-20%;z-index:0;pointer-events:none;
  background:
    radial-gradient(38% 30% at 25% 30%, rgba(70,120,255,.30), transparent 70%),
    radial-gradient(34% 28% at 75% 62%, rgba(95,227,208,.18), transparent 70%),
    radial-gradient(30% 26% at 55% 15%, rgba(150,100,255,.22), transparent 70%);
  filter:blur(60px);
  animation:aurora 26s ease-in-out infinite alternate;
}
@keyframes aurora{
  0%{transform:translate3d(0,0,0) scale(1);opacity:.85}
  50%{transform:translate3d(-3%,3%,0) scale(1.12);opacity:1}
  100%{transform:translate3d(3%,-2%,0) scale(1.05);opacity:.9}
}
[data-testid="stAppViewContainer"]>.main{position:relative;z-index:1;}

#MainMenu,footer,header{visibility:hidden;}
.block-container{padding:1.6rem 1.1rem 4rem;max-width:940px;}

/* ===== HEADER ===== */
.hero{
  text-align:center;padding:2.2rem 1.2rem;margin-bottom:1.6rem;
  background:linear-gradient(145deg,rgba(30,52,102,.55),rgba(10,18,40,.35));
  border:1px solid var(--line);border-radius:28px;
  backdrop-filter:blur(22px) saturate(160%);
  -webkit-backdrop-filter:blur(22px) saturate(160%);
  box-shadow:0 20px 60px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.10);
  animation:rise .8s cubic-bezier(.2,.8,.2,1) both;
}
.hero-logo{
  width:96px;height:96px;object-fit:contain;margin-bottom:1rem;
  filter:drop-shadow(0 0 22px rgba(127,179,255,.55));
  animation:float 5s ease-in-out infinite;
}
.hero-mark{
  width:88px;height:88px;margin:0 auto 1rem;border-radius:26px;
  display:flex;align-items:center;justify-content:center;font-size:2.4rem;
  background:linear-gradient(135deg,rgba(127,179,255,.28),rgba(95,227,208,.16));
  border:1px solid rgba(127,179,255,.35);
  box-shadow:0 0 34px rgba(127,179,255,.30);
  animation:float 5s ease-in-out infinite;
}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-9px)}}

.hero h1{
  font-size:2.5rem;font-weight:800;letter-spacing:-.5px;margin:0 0 .5rem;
  background:linear-gradient(100deg,#ffffff 10%,var(--ice) 45%,var(--gold) 90%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-clip:text;
}
.hero p{color:var(--muted);font-size:1rem;font-weight:300;margin:0;}
.hero-line{
  width:110px;height:2px;margin:1.1rem auto 0;border-radius:2px;
  background:linear-gradient(90deg,transparent,var(--gold),transparent);
}

/* ===== การ์ดกระจก ===== */
.glass{
  background:var(--glass);border:1px solid var(--line);border-radius:22px;
  padding:1.4rem;margin-bottom:1.1rem;
  backdrop-filter:blur(18px) saturate(150%);
  -webkit-backdrop-filter:blur(18px) saturate(150%);
  box-shadow:0 14px 44px rgba(0,0,0,.42), inset 0 1px 0 rgba(255,255,255,.08);
  transition:transform .35s cubic-bezier(.2,.8,.2,1), box-shadow .35s, border-color .35s;
  animation:rise .6s ease both;
}
.glass:hover{
  transform:translateY(-4px);border-color:rgba(127,179,255,.38);
  box-shadow:0 22px 60px rgba(0,0,0,.55),0 0 26px rgba(127,179,255,.14);
}
@keyframes rise{from{opacity:0;transform:translateY(22px)}to{opacity:1;transform:none}}

.q-num{
  display:inline-block;padding:.28rem .8rem;border-radius:999px;
  font-size:.74rem;font-weight:700;letter-spacing:.6px;margin-bottom:.7rem;
  background:linear-gradient(135deg,rgba(127,179,255,.22),rgba(95,227,208,.14));
  border:1px solid rgba(127,179,255,.3);color:var(--ice);
}
.q-text{font-size:1.06rem;font-weight:600;line-height:1.65;margin-bottom:.5rem;}

/* ===== แถบความมั่นใจ ===== */
.conf-wrap{height:6px;border-radius:99px;background:rgba(255,255,255,.07);overflow:hidden;margin-top:.7rem;}
.conf-bar{height:100%;border-radius:99px;box-shadow:0 0 14px currentColor;animation:grow 1.1s cubic-bezier(.2,.8,.2,1) both;}
.c-high{background:linear-gradient(90deg,#3ad2a8,#5fe3d0);color:#5fe3d0;}
.c-mid{background:linear-gradient(90deg,#e8c98a,#f3d9a8);color:#e8c98a;}
.c-low{background:linear-gradient(90deg,#ff7a8a,#ffa3ad);color:#ff7a8a;}
@keyframes grow{from{width:0}}

/* ===== ปุ่ม ===== */
.stButton>button{
  width:100%;border-radius:16px;padding:.85rem 1.2rem;
  font-weight:700;font-size:1rem;letter-spacing:.3px;
  color:#061024;border:none;
  background:linear-gradient(135deg,var(--ice),#a9cdff 45%,var(--gold));
  box-shadow:0 10px 30px rgba(127,179,255,.30);
  transition:transform .2s, box-shadow .3s, filter .3s;
}
.stButton>button:hover{transform:translateY(-2px);filter:brightness(1.07);box-shadow:0 16px 40px rgba(127,179,255,.45);}
.stButton>button:active{transform:translateY(1px) scale(.99);}

/* ===== ช่องกรอก ===== */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
.stSelectbox div[data-baseweb="select"]>div{
  background:rgba(10,20,44,.62)!important;
  border:1px solid var(--line)!important;border-radius:14px!important;
  color:var(--text)!important;backdrop-filter:blur(10px);
  transition:border-color .25s, box-shadow .25s;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus{
  border-color:var(--ice)!important;
  box-shadow:0 0 0 3px rgba(127,179,255,.18)!important;
}
label,.stMarkdown p{color:var(--text);}

/* ===== กล่องคะแนน ===== */
.score{
  text-align:center;padding:2.4rem 1.2rem;border-radius:28px;
  background:linear-gradient(145deg,rgba(232,201,138,.16),rgba(127,179,255,.10));
  border:1px solid rgba(232,201,138,.34);
  backdrop-filter:blur(22px);
  box-shadow:0 20px 60px rgba(0,0,0,.5),0 0 46px rgba(232,201,138,.14);
  animation:pop .7s cubic-bezier(.2,1.2,.3,1) both;
}
.score-val{
  font-size:3.6rem;font-weight:800;line-height:1;
  background:linear-gradient(120deg,var(--gold),#fff,var(--ice));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
.score-lb{color:var(--muted);font-size:.9rem;letter-spacing:2px;text-transform:uppercase;margin-top:.6rem;}
@keyframes pop{from{opacity:0;transform:scale(.9)}to{opacity:1;transform:none}}

.stProgress>div>div>div>div{background:linear-gradient(90deg,var(--ice),var(--aqua))!important;}
[data-testid="stExpander"]{
  background:rgba(14,26,54,.5);border:1px solid var(--line)!important;
  border-radius:16px!important;backdrop-filter:blur(12px);
}

/* ===== มือถือ ===== */
@media (max-width:640px){
  .block-container{padding:1rem .75rem 3rem;}
  .hero{padding:1.6rem .9rem;border-radius:22px;}
  .hero h1{font-size:1.8rem;}
  .hero p{font-size:.88rem;}
  .hero-logo,.hero-mark{width:70px;height:70px;}
  .glass{padding:1.05rem;border-radius:18px;}
  .q-text{font-size:.99rem;}
  .score-val{font-size:2.7rem;}
  .glass:hover{transform:none;}
}
@media (prefers-reduced-motion:reduce){
  *{animation:none!important;transition:none!important;}
}
</style>
""", unsafe_allow_html=True)


def render_header(title: str = "AI Auto Form", subtitle: str = "ระบบกรอกฟอร์มอัจฉริยะด้วย Gemini") -> None:
    b64 = _logo_b64()
    mark = (f'<img src="data:image/png;base64,{b64}" class="hero-logo">'
            if b64 else '<div class="hero-mark">◆</div>')
    st.markdown(
        f'<div class="hero">{mark}<h1>{title}</h1><p>{subtitle}</p>'
        f'<div class="hero-line"></div></div>',
        unsafe_allow_html=True,
    )
