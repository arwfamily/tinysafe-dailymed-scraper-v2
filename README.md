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

---

## v2.1 — UNII patch (성분 식별자 추가)

각 성분에 **UNII 코드**(FDA 고유 성분 식별자)를 함께 저장합니다.

- **Phase C/D 변경**: SPL XML을 1차 소스로 사용(이전엔 openFDA 1차). openFDA의
  inactive 필드는 텍스트라 UNII가 없으므로, UNII 확보를 위해 XML을 먼저 신뢰합니다.
- **출력 스키마 변경**: `active_ingredients` / `inactive_ingredients`의 각 원소가
  문자열 → `{"name": ..., "unii": ...}` dict로. UNII 미발견 시 `unii: null`.
- **이유**: 리포뮬레이션 추적 시 성분 정규화에 UNII가 필수. 같은 성분이 SPL마다 다르게
  표기됨(예: TOCOPHEROL vs .ALPHA.-TOCOPHEROL). 텍스트 diff는 오탐 폭발, UNII는 표기 무관 식별.

### 스모크 테스트로 확인
Run workflow → limit 10 → 결과의 inactive 원소가
`{"name": "WATER", "unii": "059QF0KO0R"}` 형태인지 확인.
unii가 전부 null이면 XML 경로 미작동 → 로그 확인.
