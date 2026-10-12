# Baby Sunscreen Label Dataset (US, with EU and Australian limits)

Published by **ARW House** · Author: **Angela Lee, Founder** · Findings and method: https://arwhouse.com/evidence

A weekly, reproducible dataset of every US sunscreen drug label in the FDA's
DailyMed database, with a week-by-week formulation history and the legal limits
of UV filters in the US, the EU and Australia.

For sunscreens labeled for babies or kids, each label's **printed Drug Facts**
is compared with the **structured ingredient data the manufacturer filed with
the FDA**. Where the two disagree, the printed label decides, and every
disagreement is recorded with its evidence.

## At a glance (release v1.0.0, DailyMed snapshot 2026-10-12)

| | |
|---|---|
| US sunscreen labels collected | 14,168 |
| Weekly snapshots | 9 (2026-08-26 to 2026-10-12) |
| Baby and kids candidate labels reviewed | 865, each decision with its reason |
| Baby and kids formulas counted | 448 (245 with mineral-only actives) |
| Filed active ingredients contradicted by the printed label | 18 labels, corrected with evidence |
| Published findings | 11, each with numerator, denominator and method |

## What is in this release

| Path | Content |
|---|---|
| `data/raw/dailymed/<date>/master.json` | Each weekly collection, unchanged |
| `data/canonical/us_sunscreens.jsonl` | Current state of every label: filed and printed ingredients, classification |
| `data/history/` | New, reformulated and delisted labels, week by week |
| `claims/` | Population decisions, exclusions, and the claim ledger behind every count |
| `data/corrections/` | Filing errors, image transcriptions and wording reviews, each with evidence |
| `data/regulatory/` | US (M020 and final orders), EU (Annex VI) and Australian (TGA) limits with sources |
| `data/views/` | The baby/kids subset, label text, image index, OCR, and the joined limits matrix |
| `site/evidence.json` | Everything published on the website |
| `scripts/`, `claims/registry_stats.py`, `tests/` | The complete pipeline and its tests |

Every field is described in [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md).
Publication rules are in [`docs/SITE_DATA_CONTRACT.md`](docs/SITE_DATA_CONTRACT.md).

## Method in brief

- **Collection.** Each week DailyMed is searched by the UNII code of every UV
  filter active, and the full list of DailyMed labels is scanned by title for
  sunscreens the ingredient search misses. Each label's SPL XML is parsed for
  filed actives (with strengths) and inactives (with UNII codes).
- **Population.** Sunscreen labels that say baby or kids in the product name or
  on the front panel, plus sunscreens of baby-care brands; tinted and lip
  products excluded. Front panels that exist only as images are read by OCR and
  checked by eye. Labels for another market, labels outside US limits as listed,
  and multi-product listings are left out, each with its reason.
- **Unit of count.** A formula: the same actives at the same percentages, the
  same inactive ingredients and the same form count once. Labels with the same
  filing count separately when one prints fragrance and the other does not, or
  when their printed lists name different ingredients on review
  (`data/corrections/printed_list_formula_splits.jsonl`).
- **Printed label decides.** Printed lists are read from the Drug Facts text,
  or transcribed from the label image twice independently. Active percentages
  that the text could not give were read from the image twice independently.

## Known limitations

- A DailyMed listing is not proof that a product is on US shelves today. Counts
  describe labels, not safety and not market share.
- Labels do not state inactive-ingredient concentrations, and "fragrance" is
  usually not broken down.
- For seven baby/kids labels, neither the label text nor the label images on
  DailyMed show active percentages; one (a Kroger kids
  sunstick) has a label image too small to read, so its filed percentages are
  used unverified; one (an Alba kids spray) has label text and an older label
  image that disagree, and the text is used. See
  `data/corrections/printed_actives_review.jsonl`.
- Errors in a manufacturer's filing are reproduced unless the printed label
  contradicts them.

## Reproduce

Python 3.11, standard library only.

```
python claims/registry_stats.py      # counts -> claims/claim_ledger.json
python scripts/build_evidence.py     # -> site/evidence.json
python scripts/render_site.py --check
for t in tests/test_*.py; do python "$t"; done
```

The weekly pipeline is `.github/workflows/scrape.yml`.

## Cite

See `CITATION.cff`. Each release is archived on Zenodo with its own DOI.

## License

ARW House's compilation, analysis, code and documentation: CC BY 4.0.
DailyMed data courtesy of the U.S. National Library of Medicine. Labels in
DailyMed are submitted by their manufacturers; quoted label text remains the
property of its owners and is included only as evidence for the counts.

ARW House also develops a mineral baby sunscreen. That brand does not cite or
link these findings.
