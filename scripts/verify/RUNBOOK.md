# Weekly upkeep of the Sunnytime Check (run every Monday after the DailyMed scrape)

Goal: keep the published database at the v3.12 evidence standard as labels change. Every label
whose filing is new or changed gets its package artwork read once (read1), then checked by a
second independent reader (confirm), and disagreements go to a third reader (third). Nothing is
published unless the quality gate passes.

Repos: `arwfamily/tinysafe-dailymed-scraper-v2` (data, this repo) and `arwfamily/arwhouse` (site,
`sunnytime/db.json`). In a Claude cloud session use the REST API through `env -u GH_TOKEN gh api ...` (GraphQL, and so `gh workflow run`, is not available there).
WORK below is a scratch folder outside both repos (e.g. the session scratchpad).

## 0. Wait for the weekly scrape
`env -u GH_TOKEN gh api 'repos/arwfamily/tinysafe-dailymed-scraper-v2/actions/workflows/scrape.yml/runs?per_page=1' --jq '.workflow_runs[0]|[.status,.conclusion,.created_at]'` must show today's run `completed`/`success`.
If it is still running, check again every 15 minutes (up to 6 hours). If it failed, stop and report
(do not rebuild on a failed run). Then `git pull` in both repos.

## 1. Pick the labels
`python3 scripts/verify/weekly.py targets --tag wYYYYMMDD` (cap 360) writes
`data/views/adult_batches/batch_wYYYYMMDD.txt`. Commit and push it (the image workflow reads it from main).

## 2. Fetch their package images (GitHub Actions has the network)
`env -u GH_TOKEN gh api -X POST repos/arwfamily/tinysafe-dailymed-scraper-v2/actions/workflows/label_images_batch.yml/dispatches -f ref=main -f 'inputs[batch]=wYYYYMMDD'`;
wait for it to finish (same runs query on `label_images_batch.yml`; about 20 minutes for 360 labels), then
`git fetch origin "+refs/heads/label-images-bwYYYYMMDD:refs/remotes/origin/label-images-bwYYYYMMDD" && mkdir -p WORK/images && git archive origin/label-images-bwYYYYMMDD | tar -x -C WORK/images`
(the clone may track main only, so the refspec is spelled out).

## 3. read1
`python3 scripts/verify/weekly.py packs read1 WORK --images WORK/images --targets data/views/adult_batches/batch_wYYYYMMDD.txt`
Run one agent per 3 packs (at most 14 at a time) with: "Follow scripts/verify/BRIEF_read1.md
exactly (WORK = <WORK>), for packs rNNN, rNNN, rNNN: input WORK/read1/packs/NN.json, output
WORK/read1/out/NN.json. Write each output as soon as that pack is done. Reply with counts."
Pop packs from WORK/read1/queue.txt. When all outputs exist:
`python3 scripts/verify/weekly.py merge read1 WORK`

## 4. Rebuild (so the site shows what read1 confirmed), then confirm
`python3 scripts/us_master.py && python3 scripts/us_release.py && python3 scripts/reading_queue.py && python3 scripts/site_db.py --old <arwhouse>/sunnytime/db.json --out data/site/sunnytime_db.json --index <arwhouse>/sunnytime/index.html`
(about 20 minutes; run it in the background). If the gate fails here, stop: do not run confirm on the
older site file; report the gate's examples and fix the cause first (the site keeps last week's data).
`python3 scripts/verify/weekly.py packs confirm WORK --images WORK/images`, agents with
BRIEF_confirm.md (packs cNNN, outputs WORK/confirm/out), then `weekly.py merge confirm WORK`.

## 5. third
`python3 scripts/verify/weekly.py packs third WORK --images WORK/images`, agents with
BRIEF_third.md (packs tNNN, 4 per agent), then `weekly.py merge third WORK`.

