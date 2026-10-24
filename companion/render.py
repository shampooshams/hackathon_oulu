"""Turn citations into hoverable fact chips and build the 'fact receipts' view."""
from __future__ import annotations

import html
import re

from companion.facts import FactStore

# Siniristi design tokens (Local SportsReel × Fan Companion). Light by default; dark = deep Finnish blue.
TOKENS = {
    "light": {
        "bg": "#f4f7fb", "surface": "#ffffff", "surface-2": "#eef2f7", "line": "#d8e1ec", "line-strong": "#8796a8",
        "text": "#0f1a2a", "muted": "#4f5d6e", "primary": "#003580", "on-primary": "#ffffff",
        "primary-tint": "#e6eef9", "primary-tint-line": "#b9cdea",
        "danger": "#c62828", "danger-tint": "#fdecec", "danger-line": "#f2b8b5",
        "warning": "#8a5a00", "warning-tint": "#fdf3dc", "warning-line": "#e8cf94",
        "label-ai": "#5b3fc4", "label-ai-tint": "#efebfb", "label-ai-line": "#cfc5f2",
        "label-demo": "#9a4a12", "label-demo-tint": "#fdf0e7", "label-demo-line": "#b85c1c",
        "team": "#fcd116", "team-tint": "rgba(252, 209, 22, 0.14)",
        "chart-top": "#003580", "chart-mid": "#6f9fe0", "chart-miss": "#c3cedb", "icon-ink": "#ffffff",
    },
    "dark": {
        "bg": "#002a66", "surface": "#0b3a7e", "surface-2": "#134489", "line": "#2a5596", "line-strong": "#6f8fbf",
        "text": "#ffffff", "muted": "#b8c7dd", "primary": "#ffffff", "on-primary": "#003580",
        "primary-tint": "rgba(140, 192, 255, 0.18)", "primary-tint-line": "rgba(140, 192, 255, 0.45)",
        "danger": "#ff9c9c", "danger-tint": "rgba(255, 156, 156, 0.12)", "danger-line": "rgba(255, 156, 156, 0.5)",
        "warning": "#ffd27a", "warning-tint": "rgba(255, 210, 122, 0.12)", "warning-line": "rgba(255, 210, 122, 0.5)",
        "label-ai": "#d4c9ff", "label-ai-tint": "rgba(212, 201, 255, 0.12)", "label-ai-line": "rgba(212, 201, 255, 0.45)",
        "label-demo": "#ffc29e", "label-demo-tint": "rgba(255, 194, 158, 0.12)", "label-demo-line": "#ffc29e",
        "team": "#fcd116", "team-tint": "rgba(252, 209, 22, 0.12)",
        "chart-top": "#ffffff", "chart-mid": "#8cc0ff", "chart-miss": "#2a5596", "icon-ink": "#002a66",
    },
}

