#!/usr/bin/env python3
"""arwhouse.com/sunnytime/how-we-check: the written rules behind the Sunscreen Check,
generated from the same files the check uses (flags_v31.json meta, rules_changelog.json,
the ingredient dictionary), so the page cannot drift from what the check does.

Usage: site_rules_page.py <arwhouse checkout>
"""
import html
import json
import re
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
META = json.load(open(os.path.join(ROOT, "data/reference/flags_v31.json")))["meta"]
LOG = json.load(open(os.path.join(ROOT, "data/reference/rules_changelog.json")))["changes"]

LIB = json.load(open(os.path.join(ROOT, "data/reference/evidence_library.json")))
SRC = LIB["sources"]
# the result card, in the order it shows (approved 2026-10-25)
LAYOUT = [
    ("At a glance", "The same checks on every product, in the same order, so two sunscreens can be compared side by side: "
     "FDA recall, Broad Spectrum, the UV filters (mineral or chemical), spray or powder, an age limit or adult skincare active, "
     "fragrance, and a possible SPF booster listed as an inactive ingredient."),
    ("About the UV filters", "Each chemical filter on the label, with its official limits in the US and the EU, and where state or county law bans its sale."),
    ("Label check", "What the label itself shows: a UV filter listed as an inactive, a fragrance-free claim next to a fragrance, an ingredient banned in EU cosmetics."),
    ("Check for your child", "Ingredients that matter mainly for some children. Tap Eczema, Psoriasis, Food allergy or Under 3 and the ones that apply are highlighted, with the guidance written for that situation."),
    ("Other ingredients some parents ask about", "Ingredients parents often ask about, with the official findings we found for each. Listed because parents ask, not because a rule flags them."),
]
COLOURS = [("Green", "the check found nothing of that kind on the label"),
           ("Amber", "pediatric or dermatology guidance (AAP, AAD) applies, the product is above an EU limit, an EU rule restricts the ingredient for young children, or the item matches what you told us about your child"),
           ("Blue", "a fact to know: where a law bans its sale, how a rule elsewhere treats it, a study finding, or something the label leaves unclear"),
           ("Red", "an FDA recall, an FDA order or warning that removes the ingredient or product type, or a combination pediatricians advise against")]
GROUP_TITLES = [("glance", "At a glance"), ("safety", "FDA orders and pediatric guidance"), ("filters", "UV filters"),
                ("fact", "Laws on sale and SPF"), ("label", "Label check"), ("child", "Check for your child"),
                ("profile", "Eczema and psoriasis"), ("pref", "Other ingredients some parents ask about")]
COVERED = {"chemical_filter_active", "spray_powder", "not_broad_spectrum", "age_limit", "fragrance", "essential_oil",
           "eu_fragrance_allergen", "recall", "insect_repellent", "mi_mci", "formaldehyde_releaser", "propyl_butyl_paraben",
           "retinoid", "citrus_photosensitizer", "lanolin", "capb", "propylene_glycol", "drying_alcohol", "phenoxyethanol",
           "ethoxylated", "bht_bha", "talc", "petrolatum_mineral_oil", "fragrance_free_conflict", "water_resistant",
           "peanut", "tree_nut", "soy", "wheat", "milk", "egg", "sesame", "fish_shellfish", "oat", "hidden_uv_booster"}
CLEAN = re.compile(r"\s*\([^()]*(verif|fetch|mirror|checked|not read|title/volume)[^()]*\)", re.I)


def e(s):
    return html.escape(s or "", quote=True)


def src_html(k):
    s = SRC.get(k)
    if not s:
        return ""
    return (f' <a class="srcl" href="{e(s["url"])}" rel="noopener">{e(s["org"])} · {e(s["date"])}</a>'
            + (f' <span class="st">{e(s["strength"])}</span>' if s.get("strength") else ""))


def facts(arr):
    out = []
    for x in arr or []:
        t = x["t"]
        if "{" in t:      # filled per product on the card
            t = (t.replace("{names}", "the ingredient named on the card")
                  .replace("{status}", "Its status as a UV filter in the US, the EU and Australia is shown on the card."))
        out.append(f"<li>{e(t)}{src_html(x.get('s'))}</li>")
    return "".join(out)


def topic_html(t):
    h = f'<details><summary>{e(t["title"])}</summary><ul class="f">{facts(t.get("facts"))}</ul>'
    if t.get("other_side"):
        h += f'<p class="osh">What points the other way</p><ul class="f">{facts(t["other_side"])}</ul>'
    if t.get("not_known"):
        h += '<p class="osh">Not known</p><ul class="f">' + "".join(f"<li>{e(x)}</li>" for x in t["not_known"]) + "</ul>"
    return h + "</details>"


