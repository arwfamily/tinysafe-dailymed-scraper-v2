#!/usr/bin/env python3
"""
scripts/render_site.py — render the arwhouse.com/evidence pages from
site/evidence.json and content/notes.json. Runs in CI right after
build_evidence.py, so the pages are rebuilt every week with the data.

Nothing on these pages is typed by hand except fixed labels. Every number
and every sentence about an ingredient comes from evidence.json (which only
holds verified claims) or from a note in content/notes.json that carries its
own primary source.

  python scripts/render_site.py           # write site/evidence/**
  python scripts/render_site.py --check   # also fail on contract breaks

Standard library only.
"""
import datetime
import html
import json
import os
import re
import shutil
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Overridable so the arwhouse repo can run this same file on fetched inputs.
EVIDENCE = os.environ.get("EVIDENCE_JSON") or os.path.join(ROOT, "site", "evidence.json")
NOTES = os.environ.get("NOTES_JSON") or os.path.join(ROOT, "content", "notes.json")
OUT = os.environ.get("OUT_DIR") or os.path.join(ROOT, "site", "evidence")
SITE = "https://arwhouse.com"
BASE = "/evidence"
REPO = "https://github.com/arwfamily/tinysafe-dailymed-scraper-v2"

FINDINGS = {  # display order = dict order
    "fda-more-data": {
        "title": "Over half of baby and kids sunscreen formulas in DailyMed use an ingredient the FDA has proposed needs more safety data",
        "eyebrow": "Finding · DailyMed labels × FDA review",
        "caption": "Each door is one baby or kids formula. Filled: contains at least one of the 12 ingredients."},
    "homosalate-eu-limit": {
        "title": "Homosalate in baby and kids sunscreen labels: US levels vs the EU limit",
        "eyebrow": "Finding · DailyMed labels × EU law",
        "caption": "Each door is one baby or kids formula. Filled: homosalate above 7.34%."},
    "eu-banned-preservatives": {
        "title": "Preservatives banned in EU cosmetics, on US baby sunscreen labels",
        "eyebrow": "Finding · DailyMed labels × EU law",
        "caption": "Each door is one baby or kids formula. Filled: lists isobutylparaben or methylisothiazolinone."},
    "hawaii-oxybenzone-octinoxate": {
        "title": "Oxybenzone and octinoxate in baby sunscreens, and Hawaii's law",
        "eyebrow": "Finding · DailyMed labels × Hawaii law",
        "caption": "Each door is one baby or kids formula. Filled: contains oxybenzone or octinoxate."},
    "same-ingredient-list": {
        "title": "Same ingredient list, different label",
        "eyebrow": "Finding · DailyMed labels",
        "caption": "Each door is one baby or kids formula. Filled: same ingredients as a label that does not say baby or kids."},
    "spf-boosters": {
        "title": "SPF boosters in baby sunscreens, including mineral ones",
        "eyebrow": "Finding · DailyMed labels × manufacturer data",
        "caption": "Each door is one baby or kids formula. Filled: contains at least one of the six booster ingredients."},
    "fragrance": {
        "title": "Fragrance in baby and kids sunscreens",
        "eyebrow": "Finding · DailyMed labels × AAD guidance",
        "caption": "Each door is one baby or kids formula. Filled: lists fragrance or parfum."},
    "parabens": {
        "title": "Parabens in baby and kids sunscreens",
        "eyebrow": "Finding · DailyMed labels × EU law",
        "caption": "Each door is one baby or kids formula. Filled: lists at least one paraben."},
}
FINDING_TITLES = {k: v["title"] for k, v in FINDINGS.items()}
JUR_NAME = {"US": "United States", "EU": "European Union", "AU": "Australia"}
JUR_BODY = {"US": "FDA", "EU": "European Commission", "AU": "TGA"}
ROLE = {"uv_filter_mineral": "Mineral UV filter", "uv_filter_organic": "Organic UV filter"}
# Phrases that must never reach a page (SITE_DATA_CONTRACT.md wording rules).
FORBIDDEN = [
    "absorbs uv", "absorb uv", "uv-absorbing", "hidden uv", "registered with the fda",
    "sold in the us", "hand-reviewed", "reviewed one by one", "product by product",
    "chemical uv filter", "boosts spf", "reef safe", "safest", "best sunscreen",
]
FDA_QA_URL = "https://www.fda.gov/drugs/understanding-over-counter-medicines/questions-and-answers-fdas-regulatory-actions-over-counter-sunscreen"
DRUG_FACTS = {"title": "21 CFR 201.66 — Format and content requirements for OTC drug product labeling (Drug Facts)",
              "url": "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-C/part-201/subpart-C/section-201.66"}

E = lambda s: html.escape(str(s), quote=True)


# ---------------------------------------------------------------- pieces
ARCH = ('<svg class="arch" viewBox="0 0 64 96" fill="none" aria-hidden="true">'
        '<path d="M9 94V36a23 23 0 0 1 46 0v58" stroke="currentColor" stroke-width="6" '
        'stroke-linecap="square"/><circle cx="44" cy="60" r="3.4" fill="currentColor"/></svg>')
DOOR = ('<svg class="door" viewBox="0 0 10 14" aria-hidden="true"><path d="M1.5 13.5V6a3.5 3.5 0 0 1 7 0v7.5" '
        'fill="none" stroke="currentColor" stroke-width="1.3"/></svg>')


FAVICON = ARCH.replace('currentColor', '%23141613').replace(' class="arch"', ' xmlns="http://www.w3.org/2000/svg"')


def fmt_pct(x):
    if x is None:
        return None
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s + "%"


def fmt_date(iso):
    try:
        d = datetime.date.fromisoformat(iso[:10])
    except (TypeError, ValueError):
        return iso
    return d.strftime("%B %-d, %Y")


def short_source(jur, src):
    t = src.get("title", "")
    if jur == "US":
        m = re.search(r"OTC0000\d+", t)
        if m:
            return f"FDA order {m.group(0)}"
        if "Monograph M020" in t:
            return "FDA M020"
        m = re.search(r"NDA \d+-\d+", t)
        if m:
            return f"FDA {m.group(0)}"
        return "FDA"
    if jur == "EU":
        return "EU Annex VI"
    if jur == "AU":
        return "TGA 2026"
    return t[:30]


def src_chip(label, url, title=""):
    return (f'<a class="chip" href="{E(url)}" title="{E(title)}" rel="noopener" target="_blank">'
            f'{DOOR}<span>{E(label)}</span></a>')


def glyph(status):
    # ink-only status marks; colour-blind safe, print safe
    shapes = {
        "permitted": '<circle cx="8" cy="8" r="5.5" fill="currentColor"/>',
        "permitted_with_conditions": ('<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
                                      '<path d="M8 2.5a5.5 5.5 0 0 1 0 11z" fill="currentColor"/>'),
        "listed_no_numeric_limit": ('<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
                                    '<circle cx="8" cy="8" r="2" fill="currentColor"/>'),
        "approved_product_only": ('<rect x="2.5" y="2.5" width="11" height="11" rx="1" fill="none" stroke="currentColor" stroke-width="1.4"/>'
                                  '<circle cx="8" cy="8" r="2" fill="currentColor"/>'),
        "removal_finalized_not_yet_effective": ('<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
                                                '<path d="M4 12L12 4" stroke="currentColor" stroke-width="1.4"/>'),
        "removed": ('<circle cx="8" cy="8" r="5.5" fill="currentColor"/>'
                    '<path d="M4 12L12 4" stroke="var(--paper)" stroke-width="1.6"/>'),
        "not_listed": '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="2 2"/>',
    }
    return f'<svg class="g" viewBox="0 0 16 16" aria-hidden="true">{shapes[status]}</svg>'


STATUS_WORD = {
    "permitted": "Permitted",
    "permitted_with_conditions": "Permitted, with conditions",
    "listed_no_numeric_limit": "Listed, no numeric limit",
    "approved_product_only": "Only in FDA-approved products",
    "removal_finalized_not_yet_effective": "Removal final, not yet in effect",
    "removed": "Removed",
    "not_listed": "Not listed",
}


def cell_value(l):
    st = l["status"]
    if st in ("permitted", "permitted_with_conditions", "removal_finalized_not_yet_effective") and l["max_percent"] is not None:
        return fmt_pct(l["max_percent"])
    return {"listed_no_numeric_limit": "No limit set", "approved_product_only": "NDA only",
            "removed": "Removed", "not_listed": "Not listed"}.get(st, "—")