COMPONENTS = """
h1,h2,h3,h4{font-weight:800 !important;letter-spacing:-.025em}
.brand{font-size:20px;line-height:1.2;letter-spacing:-.03em;font-weight:800;margin:.2em 0 1.2em}
.brand-sub{font-size:13px;letter-spacing:0;font-weight:500;color:var(--muted);margin-top:2px}
.dot{color:var(--primary)}
.welcome{position:relative;min-height:280px;border-radius:18px;overflow:hidden;margin:.3em 0 10px;
 background-size:cover;background-position:70% 22%;display:flex;align-items:flex-end}
.welcome::before{content:"";position:absolute;inset:0;
 background:linear-gradient(90deg,rgba(0,24,64,.88) 0%,rgba(0,24,64,.55) 38%,rgba(0,24,64,0) 62%)}
.welcome-text{position:relative;padding:24px 26px;max-width:min(440px,60%);color:#fff}
.welcome-title{font-size:clamp(22px,2.4vw,30px);font-weight:800;line-height:1.15;letter-spacing:-.02em}
.welcome-sub{font-size:15px;margin-top:6px;color:#dbe6f5}
.welcome-btn{display:inline-block;margin-top:14px;padding:10px 20px;border-radius:999px;background:#fff;
 color:#003580 !important;font-weight:800;font-size:15px;text-decoration:none !important;box-shadow:0 4px 14px rgba(0,0,0,.25)}
.welcome-btn:hover{background:#e8f0fb}
.welcome-label{position:absolute;right:10px;bottom:8px;font-size:11px;font-weight:600;color:#fff;
 background:rgba(0,0,0,.45);padding:2px 8px;border-radius:999px}
@media (max-width:560px){.welcome{min-height:300px;background-position:72% 30%}
 .welcome::before{background:linear-gradient(0deg,rgba(0,24,64,.9) 0%,rgba(0,24,64,.5) 45%,rgba(0,24,64,0) 70%)}
 .welcome-text{max-width:100%;padding:18px}}
.cap-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0 0 1.4em}
.cap{display:flex;gap:10px;align-items:flex-start;background:var(--surface);border-radius:14px;
 box-shadow:inset 0 0 0 1px var(--line);padding:14px;font-size:14px;line-height:1.4}
.premium{display:inline-block;margin-left:8px;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:700;
 letter-spacing:.04em;text-transform:uppercase;vertical-align:2px;background:var(--primary);color:var(--on-primary)}
.cap-icon{font-size:20px;line-height:1.2}
.cap-text{color:var(--muted);font-size:13px;margin-top:3px}
@media (max-width:900px){.cap-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:560px){.cap-grid{grid-template-columns:1fr}}
.kicker{font-size:12px;letter-spacing:.12em;color:var(--primary);font-weight:700;text-transform:uppercase;
 margin:.4em 0 .1em}
.hero{font-size:clamp(36px,4.5vw,48px);letter-spacing:-.03em;line-height:1.05;font-weight:800;margin:.1em 0 .45em}
.section-title{font-size:clamp(24px,3vw,30px);letter-spacing:-.02em;line-height:1.1;font-weight:800;margin:.15em 0 .3em}
.notice{display:flex;gap:12px;padding:12px 14px;border-radius:14px;font-size:14px;line-height:1.45;margin:0 0 1em}
.notice-label{font-weight:800;font-size:12px;letter-spacing:.12em;text-transform:uppercase;white-space:nowrap;padding-top:1px}
.notice-demo{background:var(--label-demo-tint);border:1px dashed var(--label-demo-line)}
.notice-demo .notice-label{color:var(--label-demo)}
/* stat cards */
.stat-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:.2em 0 1.2em}
.stat{background:var(--surface);border-radius:14px;box-shadow:inset 0 0 0 1px var(--line);padding:16px;
 display:flex;flex-direction:column;gap:4px;min-width:0;transition:background 150ms ease-out}
.stat:hover{background:var(--surface-2)}
.stat-label{font-size:13px;font-weight:500;color:var(--muted)}
.stat-value{font-size:clamp(28px,3.2vw,40px);font-weight:800;line-height:1.05;letter-spacing:-.02em;
 font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.stat-sub{font-size:13px;color:var(--muted);line-height:1.4}
.stat-value.long{font-size:clamp(20px,2.1vw,28px);line-height:1.15;overflow-wrap:normal;word-break:normal}
.stat-bar{height:6px;border-radius:3px;background:var(--line);overflow:hidden;margin-top:4px}
.stat-bar>span{display:block;height:100%;background:var(--primary)}
@media (max-width:1250px){.stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
[data-testid="stMetric"]{background:var(--surface);box-shadow:inset 0 0 0 1px var(--line);border-radius:14px;padding:14px 16px}
[data-testid="stMetricLabel"] p{font-size:13px !important;font-weight:500;color:var(--muted) !important}
[data-testid="stMetricValue"]{font-weight:800;letter-spacing:-.02em}
/* buttons and chips: pill-shaped like the design system */
.stButton button,.stDownloadButton button,[data-testid="stLinkButton"] a{border-radius:999px !important;font-weight:700}
html[data-theme="dark"] button[data-testid="stBaseButton-primary"]{color:#003580 !important}
[data-testid="stChatMessage"]{background:var(--surface);box-shadow:inset 0 0 0 1px var(--line);border-radius:18px}
.stTabs [data-baseweb="tab"] p{font-weight:700}
/* fact chips: the trust layer */
.fact{font:600 11px/1 "IBM Plex Mono",ui-monospace,monospace;padding:2px 4px;margin-left:2px;border-radius:4px;
 background:var(--primary-tint);color:var(--primary);box-shadow:inset 0 0 0 1px var(--primary-tint-line);
 cursor:help;vertical-align:super}
.fact:hover{background:var(--primary);color:var(--on-primary);box-shadow:none}
/* honest-label badges */
.badge{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 10px;border-radius:8px;
 font-weight:700;font-size:13px;line-height:1;white-space:nowrap;margin:.45em .4em 0 0}
.b-ok{background:var(--primary);color:var(--on-primary)}
.b-fix{background:var(--warning-tint);color:var(--warning);box-shadow:inset 0 0 0 1px var(--warning-line)}
.b-bad{background:var(--danger-tint);color:var(--danger);box-shadow:inset 0 0 0 1px var(--danger-line)}
.b-ai{background:var(--label-ai-tint);color:var(--label-ai);box-shadow:inset 0 0 0 1px var(--label-ai-line)}
/* game feed */
.ping{display:flex;gap:12px;align-items:flex-start;padding:12px 16px;margin:.45em 0;border-radius:14px;
 background:var(--surface);box-shadow:inset 0 0 0 1px var(--line);line-height:1.5}
.ping::before{content:"•";flex:none;width:32px;height:32px;border-radius:10px;display:grid;place-items:center;
 background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line-strong);font:700 14px "IBM Plex Mono",monospace}
.ping.goal{background:var(--primary-tint);box-shadow:inset 0 0 0 1px var(--primary-tint-line)}
.ping.goal::before{content:"▲";background:var(--primary);color:var(--on-primary);box-shadow:none}
.ping.against{background:var(--danger-tint);box-shadow:inset 0 0 0 1px var(--danger-line)}
.ping.against::before{content:"▼";background:var(--danger);color:var(--icon-ink);box-shadow:none}
.ping.alert{background:var(--warning-tint);box-shadow:inset 0 0 0 1px var(--warning-line);font-weight:700}
.ping.alert::before{content:"!";background:var(--warning);color:var(--icon-ink);box-shadow:none}
.small{font-size:14px;color:var(--muted)}
.script-line{display:flex;gap:.8em;padding:.4em 0;border-bottom:1px solid var(--line);line-height:1.55}
.script-line b{min-width:3.8em;color:var(--primary);font-size:12px;letter-spacing:.12em;text-transform:uppercase;
 padding-top:.25em}
.scoreline{display:flex;align-items:baseline;gap:.5em;font-size:20px;font-weight:700;margin:.2em 0 .6em}
.scoreline b{font-size:32px;font-weight:800;letter-spacing:-.03em;color:var(--primary);padding:0 .15em;
 font-variant-numeric:tabular-nums}
.scoreline span{margin-left:auto;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
[data-testid="stSidebar"] [data-testid="stExpander"]{margin-top:.2em}
.block-container{padding-top:3.6rem;max-width:1180px}
@media (max-width:640px){
 [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]){flex-flow:row wrap;gap:.6rem}
 [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"])>[data-testid="stColumn"]{
  flex:1 1 calc(50% - .3rem)!important;min-width:calc(50% - .3rem)!important;width:calc(50% - .3rem)!important}
 [data-testid="stMetric"]{padding:10px 12px}
 [data-testid="stMetricValue"]{font-size:1.5rem!important}
}
"""


