"""
reclassify.py — apply classifier v2 to an existing canonical file, no network.

  python3 scripts/reclassify.py data/canonical/us_sunscreens.jsonl \
      --out data/canonical/us_sunscreens.jsonl --report data/views/reclassify_report.json

Writes the v2 fields over the v1 ones (same field names where they existed,
so downstream readers keep working) and a before/after report. Safe to run
repeatedly: output depends only on input.
"""
import argparse, collections, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classify import classify, CLASSIFIER_VERSION  # noqa: E402

V1_FIELDS = ["category", "baby_labeled", "is_hundred_percent_mineral",
             "has_hidden_chemical_filter", "contains_chemical_filter", "spf", "mineral_type"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.src, encoding="utf-8")]
    trans = {f: collections.Counter() for f in V1_FIELDS}
    out = []
    for r in rows:
        before = {f: r.get(f) for f in V1_FIELDS}
        r.update(classify(r))
        for f in V1_FIELDS:
            trans[f][f"{before[f]} -> {r.get(f)}"] += 1
        out.append(r)

    C = collections.Counter
    report = {
        "classifier_version": CLASSIFIER_VERSION,
        "rows": len(out),
        "product_type": dict(C(r["product_type"] for r in out)),
        "is_sunscreen": sum(r["is_sunscreen"] is True for r in out),
        "unresolved_zinc": sum(r["is_sunscreen"] is None for r in out),
        "sunscreen_basis": dict(C(r["sunscreen_basis"] for r in out)),
        "sunscreen_product_type": sum(r["product_type"] == "sunscreen" for r in out),
        "sunscreen_tinted": sum(r["product_type"] == "sunscreen" and r["is_tinted"] for r in out),
        "baby_signal": dict(C(r["baby_signal"] for r in out)),
        "baby_named_sunscreens": sum(r["baby_labeled"] and r["product_type"] == "sunscreen" for r in out),
        "hundred_percent_mineral": sum(r["is_hundred_percent_mineral"] for r in out),
        "mineral_only_actives_with_absorber": sum(r["has_hidden_chemical_filter"] for r in out),
        "transitions_v1_to_v2": {f: dict(t.most_common()) for f, t in trans.items()},
    }
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, a.out)
    os.makedirs(os.path.dirname(a.report) or ".", exist_ok=True)
    with open(a.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "transitions_v1_to_v2"}, indent=2))


if __name__ == "__main__":
    main()
