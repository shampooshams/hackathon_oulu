"""Turn citations into hoverable fact chips and build the 'fact receipts' view."""
from __future__ import annotations

import html
import re

from companion.facts import FactStore

CSS = """
<style>
/* Visual system shared with Local SportsReel: dark panels, lime accent, heavy headlines */
:root{--bg:#0b1018;--panel:#141b24;--panel2:#18212b;--line:#2a3340;--text:#f0f4f5;--muted:#9ba7b4;
 --lime:#d3fa5b;--orange:#ff9b63;--red:#ff6b6b}
h1,h2,h3,h4{font-weight:900 !important;letter-spacing:-.04em}
.brand{display:flex;align-items:center;gap:10px;font-size:21px;letter-spacing:-1.2px;font-weight:900;margin:.2em 0 .1em}
.brand-mark{height:32px;width:32px;display:grid;place-items:center;background:var(--lime);color:var(--bg);
 font-size:22px;border-radius:8px}
.brand-thin{font-weight:400}.dot{color:var(--lime)}
.kicker{font-size:11px;letter-spacing:2px;color:var(--lime);font-weight:800;display:flex;gap:10px;
 align-items:center;text-transform:uppercase;margin:.4em 0 .2em}
.kicker:before{content:"";display:block;width:23px;height:2px;background:var(--lime)}
.hero{font-size:clamp(38px,5.4vw,76px);letter-spacing:-.055em;line-height:.98;font-weight:900;margin:.25em 0 .35em;
 text-transform:uppercase}
.hero em{font-style:normal;color:var(--lime)}
.hero-sub{color:#b5c0c8;font-size:15px;line-height:1.6;max-width:620px;margin-bottom:1em}
.demo{font-size:12px;line-height:1.5;padding:11px 14px;border:1px solid #4c482e;border-radius:8px;
 background:#272719;color:#e8dba2;margin:.2em 0 1em;display:inline-block}
.section-title{font-size:34px;letter-spacing:-1.5px;font-weight:900;margin:.15em 0 .2em}
[data-testid="stMetric"]{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 18px}
[data-testid="stMetricLabel"] p{font-size:10px !important;letter-spacing:1.3px;font-weight:700;text-transform:uppercase;
 color:var(--muted) !important}
[data-testid="stMetricValue"]{font-weight:900;letter-spacing:-.04em}
button[kind="primary"],button[data-testid="stBaseButton-primary"]{color:#122014 !important;font-weight:800}
[data-testid="stChatMessage"]{background:var(--panel);border:1px solid var(--line);border-radius:12px}
.stTabs [data-baseweb="tab"] p{font-weight:700;letter-spacing:.2px}
.fact{display:inline-block;font-size:.66em;line-height:1.3;padding:0 .45em;margin:0 .1em;border-radius:3px;
 background:rgba(211,250,91,.14);color:var(--lime);vertical-align:super;cursor:help;font-weight:800}
.badge{display:inline-block;font-size:.72em;padding:.2em .65em;border-radius:3px;margin:.35em .4em 0 0;font-weight:700;
 letter-spacing:.3px}
.b-ok{background:rgba(211,250,91,.14);color:var(--lime)}.b-fix{background:rgba(255,155,99,.16);color:var(--orange)}
.b-bad{background:rgba(255,107,107,.15);color:var(--red)}.b-ai{background:var(--panel2);color:var(--muted);
 border:1px solid var(--line)}
.ping{border:1px solid var(--line);border-left:3px solid #6b7b8b;padding:.55em .9em;margin:.45em 0;
 background:var(--panel);border-radius:0 10px 10px 0}
.ping.goal{border-left-color:var(--lime);background:#18231b}.ping.against{border-left-color:var(--red);background:#251a1d}
.ping.alert{border-left-color:var(--orange);background:#2a2018;font-weight:700}
.small{font-size:.8em;opacity:.75}
</style>
"""

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
