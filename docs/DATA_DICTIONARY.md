# Data dictionary

All files are UTF-8. `.jsonl` files hold one JSON object per line. A label is
identified by its DailyMed **setid**; a product split out of a multi-product
listing carries `#1`, `#2` ... after the setid. Percentages are w/w as printed
or filed (`percent_ww`).

## Source data

### `data/raw/dailymed/<date>/master.json`
The weekly collection, unchanged. `metadata` (scraper version, search method, UNIIs searched, coverage caveat, totals) and
`products`: every sunscreen label found through its active ingredients, with
the fields of the canonical file below as collected that week.

### `data/canonical/us_sunscreens.jsonl`
The current state of every US sunscreen label (one line per setid).

| Field | Meaning |
|---|---|
| `setid`, `spl_version`, `effective_date` | DailyMed label identity and version |
| `title`, `product_name`, `labeler`, `labeler_from_title` | Names as filed |
| `dosage_form`, `ndc_product`, `product_count` | Form, NDC product code, products in the listing |
| `monograph_id`, `marketing_category` | Regulatory route as filed (e.g. `part352`, OTC monograph) |
| `active_ingredients` | Filed actives: `name`, `unii`, `strength`/`strength_unit`, `denominator`/`denominator_unit`, `percent_ww`, `percent_basis`, `percent_source` (`label` = confirmed against the printed Drug Facts) |
| `inactive_ingredients` | Filed inactives: `name`, `unii` |
| `inactive_source`, `inactive_count` | Where the inactive list came from (`spl_xml`, `openfda`, or `empty`) and its length |
| `printed_actives`, `printed_inactives` | The lists as printed in the label's Drug Facts text |
| `panel_percents_found` | Active percentages read from the printed panel |
| `label_flags` | Printed facts: SPF, water resistance, broad spectrum claim, under-6-months direction, baby/kids words on the front panel |
| `label_checks` | Automatic printed-vs-filed checks (e.g. `fragrance_printed_not_structured`, `printed_active_missing_from_structured`, `above_us_max`) |
| `is_sunscreen`, `sunscreen_basis`, `product_type`, `category`, `is_tinted` | Classification and its basis |
| `uv_filters_mineral`, `uv_filters_organic` | UV filter actives, by type |
| `non_us_filter_active`, `non_uv_actives` | Actives that are not US sunscreen filters |
| `uv_absorbers_in_inactives` | UV-absorbing ingredients listed as inactive (e.g. butyloctyl salicylate) |
| `mineral_type`, `is_mineral_only_actives`, `is_hundred_percent_mineral`, `contains_*` | Derived flags |
| `baby_signal`, `baby_labeled` | Why a label is a baby/kids candidate |
| `formulation_hash` | Fingerprint of the filed formula (actives with percentages, inactive UNIIs, form) |
| `first_seen`, `last_seen` | Collection dates |

### `data/history/us_formulation_history.jsonl`
One line per event: `observed_on`, `setid`, `change` (`new`, `reformulated`,
`delisted`, `metadata`), `formulation_hash`, and the formula at that date.
Reformulations carry `previous_hash`, `keys_added`, `keys_removed` and a
`confidence`. `data/history/archive/` holds the log under the earlier
fingerprint version; `_state.json` is the last run's state.

## Baby and kids population

| File | Content |
|---|---|
| `claims/baby_review_2026-10-08.csv` | First full review of baby/kids candidates, with the rule applied |
| `claims/baby_decisions.csv` | Every include/exclude decision since: `setid`, `decision`, `stage`, `reason`, `decided_on` |
| `claims/population_exclusions.csv` | Included labels left out of the counts by rule (another market, outside US limits, multi-product listing), with reason. A multi-product listing is split: each of its products that is itself a baby/kids sunscreen re-enters the counts as its own formula (`setid#n`), from its own filing |
| `data/views/baby_sunscreens.jsonl` | Canonical records of the baby/kids candidates, with `baby_decision`. Values are as filed; corrections where the printed label contradicts the filing are in `data/corrections/spl_label_errors.jsonl` and are applied in the counts |
| `data/views/baby_label_text.jsonl` | Label text by section, as published on DailyMed (evidence for wording findings) |
| `data/views/label_images_index.json` | The label images DailyMed lists for each label (names, hashes) |
| `data/views/ocr/` | OCR of front-panel images (baby/kids wording) |
| `data/state/baby_printed_lists.json` | The printed inactive list read for each baby/kids label, by setid, with its label date |

## Corrections and reviews (`data/corrections/`)

Each line carries its evidence and the date it was checked.

| File | Content |
|---|---|
| `spl_label_errors.jsonl` | Labels whose filed actives contradict the printed label; `use` holds the values used instead |
| `printed_actives_review.jsonl` | Active percentages checked on the label image where the text could not give them: `matches`, `corrected`, `percent_not_printed`, `unreadable`, `text_image_conflict` |
| `printed_lists_from_images.jsonl` | Inactive lists transcribed from label images (two independent readings) |
| `printed_list_formula_splits.jsonl` | Labels with an identical filing but a different printed list, counted as separate formulas |
| `front_mineral_wording.jsonl` | Front-panel "mineral" wording review |
| `hypoallergenic_wording.jsonl` | "Hypoallergenic" wording and fragrance review |

## Regulatory limits (`data/regulatory/`)

| File | Content |
|---|---|
| `us_monograph_m020.jsonl`, `us_non_monograph.jsonl` | US OTC monograph M020 actives and limits; actives outside it (final orders) |
| `eu_annex_vi.jsonl` | EU Cosmetics Regulation Annex VI UV filters |
| `au_permissible_ingredients.json` | TGA Permissible Ingredients Determination |
| `data/views/jurisdiction_matrix.json` | The three joined, each cell with its source URL and version |

## Counts

| File | Content |
|---|---|
| `claims/claim_ledger.json` | Every count with its status, sentence, numerator, denominator, method and known limits. Only `verified` claims are published |
| `claims/same_ingredient_list_pairs_published.csv` | Baby/kids labels whose printed list matches a label without baby/kids wording |
| `site/evidence.json` | Everything the website shows, built from the files above |
| `data/reports/` | Weekly run reports and review notes |
