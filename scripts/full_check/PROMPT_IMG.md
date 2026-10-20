You are reading sunscreen label images from FDA DailyMed to transcribe the inactive-ingredient list. Accuracy matters more than speed.

Input: BATCH_FILE (a JSON array). Each entry: setid, name, actives, images (absolute paths of label images), db_list (our current database list, for reference only).

For each entry open every image with the Read tool and look for the "Inactive ingredients" panel (or "Ingredients:" / "Other ingredients"). Transcribe it, in label order:
- One ingredient per item, exactly as printed; keep bracketed common names with their ingredient.
- If a word is not legible, write your best reading and append " [?]". Never fill a gap from db_list.
- Leave out the declared actives, headings, footnotes, company text.
- If the images show a different product than `name`, set mismatch=true.
- If no image shows an inactive-ingredient list, found=false (say what the images show in note, e.g. "front panel only").
- legibility: "clear" | "partial" | "unreadable".

Do not read any other files in the results folder. Write the output with the Write tool to OUT_FILE as a JSON array:
[{"setid": "...", "found": true, "inactives": ["..."], "legibility": "clear", "mismatch": false, "note": ""}]
Then reply with just: done N.
