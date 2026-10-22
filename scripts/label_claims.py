#!/usr/bin/env python3
"""Read the full text of every in-scope label once and record its sun-protection
claims (runs on GitHub Actions; the dev container cannot reach DailyMed).

  broad_spectrum : the label claims Broad Spectrum. The Drug Facts boilerplate
                   "use a sunscreen with a Broad Spectrum SPF value of 15 or higher"
                   does not count.
  aging_alert    : the label carries the FDA "Skin Cancer/Skin Aging Alert", which a
                   sunscreen must print when it is NOT broad spectrum or is SPF 2-14
                   (21 CFR 201.327). Definitive.
Output: label_claims/claims.jsonl, label_claims/failed.json
"""
import concurrent.futures as cf
import html
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import dailymed_scraper as D  # noqa: E402

BOILER = re.compile(r"broad[\s-]*spectrum\s+SPF\s+(?:value\s+)?(?:of\s+)?15\s+(?:or\s+)?(?:higher|more|greater)", re.I)
BS = re.compile(r"broad[\s-]*spectrum", re.I)
ALERT = re.compile(r"skin\s+cancer\s*/\s*skin\s+aging\s+alert", re.I)


def text_of(xml):
    t = re.sub(r"<[^>]+>", " ", xml or "")
    return re.sub(r"\s+", " ", html.unescape(t))


def claims(sid):
    for i in range(3):
        try:
            xml = D.http_xml(f"{D.BASE}/spls/{sid}.xml")
            if xml:
                t = text_of(xml)
                rest = BOILER.sub(" ", t)
                return {"setid": sid, "broad_spectrum": bool(BS.search(rest)), "aging_alert": bool(ALERT.search(t)),
                        "chars": len(t)}
        except Exception as e:  # noqa: BLE001
            print("retry", sid, e, flush=True)
        time.sleep(5 * (i + 1))
    return None


def main():
    want = []
    for line in open(os.path.join(ROOT, "data/master/us_master.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("in_scope") and r.get("status") == "active":
            want.append(r["setid"])
    os.makedirs("label_claims", exist_ok=True)
    out, failed = [], []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for n, (sid, r) in enumerate(zip(want, ex.map(claims, want)), 1):
            (out.append(r) if r else failed.append(sid))
            if n % 500 == 0:
                print(n, "done", len(failed), "failed", flush=True)
    with open("label_claims/claims.jsonl", "w") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    json.dump(failed, open("label_claims/failed.json", "w"))
    print(f"read {len(out)} of {len(want)}")


if __name__ == "__main__":
    main()
