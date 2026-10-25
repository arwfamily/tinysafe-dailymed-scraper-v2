# Settle a disagreement between the site and the label text

Each item is one sunscreen label where an automatic check found that what the site shows differs from the
label's own FDA text. Most differences are the checker misreading the text (a typo like "Titianium",
a strength written before the name, a comma inside "1,2-Hexanediol", an address or marketing sentence
taken as an ingredient). Some are real errors on the site. Your job is to tell them apart, using only
the sources in the item.

Each item has: "site_shows" (what parents see), "label_text" (the current FDA label text), "issues"
(what the checker flagged), "package_read_actives" / "package_read_twice" (an earlier reading of the
package artwork), and "images" (package artwork files, open them with the Read tool when present).

For each issue decide:
- "checker_noise": the site is right; the checker misread (say how, in a few words).
- "site_wrong": the label text (or the package images) clearly prints something the site gets wrong.
  Give the fix: for actives, "actives": [[NAME, percent], ...] exactly as printed (US names: octinoxate
  for ethylhexyl methoxycinnamate, octisalate for ethylhexyl salicylate, avobenzone for butyl
  methoxydibenzoylmethane, oxybenzone for benzophenone-3, ensulizole for phenylbenzimidazole sulfonic
  acid); for inactives, "add_inactives": [names exactly as printed] (only real ingredient names the
  label prints and the site lacks under any spelling).
- "package_differs": the site follows the package artwork (read twice), the text prints another
  formula; both are official. Say which values each shows.
- "cannot_tell": the sources do not settle it.
Never guess. A wrong fix is worse than "cannot_tell".

Write a JSON array to the output path: one object per item
{"setid", "spl_version", "verdicts": [{"type", "verdict", "actives"?, "add_inactives"?, "why"}]}.
Reply with counts: items, site_wrong, package_differs, cannot_tell, checker_noise.