def _vars(theme: str) -> str:
    return ";".join(f"--{k}:{v}" for k, v in TOKENS[theme].items())


# Both themes live in the stylesheet, like siniristi.css: light on :root, dark on html[data-theme="dark"].
CSS = f"<style>:root{{{_vars('light')}}}html[data-theme=\"dark\"]{{{_vars('dark')}}}{COMPONENTS}</style>"

# Streamlit doesn't tell the page which theme the fan picked (⋮ → Settings), so this watches the app's
# background colour and sets data-theme on <html>. Our custom HTML then switches instantly with Streamlit.
THEME_SYNC = """<script>
const doc = window.parent.document;
function sync() {
  const app = doc.querySelector('.stApp'); if (!app) return;
  const rgb = (getComputedStyle(app).backgroundColor.match(/\\d+/g) || []).map(Number);
  if (rgb.length < 3) return;
  const theme = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) < 128 ? 'dark' : 'light';
  if (doc.documentElement.dataset.theme !== theme) doc.documentElement.dataset.theme = theme;
}
sync(); setInterval(sync, 400);
// "Chat with me" on the welcome banner: open the Chat tab, scroll to the message box and focus it.
if (!doc.__chatJump) {
  doc.__chatJump = true;
  doc.addEventListener('click', (e) => {
    if (!e.target.closest('.welcome-btn')) return;
    e.preventDefault();
    const tab = [...doc.querySelectorAll('[role="tab"]')].find(t => t.textContent.trim() === 'Chat');
    if (tab) tab.click();
    setTimeout(() => {
      const box = doc.querySelector('[data-testid="stChatInput"] textarea');
      if (!box) return;
      box.scrollIntoView({behavior: 'smooth', block: 'center'});
      box.focus({preventScroll: true});
    }, 150);
  });
}
</script>"""


