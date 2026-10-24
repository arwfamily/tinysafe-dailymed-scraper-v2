# Transcribe the package artwork of baby/kids sunscreens

For each product in your pack, open EVERY image file listed in "images" with the Read tool. These are the package artworks (carton, tube, label) the brand filed with the FDA. Zoom in by re-reading if text is small; you may crop with Python/PIL into your own scratch files if needed.

Transcribe exactly what the artwork prints. Read each product only from its own images; never borrow a list from another product in the pack, even if it looks like the same formula. Never guess or fill from memory: if something is not visible or not readable, use null and say so in "notes".

Write a JSON array to the output path you are given, one object per product:
{
 "setid": "...",
 "readable": true | false,                  // false if no image shows the Drug Facts panel legibly
 "variants": 1,                             // how many different products/formulas the images show (different SPF, scent, formula, size with different lists)
 "spf": 50 | null,                          // as printed; if variants differ, the main product's, and list all in notes
 "broad_spectrum": true | false | null,       // true if "Broad Spectrum" is printed anywhere as this product's claim (front, name or Uses; NOT the boilerplate "Broad Spectrum SPF value of 15 or higher"); false only when the whole label is visible and never claims it; if only part of the label is shown and no claim is seen, null
 "form": "lotion|cream|stick|spray|aerosol spray|non-aerosol spray|powder|oil|other" | null,
 "actives": [["Zinc Oxide", 20.0], ...] | null,   // Drug Facts "Active ingredient(s)" with printed %
 "inactives": ["Water", "..."] | null,      // the Drug Facts "Inactive ingredients" list, in printed order, each ingredient as printed (keep parentheses), split on commas
 "fragrance_free_claim": true | false,      // "fragrance free", "unscented", "no fragrance" anywhere on the artwork
 "scent_named": "Fun Melon" | null,         // a scent named on the front ("Coconut scent", "... Fragrance")
 "allergen_statement": "Allergens: soybeans (glycerin)" | null,
 "age_limit": "Do not use on children under 12" | null,   // an age limit the label prints, in its words, other than the standard "children under 6 months: ask a doctor"
 "notes": "anything that matters: several variants, unreadable parts, a footnote listing fragrance components, etc."
}

Reply only with: number transcribed, number unreadable, number with more than one variant.

If you crop images, put the crops in your own folder named after your pack, e.g. WORK/crops_<pack name> (other agents work at the same time).
