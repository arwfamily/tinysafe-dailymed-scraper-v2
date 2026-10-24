# Third, independent read of a few disputed facts on a sunscreen package

Two earlier readers disagreed about a few facts on each product's package artwork. You settle them by reading the artwork yourself. You are NOT told what either reader said.

Each product in your pack has "images" (package artwork filed with the FDA), "product" (its name) and "questions":
- "broad_spectrum": present when we need to know whether the package prints the claim "Broad Spectrum" (on the front or principal panel, or in the Drug Facts "Uses"/claim). Answer true (printed), false (not printed anywhere on these images) or "unclear".
- "names": a list of ingredient names. For each, answer whether the package's ingredient list (Drug Facts "Inactive ingredients" or a full ingredient list) prints that ingredient: "printed", "not_printed" or "unclear". Ignore case, punctuation and trivial spelling; a colorant in a "may contain" group counts as printed. A different ingredient with a similar name (methyl vs menthyl lactate; leaf extract vs leaf juice) is "not_printed".

Steps:
1. Open every image with the Read tool. Crop/zoom with python3 -I and PIL into WORK/crops3_<pack name>/ (put any helper script inside that folder, never in a shared folder; delete the folder when you finish).
2. Never guess. If you cannot read it with confidence, answer "unclear". A wrong answer is worse than unclear.
3. If the images show another product, set "wrong_product": true; if several products or formulas, "variants": n.

Write a JSON array to the output path, one object per product:
{"setid", "spl_version" (copy), "broad_spectrum": true|false|"unclear"|null (null when not asked), "names": {name: "printed"|"not_printed"|"unclear"}, "wrong_product": bool, "variants": n, "notes": short}

Reply only with counts: products done, wrong_product, unclear answers.
