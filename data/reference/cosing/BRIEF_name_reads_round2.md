# Task: map US sunscreen label ingredient names to their EU CosIng INCI name

You get a JSON list of ingredient names as they appear on US sunscreen labels (printed Drug Facts,
or the FDA's filed substance names, which use USAN/UNII wording such as "EDETATE DISODIUM",
".ALPHA.-TOCOPHEROL", or bare common plant names such as "GUAVA").
These are the names an automatic matcher could NOT match exactly. Accuracy matters more than
coverage: parents will read the result. A wrong mapping is much worse than "unsure".

For EVERY name, output one object:
  {"name": <exactly as given>, "kind": K, "inci": <string or null>, "plant": <string or null>, "category": <string or null>, "confidence": "high"|"low", "note": <short>}

kind is one of:
  - "INCI"   : the name is the same ingredient as one CosIng INCI name. Put that INCI name in "inci",
               copied EXACTLY from cosing_inci_names.txt (grep it; it must exist there verbatim,
               case-insensitive). Typos, US vs EU spelling, USAN names, word order, missing
               plant part where the part is unambiguous, extra words like "Color"/"organic" all count.
               Only when you are sure it is the same substance. A salt, ester, hydrogenated or
               ethoxylated form is NOT the same substance.
  - "PLANT"  : a plant (or alga/fungus) material where the label does not say which part or
               preparation, so no single INCI fits (e.g. "GUAVA", "LINGONBERRY", "CHAMOMILE").
               Put the Latin binomial in "plant" (e.g. "Psidium guajava"). If the plant itself
               is ambiguous (several species), put the common name and confidence "low".
  - "NO_COSING": a real cosmetic ingredient with no CosIng entry you can find. Put a functional
               category in "category" from this list only:
               emollient, emulsifier, humectant, thickener, film former, preservative, antioxidant,
               chelating, pH adjuster, colorant, fragrance, solvent, skin conditioning, soothing,
               UV filter, silicone, surfactant, plant-derived, other
  - "NOT_INGREDIENT": a fragment, a header, a marketing phrase, a mix of several ingredients run
               together that cannot be split, or garbage text.

Rules:
- Do not guess. If unsure between two INCI names, use kind "INCI" with confidence "low" and say why in note,
  or kind "NO_COSING".
- Fragrance-allergen chemical names (e.g. ".ALPHA.-HEXYLCINNAMALDEHYDE") map to their INCI (HEXYL CINNAMAL).
- UV filter USAN names map to INCI (e.g. TROLAMINE SALICYLATE -> TEA-SALICYLATE).
- Work independently; do not look for other people's answers in the scratchpad.

Files:
- names: the batch file you are given
- valid INCI names: cosing_inci_names.txt in the same folder (one per line)
Write your output as a JSON array to the output path you are given, then reply with only:
counts per kind, and the number with confidence low.

Extra notes: many of these names occur on only one label and are typos, OCR errors or pieces of a split list. Fix obvious typos to the right INCI (high confidence only when certain). Storage or usage text, headers, and pieces that cannot be identified are NOT_INGREDIENT.
