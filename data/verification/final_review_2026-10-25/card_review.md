# Proposed card (renderNew) review, 2026-10-25

Scope: `renderNew(p)` in preview.html (lines ~195-287). The 8 preview products were rendered with Playwright. The same logic was re-run in Python on all 9,460 products in `data/site/sunnytime_db.json` (flags v3, `names[i]` inactives). Counts below are for the full DB. Fact sentences in evidence_library.json are out of scope, except where the card's own headline text depends on them.

---

## MUST-FIX

### M1. Green "Mineral filters only" and "No SPF booster" ticks shown on products with a chemical UV filter listed as an inactive
- **Where:** `renderNew`, glance block: `else if(p.ft==='mineral_only') … 'Mineral filters only'` and `bn.length? … : ITEM('ok','✓','No SPF booster listed as inactive',…)`.
- **What:** renderNew never reads the `chemical_filter_in_inactives` flag. The current card shows it as a red item. The flag fires on 170 products.
  - 53 are `ft=mineral_only`, so they get a green "Mineral filters only" tick while the inactives list octinoxate (ethylhexyl methoxycinnamate), homosalate, octocrylene or avobenzone. Examples: Beaute De Cell Perfect Sun-Shield SPF 50 (TiO2 active; inactives include ethylhexyl methoxycinnamate, homosalate, ethylhexyl salicylate, octocrylene) and Bisutang Sunscreen Liquid.
  - 116 have no `hidden_uv_booster` flag, so they also get the green "No SPF booster listed as inactive" tick.
- **Why:** this is the card's main promise, and a green tick here is plainly false. FDA monograph M020 recognises only listed actives as sunscreen actives.
- **Fix:**
```js
const cfi=flag(p,'chemical_filter_in_inactives');
// filters line
if(cf){…}
else if(p.ft==='mineral_only'&&!cfi) out.glance.push(ITEM('ok','✓','Mineral active ingredients only',esc(p.z.map(z=>nice(z[0])).join(', ')),'filters'));
else if(p.ft==='mineral_only'&&cfi) out.glance.push(ITEM('warn','!','Mineral actives, but a chemical UV filter is listed as inactive',esc(names(cfi,4)),'uv_absorbing_inactive',{names:names(cfi,9),status:''}));
// booster line: treat cfi like a booster
const bn=(hb?hb.m.filter(n=>!BOOST_EXCL.test(up(n))):[]).concat(cfi&&p.ft!=='mineral_only'?cfi.m:[]);
```
  Also never show the "No SPF booster" tick when `BOOST_EXCL` removed names (see S9).

### M2. A red "PABA or trolamine salicylate · not safe and effective" stop on 15 padimate O products
- **Where:** `if(A.some(a=>/PADIMATE|AMINOBENZOIC|TROLAMINE/.test(a)))`.
- **What:** In the DB, the only products this matches are the 15 with **PADIMATE O** as an active: Pro-Tect Everyday SPF 15, Vertra Pearl White Face Stick SPF 50, Kroger/Meijer/Ulta SPF 4 tanning, Rayito De Sol, Techniblock. Padimate O is a PABA *ester*. The Sept 2026 final order removes **PABA (aminobenzoic acid) and trolamine salicylate** only. Padimate O stays one of the 15 permitted actives, with its status still unresolved, like the other 12 filters. FDA also says it is "not aware of any sunscreen drug products currently marketed in the United States" with PABA or trolamine salicylate. So today this item fires only as a false positive, and it tells parents an FDA finding applies to a product it doesn't cover. That is a disparagement risk.
- **Source:** FDA Final Administrative Order OTC000008 (PABA/trolamine), https://www.accessdata.fda.gov/drugsatfda_docs/omuf/Order/FinalAdministrativeOrderOTC000008-PABATrolamine.pdf; summary https://www.afslaw.com/perspectives/alerts/there-goes-the-sunscreen-fda-removes-paba-and-trolamine-salicylate-otc
- **Fix:** match the exact actives, and use the order's own wording ("not GRASE", not "not safe and effective"):
```js
if(A.some(a=>/^(AMINOBENZOIC ACID|PABA|TROLAMINE SALICYLATE)$/.test(a)))
  out.filters.push(ITEM('stop','!','PABA or trolamine salicylate','FDA final order (Sept 2026): not generally recognized as safe and effective; can’t be sold under the monograph from Sept 11, 2027','paba_trolamine'));
```
  Optional, info only: `if(A.includes('PADIMATE O'))` → "Padimate O (a PABA ester) · One of the 12 filters FDA says need more safety data; not a finding that it is unsafe" (topic `filters`).