def units(n, total, cols, label):
    """A field of small arch doors, one per formulation; filled = counted."""
    w, h, gx, gy = 10, 14, 4, 5
    rows = -(-total // cols)
    vw, vh = cols * (w + gx) - gx, rows * (h + gy) - gy
    parts = []
    for i in range(total):
        x, y = (i % cols) * (w + gx), (i // cols) * (h + gy)
        d = f"M{x+1} {y+13.5}V{y+6}a4 4 0 0 1 8 0v{7.5}"
        if i < n:
            parts.append(f'<path d="{d}z" class="on"/>')
        else:
            parts.append(f'<path d="{d}" class="off"/>')
    return (f'<svg class="units" viewBox="-1 -1 {vw+2} {vh+2}" role="img" aria-label="{E(label)}">'
            + "".join(parts) + "</svg>")


def jsonld(obj):
    return ('<script type="application/ld+json">'
            + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>")


def person():
    return {"@type": "Person", "name": "Angela Lee", "jobTitle": "Founder",
            "worksFor": {"@type": "Organization", "name": "ARW House", "url": SITE}}


def org():
    return {"@type": "Organization", "name": "ARW House", "url": SITE}


CSS = r"""
:root{--paper:#FAFAF7;--ink:#141613;--grey:#6E766A;--hair:#E6E8E0;--line:rgba(20,22,19,.12);--soft:rgba(20,22,19,.045);
--serif:"Instrument Serif",Georgia,serif;--sans:"DM Sans",-apple-system,"Segoe UI",sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#171A16;--ink:#F1F0EA;--grey:#A3A99D;--hair:#2A2E28;--line:rgba(241,240,234,.14);--soft:rgba(241,240,234,.05)}}
:root[data-theme="dark"]{--paper:#171A16;--ink:#F1F0EA;--grey:#A3A99D;--hair:#2A2E28;--line:rgba(241,240,234,.14);--soft:rgba(241,240,234,.05)}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:400 17px/1.65 var(--sans);-webkit-font-smoothing:antialiased;font-feature-settings:"tnum" 1}
a{color:inherit;text-decoration-thickness:1px;text-underline-offset:3px}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px}
@media(min-width:720px){.wrap{padding:0 32px}}
.top{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:66px;position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--paper) 85%,transparent);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);box-shadow:0 0 0 100vmax color-mix(in srgb,var(--paper) 85%,transparent);clip-path:inset(0 -100vmax)}
.word{font-family:var(--serif);font-size:26px;text-decoration:none;display:inline-flex;align-items:baseline;gap:9px;white-space:nowrap}
.word .arch{height:.74em;width:auto}
.word em{font-style:normal;color:var(--grey)}
.top{flex-wrap:wrap}.top nav{display:flex;gap:28px;font-size:14px;letter-spacing:.01em}
.top nav a{text-decoration:none;color:var(--grey)}.top nav a:hover,.top nav a[aria-current]{color:var(--ink)}
.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--grey);margin:0 0 14px}
h1,h2,h3{font-family:var(--serif);font-weight:400;letter-spacing:-.01em;margin:0}
h1{font-size:clamp(40px,7vw,72px);line-height:.98;max-width:16ch}
h1 em{font-style:italic}
h2{font-size:clamp(28px,4vw,38px);line-height:1.1;margin-bottom:14px}
h3{font-size:22px;line-height:1.2}
.hero{padding:64px 0 44px}
.lede{font-size:19px;max-width:58ch;margin:22px 0 0}
.byline{font-size:14px;color:var(--grey);margin:22px 0 0}
.crumb{font-size:14px;color:var(--grey);margin:28px 0 0}.crumb a{color:var(--grey)}
section{padding:44px 0;border-top:1px solid var(--line)}
.ledger{display:grid;grid-template-columns:repeat(2,1fr);gap:0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
@media(min-width:720px){.ledger{grid-template-columns:repeat(4,1fr)}}
.ledger div{padding:20px 16px 18px 0}
.fig{font-family:var(--serif);font-size:clamp(44px,6vw,64px);line-height:1}
.fig small{font-size:.42em;color:var(--grey);margin-left:4px}
.figcap{font-size:13px;color:var(--grey);margin-top:6px;max-width:22ch}
.chip{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;line-height:1;color:var(--grey);text-decoration:none;
border:1px solid var(--line);border-radius:999px;padding:4px 8px 4px 6px;white-space:nowrap;vertical-align:middle}
.chip:hover{color:var(--ink);border-color:var(--ink)}
.door{width:8px;height:11px}
.g{width:15px;height:15px;flex:none}
table.matrix{width:100%;border-collapse:collapse;font-size:15px}
.matrix th{font-weight:500;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--grey);text-align:left;padding:10px 8px;border-bottom:1px solid var(--ink)}
.matrix td{padding:12px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.matrix td:first-child{padding-left:0}
.matrix .name a{font-family:var(--serif);font-size:20px;text-decoration:none}
.matrix .name a:hover{text-decoration:underline}
.matrix .name span{display:block;font-size:12px;color:var(--grey)}
.v{display:flex;align-items:center;gap:7px;font-variant-numeric:tabular-nums}
.v + .chip{margin-top:6px}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:13px;color:var(--grey);margin:0 0 18px;padding:0;list-style:none}
.legend li{display:flex;align-items:center;gap:6px}
@media(max-width:640px){
 .matrix thead{display:none}.matrix,.matrix tbody,.matrix tr,.matrix td{display:block;width:100%}
 .matrix tr{padding:14px 0;border-bottom:1px solid var(--line)}.matrix td{border:0;padding:4px 0}
 .matrix td[data-j]{display:flex;align-items:center;justify-content:space-between;gap:10px}
 .matrix td[data-j]::before{content:attr(data-j);font-size:12px;letter-spacing:.1em;color:var(--grey);width:34px}
 .matrix td[data-j] .v{flex:1}.v + .chip{margin-top:0}}
.card{border:1px solid var(--line);border-radius:28px;padding:26px}
@media(min-width:720px){.card{padding:34px}}
.finding{display:grid;gap:26px}
@media(min-width:820px){.finding{grid-template-columns:1.05fr 1fr;align-items:center}}
.units{width:100%;max-width:440px;height:auto;display:block}
.units .on{fill:var(--ink);stroke:var(--ink);stroke-width:1.2}
.units .off{fill:none;stroke:var(--grey);stroke-width:1;opacity:.55}
.sentence{font-family:var(--serif);font-size:clamp(22px,2.6vw,28px);line-height:1.3;margin:0}
.fine{font-size:13px;color:var(--grey);margin:12px 0 0}
.framing{font-size:15px;border-left:2px solid var(--ink);padding:2px 0 2px 14px;margin:18px 0 0}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px}
.more{display:inline-block;margin-top:18px;font-size:15px}
.answer{font-family:var(--serif);font-size:clamp(22px,2.8vw,30px);line-height:1.3;max-width:34ch;margin:0}
.jur{display:grid;gap:14px}
@media(min-width:820px){.jur{grid-template-columns:repeat(3,1fr)}}
.jur .card{padding:24px;display:flex;flex-direction:column;gap:10px}
.jur h3{font-family:var(--sans);font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--grey);font-weight:500}
.jur .big{font-family:var(--serif);font-size:56px;line-height:1}
.jur .st{display:flex;align-items:center;gap:7px;font-size:14px}
.jur ul{margin:0;padding-left:18px;font-size:14px}
.jur .notes{font-size:14px;color:var(--grey);margin:0}
.jur .srcline{margin-top:auto;padding-top:12px;border-top:1px solid var(--line);font-size:12.5px;color:var(--grey)}
.jur .srcline a{color:var(--ink)}
.notebox{background:var(--soft);border-radius:28px;padding:26px}
.notebox h3{margin-bottom:8px}
.notebox p{margin:0;max-width:62ch}
details{border-top:1px solid var(--line);padding:16px 0}
details:last-of-type{border-bottom:1px solid var(--line)}
summary{cursor:pointer;font-family:var(--serif);font-size:21px;list-style:none;display:flex;justify-content:space-between;gap:16px}
summary::-webkit-details-marker{display:none}
summary::after{content:"+";font-family:var(--sans);color:var(--grey)}
details[open] summary::after{content:"–"}
details p{margin:10px 0 0;max-width:64ch}
.pn{display:flex;justify-content:space-between;gap:16px;font-size:15px}
.cols{display:grid;gap:28px}@media(min-width:820px){.cols{grid-template-columns:1fr 1fr}}
.prose p,.prose li{max-width:64ch}
.srclist{list-style:none;padding:0;margin:0;font-size:15px}
.srclist li{padding:12px 0;border-bottom:1px solid var(--line)}
.srclist span{display:block;font-size:13px;color:var(--grey)}
.minis{display:grid;gap:14px;margin-top:14px}@media(min-width:720px){.minis{grid-template-columns:1fr 1fr}}
.card.mini{display:flex;flex-direction:column;gap:10px;text-decoration:none;padding:24px}
.card.mini:hover{border-color:var(--ink)}.card.mini h3{font-size:22px}.card.mini .fig{font-size:44px}.card.mini .more{margin-top:auto}
.tablewrap{overflow-x:auto}table.pairs{width:100%;border-collapse:collapse;font-size:14px}
.pairs th{font-weight:500;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--grey);text-align:left;padding:10px 8px;border-bottom:1px solid var(--ink)}
.pairs td{padding:10px 8px;border-bottom:1px solid var(--line);vertical-align:top}.pairs a{text-decoration:none}.pairs a:hover{text-decoration:underline}
.bars{list-style:none;padding:0;margin:0;display:grid;gap:8px;max-width:720px}
.bars li{display:grid;grid-template-columns:minmax(120px,190px) 1fr 44px;gap:12px;align-items:center;font-size:15px}
.bars.pct li{grid-template-columns:64px 1fr 44px}
.bars a{text-decoration:none}.bars a:hover{text-decoration:underline}
.bars .bar{height:10px;border-radius:999px;background:var(--soft);overflow:hidden;display:block}
.bars .bar i{display:block;height:100%;background:var(--grey);border-radius:999px}
.bars:not(.pct) .bar i,.bars .bar i.over{background:var(--ink)}
.bars b{font-weight:500;text-align:right;font-variant-numeric:tabular-nums}
footer{margin-top:56px;padding:40px 0 70px;font-size:13px;color:var(--grey);background:var(--hair);box-shadow:0 0 0 100vmax var(--hair);clip-path:inset(0 -100vmax)}
footer .word{font-size:20px;color:var(--ink)}
footer p{margin:10px 0 0;max-width:72ch}
"""


def shell(path, title, description, body, ld, current=""):
    canon = SITE + path
    nav = [("Library", BASE), ("Findings", f"{BASE}/findings"), ("Method", f"{BASE}/methodology")]
    cur = ' aria-current="page"'
    navh = "".join(f'<a href="{u}"{cur if current == n else ""}>{n}</a>' for n, u in nav)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<meta name="description" content="{E(description)}">
<link rel="canonical" href="{E(canon)}">
<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(description)}">
<meta property="og:url" content="{E(canon)}"><meta property="og:type" content="article"><meta property="og:site_name" content="ARW House">
<meta name="author" content="Angela Lee">
<link rel="icon" href="data:image/svg+xml,{E(FAVICON)}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500&family=Instrument+Serif&display=swap" rel="stylesheet">
<style>{CSS}</style>
{''.join(jsonld(x) for x in ld)}
</head><body>
<div class="wrap">
<header class="top"><a class="word" href="/">{ARCH}ARW House <em>Evidence</em></a><nav>{navh}</nav></header>
{body}
<footer>
<a class="word" href="/">{ARCH}ARW House</a>
<p>ARW House also makes Sunnytime, a mineral baby sunscreen. These pages do not rank or recommend products, and they are not medical advice. For medical decisions about your child, talk to your pediatrician.</p>
<p>Corrections: angela@arwhouse.com · <a href="{BASE}/data.json">Download the data (JSON)</a> · <a href="{REPO}">Source code and raw data</a></p>
</footer>
</div></body></html>
"""


# ---------------------------------------------------------------- pages
def page_index(d, notes):
    pop = d["registry_population"]
    n_cells = sum(len(i["limits"]) for i in d["ingredients"])
    rows = []
    for i in d["ingredients"]:
        tds = []
        for l in i["limits"]:
            s = l["source"]
            tds.append(f'<td data-j="{l["jurisdiction"]}"><div class="v">{glyph(l["status"])}'
                       f'<span title="{E(STATUS_WORD[l["status"]])}">{E(cell_value(l))}</span></div>'
                       f'{src_chip(short_source(l["jurisdiction"], s), s["url"], s.get("title", "") + " — " + s.get("version", ""))}</td>')
        rows.append(f'<tr><td class="name"><a href="{BASE}/ingredients/{i["slug"]}">{E(i["name"])}</a>'
                    f'<span>{E(ROLE.get(i["role"], ""))}</span></td>{"".join(tds)}</tr>')
    legend = "".join(f"<li>{glyph(k)}{E(v)}</li>" for k, v in STATUS_WORD.items())
    fs = ordered_findings(d)
    finding_html = ""
    if fs:
        minis = "".join(finding_card(f, big=False) for f in fs[1:])
        finding_html = f"""
<section><p class="eyebrow">Findings</p><h2>What the labels show</h2>
{finding_card(fs[0])}
<div class="minis">{minis}</div>
<a class="more" href="{BASE}/findings">All findings →</a></section>"""
    site_notes = "".join(
        f'<section><div class="notebox"><h3>{E(n["heading"])}</h3><p>{E(n["text"])}</p>'
        f'<div class="chips">{src_chip("FDA", n["source"]["url"], n["source"]["title"])}</div></div></section>'
        for n in notes if "site" in n["applies_to"])
    body = f"""
<div class="hero"><p class="eyebrow">Baby sunscreen · Evidence library</p>
<h1>Sunscreen filters, <em>checked at the source.</em></h1>
<p class="lede">{len(d["ingredients"])} UV filters. Their legal limits in the United States, the European Union and Australia. How often baby and kids sunscreen labels in the FDA's DailyMed database list each one. Every number opens its source.</p>
<p class="byline">By Angela Lee, Founder · ARW House · Updated {E(fmt_date(d["built_on"]))}</p></div>
<div class="ledger">
 <div><div class="fig">{len(d["ingredients"])}</div><div class="figcap">UV filters</div></div>
 <div><div class="fig">{n_cells}</div><div class="figcap">legal limits, each linked to its own source</div></div>
 <div><div class="fig">{pop["formulations"]}</div><div class="figcap">baby and kids sunscreen formulas read from FDA DailyMed</div></div>
 <div><div class="fig">{pop["mineral_only"]}</div><div class="figcap">of them use only mineral actives</div></div>
</div>
{finding_html}
<section><h2>The limits</h2>
<p class="fine" style="margin:0 0 18px">Maximum concentration of each filter in a finished sunscreen. Tap a filter for conditions, notes and the full source.</p>
<ul class="legend">{legend}</ul>
<table class="matrix"><thead><tr><th>Filter</th><th>United States</th><th>European Union</th><th>Australia</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></section>
{site_notes}
"""
    ld = [{"@context": "https://schema.org", "@type": "Dataset",
           "name": "Baby sunscreen ingredient evidence: UV filter limits (US, EU, Australia) and baby and kids label counts from FDA DailyMed",
           "description": (f"Maximum permitted concentrations for {len(d['ingredients'])} sunscreen UV filters in the United States, "
                           f"European Union and Australia, each linked to its regulatory source, plus how many of "
                           f"{pop['formulations']} baby and kids sunscreen formulas in FDA DailyMed list each filter."),
           "url": SITE + BASE, "dateModified": d["built_on"], "creator": org(), "author": person(),
           "publisher": org(),
           "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                             "contentUrl": SITE + BASE + "/data.json"}],
           "isBasedOn": sorted({l["source"]["url"] for i in d["ingredients"] for l in i["limits"]})}]
    return shell(BASE, "Baby Sunscreen Ingredient Evidence — UV filter limits in the US, EU and Australia · ARW House",
                 f"Legal limits for {len(d['ingredients'])} sunscreen UV filters in the US, EU and Australia, and how often "
                 f"baby and kids sunscreen labels in FDA DailyMed list each one. Every number linked to its source.",
                 body, ld, "Library")


def page_ingredient(d, i, prev, nxt, notes):
    reg = i["registry"]
    cards = []
    for l in i["limits"]:
        s, st, j = l["source"], l["status"], l["jurisdiction"]
        big = cell_value(l)
        sub = "maximum concentration" if l["max_percent"] is not None else ""
        conds = ""
        if l["conditions"]:
            conds = "<ul>" + "".join(
                f'<li>{E(c.get("applies_to", ""))}: up to {E(fmt_pct(c.get("max_percent")))}</li>' if isinstance(c, dict) else f"<li>{E(c)}</li>"
                for c in l["conditions"]) + "</ul>"
        note = (l.get("notes") or "").strip()
        names = {i["name"].lower(), *(a.lower() for a in i["also_known_as"])}
        if note.lower().strip(". ") in names:  # EU rows that only repeat the name
            note = ""
        noteh = f'<p class="notes">{E(note)}</p>' if note else ""
        eff = ""
        if st == "removal_finalized_not_yet_effective":
            eff = (f'<p class="notes"><strong>Removal takes effect {E(fmt_date(l.get("effective_date", "")))}.</strong> '
                   f'{src_chip("FDA order OTC000008-1", l.get("status_source_url", ""), "Final administrative order")}</p>')
        if st == "removed":
            eff = f'<p class="notes">{src_chip("FDA removal order", l.get("status_source_url", ""), "Final administrative order")}</p>'
        cards.append(f"""<div class="card"><h3>{JUR_NAME[j]} · {JUR_BODY[j]}</h3>
<div class="big">{E(big)}</div><div class="fine" style="margin:0">{sub}</div>
<div class="st">{glyph(st)}{E(STATUS_WORD[st])}</div>{conds}{eff}{noteh}
<div class="srcline">{DOOR} <a href="{E(s["url"])}" rel="noopener" target="_blank">{E(s.get("title", ""))}</a><br>{E(s.get("version", ""))} · checked {E(s.get("data_as_of", ""))}</div></div>""")
    regh = ""
    for r in reg:
        s = r["source"]
        regh += f"""
<div class="card finding" style="margin-top:14px">
 <div><div class="fig">{r["numerator"]}<small>of {r["denominator"]}</small></div>
 {units(r["numerator"], r["denominator"], 30 if r["denominator"] > 200 else 21, f'{r["numerator"]} of {r["denominator"]}')}</div>
 <div><p class="sentence">{E(r["sentence"])}</p><p class="fine">{E(r["caveat"])}</p>
 <div class="chips">{src_chip("Registry data", s["url"])}{src_chip("Review file", s["list_url"])}{src_chip("Method", s["method_url"])}</div>
 <p class="fine">DailyMed snapshot {E(s["snapshot"])}.</p></div></div>"""
    if regh:
        regh = f'<section><p class="eyebrow">On DailyMed labels</p><h2>How often baby and kids sunscreen formulas list it</h2>{regh}</section>'
    own = [n for n in notes if i["slug"] in n["applies_to"]] + [n for n in notes if "site" in n["applies_to"]]
    notesh = "".join(
        f'<div class="notebox" style="margin-top:14px"><h3>{E(n["heading"])}</h3><p>{E(n["text"])}</p>'
        f'<div class="chips">{src_chip("Source", n["source"]["url"], n["source"]["title"])}</div></div>' for n in own)
    faq = [(f"What is the maximum concentration of {i['name'].lower()} allowed in sunscreen?", i["summary"])]
    for r in reg:
        if r["id"].startswith("US-BABY-ACTIVE-"):
            faq.append((f"How many baby and kids sunscreen formulas in the FDA's DailyMed list {i['name'].lower()} as an active ingredient?", r["sentence"]))
    faqh = "".join(f"<details><summary>{E(q)}</summary><p>{E(a)}</p></details>" for q, a in faq)
    aka = f'<p class="fine">Also listed as {E(", ".join(a.title() for a in i["also_known_as"]))}.</p>' if i["also_known_as"] else ""
    pn = (f'<div class="pn">' + (f'<a href="{BASE}/ingredients/{prev["slug"]}">← {E(prev["name"])}</a>' if prev else "<span></span>")
          + (f'<a href="{BASE}/ingredients/{nxt["slug"]}">{E(nxt["name"])} →</a>' if nxt else "<span></span>") + "</div>")
    body = f"""
<p class="crumb"><a href="{BASE}">Library</a> / {E(i["name"])}</p>
<div class="hero" style="padding-top:28px"><p class="eyebrow">{E(ROLE.get(i["role"], ""))}</p>
<h1>{E(i["name"])}</h1>{aka}
<p class="byline">By Angela Lee, Founder · ARW House · Updated {E(fmt_date(d["built_on"]))}</p></div>
<section><p class="eyebrow">The short answer</p><p class="answer">{E(i["summary"])}</p></section>
<section><p class="eyebrow">By jurisdiction</p><div class="jur">{"".join(cards)}</div></section>
{regh}
<section><p class="eyebrow">Worth knowing</p>{notesh}</section>
<section><h2>Questions</h2>{faqh}</section>
<section>{pn}</section>"""
    path = f"{BASE}/ingredients/{i['slug']}"
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": f"{i['name']} in sunscreen: legal limits and baby label data from FDA DailyMed",
           "url": SITE + path, "dateModified": d["built_on"], "author": person(), "publisher": org(),
           "about": {"@type": "ChemicalSubstance", "name": i["name"], "alternateName": i["also_known_as"]},
           "citation": sorted({l["source"]["url"] for l in i["limits"]})},
          {"@context": "https://schema.org", "@type": "FAQPage",
           "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}]
    return path, shell(path, f"{i['name']} in sunscreen — limits in the US, EU and Australia · ARW House Evidence",
                       i["summary"] + (" " + reg[0]["sentence"] if reg else ""), body, ld)


def _lim(d, slug, jur):
    for i in d["ingredients"]:
        if i["slug"] == slug:
            for l in i["limits"]:
                if l["jurisdiction"] == jur:
                    return l
    return None


def _reg(d, slug):
    for i in d["ingredients"]:
        if i["slug"] == slug:
            for r in i["registry"]:
                if r["id"] == f"US-BABY-ACTIVE-{slug}":
                    return i, r
    return None, None


FDA12 = ["avobenzone", "cinoxate", "dioxybenzone", "ensulizole", "homosalate", "meradimate", "octinoxate",
         "octisalate", "octocrylene", "oxybenzone", "padimate-o", "sulisobenzone"]


def finding_body(d, f):
    """Per-finding explanation. Every sentence here restates a cited source or
    a verified number from evidence.json; chips link the source in place."""
    pop = d["registry_population"]
    key = f["finding"]
    isrc = f.get("ingredient_source") or {}
    howto = (f"Population: {pop['definition']}. That is {pop['formulations']} unique formulations, of which "
             f"{pop['mineral_only']} use only mineral actives (zinc oxide and/or titanium dioxide).")
    if key == "fda-more-data":
        rows = []
        for slug in FDA12:
            i, r = _reg(d, slug)
            if r and r["numerator"] > 0:
                rows.append((r["numerator"], i, r))
        rows.sort(key=lambda x: -x[0])
        bars = "".join(
            f'<li><a href="{BASE}/ingredients/{i["slug"]}">{E(i["name"])}</a>'
            f'<span class="bar"><i style="width:{100 * n / r["denominator"]:.1f}%"></i></span><b>{n}</b></li>'
            for n, i, r in rows)
        zero = [(_reg(d, s)[0] or {}).get("name", s) for s in FDA12 if (_reg(d, s)[1] or {}).get("numerator") == 0]
        mean = f"""
<p>The FDA has proposed that 12 sunscreen active ingredients are not GRASE (generally recognized as safe and effective) because the public record does not contain sufficient data to support a positive determination, and it is asking for safety data on them. {src_chip("FDA", FDA_QA_URL, "FDA Q&A on OTC sunscreen")}</p>
<p>For zinc oxide and titanium dioxide, the FDA says its review of publicly available evidence found sufficient safety data. {src_chip("FDA", FDA_QA_URL, "FDA Q&A on OTC sunscreen")}</p>
<p>All 12 remain permitted under the current US monograph, at the limits shown on each ingredient page.</p>"""
        extra = f"""<section><p class="eyebrow">Which of the 12</p><h2>How many of the {f["denominator"]} formulas list each one</h2>
<ul class="bars">{bars}</ul>
<p class="fine">{E(", ".join(zero))}: none of the {f["denominator"]}. One formula can contain several; {f["detail"]["four_or_more"]} contain four or more.</p></section>"""
        faq = [
            ("Does this mean these sunscreens are unsafe?",
             "This finding makes no safety judgment. The FDA has proposed that these 12 ingredients need more data before "
             "they can be recognized as safe and effective, and all 12 remain permitted under the current US monograph."),
            ("Which sunscreen ingredients does the FDA say have sufficient safety data?",
             "Zinc oxide and titanium dioxide. The FDA says its review of publicly available evidence found sufficient "
             "safety data on both."),
            ("How were these products selected?", howto),
        ]
    elif key == "homosalate-eu-limit":
        us, au, eu = (_lim(d, "homosalate", j) for j in ("US", "AU", "EU"))
        det = f["detail"]
        mx = max(v for _, v in det["by_percent"])
        bars = "".join(
            f'<li><span>{E(k)}%</span><span class="bar"><i class="{"over" if float(k) > 7.34 else ""}" '
            f'style="width:{100 * v / mx:.1f}%"></i></span><b>{v}</b></li>' for k, v in det["by_percent"])
        mean = f"""
<p>The US monograph permits homosalate up to {fmt_pct(us["max_percent"])} in a sunscreen. {src_chip("FDA M020", us["source"]["url"], us["source"]["title"])} Australia permits up to {fmt_pct(au["max_percent"])}. {src_chip("TGA 2026", au["source"]["url"], au["source"]["title"])}</p>
<p>In the EU, Regulation (EU) 2022/2195 set the limit at 7.34% and allowed homosalate only in face products, excluding propellant sprays. Products that did not comply could no longer be made available on the EU market from July 1, 2025. {src_chip("EU Annex VI", isrc.get("url", ""), isrc.get("title", ""))}</p>"""
        extra = f"""<section><p class="eyebrow">Concentrations on the labels</p><h2>Homosalate level in each of the {sum(v for _, v in det["by_percent"])} formulas</h2>
<ul class="bars pct">{bars}</ul>
<p class="fine">Filled bars are above 7.34%.{(" " + str(det["excluded_unreliable_percent"]) + " more formulas with homosalate were left out because their structured label data lists an active ingredient above its US legal maximum, so their percentages cannot be trusted.") if det["excluded_unreliable_percent"] else ""}</p></section>"""
        faq = [
            ("Are these sunscreens illegal?", f["legal_framing"]),
            ("What is the EU limit for homosalate?",
             "7.34%, and only in face products other than propellant sprays, under Regulation (EU) 2022/2195. "
             "Non-compliant products could not be made available on the EU market from July 1, 2025."),
            ("How were these products selected?", howto),
        ]
    elif key == "same-ingredient-list":
        det = f["detail"]
        us = _lim(d, "zinc-oxide", "US")
        rows = "".join(
            f'<tr><td><a href="{E(p["baby"][1])}" rel="noopener" target="_blank"><span class="pname">{E(html.unescape(p["baby"][0]))}</span></a></td><td>'
            + "<br>".join(f'<a href="{E(u)}" rel="noopener" target="_blank"><span class="pname">{E(html.unescape(t))}</span></a>' for t, u in p["same_list"])
            + f'</td><td>{"Yes" if p["same_company"] else "Different name"}</td></tr>' for p in det["pairs"])
        mean = f"""
<p>The US sunscreen monograph sets one limit per active ingredient. It has no separate formula rules for products labeled for babies or kids. {src_chip("FDA M020", us["source"]["url"], us["source"]["title"])}</p>
<p>So a baby or kids label can carry exactly the same formula as another sunscreen. This finding counts how often the Drug Facts of a baby or kids label, as filed with the FDA, match another label item for item.</p>"""
        extra = f"""<section><p class="eyebrow">Every pair</p><h2>The labels, side by side</h2>
<div class="tablewrap"><table class="pairs"><thead><tr><th>Baby or kids label</th><th>Same ingredients as</th><th>Same labeler</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="fine">Each name links to its FDA DailyMed record. <a href="{E(det["pairs_csv"])}">Download the list (CSV)</a>.</p></section>"""
        faq = [
            ("Is it wrong to sell the same formula under a baby label?", f["legal_framing"]),
            ("How was \"the same\" decided?",
             "Both labels list the same active ingredients at the same percentages, have the same product form, and print "
             "the same inactive ingredients in the same order in their Drug Facts (at least five). The other label does not "
             "say baby or kids in its name or on its front panel. Labels whose printed list could not be read were left out. "
             "The SPF number printed on the two labels can differ."),
            ("How were these products selected?", howto),
        ]
    elif key == "eu-banned-preservatives":
        det = f["detail"]
        ec = det["eu_cosmetic_source"]
        rows = "".join(
            f'<tr><td><b>{E(x["name"])}</b></td><td class="num">{x["count"]}</td>'
            f'<td>{E(x["rule"])} {src_chip("EU law", x["source"]["url"], x["source"]["title"])}</td></tr>'
            for x in det["ingredients"])
        frows = "".join(
            f'<tr><td><a href="{E(p["url"])}" rel="noopener" target="_blank"><span class="pname">{E(html.unescape(p["title"]))}</span></a></td>'
            f'<td>{E(", ".join(p["ingredients"]))}</td><td>{E(p["label_date"])}</td><td>{E(", ".join(p["listed_in"]))}</td></tr>'
            for p in det["formulas"])
        mean = f"""
<p>In the EU, a sunscreen is a cosmetic, so EU cosmetics law decides which preservatives it may contain. {src_chip("EU law", ec["url"], ec["title"])}</p>
<p>The EU has banned isobutylparaben from all cosmetics and methylisothiazolinone from leave-on cosmetics, which include sunscreens. US rules for sunscreen inactive ingredients have no such ban. This finding counts baby and kids labels in DailyMed that list either one.</p>"""
        extra = f"""<section><p class="eyebrow">Two preservatives</p><h2>What the EU decided, and how many labels list each</h2>
<div class="tablewrap"><table class="pairs"><thead><tr><th>Ingredient</th><th>Formulas</th><th>EU rule</th></tr></thead><tbody>{rows}</tbody></table></div></section>
<section><p class="eyebrow">Every formula</p><h2>The {f["numerator"]} labels</h2>
<div class="tablewrap"><table class="pairs"><thead><tr><th>Baby or kids label</th><th>Lists</th><th>Label version date</th><th>Where it is listed</th></tr></thead><tbody>{frows}</tbody></table></div>
<p class="fine">Each name links to its FDA DailyMed record. The date is that of the label version currently in DailyMed; an old label date does not show whether the product is still sold.</p></section>"""
        faq = [
            ("Are these products illegal?", f["legal_framing"]),
            ("What exactly did the EU ban?",
             "Isobutylparaben was added to the list of substances banned in cosmetics by Commission Regulation (EU) No 358/2014; "
             "products containing it could no longer be made available on the EU market from July 30, 2015. "
             "Methylisothiazolinone was limited to rinse-off products by Commission Regulation (EU) 2016/1198, so leave-on "
             "products containing it could no longer be made available from February 12, 2017."),
            ("Are other parabens banned too?",
             "This finding counts only isobutylparaben among the parabens. The same EU regulation also banned isopropylparaben, "
             "phenylparaben, benzylparaben and pentylparaben; "
             + ("none of the baby and kids labels lists them. " if not det["other_banned_parabens_found"]
                else f"{det['other_banned_parabens_found']} baby and kids formulas list one of them and are not counted here. ")
             + "Methylparaben, "
             "ethylparaben, propylparaben and butylparaben remain allowed in the EU within limits."),
            ("How were these products selected?", howto),
        ]
    elif key == "fragrance":
        det = f["detail"]
        (mn, md), (on, od) = det["mineral"], det["other"]
        frows = "".join(
            f'<tr><td><a href="{E(p["url"])}" rel="noopener" target="_blank"><span class="pname">{E(html.unescape(p["title"]))}</span></a></td>'
            f'<td>{"Mineral only" if p["mineral"] else "Other filters"}</td><td>{E(", ".join(p["listed_in"]))}</td></tr>'
            for p in det["formulas"])
        mean = f"""
<p>For children with eczema, the American Academy of Dermatology advises a sunscreen that is fragrance-free, and advises choosing fragrance-free rather than unscented products. {src_chip("AAD", isrc["url"], isrc["title"])}</p>
<p>This finding counts the baby and kids sunscreen labels whose ingredient list names fragrance, parfum or perfume. It is about what the labels say, not about any brand.</p>"""
        extra = f"""<section><p class="eyebrow">Mineral and other filters</p><h2>Fragrance by type of sunscreen</h2>
<ul class="bars"><li><span>Mineral only</span><span class="bar"><i style="width:{100 * mn / md:.1f}%"></i></span><b>{mn} of {md}</b></li>
<li><span>Other filters</span><span class="bar"><i style="width:{100 * on / od:.1f}%"></i></span><b>{on} of {od}</b></li></ul>
<p class="fine">Not counted: {E(det["not_counted"])}.</p>
<p>In {det["printed_only"]} of the {f["numerator"]}, fragrance appears on the printed label but not in the ingredient list the labeler filed with the FDA. Apps and databases that read only the filed list will not see it.</p></section>
<section><p class="eyebrow">Every formula</p><h2>The {f["numerator"]} labels</h2>
<div class="tablewrap"><table class="pairs"><thead><tr><th>Baby or kids label</th><th>Type</th><th>Where it is listed</th></tr></thead><tbody>{frows}</tbody></table></div>
<p class="fine">Each name links to its FDA DailyMed record.</p></section>"""
        faq = [
            ("Is fragrance allowed in baby sunscreen?", f["legal_framing"]),
            ("What does the American Academy of Dermatology say?",
             "For children with eczema, it advises a sunscreen that is fragrance-free, with titanium dioxide and/or zinc oxide, "
             "broad-spectrum protection and SPF 30 or higher, and it advises choosing fragrance-free rather than unscented products."),
            ("Why do some FDA records not show the fragrance?",
             f"In {det['printed_only']} of the {f['numerator']} formulas, fragrance is printed on the label's Drug Facts but is "
             "missing from the ingredient list the labeler filed with the FDA. We count what either the printed label or the "
             "filing lists, and the printed label decides when the two disagree."),
            ("Do mineral sunscreens contain fragrance?",
             f"Some do: {mn} of the {md} mineral-only baby and kids formulas list fragrance, against {on} of the {od} formulas that use other filters."),
            ("How were these products selected?", howto),
        ]
    elif key == "hawaii-oxybenzone-octinoxate":
        det = f["detail"]
        mx = max(v for _, v in det["per_filter"])
        bars = "".join(f'<li><a href="{BASE}/ingredients/{E(n)}">{E(n)}</a><span class="bar"><i style="width:{100 * v / mx:.1f}%"></i></span><b>{v}</b></li>'
                       for n, v in det["per_filter"])
        frows = "".join(
            f'<tr><td><a href="{E(p["url"])}" rel="noopener" target="_blank"><span class="pname">{E(html.unescape(p["title"]))}</span></a></td>'
            f'<td>{E(", ".join(p["filters"]))}</td><td>{E(p["label_date"])}</td></tr>' for p in det["formulas"])
        mean = f"""
<p>Hawaii law says that beginning January 1, 2021, it is unlawful to sell, offer for sale or distribute for sale in the state any sunscreen that contains oxybenzone or octinoxate, or both, without a prescription issued by a licensed healthcare provider. {src_chip("HRS §342D-21", isrc["url"], isrc["title"])} {src_chip("Act 104 text", det["act_text"]["url"], det["act_text"]["title"])}</p>
<p>Both remain permitted active ingredients under the FDA sunscreen monograph, and both are among the 12 ingredients the FDA has proposed need more safety data. {src_chip("FDA", FDA_QA_URL, "FDA Q&A on OTC sunscreen")}</p>"""
        extra = f"""<section><p class="eyebrow">Which filter</p><h2>How many of the {f["denominator"]} formulas list each one</h2>
<ul class="bars">{bars}</ul>
<p class="fine">{det["both"]} formulas contain both. The newest label version of {det["label_updated_since_2021"]} of the {f["numerator"]} is dated 2021 or later.</p></section>
<section><p class="eyebrow">Every formula</p><h2>The {f["numerator"]} labels</h2>
<div class="tablewrap"><table class="pairs"><thead><tr><th>Baby or kids label</th><th>Filter</th><th>Label version date</th></tr></thead><tbody>{frows}</tbody></table></div>
<p class="fine">Each name links to its FDA DailyMed record. The label version date is the date of the newest version in DailyMed; it does not show whether, or where, the product is still sold.</p></section>"""
        faq = [
            ("Are these sunscreens illegal?", f["legal_framing"]),
            ("What does Hawaii's law prohibit?",
             "From January 1, 2021, selling, offering for sale or distributing for sale in Hawaii a sunscreen that contains "
             "oxybenzone or octinoxate, or both, without a prescription issued by a licensed healthcare provider."),
            ("How were these products selected?", howto),
        ]
    elif key == "parabens":
        det = f["detail"]
        mx = max(v for _, v in det["per_paraben"])
        bars = "".join(f'<li><span>{E(n)}</span><span class="bar"><i style="width:{100 * v / mx:.1f}%"></i></span><b>{v}</b></li>'
                       for n, v in det["per_paraben"])
        frows = "".join(
            f'<tr><td><a href="{E(p["url"])}" rel="noopener" target="_blank"><span class="pname">{E(html.unescape(p["title"]))}</span></a></td>'
            f'<td>{E(", ".join(p["parabens"]))}</td></tr>' for p in det["formulas"])
        mean = f"""
<p>Parabens are preservatives. In the US they are allowed in sunscreens. In the EU, isobutylparaben is banned from all cosmetics. {src_chip("EU 358/2014", "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32014R0358", "Commission Regulation (EU) No 358/2014")}</p>
<p>The EU also limits propylparaben and butylparaben to 0.14% combined, and does not allow them in leave-on products designed for the nappy area of children under three. {src_chip("EU 1004/2014", isrc["url"], isrc["title"])} Sunscreen labels do not state paraben percentages, so the 0.14% limit cannot be checked from them.</p>"""
        extra = f"""<section><p class="eyebrow">Which parabens</p><h2>How many of the {f["denominator"]} formulas list each one</h2>
<ul class="bars">{bars}</ul>
<p class="fine">One formula can contain several. {det["mineral"][0]} of the {det["mineral"][1]} mineral formulas list a paraben.</p></section>
<section><p class="eyebrow">Every formula</p><h2>The {f["numerator"]} labels</h2>
<div class="tablewrap"><table class="pairs"><thead><tr><th>Baby or kids label</th><th>Parabens listed</th></tr></thead><tbody>{frows}</tbody></table></div>
<p class="fine">Each name links to its FDA DailyMed record.</p></section>"""
        faq = [
            ("Are parabens allowed in baby sunscreen?", f["legal_framing"]),
            ("How were these products selected?", howto),
        ]
    else:  # spf-boosters
        det = f["detail"]
        mx = max(x["count"] for x in det["ingredients"])
        rows = "".join(
            f'<tr><td><b>{E(x["name"])}</b></td><td class="num">{x["count"]}</td><td class="num">{x["mineral"]}</td>'
            f'<td>{E(x["function"])} {src_chip("Source", x["source"]["url"], x["source"]["title"])}</td></tr>'
            for x in det["ingredients"])
        frows = "".join(
            f'<tr><td><a href="{E(p["url"])}" rel="noopener" target="_blank"><span class="pname">{E(html.unescape(p["title"]))}</span></a></td>'
            f'<td>{"Mineral" if p["mineral"] else "Other"}</td><td>{E(", ".join(p["boosters"]))}</td></tr>' for p in det["formulas"])
        mean = f"""
<p>A mineral sunscreen's active ingredients are zinc oxide and/or titanium dioxide. On a US sunscreen, the Active ingredients section of the Drug Facts label lists only FDA sunscreen actives. {src_chip("21 CFR 201.66", DRUG_FACTS["url"], DRUG_FACTS["title"])}</p>
<p>Ingredients that help reach the labeled SPF but are not FDA sunscreen actives therefore appear under Inactive ingredients. This finding counts six of them, each with its manufacturer's or regulator's own description, in the full ingredient lists of baby and kids sunscreens. In mineral formulas they matter most, because parents reading only the Active ingredients section see zinc oxide and/or titanium dioxide alone. {det["mineral"][0]} of the {det["mineral"][1]} mineral formulas contain at least one. It is about how labels work, not about any brand.</p>"""
        extra = f"""<section><p class="eyebrow">Six ingredients</p><h2>How many of the {f["denominator"]} formulas list each one</h2>
<div class="tablewrap"><table class="pairs"><thead><tr><th>Ingredient</th><th>All formulas</th><th>Mineral formulas</th><th>What its maker or regulator says it does</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="fine">One formula can contain several; {det["two_or_more"]} contain two or more. Counted in {E(det["lists_used"])}.</p></section>
<section><p class="eyebrow">Every formula</p><h2>The {f["numerator"]} labels</h2>
<div class="tablewrap"><table class="pairs"><thead><tr><th>Baby or kids label</th><th>Type</th><th>Booster ingredients listed</th></tr></thead><tbody>{frows}</tbody></table></div>
<p class="fine">Each name links to its FDA DailyMed record.</p></section>"""
        faq = [
            ("Does this mean these products break the law?", f["legal_framing"]),
            ("Is a mineral sunscreen with these ingredients still a mineral sunscreen?",
             "Yes. Its active ingredients are only zinc oxide and/or titanium dioxide. These six ingredients are not "
             "FDA sunscreen actives, so they appear under Inactive ingredients. Parents reading only the Active "
             "ingredients section will not see them there."),
            ("Which ingredients were counted?",
             "; ".join(f'{x["name"]}: {x["function"]}' for x in det["ingredients"])),
            ("How were these products selected?", howto),
        ]
    return mean, extra, faq, howto


def finding_card(f, big=True):
    meta = FINDINGS[f["finding"]]
    cols = 30 if f["denominator"] > 200 else 21
    if big:
        return f"""<div class="card finding">
 <div><div class="fig">{f["numerator"]}<small>of {f["denominator"]}</small></div>
 {units(f["numerator"], f["denominator"], cols, f'{f["numerator"]} of {f["denominator"]}')}
 <p class="fine">{E(meta["caption"])}</p></div>
 <div><p class="eyebrow">{E(meta["eyebrow"])}</p><p class="sentence">{E(f["sentence"])}</p>
 <a class="more" href="{BASE}/findings/{f["finding"]}">Read the finding →</a></div></div>"""
    return f"""<a class="card mini" href="{BASE}/findings/{f["finding"]}">
 <p class="eyebrow">{E(meta["eyebrow"])}</p><div class="fig">{f["numerator"]}<small>of {f["denominator"]}</small></div>
 <h3>{E(meta["title"])}</h3><span class="more">Read the finding →</span></a>"""


def ordered_findings(d):
    order = list(FINDINGS)
    return sorted(d["findings"], key=lambda f: order.index(f["finding"]) if f["finding"] in order else 99)


def page_finding(d, f):
    s, isrc = f["source"], f.get("ingredient_source") or {}
    meta = FINDINGS[f["finding"]]
    title = meta["title"]
    mean, extra, faq, howto = finding_body(d, f)
    faqh = "".join(f"<details><summary>{E(q)}</summary><p>{E(a)}</p></details>" for q, a in faq)
    src_label = {"fda-more-data": "FDA source", "hawaii-oxybenzone-octinoxate": "Hawaii law", "fragrance": "AAD guidance", "parabens": "EU law", "eu-banned-preservatives": "EU law",
                 "homosalate-eu-limit": "EU law", "eu-banned-preservatives": "EU law",
                 "fragrance": "AAD guidance"}.get(f["finding"], "Source")
    body = f"""
<p class="crumb"><a href="{BASE}">Library</a> / <a href="{BASE}/findings">Findings</a></p>
<div class="hero" style="padding-top:28px"><p class="eyebrow">{E(meta["eyebrow"])}</p>
<h1>{E(title)}</h1>
<p class="byline">By Angela Lee, Founder · ARW House · Updated {E(fmt_date(d["built_on"]))}</p></div>
<section><div class="card finding">
 <div><div class="fig">{f["numerator"]}<small>of {f["denominator"]}</small></div>
 {units(f["numerator"], f["denominator"], 30 if f["denominator"] > 200 else 21, f'{f["numerator"]} of {f["denominator"]}')}
 <p class="fine">{E(meta["caption"])}</p></div>
 <div><p class="sentence">{E(f["sentence"])}</p>
 <div class="chips">{src_chip(src_label, isrc["url"], isrc.get("title", "")) if isrc.get("url") else ""}{src_chip("Registry data", s["url"])}{src_chip("Review file", s["list_url"])}{src_chip("Method", s["method_url"])}</div>
 <p class="framing">{E(f["legal_framing"])}</p>
 <p class="fine">{E(f["caveat"])}</p></div></div></section>
{extra}
<section class="cols prose"><div><h2>What this means</h2>{mean}</div>
<div><h2>How we counted</h2><p>{E(howto)} DailyMed snapshot {E(d["registry_population"]["snapshot"])}.</p>
<p><a href="{E(s["list_url"])}">Every include and exclude decision, with its reason</a> · <a href="{E(s["method_url"])}">The counting script</a> · <a href="{REPO}/blob/main/data/corrections/spl_label_errors.jsonl">Label errors we corrected</a></p></div></section>
<section><h2>Questions</h2>{faqh}</section>"""
    path = f"{BASE}/findings/{f['finding']}"
    ld = [{"@context": "https://schema.org", "@type": "Dataset", "name": title, "description": f["sentence"],
           "url": SITE + path, "dateModified": d["built_on"], "creator": org(), "author": person(),
           "isBasedOn": [u for u in (s["url"], s["list_url"], isrc.get("url", "")) if u],
           "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": SITE + BASE + "/data.json"}]},
          {"@context": "https://schema.org", "@type": "FAQPage",
           "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}]
    return path, shell(path, f"{title} · ARW House Evidence", f["sentence"], body, ld, "Findings")


def page_findings_index(d):
    fs = ordered_findings(d)
    cards = "".join(f'<section>{finding_card(f)}</section>' for f in fs)
    body = f"""
<div class="hero"><p class="eyebrow">Findings</p><h1>What the labels show, <em>counted.</em></h1>
<p class="lede">Each finding is a count of baby and kids sunscreen labels in the FDA's DailyMed database, checked against the rules that apply to them. Every number links to its data and every rule to its source.</p>
<p class="byline">By Angela Lee, Founder · ARW House · Updated {E(fmt_date(d["built_on"]))}</p></div>
{cards}"""
    path = f"{BASE}/findings"
    ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": "Findings — ARW House Evidence",
           "url": SITE + path, "dateModified": d["built_on"], "author": person(), "publisher": org(),
           "hasPart": [{"@type": "Dataset", "name": FINDINGS[f["finding"]]["title"], "url": f"{SITE}{BASE}/findings/{f['finding']}"} for f in fs]}]
    return path, shell(path, "Findings — baby sunscreen labels, counted · ARW House Evidence",
                       "Counts of baby and kids sunscreen labels in FDA DailyMed checked against FDA and EU rules, each linked to its data and sources.",
                       body, ld, "Findings")


def page_method(d, notes):
    pop = d["registry_population"]
    srcs = {}
    for i in d["ingredients"]:
        for l in i["limits"]:
            s = l["source"]
            srcs.setdefault(s["url"], (s.get("title", ""), s.get("version", ""), JUR_NAME[l["jurisdiction"]]))
            if l.get("status_source_url"):
                srcs.setdefault(l["status_source_url"], ("FDA Final Administrative Order OTC000008-1 (aminobenzoic acid and trolamine salicylate)", "", "United States"))
    for n in notes:
        srcs.setdefault(n["source"]["url"], (n["source"]["title"], n["source"].get("version", ""), ""))
    for f in d["findings"]:
        if f.get("ingredient_source"):
            srcs.setdefault(f["ingredient_source"]["url"], (f["ingredient_source"]["title"], "checked " + f["ingredient_source"].get("checked", ""), ""))
    srcs.setdefault(DRUG_FACTS["url"], (DRUG_FACTS["title"], "eCFR, current", "United States"))
    srch = "".join(f'<li><a href="{E(u)}" rel="noopener" target="_blank">{E(t)}</a><span>{E(" · ".join(x for x in (j, v) if x))}</span></li>'
                   for u, (t, v, j) in srcs.items())
    body = f"""
<div class="hero"><p class="eyebrow">Method</p><h1>How every number <em>here is made.</em></h1>
<p class="lede">These pages are rebuilt every week from public regulatory texts and the FDA's DailyMed label database. No number is typed by hand.</p>
<p class="byline">By Angela Lee, Founder · ARW House · Updated {E(fmt_date(d["built_on"]))}</p></div>
<section class="cols prose"><div><h2>Limits</h2>
<p>Each legal limit comes from the regulatory text of its jurisdiction: the FDA's OTC sunscreen monograph (M020) and its final orders, Annex VI of the EU Cosmetics Regulation, and Australia's Permissible Ingredients Determination. Each limit on this site links to the exact document and version it was read from.</p>
<p>Some statuses depend on a date. When an FDA removal order takes effect, the status changes on the next weekly rebuild.</p></div>
<div><h2>Label counts</h2>
<p>Population: {E(pop["definition"])}. {pop["formulations"]} unique formulations, {pop["mineral_only"]} with only mineral actives. Labels with the same active ingredients at the same percentages, the same inactive ingredients and the same form (lotion, cream, stick, spray) are counted once; pump and aerosol sprays count as one form because filers code them inconsistently. DailyMed snapshot {E(pop["snapshot"])}.</p>
<p>DailyMed lists drug labels submitted to the FDA, including labels for products made in US facilities for other markets. A listing is not proof that a product is on US shelves today.</p>
<p>Left out of the counts, by rule: labels for another market, labels that do not meet US sunscreen limits as listed (an active above its US limit, or an active not permitted in the US), and listings that bundle several products. <a href="{REPO}/blob/main/claims/population_exclusions.csv">Every label left out, with its reason</a>. Where a manufacturer's structured filing contradicts its own Drug Facts, the Drug Facts are used: <a href="{REPO}/blob/main/data/corrections/spl_label_errors.jsonl">corrections</a>.</p>
<p>Inactive ingredients are counted from two lists: the one the labeler filed with the FDA, and the one printed in the label's Drug Facts. When the printed list is readable as text, it decides: an ingredient that appears only in the filing is not counted. When the printed list is only an image, it is transcribed from the label image twice, independently, and used once both readings agree; <a href="{REPO}/blob/main/data/corrections/printed_lists_from_images.jsonl">every transcription, with its image</a>. Labels whose image shows no list (some print only a QR code) or is illegible fall back to the filing. Every finding table shows where each ingredient was listed.</p>
<p>Formula changes are tracked weekly from the filing, and changes to the printed inactive list are tracked separately for baby and kids labels. Inactive-ingredient percentages are not printed on US labels, so a change in proportions alone cannot be seen.</p>
<p><a href="{REPO}/blob/main/claims/{E(pop["review_file"])}">Review file</a> · <a href="{REPO}/blob/main/claims/registry_stats.py">Counting script</a> · <a href="{REPO}/blob/main/docs/SITE_DATA_CONTRACT.md">Publishing rules</a></p></div></section>
<section class="cols prose"><div><h2>What we will not publish</h2>
<p>A sentence about what an ingredient does, unless a source for that exact ingredient says it. A number that has not passed its check. A ranking or a recommendation of products.</p></div>
<div><h2>Corrections</h2><p>If you find an error, write to angela@arwhouse.com with the page and the source. Fixes go into the data first, then into every page on the next rebuild.</p></div></section>
<section><h2>Sources</h2><ul class="srclist">{srch}</ul></section>"""
    path = f"{BASE}/methodology"
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": "Method — ARW House Evidence", "url": SITE + path,
           "dateModified": d["built_on"], "author": person(), "publisher": org(), "citation": list(srcs)}]
    return path, shell(path, "Method — how every number is made · ARW House Evidence",
                       "How ARW House builds its baby sunscreen evidence pages: regulatory sources, DailyMed label counts, and publishing rules.",
                       body, ld, "Method")


# ---------------------------------------------------------------- build
def check(pages, d, notes):
    errs = []
    for n in notes:
        if not (n.get("source") or {}).get("url"):
            errs.append(f"note {n.get('id')}: no source url")
    for f in d["findings"]:
        if (f["finding"] == "fda-more-data" and FINDINGS["fda-more-data"]["title"].startswith("Over half")
                and not f["numerator"] * 2 > f["denominator"]):
            errs.append("fda-more-data title says 'Over half' but the share is not above 50%")
        if f["finding"] not in FINDING_TITLES:
            errs.append(f"finding {f['finding']}: no title in FINDING_TITLES")
    n_limits = sum(len(i["limits"]) for i in d["ingredients"])
    for path, h in pages.items():
        # product names are quoted data, not our wording: exempt from the phrase check
        text = re.sub(r"<script.*?</script>|<style.*?</style>|<span class=\"pname\">.*?</span>", " ", h, flags=re.S)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text)).lower()
        ld = " ".join(re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)).lower()
        for p in FORBIDDEN:
            if p in text or p in ld:
                errs.append(f"{path}: forbidden phrase {p!r}")
        # Owner rule 2026-10-08: every word and every link on the site is English.
        foreign = sorted({c for c in h if c.isalpha() and not c.isascii()
                          and not unicodedata.name(c, "").startswith("LATIN")})
        if foreign:
            errs.append(f"{path}: non-English letters {''.join(foreign)[:20]!r}")
        if any(not u.isascii() for u in re.findall(r'href="([^"]*)"', h)):
            errs.append(f"{path}: non-ASCII link")
        if 'href=""' in h:
            errs.append(f"{path}: empty link")
    idx = pages[BASE]
    chips = idx.count('class="chip"')
    if chips < n_limits:
        errs.append(f"index: {chips} source chips for {n_limits} limits")
    return errs


def share_words(n, d):
    """Plain-English share that is true for n/d; never rounds up past a threshold."""
    x = n / d
    if x > 0.5:
        return "Over half"
    if x >= 0.45:
        return "Nearly half"
    if x > 1 / 3:
        return "Over a third"
    return f"{n} of {d}"


def main():
    d = json.load(open(EVIDENCE, encoding="utf-8"))
    for f in d["findings"]:
        if f["finding"] == "fda-more-data":
            t = FINDINGS["fda-more-data"]["title"].split(" of baby", 1)[1]
            FINDINGS["fda-more-data"]["title"] = share_words(f["numerator"], f["denominator"]) + " of baby" + t
            FINDING_TITLES["fda-more-data"] = FINDINGS["fda-more-data"]["title"]
    notes = json.load(open(NOTES, encoding="utf-8"))["notes"]
    pages = {BASE: page_index(d, notes)}
    ings = d["ingredients"]
    for k, i in enumerate(ings):
        p, h = page_ingredient(d, i, ings[k - 1] if k else None, ings[k + 1] if k + 1 < len(ings) else None, notes)
        pages[p] = h
    for f in ordered_findings(d):
        p, h = page_finding(d, f)
        pages[p] = h
    p, h = page_findings_index(d)
    pages[p] = h
    p, h = page_method(d, notes)
    pages[p] = h
    errs = check(pages, d, notes)
    if errs:
        print("RENDER CHECK FAILED:\n  " + "\n  ".join(errs))
        if "--check" in sys.argv:
            sys.exit(1)
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)  # stale pages (a withdrawn finding) must disappear
    for path, h in pages.items():
        rel = path[len(BASE):].strip("/")
        fp = os.path.join(OUT, (rel + ".html") if rel else "index.html")
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "w", encoding="utf-8").write(h)
    shutil.copyfile(EVIDENCE, os.path.join(OUT, "data.json"))
    urls = "".join(f"<url><loc>{SITE}{p}</loc><lastmod>{d['built_on']}</lastmod></url>" for p in pages)
    open(os.path.join(OUT, "sitemap.xml"), "w").write(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    print(f"rendered {len(pages)} pages into {OUT} ({'checks passed' if not errs else 'WITH ERRORS'})")


if __name__ == "__main__":
    main()
