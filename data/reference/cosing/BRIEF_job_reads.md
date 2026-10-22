# Task: the main job of each cosmetic ingredient in a SUNSCREEN

Each item: an INCI name, how many US sunscreen labels use it, and the functions the EU CosIng
register lists for it. CosIng lists every function an ingredient MAY serve in any cosmetic,
so it is evidence, not the answer. You decide the ONE main job this ingredient does in a
leave-on sunscreen (secondary job optional). Parents will read it next to the ingredient,
and ingredient-savvy parents will compare it with INCIDecoder. It must be right.

Allowed jobs (use the key):
  base (water), emollient, occlusive, humectant, emulsifier, emulsion_stabiliser, thickener,
  film_former, preservative, preservative_booster, chelating, antioxidant, ph, colorant,
  opacifier, absorbent (oil-absorbing/mattifying powder), slip (silicones/powders for feel),
  dispersing (keeps UV-filter particles spread), mineral_coating (surface treatment of ZnO/TiO2),
  solvent, fragrance, soothing, skin_conditioning, skin_protecting, uv_filter, uv_booster
  (absorbs UV but is not an approved US active, e.g. butyloctyl salicylate, ethyl ferulate,
  diethylhexyl syringylidenemalonate), photostabiliser, cleansing, propellant, denaturant,
  astringent, exfoliant, other

Rules:
- Prefer a job that matches one of the CosIng functions. If none fits (CosIng is incomplete or
  only lists perfuming for a plant oil), pick the right job and set "override": true with a
  one-line reason.
- "fragrance" only for ingredients added for scent: Parfum/Fragrance, essential oils,
  aroma chemicals, EU-listed fragrance allergens. A plant oil or extract whose CosIng entry
  only says "perfuming" is NOT fragrance; give its real job (emollient for a fixed oil,
  skin_conditioning or antioxidant or soothing for an extract) and override true.
- Never use an origin (plant, animal, synthetic) as a job.
- confidence "low" when reasonable formulators would disagree.

Output a JSON array, one object per input item, same order:
  {"inci": ..., "job": <key>, "secondary": <key or null>, "override": true|false, "reason": <short or "">, "confidence": "high"|"low"}
Work independently; do not read other output files in this folder.
Write to the output path you are given, then reply only with counts per job and number of overrides.