### M3. "Broad Spectrum not stated · The label doesn't claim it" shown on 1,395 products whose status is simply unknown
- **Where:** glance, third branch of the broad-spectrum ternary.
- **What:** In us_master, `broad_spectrum: null` means the parser didn't decide. It does not mean the label lacks the claim. Every `bs=0` product already carries `not_broad_spectrum`. 28 of the null products say "Broad Spectrum" in their own name, for example "Broad Spectrum SPF50 SPF 50 Gel" (Naked Sundays), Neutrogena Healthy Skin Radiant Tinted Moisturizer Broad Spectrum SPF 25, Walgreens Day Cream Broad Spectrum SPF18 and Absolue Premium Bx Broad Spectrum SPF 15. In the preview, Banana Boat Kids Protect and Play SPF 50 gets the yellow "?". The card states something about a competitor's label that we haven't established.
- **Fix:**
```js
: p.bs===0 ? ITEM('warn','!','Broad Spectrum not claimed','The label doesn’t say Broad Spectrum','broad_spectrum')
: ITEM('info','i','Broad Spectrum: not confirmed yet','We couldn’t read it from the FDA filing; check the front of the package','broad_spectrum')
```

### M4. Eczema mode gives a green "Nothing from the NEA exclusion list" tick that the NEA's own criteria contradict (5,538 products)
- **Where:** `prof.has('eczema')` → `neaHits.length?…:ITEM('ok','✓','Nothing from the NEA exclusion list','None of its excluded ingredients is on this label')`.
- **What:**
  1. The NEA Seal excludes chemical UV absorbers outright ("only physical sunscreens… titanium, zinc, and iron") and requires products to be fragrance-free. 2,123 chemical sunscreens and 835 products with a fragrance or essential-oil flag still get the green tick.
  2. Substring matching misses INCI spellings. "ORANGE PEEL OIL" doesn't match "Citrus Aurantium Dulcis (Orange) Peel Oil" (93 labels). "Lime/Lemon Peel Powder" doesn't match the Citrus … (Lime) form either. The NEA list's "Citrus extract" entry is missing from `D.nea` (citrus peel/fruit extracts on more than 60 labels).
  3. "Formaldehyde releasers" is an NEA criterion, but only 5 named releasers are in the list. 2 products with the `formaldehyde_releaser` flag pass.
- **Source:** NEA Ecz-clusion list and Seal criteria, https://nationaleczema.org/eczema-products/the-ecz-clusion-list
- **Fix:** let any NEA-relevant flag decide the result, and soften the tick:
```js
const neaFail=neaHits.length||cf||fr.some(r=>r.id!=='eu_fragrance_allergen')||flag(p,'formaldehyde_releaser')||flag(p,'mi_mci')||flag(p,'mdbgn');
// green only if !neaFail, worded: 'None of the NEA-excluded ingredients we check for' + sub 'Not the NEA Seal; the Seal also needs testing'
```
  Match on the flags plus normalised names (strip parentheses, compare word sets), not on raw substrings. Add "Citrus extract" and "Citrus Aurantium Dulcis Peel Oil" to `nea`.