# The design's "Toggle dark" button. Streamlit can't switch themes from Python, so the button (in its own
# frame) picks Light or Dark in Streamlit's own menu (⋮ → Settings): native widgets, our HTML and the saved
# choice all stay in step. It shows the theme you'd switch to.
THEME_TOGGLE = """<style>
 :root{--t:#0f1a2a;--l:#8796a8;--h:#eef2f7}
 html[data-theme=dark]{--t:#fff;--l:#6f8fbf;--h:#134489}
 html,body{background:transparent}
 body{margin:0;padding:3px 3px 3px 0;display:flex;justify-content:flex-end;
   font-family:'Plus Jakarta Sans',Helvetica,Arial,sans-serif}
 button{height:34px;padding:0 12px;border-radius:999px;border:1px solid var(--l);background:transparent;
   color:var(--t);font-weight:600;font-size:13px;line-height:1;font-family:inherit;cursor:pointer;white-space:nowrap}
 button:hover{background:var(--h);border-color:var(--t)}
 button:focus-visible{outline:2px solid var(--t);outline-offset:2px}
</style>
<button id="t" type="button"></button>
<script>
 const doc = window.parent.document, btn = document.getElementById('t');
 const current = () => doc.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
 function paint() {
   const dark = current() === 'dark';
   document.documentElement.dataset.theme = current();
   btn.textContent = dark ? '☀ Light' : '☾ Dark';
   btn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
 }
 btn.onclick = () => {
   const target = current() === 'dark' ? 'Light' : 'Dark';
   const menu = doc.querySelector('[data-testid="stMainMenuButton"]') || doc.querySelector('[data-testid="stMainMenu"] button');
   if (!menu) return;
   const hide = doc.createElement('style');   // keep Streamlit's menu invisible while we use it
   hide.textContent = '[data-floating-ui-portal]{opacity:0 !important}';
   doc.head.appendChild(hide);
   menu.click();
   let tries = 0;
   const pick = setInterval(() => {
     const item = doc.querySelector('[data-testid="stMainMenuItem-theme-' + target + '"]');
     if (!item && ++tries <= 40) return;
     clearInterval(pick);
     if (item) item.click();
     setTimeout(() => {
       if (doc.querySelector('[data-testid="stMainMenuItem-theme-Light"]')) menu.click();   // close the menu
       setTimeout(() => hide.remove(), 150);
     }, 50);
   }, 25);
 };
 paint(); setInterval(paint, 300);
</script>"""


CITE = re.compile(r"\[([A-Z]\d+)\]")


def to_html(text: str, fs: FactStore) -> str:
    safe = html.escape(text, quote=False)

    def chip(m):
        f = fs.facts.get(m.group(1))
        if not f:
            return f'<span class="fact" style="background:rgba(217,48,37,.15);color:#d93025">{m.group(1)}?</span>'
        tip = html.escape(f"{f.label}: {f.display} — {f.source}", quote=True)
        return f'<span class="fact" title="{tip}">{f.id}</span>'

    safe = CITE.sub(chip, safe)
    return safe.replace("\n", "  \n")


def badges(reply) -> str:
    rep = reply.report
    if reply.status == "verified":
        cls, txt = "b-ok", f"✓ {rep.numbers_verified}/{rep.numbers_checked} numbers verified against data"
    elif reply.status == "corrected":
        cls, txt = "b-fix", f"↻ caught an error and corrected it · {rep.numbers_verified}/{rep.numbers_checked} verified"
    else:
        cls, txt = "b-bad", "⚠ unverifiable sentence removed"
    if rep.numbers_checked == 0 and reply.status == "verified":
        cls, txt = "b-ai", "opinion / no data claims"
    label = "Auto-generated" if "emplate" in reply.engine else "AI-generated"
    return (f'<span class="badge b-ai">{label} · {html.escape(reply.engine)}</span>'
            f'<span class="badge {cls}">{txt}</span>')


def receipts_rows(reply) -> list[dict]:
    rows = []
    for fid in reply.report.cited_ids:
        f = reply.facts.facts.get(fid)
        if f:
            rows.append({"ID": f.id, "Fact": f.label, "Value": f.display, "Source": f.source})
    return rows
