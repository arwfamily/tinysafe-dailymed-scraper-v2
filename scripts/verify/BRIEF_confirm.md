# Second, independent check of a sunscreen record against its package artwork

Each product in your pack has "images" (package artwork filed with the FDA) and "shown": what our database shows (name, spf, broad_spectrum, actives with percent, inactives in order, form). One reader has already checked it once. You are the independent second check.

For each product:
1. Open every image with the Read tool. Crop/zoom with python3 -I and PIL into WORK/crops_<pack name>/ (keep crops small; put any helper script you write inside that same folder, never in a shared folder; delete the folder when you finish).
2. Read the artwork YOURSELF first (front panel for SPF and Broad Spectrum; Drug Facts for actives and inactives; any full ingredient list), THEN compare with "shown".
3. Check: spf, broad_spectrum (printed or not), each active and its percent, and the inactive list: list every name shown that the artwork does NOT print, and every name the artwork prints that is NOT shown (ignore case, punctuation and trivial spelling; a colorant in a "may contain" group counts).
4. Never guess. If something cannot be read with confidence, say "unclear" for that field. A wrong value is worse than unclear.

Decision per product:
- "confirmed": every field you could read matches "shown" (minor spelling or order differences are fine; list them in notes).
- "differs": at least one field you read with confidence differs (wrong SPF, wrong or missing active, wrong percent, an ingredient missing or extra).
- "unreadable": the artwork cannot be read well enough to check actives and inactives.
- If the images show another product, set "wrong_product": true; if several products or formulas, "variants": n.

Write a JSON array to the output path, one object per product:
{"setid", "spl_version" (copy), "decision", "spf": n|"unclear"|null, "broad_spectrum": true|false|"unclear", "actives": [[name, pct]]|null, "shown_not_on_artwork": [...], "on_artwork_not_shown": [...], "wrong_product": bool, "variants": n, "age_limit": "the label's own words" | null, "notes": short}

"age_limit": an age limit the label prints (e.g. "not for use on children under 12", "for adult use only"), other than the standard "children under 6 months: ask a doctor"; null if none is printed.

Reply only with counts: confirmed / differs / unreadable.
