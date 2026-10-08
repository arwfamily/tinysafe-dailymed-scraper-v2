# Notes waiting for a source (not published)

Prose from the Muse prototype (index-13, 2026-10-08) that is NOT on the site.
Each line can come back only as a note in `content/notes.json` with a primary
source for that exact statement. Reason in brackets.

## Wrong or misleading as written
- Zinc oxide: "twelve chemical filters were put in 'insufficient data' status" [the 2019 proposed rule / 2021 proposed order is the source; "chemical" is banned wording; needs the exact FDA sentence]
- Dioxybenzone: "This page will show verified counts once the baby-product review is complete" [stale: the count is published]
- Avobenzone / homosalate: "The US kept its older approved level; the EU re-evaluated" [the US half is an invented explanation; EU homosalate change is SCCS-based and needs that citation]
- Drometrizole trisiloxane: "Review, not science, was the bottleneck" [opinion]
- Ecamsule: "exposes the blind spot of US-centric ratings" [opinion]

## Plausible but unsourced
- Bemotrizinol: "first filter added to the US monograph in more than two decades" / "No new active since the late 1990s"
- Zinc oxide: "higher concentrations usually mean more white cast"; "SPF is not set by one concentration alone"
- Titanium dioxide: "particle size affects white cast"; "spray forms are generally discouraged over inhalation concerns"; "zinc oxide covers a broader UVA range"
- Avobenzone: "the FDA has requested additional safety data"
- Octocrylene: "paired with avobenzone to slow its photodegradation"
- Ensulizole: "solubility suits lightweight formulas"; "mostly UVB"
- Sulisobenzone: "used in daily-wear rather than waterproof products"
- PABA: "The FDA states it knows of no US product currently sold containing it" [find the sentence in order OTC000008-1]
- Trolamine salicylate: "better known as an analgesic salicylate"
- Octinoxate: "'Reef safe' has no legal definition"

## Already covered by a sourced note
- 12 ingredients 'insufficient data' (zinc oxide FAQ, avobenzone, homosalate) -> NOTE-MORE-DATA-12 (FDA Q&A); zinc/titanium GRASE -> NOTE-MINERAL-GRASE
- Bemotrizinol 'first since the late 1990s' -> NOTE-BEMT-FIRST (FDA press announcement 2026-06-09)
- PABA/trolamine 'no US product sold' -> NOTE-PABA-TROL-MARKET (FDA Q&A)
- Hawaii Act 104 (oxybenzone, octinoxate) -> NOTE-HAWAII-ACT104
- Babies under 6 months -> NOTE-INFANTS-FDA (FDA consumer update; the AAP is not cited)

## Held findings (sourced, but not published)
- Polysilicone-15 in 2 mineral baby formulas: manufacturer (DSM-Firmenich) calls it a "UV-B absorber"/"polymeric UVB filter"; EU Annex VI 10%, TGA 10%; US: not a sunscreen active. HELD: both formulas are one brand (MDSolarSciences), so a standalone page would single out a brand.
- Muse dossier 2026-10-08 checked: polyester-8 source (CosmeticsDesign 2012) is about PolycryleneS1, not polyester-8; ethyl ferulate NCATS page not readable (bot wall); "BOS: source-backed absorption" in its verdict contradicts the Hallstar Q&A. Do not cite abnewswire "1,095 products" release (sponsored).

## Label audit queue (title vs structured actives, baby set)
- 2db243d3-3b59-4be9-967c-0d4aea4d0066 Peter Island Kids SPF 50: title names octocrylene, structured data has octisalate. DailyMed page not readable 2026-10-08 (rate limit). Verify Drug Facts; at most +/-1 on octocrylene or octisalate.
- Checked, data correct (title is stale): Banana Boat Ultra Mist Kids LATAM (3aa6550e), Bull Frog Kids 35 (60cdfbfa) — no oxybenzone in Drug Facts.
