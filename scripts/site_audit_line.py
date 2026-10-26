#!/usr/bin/env python3
"""Rewrite the Check's numbers and accuracy line in <arwhouse>/sunnytime/index.html from the published db.json
and the latest data/verification/audit_history.jsonl row, without a rebuild (used after the monthly audit).

Usage: site_audit_line.py <arwhouse checkout>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import site_db  # noqa: E402

site = sys.argv[1]
db = json.load(open(os.path.join(site, "sunnytime/db.json"), encoding="utf-8"))
h = site_db.headline(db)
for rel in ("sunnytime/index.html", "sunscreen-check/index.html"):
    idx = os.path.join(site, rel)
    if os.path.exists(idx):
        html = open(idx, encoding="utf-8").read()
        open(idx, "w", encoding="utf-8").write(site_db.patch_index(html, h))
        print("rewrote", idx)