## 6. Rebuild, gate, publish
`python3 scripts/verify/image_names.py` (adds this week's package-image names for the product photos) and
`python3 scripts/verify/weekly.py thumbs --images WORK/images --site <arwhouse>` (their thumbnails, sunnytime/p/<setid>.webp), then rebuild as in step 4. The site_db step prints the gate; it exits non-zero (and writes nothing) if
any unchanged label lost an ingredient or a warning. On a gate failure: do not publish; report the
examples. Then
`python3 scripts/verify/weekly.py report <arwhouse>/sunnytime/db.json data/site/sunnytime_db.json --out data/reports/weekly_YYYY-MM-DD_flag_changes.md`
lists labels whose filing changed and lost a warning; and
`python3 scripts/verify/selfcheck.py data/site/sunnytime_db.json --site <arwhouse>` must exit 0 (no placeholder or run-together ingredient names, every warning has its text, every photo its thumbnail); read each one (a brand removing an ingredient is
expected; a filing error is not) and note them in the report.
Commit the data repo (`data/`, corrections) and push; `cp data/site/sunnytime_db.json <arwhouse>/sunnytime/db.json`;
`python3 scripts/verify/card_render_check.py <arwhouse>` must exit 0 (every product's card on arwhouse.com/sunscreen-check renders, with and without the child options, and every item has its sources panel);
`python3 scripts/site_rules_page.py <arwhouse>` and `python3 scripts/site_corrections_page.py <arwhouse>` (both generated
from the data repo: the evidence library, flag texts, changelog, audits and reader reports);
commit `sunnytime/db.json`, `sunnytime/evidence.json` (written by site_db next to index.html), new thumbnails in
`sunnytime/p/`, `sunnytime/index.html` (headline numbers, intro count and audit line only),
`sunscreen-check/index.html` (numbers and accuracy line only), `sunscreen-check/how-we-check/index.html` and `sunscreen-check/corrections/index.html`, and push.
Never change any other site copy in this job: copy changes need the owner's approval.

### Reader error reports (angela@arwhouse.com)
Reports arrive by email to the owner. A report changes nothing by itself: two readers check the evidence
(package photo or link) within 7 days, as for any correction. A brand's request to remove an item needs
evidence that the ingredient is not in the product. Record every handled report, changed or not, as one line in
`data/corrections/reader_reports.jsonl` ({date, product, setid, reported_by: parent|brand, what, fix}); the
corrections page lists them. Never put the reporter's name or email in that file.
Then confirm the site actually deployed: `env -u GH_TOKEN gh api repos/arwfamily/arwhouse/commits/<sha>/status --jq '.statuses[]|[.context,.state,.description]'`
must show `Vercel success` within about 5 minutes. If no status appears after 10 minutes, push an empty commit
(`git commit --allow-empty -m "Redeploy"`) and check again; report it if it still does not deploy.

`python3 scripts/verify/fullcheck.py data/site/sunnytime_db.json --out WORK/fullcheck.json` compares every
published label with its own label text (actives and strengths, SPF, printed inactive names, fragrance,
age limit). For each label whose filing changed this week and is listed there, run reviewers with
scripts/verify/BRIEF_adjudicate.md (packs of 40, built as in the 2026-10-24 session: site_shows,
label_text, issues, images) and add their "site_wrong" fixes to data/corrections/text_review.jsonl
(only UV-filter actives; no names for a label whose list is withheld); then rebuild.
A Broad Spectrum claim that rests on one package read (no claim in the label text, no second read)
gets a second blind read (BRIEF_third with only the broad_spectrum question) into
data/corrections/bs_reads.jsonl before it is shown.

`python3 scripts/verify/weekly.py recalls` lists recall matches still "under review" (brand + name
only). Judge each against its recall description (name, form, SPF, actives and strengths) and record
the verdict in `data/reference/recall_reviews.json` (`same_product` / `not_this_product` + why); when
the description cannot tell (a skin type or size not stated), leave it under review. Rebuild if any changed.

## 7. Report
Send the owner a short summary in Korean: labels changed this week, read1/confirm/third counts,
tier A/B/C totals, gate result, any warnings lost by changed labels, and anything that needs a
decision. Commit messages end with the session's attribution lines.

## Rules that must not be loosened
- A field read once that disagrees with the filing is not used until a second reader agrees.
- Lists only gain names (a package can print two lists); nothing is renamed on reads. The one
  removal: a filed name three readers found printed nowhere, that gives no warning, AND whose
  printed form is already in the list (a duplicate or misspelling) or that is a footnote.
- A package read never takes a filed active away in a kit or multi-product filing, and never takes
  away an active that is not a sunscreen filter (its warning must stay).
- Recalls: a recall is shown on a label only when matched by setid, NDC, a person's review, or the
  same brand + product words + SPF + every active strength + form. A brand + name match alone shows
  "under review" until it is reviewed in data/reference/recall_reviews.json.
- A confirmation the reader was unsure of does not make tier A.
- Reads are tied to spl_version; a changed label is read again.
- A first read counts as a package check (tier B) only when every active and its % was legible and
  the reader was sure; otherwise the label stays "filing only" (C). (2026-10-25)
- A one-read label whose second reader saw another product, another SPF or other actives is C,
  never B. (2026-10-25)
- Filed images below about 400k pixels are rarely legible; read them only if time allows, and an
  unreadable result keeps the label at C.