### M5. Eight T1 flags and five T2/T3 allergen flags are computed but never shown, which loses information the current card shows
- **Where:** renderNew reads no flag outside its own hard-coded list.
- **Missing T1:** `chemical_filter_in_inactives` (170, see M1), `insect_repellent` (17: Avon Skin-So-Soft Bug Guard Plus, Bull Frog Mosquito Coast…), `ipbc` (194), `under3_restricted` (69), `talc_inhalable` (22), `mdbgn` (17), `no_preservative_water_base` (49), `phthalate` (1).
- **Missing allergens:** `asteraceae` (1,311, e.g. feverfew in the preview's Aveeno Baby), `alkyl_glucoside` (1,280, e.g. coco-/cetearyl glucoside in the preview's Babyganics; ACDS Allergen of the Year 2017; the current card shows it as T2), `propolis_beeswax` (992), `sulfite` (119, ACDS 2024), `isobornyl_acrylate` (170).
- **Why:** the insect-repellent combination is the clearest pediatric "don't" there is. AAP: "AAP does not recommend products that combine sunscreen with DEET" (https://www.aap.org/en/news-room/news-releases/health--safety-tips/american-academy-of-pediatrics-get-kids-outdoors-and-use-these-safety-tips-to-ward-off-insects-and-prevent-sunburn/). AAD: https://www.aad.org/sun-protection/sunscreen-faqs. Topic `insect_repellent` already exists in the library. With these flags missing, the card can't honestly claim to show "every" check.
- **Fix:** glance `if(flag(p,'insect_repellent')) ITEM('stop','!','Combined with an insect repellent',names(..),'insect_repellent')`. Child section: add `asteraceae`, `alkyl_glucoside`, `propolis_beeswax`, `sulfite`, `isobornyl_acrylate` as `C(...,'soft',…,['eczema'])`. Add `ipbc` and `under3_restricted` with tag `young`, `mdbgn` with tag `eczema`. Fold `talc_inhalable` into the spray item. Add a final safety net that renders any T1/T2 flag in META that no branch consumed, so new rules can't silently disappear:
```js
const USED=new Set([...]);(p.v3||[]).filter(f=>!USED.has(f[0])&&['T1','T2'].includes((META[f[0]]||{}).t)).forEach(f=>out.label.push(ITEM('warn','!',esc(f[2]),esc(names({m:f[1]},3)),null)));
```

### M6. Green "Not a spray · Nothing to breathe in" on real sprays; powders described as sprays
- **Where:** `flag(p,'spray_powder')?ITEM('stop','!','Spray','Don’t spray near the face; spray into hands','spray'):ITEM('ok','✓','Not a spray','Nothing to breathe in','spray')`.
- **What:**
  - False negatives with a false green tick: "H.E.B Baby (SPF 50 Sunscreen) Aerosol, Spray", "Panama Jack SPF 15 Spray", "No-Ad SPF4 Dark Tanning Oil Spray", Ultrasol Kids aerosol foams.
  - 117 products flagged `spray_powder` are powders (Bareminerals Mineral Veil, Aloha brush-on powder, "Babies Kidssun Protection Powder"…). They are told "Spray · Don't spray near the face; spray into hands", which is meaningless advice for a brush-on powder.
- **Fix:** add a name/dosage-form backstop (`/\b(SPRAY|MIST|AEROSOL)\b/` on `p.n` and the SPL dosage form) and split the text:
```js
const isPowder=/\bPOWDER\b/i.test(p.n);
sp? ITEM('warn','!',isPowder?'Loose powder':'Spray',isPowder?'Avoid breathing it in; apply with a brush away from the face':'Never spray on the face; spray into hands, then apply','spray')
  : ITEM('ok','✓','Not a spray or powder','A lotion, cream or stick','spray')
```
  Colour: see S1.

### M7. "Your preferences · not a safety concern" is a safety claim the cited sources don't support
- **Where:** fold header ``<h4>Your preferences <span class="small">· not a safety concern</span>``.
- **What:** This bucket holds BHA (California Prop 65 carcinogen listing, cited in the library's own `bha` topic), talc (the library's own topic covers asbestos testing), PFAS, triclosan, D4 (an EU-restricted substance) and nano filters. Saying "not a safety concern" is the publisher's own safety verdict. It contradicts the "Why this matters" text inside the same fold, and it is exactly the unsupported reassurance the brief says to avoid.
- **Fix:** `Other ingredients some parents avoid · no flag from FDA or AAP` and the sub-line "We list these because parents ask. Official findings are under each."

---

## SHOULD-FIX

### S1. The colour doesn't match the evidence in four places
- **Spray** gets red "stop", the same as a recall or a PABA order, but sprays are a lawful form. FDA's 2021 proposal keeps them, subject to testing. The sources are usage advice (FDA: "should never be applied directly to your face"; AAD). → `warn`.
- **Alcohol** (`drying_alcohol`, 1,568 products) is yellow `!` and tagged eczema/psoriasis. META says "TinySafe formulation judgment. No specific AAD or NEA document identified." → `soft` (info unless a chip matches), or drop the eczema/psoriasis tags. The AAP dermatology section's "alcohol-free" advice (`aap_rashes` in eczema_sunscreen) is the one usable source; cite it if kept.
- **Food-derived ingredients** is yellow on 2,654 products (28% of the DB). 1,448 of them are only "Lecithin (source not stated…)", and `nice()` strips that qualifier (see S6). "Soluble collagen" is counted as fish. The library itself calls skin exposure "a hypothesis, not a proven cause". → `soft`. Keep `warn` only for protein-bearing names (hydrolyzed wheat/milk/oat protein, peanut/arachis oil, whole extracts).
- **"Contains an EU-listed fragrance allergen"** fires yellow on 271 products whose only match is **benzyl alcohol**, a common preservative. Eczema mode then adds "Fragrance on this label · The AAD advises a fragrance-free sunscreen". A product preserved with benzyl alcohol can be legitimately fragrance-free. → when the only match is benzyl alcohol, use info "Benzyl alcohol (preservative; on the EU fragrance-allergen list)", and fire the eczema "Fragrance on this label" item only for `fragrance`/`essential_oil`.

### S2. Wrong or overstated headline text
| Where | Now | Problem | Proposed |
|---|---|---|---|
| label, bemotrizinol | "An FDA-approved UV filter since Aug 2026, listed here as inactive" | Not "approved": FDA added it to the monograph as GRASE by final order OTC000039 (issued June 10, 2026, effective Aug 9, 2026), up to 6%, ages 6 months and up, no powders or propellant aerosols (https://www.venable.com/insights/publications/2026/06/fda-clears-the-way-for-bemotrizinol-first-new-otc) | "Added to FDA’s sunscreen monograph in Aug 2026 (up to 6%); listed here as inactive" |
| filters, oxybenzone | "EU limit 6% face, 2.2% body" / "EU allows up to 6% in face products" | The EU 6% covers face, hand and lip products **excluding sprays**; body products **and sprays** get 2.2% (Reg. (EU) 2022/1176; https://biorius.com/regulatory/octocrylene-and-benzophenone-3/). 170 sprays at 2.2-6% are wrongly told that up to 6% is allowed for face products | `const lim=sp?2.2:null;` for a spray: "Above the EU limit for sprays (2.2%)". Otherwise: "EU: 6% face, hand and lip; 2.2% body and sprays" |
| filters, homosalate | fires only if >7.34% | The EU allows homosalate **only** in face products (not propellant sprays) at ≤7.34%, so any homosalate in a body lotion or spray is outside EU rules. 728 products at ≤7.34% and 288 with no % get nothing | Fire on any homosalate. ≤7.34 and not a spray: "EU: allowed only in face products, up to 7.34%. US allows 15%". >7.34 or a spray: keep "above the EU limit" |
| filters, Hawaii | "Can't be sold in Hawaii · State law bans oxybenzone and octinoxate (since 2021)" | (a) Matches actives only. Hawaii Act 104 covers any sunscreen *containing* them, so 56 products with octinoxate or oxybenzone (benzophenone-3) among their inactives are missed. (b) Maui County (from Oct 1, 2022) and Hawaiʻi County (from Dec 1, 2022) ban all non-mineral sunscreens (https://mauinow.com/2022/08/05/maui-ban-on-non-mineral-sunscreen-goes-into-effect-on-oct-1/; https://www.jeffsetter.com/hawaii-county-bans-nonmineral-sunscreens/). Every `cf` product is affected | Statewide line: test `A` plus `I` against `/OXYBENZONE|BENZOPHENONE-3|OCTINOXATE|ETHYLHEXYL METHOXYCINNAMATE|OCTYL METHOXYCINNAMATE/`. Add, for any `cf` or `cfi`: "Can’t be sold on Maui or Hawaiʻi Island · County laws allow mineral-only sunscreens (since 2022)" (needs a new library source) |
| label, 4-MBC | "Banned in EU cosmetics since 2026" | Placing on the market ended May 1, 2025 and all sales on May 1, 2026 (Reg. (EU) 2024/996; https://cirs-group.com/en/cosmetics/eu-bans-4-mbc-and-supplements-alpha-arbutin-and-arbutin-into-the-restricted-ingredients-list-from-2025). It is also not a US monograph active (11 labels list enzacamene as an active) | "Banned in EU cosmetics (off shelves since May 2026); not an FDA monograph active" |
| filters, SPF>50 | "AAP recommends SPF 15 to 50; FDA proposed a 60+ label cap" | Reads as if AAP advises against more than 50. AAP: at least 15 "(up to SPF 50)", "15 or 30 should be fine", more research needed on >50 (https://www.healthychildren.org/English/safety-prevention/at-play/Pages/Sun-Safety.aspx) | "AAP: SPF 15–50 is enough; no proof higher adds protection. FDA has proposed (not final) capping labels at 60+" |
| glance, filters | "AAP: mineral-based is preferable for children; avoid oxybenzone if possible" | Accurate to the AAP pages, but the "avoid oxybenzone" half repeats the oxybenzone item (S4) | Drop "; avoid oxybenzone if possible" here |
| glance, broad spectrum ✓ | "Tested for UVA and UVB" | SPF measures (mostly) UVB, and the broad-spectrum test is the UVA test (21 CFR 201.327(j)) | "Passed FDA’s UVA test as well as SPF" |
| child, retinyl | header "Retinyl palmitate (vitamin A)" | The regex also matches retinol (55 labels) and other esters | "Vitamin A (retinol or retinyl esters)" |
| child, lavender | "Lavender or tea tree oil" | 160 of 468 matches are extracts or flower/leaf waters, not oils. The NEJM 2007 cases involved the oils | Match only names flagged `essential_oil` (or `/\bOIL\b/`); otherwise drop |
| child, salicylic | `/SALICYLIC ACID/` | Matches **capryloyl salicylic acid** (42 labels), a different substance not covered by the EU under-3 salicylic acid entry the topic cites | `/^SALICYLIC ACID\b/i` (as `under3_restricted` does) |
| eczema, UV allergy | fires on any `cf`: "Oxybenzone is the most reported UV-filter allergen" | Shown on products without oxybenzone; octocrylene photoallergy is the other main one | Fire only if oxybenzone or octocrylene is present, and name the one(s) on the label |

### S3. Hydroquinone actives get a soft yellow "Adult skincare active"
- **What:** 35 labels list hydroquinone as an active. FDA (Apr 19, 2022): "OTC skin lightening products containing hydroquinone are deemed to be new drugs and are misbranded." (https://www.fda.gov/drugs/drug-safety-and-availability/fda-works-protect-consumers-potentially-harmful-otc-skin-lightening-products)
- **Fix:** `if(A.includes('HYDROQUINONE')) out.filters.push(ITEM('stop','!','Hydroquinone','FDA: OTC skin-lightening products with hydroquinone can’t be legally sold without approval (2022)',…))`. This needs a library topic. Separately, `adult_active` currently opens the `age` topic (about under-6-months), which is irrelevant. Give it its own topic.

### S4. Things shown twice
- Retinoid: glance "Adult skincare active" plus child "Retinyl palmitate" (all 811 retinyl products; seen on Banana Boat Kids).
- Salicylic acid: glance `adult_active` plus child "Salicylic acid" (all 104).
- Tea tree/lavender oil: glance "Contains fragrance and essential oil" plus child "Lavender or tea tree oil" (Australian Gold).
- Oxybenzone "avoid if possible": glance plus filters item.
- Fragrance in eczema mode: glance plus NEA item plus "Fragrance on this label" (three times on Australian Gold).
- Broad Spectrum/SPF/Mineral only: glance plus the `.act` footer line.
- **Fix:** keep retinoid and salicylic in the child section only, and in glance show `adult_active` only when it isn't a retinoid or salicylic acid. Skip the child lavender item when the glance fragrance item already names that oil, and add the hormone note to the fragrance item's sub-line instead. Drop "avoid oxybenzone" from glance. In eczema mode, merge the fragrance mention into the NEA item. Drop BS/mineral from the footer.

### S5. Green ticks on incomplete or empty ingredient lists
- 11 products have an empty `ing`. 344 are `thin` (≤7 names, including 17 with no printed list), and 148 of those get a green "No fragrance listed". 545 tier-C products get the same tick.
- Essential-oil misses that also get a green tick: "Cedarwood Essential Oils", "citrus reticulata (mandarin) & citrus aurantium (petitgrain) pure essential oils", "Vanilla plantifolia (Vanilla essential oil)". `is_essential_oil` needs `/ESSENTIAL OIL/`.
- **Fix:** `const thin=!p.ing.length||p.thin||p.ev==='C';` For thin lists, render the fragrance, booster and NEA ticks as info: "Not on the filed list · this list may be incomplete". In sunnytime_rules.py add `ESSENTIAL OILS?` to the essential-oil test.

### S6. `nice()` deletes the qualifiers parents need
`nice=n=>…replace(/\(.*?\)/g,'')`. This drops "(Tea Tree)", "(Oat)", "(Soybean)", "(Lavender)" and, critically, "(source not stated; lecithin is most often from soy)". A tired parent can't tell what "Melaleuca Alternifolia Leaf Oil" or "Glycine Soja Oil" is. Fix: keep a short parenthesised common name (≤20 chars). For annotations that start "source not stated", render "(source not stated)".

### S7. The recall item lost its reason and link
New card: "Recall on record · Check the lot number on your tube against the FDA notice". The current card says "Contamination" or "Benzene". It has no date and no notice URL, and says "tube" for spray cans. It also ignores `p.rk` (all 9,460 are `rk=1` today, but the tick would be false if a product hadn't been checked). Fix: show the reason (`p.r`) and the recall date and link (`p.rr`), and say "package". Guard `p.rk?…:''` like renderNow.

### S8. The chemical-filter list is cut short without saying so
`esc(names(cf,3).replace(/…$/,''))` shows 3 of 5 filters with no ellipsis. Australian Gold shows "Avobenzone, Homosalate, Octisalate" and hides octocrylene and oxybenzone. Fix: `names(cf,6)`.

### S9. Bemotrizinol/4-MBC produce contradictory output
45 products whose only booster match is in `BOOST_EXCL` get a green "No SPF booster listed as inactive" tick, while the Label check section names a UV filter listed as inactive. Fix: `hb&&!bn.length` → no tick at all.

### S10. Disclosure placement (FTC)
"I also make Sunnytime…" appears only after the ingredient fold at the very bottom of each card. FTC guidance asks for disclosure of a material connection that is clear and conspicuous, close to the claims and hard to miss (https://www.ftc.gov/business-guidance/resources/ftcs-endorsement-guides-what-people-are-asking). Fix: also put a one-line disclosure at the page top or next to the search: "Made by ARW House, which also sells Sunnytime (a mineral baby sunscreen). Same rules for every product." Keep the card-bottom line.

---

## NICE-TO-HAVE

- **Coverage (sourceable):**
  - **Flammable spray**: 810 sprays contain alcohol; FDA's 2012 warning on burns near flame (https://cbsnews.com/news/fda-reminds-consumers-spray-on-sunscreens-can-catch-fire), plus the 2019 proposed flammability labelling (fr_2019).
  - **Non-monograph actives** (drometrizole trisiloxane 23, DHHB 15, ethylhexyl triazone 13, ecamsule 10 (NDA-approved), bisoctrizole, amiloxate, ethyl methoxycinnamate): an info line "Not one of FDA’s monograph actives".
  - **Octocrylene EU limit** (10%; 9% in propellant sprays): Banana Boat spray is at 10%.
  - **SPF below 30**: info "AAD and Health Canada recommend SPF 30+". This matters more under the psoriasis chip, since AAD psoriasis advice is SPF 30+ and water resistant (verified: https://www.aad.org/public/diseases/psoriasis/triggers/flares; the 10-14 day flare timing is accurate).
  - **Water resistant**: show "(40/80 minutes)" and "reapply every 2 hours and after swimming" in the glance, not only in the footer.
  - **Under 3 chip**: add `ipbc`, `under3_restricted`, and phenoxyethanol (ANSM nappy-area advice).
  - **Under 6 months**: the `age` topic already says shade first; consider a chip.
- **Recall copy:** "No recalls on record" → "No FDA recall found (as of …)". This avoids a green tick that reads as a safety endorsement.
- **Booster status line:** `UVS` says "EU not permitted" for butyloctyl/tridecyl salicylate. That means "not on the EU UV-filter list"; it is not banned as an ingredient. Say so in the `status` fill.
- **Wording:** "Mineral filters only · Zinc oxide or titanium dioxide" → show the product's actual actives (done in M1). In head(), "Label on file 2026-10-25" should use `fmtD`, like the other dates.
- **Phone usability:**
  - Every item carries an identical "Why this matters · sources" disclosure: 15-25 per card, a long scroll.
  - Collapse the green ticks into one row ("5 checks passed ▸") and sort red, then yellow, then blue.
  - The ★ icon for a chip match is unexplained. Use a text badge such as "Eczema".
  - With no chip selected, the whole "Check for your child" list shows as yellow `!`. Consider showing it collapsed until a chip is tapped.
  - "Checked against the package by two readers" needs a tap-to-explain.

## Verified as accurate (no change)
- "Homosalate … EU allows up to 7.34%, face products only. US allows 15%": Reg. (EU) 2022/2195 and M020. The text is right; only the threshold logic is wrong (S2).
- "FDA: shown only to help prevent sunburn": 21 CFR 201.327 / FDA consumer page.
- "Only the 'under 6 months: ask a doctor' line every US sunscreen must carry": 21 CFR 201.327(e).
- "No federal standard for 'hypoallergenic'": FDA.
- "A 2021 study found benzophenone forming in [octocrylene] as products aged": Downs et al., Chem Res Toxicol 2021.
- "Sunburn can trigger a flare 10 to 14 days later": AAD psoriasis flares page.
- AAD eczema advice "only… titanium dioxide and/or zinc oxide" and fragrance-free: consistent with the library quote.
- AAP "If possible, avoid… oxybenzone": healthychildren.org Sun Safety.
