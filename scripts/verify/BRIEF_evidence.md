# Fact-check brief: the Sunscreen Check evidence library

Context: arwhouse.com/sunnytime ("Sunscreen Check") shows every US sunscreen with short items, each with a
"Why this matters · sources" panel: single factual sentences, each tied to one source. The publisher also makes a
mineral baby sunscreen, so neutrality matters: every sentence must be a fact the cited source actually supports,
at the strength the source states it (a law is a law, a proposal a proposal, a study a study).

File: data/reference/evidence_library.json (generated from data/reference/evidence_library_src.py; do NOT edit either)
- `sources`: key -> {org, title, url, date, strength}
- `topics`: list of {id, title, facts:[{t, s}], other_side:[{t,s}], not_known:[...]}; `s` is a source key.

For every sentence in YOUR assigned topics (facts and other_side):
1. Open the cited source (WebFetch; WebSearch if the URL fails or to find the current official page; the shell has no network).
2. Verdict: OK / WORDING (supported but overstated, understated, missing a qualifier, quote not verbatim,
   wrong date or number) / WRONG (source does not say it, or says otherwise) / OUTDATED (true when written,
   but a newer official action changed it) / UNVERIFIABLE (could not reach; say what you tried).
3. For anything not OK give the exact corrected sentence and a supporting quote (25 words or fewer) with its URL.
4. Check each source's org, title, date and URL.
5. Look for official changes since the library's version date: FDA (orders, proposed rules, monograph changes),
   EU (Cosmetics Regulation amendments, SCCS final opinions), Health Canada, Australia TGA decisions, AAP/AAD/NEA
   guidance updates, US state laws on sunscreen ingredients. Name each change with its primary source.
6. Note any important official counterpoint missing from `other_side`.
Use only primary or official sources for a correction; news alone is not enough (say so if that is all you found).

Output: write your findings to <OUT>/<your_name>.md as a table (topic id | # | verdict | issue | corrected sentence |
quote + url), then lists of outdated items and missing counterpoints. Return a summary with counts per verdict and
every non-OK item.
