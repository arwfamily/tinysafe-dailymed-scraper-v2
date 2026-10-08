# Baby Sunscreen Label Dataset (US, with EU and Australian limits)

Published by **ARW House** · Author: **Angela Lee, Founder** · Site: https://arwhouse.com/evidence

A weekly, reproducible dataset of US sunscreen drug labels from the FDA's
DailyMed database, with:

- every sunscreen label found through its active ingredients (13,000+ SPLs),
  snapshotted weekly in `data/raw/dailymed/<date>/` and kept current in
  `data/canonical/us_sunscreens.jsonl`;
- a formulation history (`data/history/us_formulation_history.jsonl`): new,
  reformulated and delisted labels, week by week;
- legal limits for 20 UV filters in the US (FDA OTC monograph M020 and final
  orders), the EU (Cosmetics Regulation Annex VI) and Australia (TGA
  Permissible Ingredients Determination), each value linked to its source
  (`site/evidence.json`);
- counts for baby and kids sunscreen labels (`claims/claim_ledger.json`),
  computed by `claims/registry_stats.py` from the files above.

## What the counts mean

- **Population:** unique formulations of sunscreen labels that say baby or
  kids, selected by rule from the label, edge cases decided by hand
  (`claims/baby_review_*.csv`, every decision with its reason). Labels for
  another market, labels that do not meet US limits as listed, and
  multi-product listings are left out (`claims/population_exclusions.csv`).
- **Corrections:** where a manufacturer's structured filing contradicts its
  own Drug Facts, the Drug Facts are used (`data/corrections/`).
- **Limits of the data:** a DailyMed listing is not proof that a product is
  on US shelves today. Counts describe labels, not safety, and not market share.

## Reproduce

Python 3.11, standard library only.

```
python claims/registry_stats.py      # counts -> claims/claim_ledger.json
python scripts/build_evidence.py     # -> site/evidence.json
python scripts/render_site.py --check
python tests/test_classify.py && python tests/test_matrix.py && python tests/test_fingerprint.py
```

The weekly pipeline is `.github/workflows/scrape.yml`.

## Cite

See `CITATION.cff`. Each release is archived on Zenodo with its own DOI.

## License

Data and documentation: CC BY 4.0. Source FDA DailyMed content is public
information from the U.S. National Library of Medicine.
