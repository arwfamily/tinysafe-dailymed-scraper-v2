# Site data contract — arwhouse.com evidence pages

Status: v1, 2026-10-08. Owner decisions (Angela Lee, 2026-10-08):

1. Every word and every link on the site is English (enforced by render_site.py --check).
2. The evidence pages live on **arwhouse.com** (not tinysafe.app).
3. Every number on a page links to its own source, at the cell level.
4. v1 includes registry measurements (what share of real baby sunscreens
   contain an ingredient), but only numbers marked `verified`.
5. `/radar/` (reformulation alerts) is on hold until formulation history is
   rebuilt and audited.
6. Byline (decided 2026-10-08): publisher **ARW House**; author
   **Angela Lee, Founder** on every page, as a named person (Person schema),
   not an institutional label. A named pharmacist/clinical reviewer is
   added only once confirmed in writing; until then no reviewer line.

This file defines what the data side delivers and what the site may do with it.
The site never types, edits, rounds or recomputes a number. If a number is
wrong, it is fixed in the data repo and regenerated.

---

## 1. What the data side delivers

One file per build: `site/evidence.json`, generated in
`arwfamily/tinysafe-dailymed-scraper-v2` from the jurisdiction matrix, the
US registry and the claim ledger. Shape:

```json
{
  "built_on": "2026-10-12",
  "commit": "4a0c6af",
  "ingredients": [
    {
      "slug": "zinc-oxide",
      "name": "Zinc Oxide",
      "also_known_as": ["CI 77947"],
      "role": "uv_filter_mineral",
      "limits": [
        {
          "jurisdiction": "US",
          "status": "permitted",
          "max_percent": 25.0,
          "conditions": [],
          "source": {
            "title": "FDA OTC Monograph M020, § M020.10(p)",
            "url": "https://www.accessdata.fda.gov/...M020...pdf",
            "version": "Final Administrative Order OTC000006, posted 2021-09-24",
            "verified_date": "2026-10-08"
          }
        }
      ],
      "registry": [
        {
          "id": "US-BABY-ZNO-SHARE",
          "status": "verified",
          "sentence": "160 of 163 baby mineral sunscreen formulas registered with the FDA contain zinc oxide.",
          "numerator": 160,
          "denominator": 163,
          "population": "unique formulations, baby-labeled, mineral-only actives, product_type=sunscreen",
          "source": {
            "title": "FDA DailyMed SPL registry, ARW House analysis",
            "url": "https://github.com/arwfamily/tinysafe-dailymed-scraper-v2/blob/<commit>/data/canonical/us_sunscreens.jsonl",
            "method_url": "https://github.com/arwfamily/tinysafe-dailymed-scraper-v2/blob/<commit>/scripts/verify_ledger.py",
            "snapshot": "2026-10-05",
            "verified_date": "2026-10-08"
          }
        }
      ]
    }
  ]
}
```

(The registry numbers above illustrate the shape. They are not yet verified —
see §3.)

### Registry claims and findings (added 2026-10-08)

- Each `registry` item and each top-level `findings` item carries
  `sentence`, `numerator`, `denominator`, `population`, `caveat` and
  `source` (`url` = data file, `list_url` = reviewed product list,
  `method_url` = the script that computed it, `snapshot`).
- The site renders `sentence` verbatim and shows `caveat` with it (the
  caveat says a DailyMed listing is not proof a product is on US shelves).
