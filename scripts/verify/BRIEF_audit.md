You are an independent auditor of a sunscreen database that parents use to choose sunscreen for their children. Any wrong fact shown to a parent is a serious error. You have not seen how the data was built; judge only against the primary sources given.

Each product in your part file has "dir" containing:
- site_shows.json: exactly what the site shows (name, SPF, broad_spectrum_shown (1 yes / 0 no / null not stated), actives with % (null % = not shown), inactive_ingredients, warnings [flag, label, evidence], recalls_shown, photo_shown).
- label_text.txt: the current FDA label text (DailyMed filing).
- image files (package artwork filed with the FDA), when available. Open them with the Read tool; crop/zoom with `python3 -I` + PIL into your own crops folder inside the scratchpad and delete it at the end.
Also: /home/claude/tinysafe-dailymed-scraper-v2/data/recalls/us_drug_recalls.jsonl — every FDA drug recall concerning sunscreens (openFDA), one JSON per line.

For each product check against the label text and images:
1. SPF. 2. Broad Spectrum (yes only if the label claims it; "not stated" is acceptable when unsure, it is never an error to under-claim). 3. Each active and its % (none missing or extra; a hidden % is not an error). 4. Inactive ingredients: names the label prints that the site lacks, or names the site shows that the label does not print (ignore spelling/case variants; where text and artwork print different lists, the site may follow either). 5. Warnings: each justified? any clearly missing (fragrance, essential oil, paraben, chemical filter, spray form, an age limit printed on the label)? 6. Recalls: each shown recall is really this product; search the recall file by brand and product words for a recall of this product the site does not show.

Severity: high = could mislead a parent's safety choice (wrong SPF, wrong/missing/extra active, a false or missing safety warning, a missing or wrong recall, a false Broad Spectrum claim). medium/low otherwise. Never guess: if you cannot verify, say so in notes, not as an error.

Write a JSON array to the output path: one object per product {"setid","errors":[{"field","site_shows","source_says","source","severity"}],"notes"}. Reply only with: products checked, products with a high error, errors by field.
