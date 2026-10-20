You are transcribing sunscreen inactive-ingredient lists from FDA DailyMed label text. Accuracy matters more than speed.

Input: BATCH_FILE (a JSON array). Each entry: setid, name, actives (the declared active ingredients), label_text (the label's printed inactive-ingredient text as filed with FDA; it may be run together with no separators, OCR-garbled, bilingual, or contain several products' lists), db_list (our current database list, for reference only).

For each entry produce the label's inactive ingredient list, in label order:
- Split run-together text into individual ingredient names using your INCI knowledge ("Caprylyl GlycolCetyl Alcohol" -> "Caprylyl Glycol", "Cetyl Alcohol"; "Water (Aqua) Cetyl Alcohol Glycerin" -> "Water (Aqua)", "Cetyl Alcohol", "Glycerin"). Keep bracketed common names with their ingredient ("Butyrospermum Parkii (Shea) Butter").
- Fix an OCR misspelling only when the intended INCI name is certain ("Propanedi01" -> "Propanediol"). If a word cannot be determined, keep your best reading and append " [?]".
- Leave out: the declared actives (and their INCI synonyms, e.g. Octocrylene, Ethylhexyl Salicylate, Butyl Methoxydibenzoylmethane, Zinc Oxide), headings, footnotes ("*Certified organic", "Denotes ..."), company names/addresses, marketing text, lot/formula codes.
- Only list what is in label_text. Never add an item from db_list that the text does not contain.
- If label_text holds lists for several products, use the one matching `name`; say so in note.
- If label_text contains no ingredient list at all, found=false.

Do not read any other files in the results folder. Write the output with the Write tool to OUT_FILE as a JSON array:
[{"setid": "...", "found": true, "inactives": ["...", "..."], "note": "short note or empty"}]
Then reply with just: done N.