- Wording rule: say "listed in the FDA's DailyMed label database", never
  "registered with the FDA" or "sold in the US". Never describe what a
  non-active ingredient does (absorbs UV, boosts SPF, stabilises filters)
  unless the finding carries an `ingredient_source` for that exact ingredient
  and the sentence stays inside what that source says. (2026-10-08: "absorbs
  UV light" was withdrawn; the BOS manufacturer and DrugBank do not support it.)
- A finding with `ingredient_source` must link it next to the sentence.
- `findings` are verified results that belong to no single filter page
  (hidden UV absorbers, butyloctyl salicylate). They need their own page;
  they must not be pasted into a filter page.
- `legal_framing`, when present, must appear next to the finding.
- Population (owner decision 2026-10-08, strict): labels that say baby or
  kids, selected by rule from the label, edge cases decided by hand; every
  decision and its reason is in `claims/baby_review_*.csv`. Never say the
  whole list was reviewed by hand.

### Allowed `status` values for a limit

| status | what the site shows |
|---|---|
| `permitted` | "Permitted up to X%" (+ conditions, each on its own line) |
| `permitted_with_conditions` | max per condition, e.g. EU oxybenzone 6% face/hand/lip, 2.2% body, 0.5% formulation protection |
| `approved_product_only` | "Not in the monograph; allowed only in specifically FDA-approved products" (e.g. ecamsule, US, since 2006) |
| `removal_finalized_not_yet_effective` | "Removal finalized; takes effect {date}" |
| `removed` | "Removed on {date}" |
| `not_listed` | "Not on this jurisdiction's permitted list" — never "banned" |
| `listed_no_numeric_limit` | "Permitted; no concentration limit in the regulation" |

A missing entry is **not** the same as `not_listed`. If the data side has no
row, the site shows "Not yet reviewed" and no badge.

---

## 2. Rules for the site

1. **Cell-level sources.** Every limit cell and every registry sentence
   renders its own `source.url` as a link, with `version` and
   `verified_date` visible on hover or in a footnote. No page-level "Sources"
   list as a substitute.
2. **Only `status: "verified"` registry numbers are rendered.** Anything else
   is not shown at all, not even greyed out.
3. **No other numbers.** A percentage, count or ratio that is not in
   `evidence.json` does not go on the page. Prose may say "most", "some" only
   if the sentence comes from `evidence.json`.
4. **Wording comes from the data side** for limits and registry sentences.
   The site may write the surrounding explanation (what an ingredient does,
   how to read a label) but must not restate a number in its own words.
5. **No safety verdicts.** "Permitted / not listed / removed", never "safe /
   dangerous". Medical guidance only as attributed summaries (AAP, FDA,
   Health Canada, TGA/Cancer Council, NHS), each with its own link.
6. **No product rankings on evidence pages.** No Sunnytime mentions on
   evidence pages. Footer disclosure on every page:
   "ARW House also makes Sunnytime, a mineral baby sunscreen. This page does
   not rank or recommend products."
7. **Structured data.** Each ingredient page: `FAQPage` for its FAQ,
   `Dataset` pointing to `evidence.json` (with `dateModified = built_on`),
   `Organization` = ARW House (publisher), `Person` = Angela Lee, Founder
   (author), with `datePublished` and `dateModified`. Tables are real
   `<table>` elements. No "TinySafe Research" or "ARW House Research" labels.
8. **Date-aware statuses** are rendered from the data as delivered. The site
   does not compute "today vs effective date"; the data side does.

---

## 3. What is verified today (2026-10-08)

| Item | State | Blocker |
|---|---|---|
| US M020 limits incl. bemotrizinol, PABA/trolamine | verified | — |
| EU Annex VI limits | verified, conditions structured | |
| AU limits | verified for the 20 filters | own-concentration sentences only |
| Name merging across jurisdictions | fixed | |
| Ecamsule US status | `approved_product_only` | source is secondary; replace with Drugs@FDA record |
| Canada limits | not collected | Health Canada sunscreen monograph not in the matrix |
| US registry shares (baby) | verified (strict definition) | 21 claims in evidence.json |
| Hidden UV absorbers (BOS etc.) shares | verified | 2 findings in evidence.json; need their own page |

The data side fixes the matrix items first, then the baby review, then
marks registry numbers `verified` in the claim ledger. `evidence.json` is
generated only from those.

## Rendering and deployment (2026-10-08)

- `scripts/render_site.py --check` turns `site/evidence.json` and
  `content/notes.json` into `site/evidence/**` (library, one page per
  ingredient, one per finding, method, `data.json`, `sitemap.xml`). CI runs it
  every week right after `build_evidence.py`; nobody edits these HTML files.
- Free text about an ingredient lives only in `content/notes.json`, one fact
  per note, each with its own primary source. No source, no note.
- The check fails on forbidden wording, on a note without a source, on an
  unknown finding, or on a limit without its source link.
- Serving: the Vercel project for this repo uses `site/` as its root
  (`site/vercel.json`, clean URLs). arwhouse.com proxies `/evidence/*` to it,
  so canonical URLs are `https://arwhouse.com/evidence/...`.

## Baby/kids decisions and weekly tracking (2026-10-08)

- `claims/baby_decisions.csv` is the population ledger: the 2026-10-08 hand
  review carried forward, plus one rule decision per new candidate
  (`scripts/baby_track.py`, weekly). Rule: baby/kids word in the product name
  + product type sunscreen + not a kit -> include; non-sunscreen product types
  -> exclude; anything else -> `claims/baby_queue.csv`, not counted until a
  person decides. A decision is never overwritten by the rule.
- `data/views/baby_sunscreens.jsonl`: the baby subset of the full dataset.
- `data/reports/<date>.md|json`: every week, all labels and baby labels:
  new, reformulated (ingredients added/removed), delisted.