def main():
    site = sys.argv[1]
    layout = "".join(f"<li><b>{e(a)}.</b> {e(b)}</li>" for a, b in LAYOUT)
    colours = "".join(f"<li><b>{e(a)}</b>: {e(b)}.</li>" for a, b in COLOURS)
    by = {}
    for t in LIB["topics"]:
        by.setdefault(t["group"], []).append(t)
    parts = []
    for g, title in GROUP_TITLES:
        if by.get(g):
            parts.append(f'<h3>{e(title)}</h3>' + "".join(topic_html(t) for t in by[g]))
    other = "".join(
        f'<details><summary>{e(v["l"])}</summary><p>{e(v.get("w"))}</p><span class="src">Source: {e(CLEAN.sub("", v.get("s") or ""))}</span>'
        + ('<span class="src">This flag is our own judgment, not an official rule.</span>' if v.get("basis") == "judgment" else "")
        + "</details>"
        for k, v in META.items() if k not in COVERED and v.get("t") in ("T1", "T2", "T3") and v.get("w"))
    log = "".join(f'<li><b>{e(c["version"])} · {e(c["date"])}</b> {e(c["change"])} <span class="why">{e(c.get("why"))}</span></li>'
                  for c in LOG)
    page = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Sunnytime — How the Sunscreen Check works</title>
