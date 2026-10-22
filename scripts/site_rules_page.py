#!/usr/bin/env python3
"""arwhouse.com/sunnytime/how-we-check: the written rules behind the Sunscreen Check,
generated from the same files the check uses (flags_v31.json meta, rules_changelog.json,
the ingredient dictionary), so the page cannot drift from what the check does.

Usage: site_rules_page.py <arwhouse checkout>
"""
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
META = json.load(open(os.path.join(ROOT, "data/reference/flags_v31.json")))["meta"]
LOG = json.load(open(os.path.join(ROOT, "data/reference/rules_changelog.json")))["changes"]

GROUPS = [
    ("T1", "Act on it",
     "The label hides what an ingredient does (a UV absorber that is not listed as an active), a regulator has "
     "banned or restricted the ingredient in cosmetics or in products for young children, or pediatric guidance "
     "advises against it for children."),
    ("T2", "Check if your child reacts",
     "The ingredient is on one of three named lists: the American Contact Dermatitis Society's Allergen of the "
     "Year (any year, except a year the society named a non-allergen), the EU list of fragrance allergens that must "
     "be named on labels, or the US major food allergens. Fragrance and essential oils are here because they are "
     "how those fragrance allergens get into a product."),
    ("T3", "Also in it",
     "Everything else we can say for certain from the label. These are facts, not warnings. If you tell us your "
     "child has eczema or a food allergy, the facts that match move up and are starred."),
]
# what the result card says, in the result card's own words, for the three fixed questions
TOP = [("Hidden UV booster", "Does the label list every ingredient that absorbs UV as an active?"),
       ("Fragrance", "Does it contain fragrance, an essential oil or an EU-listed fragrance allergen?"),
       ("Recalls", "Is there an FDA recall on record for this product?")]
ORDER_SKIP = {"water_resistant"}   # a label fact, listed under T3 like the rest


def e(s):
    return html.escape(s or "", quote=True)


def main():
    site = sys.argv[1]
    tiers = {t: [] for t, _, _ in GROUPS}
    for k, v in META.items():
        if v.get("t") in tiers:
            tiers[v["t"]].append((k, v))
    parts = []
    for t, name, test in GROUPS:
        items = "".join(
            f'<details><summary>{e(v["l"])}</summary><p>{e(v.get("w"))}</p>'
            f'<span class="src">Source: {e(v.get("s"))}</span></details>' for k, v in tiers[t])
        parts.append(f'<h2>{e(name)}</h2><p class="sub">{e(test)}</p>{items}')
    log = "".join(f'<li><b>{e(c["version"])} · {e(c["date"])}</b> {e(c["change"])} <span class="why">{e(c.get("why"))}</span></li>'
                  for c in LOG)
    top = "".join(f"<li><b>{e(a)}.</b> {e(b)}</li>" for a, b in TOP)
    page = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Sunnytime — How the Sunscreen Check works</title>
<meta name="description" content="The written rules behind the Sunnytime Sunscreen Check: what shows first, what each ingredient does, and the sources. The same rules for every brand, including ours.">
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
</style>
</head>
<body>
<div class="wrap">
<nav><a class="word" href="/sunnytime">sunnytime</a><a class="back" href="/sunnytime#check">← Back to the Check</a></nav>
<h1>How the Check works.</h1>
<p class="lead">We don't score sunscreens. We read every label the FDA has on file, the printed Drug Facts and the filing behind it, and sort what we find with one written test for each group. The test is the same for every brand, including ours.</p>
<div class="box"><p><b>Sunnytime is checked the same way.</b> We make a mineral sunscreen. When ours is on the FDA registry it goes through these exact rules, and what they find about it shows up like everyone else's, including the synthetic polymer powders it uses for texture.</p></div>

<h2>The first three lines</h2>
<p class="sub">Every result opens with the same three questions, in the same order, so you can compare two sunscreens at a glance.</p>
<ul>{top}</ul>
{"".join(parts)}

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
