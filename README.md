# TinySafe DailyMed Scraper v2.0 — ingredient-based

Searches FDA DailyMed by **active ingredient (UNII)**, not by keyword. This collects every
mineral sunscreen containing Zinc Oxide and/or Titanium Dioxide — including adult/family
products (Native, Vanicream, EltaMD) that the old baby-keyword scraper missed.

## Why this version exists
The v1 scraper searched product names for "baby/kids/infant". Products like Native
("mineral sunscreen with zinc oxide" but no "baby" wording) were never collected. v2 searches
by the UNII ingredient code, so wording is irrelevant — only the actual active ingredient matters.

## What it does
- **Phase A** search: `/v2/spls.json?unii_code=<UNII>` for ZnO (SOI2LOH54Z) and TiO2 (15FIX9V2JP), paginated
- **Phase B** dedup setids (union of both)
- **Phase C** active ingredients via `/v2/spls/{setid}/packaging.json`
- **Phase D** inactive ingredients: openFDA (primary) -> SPL XML `IACT` classCode (fallback). Active never leaks into inactive.
- **Phase E** enrich: SPF parse, mineral_type, chemical/hidden-filter flags, baby_labeled, category
- **Phase F** two outputs:
  - `tinysafe_dailymed_v2_master.json` — ALL collected SPLs (raw; incl. chemical & non-sunscreen)
  - `tinysafe_dailymed_v2_mineral_sun.json` — filtered: sunscreen + ZnO + no chemical filter

## Run (GitHub Actions)
Actions -> "DailyMed Mineral Scraper v2" -> Run workflow
- Smoke test: limit `10`, parallel `5`
- Full run: limit `0`, parallel `5`

Download both artifacts from the run page.

## Output fields (per product)
setid, title, product_name, active_ingredients[{name,strength}], inactive_ingredients[],
inactive_source (openfda|spl_xml|empty), inactive_count, spf, contains_zinc_oxide,
contains_titanium_dioxide, contains_chemical_filter, has_hidden_chemical_filter,
mineral_type (zinc|zinc_titanium|titanium|none), is_hundred_percent_mineral, baby_labeled,
category (sunscreen|diaper_cream|lip_balm|calamine|other), dailymed_url

## Health check
The run log prints inactive_source breakdown + % missing. If "empty" is high, some SPLs lack
both openFDA and IACT data and need a retry pass.