<meta name="description" content="How the Sunnytime Sunscreen Check works: how a result is laid out, every fact it shows with its official source, and how the data is checked. The same rules for every brand, including ours.">
<link rel="canonical" href="https://arwhouse.com/sunnytime/how-we-check">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600&display=swap" rel="stylesheet">
<style>
:root{{box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);--paper:#FAFAF7;--ink:#141613;--ink2:#3A4238;--grey:#7A8276;--hair:#E6E8E0;--sage:#3B6D11;--sage-deep:#173404;--sage-tint:#DEEAD0}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--paper:#171A16;--ink:#F1F0EA;--ink2:#C9CCC3;--grey:#9AA094;--hair:#2A2E28;--sage-tint:#2E3A24}}}}
:root[data-theme="dark"]{{--paper:#171A16;--ink:#F1F0EA;--ink2:#C9CCC3;--grey:#9AA094;--hair:#2A2E28;--sage-tint:#2E3A24}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:"DM Sans",-apple-system,BlinkMacSystemFont,Helvetica,Arial,sans-serif;line-height:1.5;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:720px;margin:0 auto;padding:28px max(22px,env(safe-area-inset-right,0px)) 90px max(22px,env(safe-area-inset-left,0px))}}
nav{{display:flex;align-items:center;justify-content:space-between;margin-bottom:40px}}
.word{{font-weight:500;letter-spacing:-.01em;font-size:17px;text-decoration:none;color:var(--ink)}}
.back{{font-size:14px;color:var(--ink2);text-decoration:none}}
h1{{font-size:clamp(34px,6vw,52px);line-height:1.02;letter-spacing:-.03em;font-weight:500;margin:0 0 10px}}
.lead{{color:var(--ink2);font-size:17px;max-width:56ch;margin:0 0 28px}}
h2{{font-size:22px;font-weight:500;letter-spacing:-.02em;margin:44px 0 6px}}
.sub{{color:var(--ink2);font-size:15px;margin:0 0 14px;max-width:62ch}}
p{{max-width:62ch}}
ul{{padding-left:20px;color:var(--ink2);max-width:62ch}} li{{margin-bottom:8px}}
details{{border-top:1px solid var(--hair);padding:12px 0}}
details:last-of-type{{border-bottom:1px solid var(--hair)}}
summary{{cursor:pointer;font-size:16px;font-weight:500;list-style:none;display:flex;justify-content:space-between;gap:12px}}
summary::-webkit-details-marker{{display:none}}
summary::after{{content:"+";color:var(--sage);font-weight:400;flex:0 0 auto}}
details[open] summary::after{{content:"–"}}
summary:focus-visible{{outline:2px solid var(--sage);outline-offset:4px;border-radius:4px}}
details p{{margin:8px 0 0;color:var(--ink2)}}
.src{{display:block;margin-top:6px;font-size:13px;color:var(--grey)}}
.why{{display:block;color:var(--grey);font-size:14px;margin-top:2px}}
.box{{background:var(--sage-tint);border-radius:16px;padding:16px 18px;margin:0 0 8px}}
.box p{{margin:0}}
footer{{margin-top:60px;font-size:13px;color:var(--grey)}}
a{{color:var(--sage)}}
h3{{font-size:17px;font-weight:600;margin:28px 0 4px}}
ul.f{{margin:8px 0 0;padding-left:18px}} ul.f li{{margin-bottom:6px;color:var(--ink2)}}
.srcl{{font-size:12.5px;color:var(--sage);white-space:nowrap}}
.st{{font-size:11.5px;color:var(--grey)}}
.osh{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--grey);margin:12px 0 0}}
</style>
</head>
<body>
<div class="wrap">
<nav><a class="word" href="/sunnytime">sunnytime</a><a class="back" href="/sunnytime#check">← Back to the Check</a></nav>
<h1>How the Check works.</h1>
<p class="lead">We don't score or rank sunscreens. We read every label the FDA has on file, the printed Drug Facts and the filing behind it, and show what we find as facts, each with its official source. What to avoid is your call. The rules are the same for every brand, including ours.</p>
<div class="box"><p><b>Sunnytime is checked the same way.</b> I make a mineral sunscreen. When ours is on the FDA registry it goes through these exact rules, and what they find about it shows up like everyone else's, including the synthetic polymer powders it uses for texture.</p></div>

<h2>How a result is laid out</h2>
<ul>{layout}</ul>
<p class="sub">What the colours mean:</p>
<ul>{colours}</ul>
<p class="sub">Products are never ranked by how many items they have. Under every item, "Why this matters" lists the facts behind it, one sentence per source, then what points the other way and what no source has settled.</p>

<h2>Every fact, with its source</h2>
<p class="sub">These are the same sentences the result card shows. A law is called a law, a proposal a proposal, a recommendation a recommendation, and a single study a study.</p>
{"".join(parts)}

<h2>Other checks we run</h2>
<p class="sub">Less common findings, each with the rule or reference it rests on. Where a flag is our own judgment rather than an official rule, it says so.</p>
{other}

<h2>How we check the data</h2>
<ul>
<li><b>Two readers.</b> Each label's actives, Broad Spectrum claim and ingredient list are read from the package artwork filed with the FDA. The card says whether two readers agreed, one reader read it, or only the FDA filing was available.</li>
<li><b>Every week.</b> Every label is re-checked against FDA DailyMed, and the card shows the date.</li>
<li><b>Every month.</b> An independent audit re-reads 300 randomly picked labels against the package. The error rate and its 95% range are shown on the Check.</li>
<li><b>Corrections.</b> Anyone, parent or brand, can report an error from a product card or at angela@arwhouse.com, with a photo of the package or a link. Two readers check it within 7 days; one report alone never changes a card. <a href="/sunnytime/corrections">Every correction is listed.</a></li>
</ul>

<h2>What each ingredient does</h2>
<p>Next to every ingredient we give its main job in a sunscreen. The source is the European Commission's CosIng ingredient register, which lists the functions each cosmetic ingredient is registered for. CosIng lists every function an ingredient may serve in any product, so for the most-used ingredients two people chose the main job separately and we kept it only when they agreed. For plant extracts we name what they are used as, not a benefit they promise.</p>
<p>Some labels print several ingredients run together; we split those and give each its job. When a name on the label can't be identified, a cut-off word or a typo we can't resolve, we say <i>not yet checked</i> instead of guessing.</p>

<h2>What a label can't tell you</h2>
<p class="sub">This check reads labels, so it can only report what a label says. Some things that matter for a child's sunscreen never appear on one:</p>
<ul>
<li><b>Contamination.</b> Benzene in some aerosol sprays, bacteria or mold in a bad batch. We show it when the FDA records a recall; we cannot test products ourselves.</li>
<li><b>Particle size.</b> US labels don't have to say whether zinc oxide or titanium dioxide is nano-sized.</li>
<li><b>Heavy metals.</b> Mineral filters are mined; their purity is a manufacturing spec, not a label line.</li>
<li><b>Whether the SPF holds up.</b> The SPF on the label is the brand's own test result. We report it as printed.</li>
<li><b>Amounts of inactive ingredients.</b> Labels list them roughly from most to least, without amounts, and many brands list them alphabetically.</li>
</ul>

<h2>Changes to these rules</h2>
<ul>{log}</ul>

<h2>Sources</h2>
<ul>
<li>FDA DailyMed, Structured Product Labeling for every OTC sunscreen</li>
<li>European Commission CosIng ingredient register</li>
<li>American Contact Dermatitis Society, Allergen of the Year</li>
<li>EU Cosmetics Regulation (EC) No 1223/2009, Annexes II, III and V, and Regulation (EU) 2023/1545</li>
<li>US major food allergens: FALCPA, FASTER Act 2021, FDA food allergen guidance (January 2025)</li>
<li>FDA recall enforcement reports</li>
<li>Every source cited above, linked next to its sentence</li>
</ul>
<footer>Questions or a correction? angela@arwhouse.com · ARW House</footer>
</div>
</body>
</html>
'''
    out = os.path.join(site, "sunnytime/how-we-check/index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(page)
    print("wrote", out)


if __name__ == "__main__":
    main()
