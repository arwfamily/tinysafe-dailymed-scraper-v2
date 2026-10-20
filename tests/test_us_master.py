#!/usr/bin/env python3
"""Regression tests for the v4 master rules (scope, filter type, baby/kids, ledger versions, recalls)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import ledger as L  # noqa: E402
import scope_rules as S  # noqa: E402
import us_master as M  # noqa: E402


def acts(*pairs):
    return [{"name": n, "percent": p} for n, p in pairs]


def test_filter_type():
    c = {"uv_filters_organic": []}
    assert M.filter_split(c, acts(("ZINC OXIDE", 20.0)))[0] == "mineral_only"
    assert M.filter_split(c, acts(("AVOBENZONE", 3.0), ("HOMOSALATE", 10.0)))[0] == "chemical_only"
    assert M.filter_split(c, acts(("ZINC OXIDE", 12.0), ("OCTISALATE", 5.0)))[0] == "hybrid_mineral_primary"
    assert M.filter_split(c, acts(("TITANIUM DIOXIDE", 2.0), ("OCTINOXATE", 7.5)))[0] == "hybrid_chemical_primary"
    assert M.filter_split(c, acts(("ZINC OXIDE", 5.0), ("OCTISALATE", 5.0)))[0] == "hybrid_equal"
    assert M.filter_split(c, acts(("ZINC OXIDE", None), ("OCTISALATE", 5.0)))[0] == "hybrid_pct_unknown"
    # INCI names count as chemical filters; a skin protectant does not
    assert M.filter_split(c, acts(("ZINC OXIDE", 10.0), ("ETHYLHEXYL SALICYLATE", 5.0)))[0] == "hybrid_mineral_primary"
    assert M.filter_split(c, acts(("ZINC OXIDE", 10.0), ("DIMETHICONE", 1.0)))[0] == "mineral_only"


def test_baby_kids():
    yes = ["BABY SUNSCREEN SPF 50", "Babyganics Mineral", "KIDS SPORT SPF 50", "Children's Sunscreen",
           "Thinkbaby", "Little Ones SPF 30", "Bebe Soleil"]
    yes += ["Thinkkids SPF 50", "Kidstick", "Safe4Kidz"]
    for s in yes:
        assert M.BABY_KIDS.search(s), s
    for s in ["Sport SPF 50", "Kidney bean oil sunscreen"]:
        assert not M.BABY_KIDS.search(s), s
    assert M.baby_kids({"product_name": "Banana Boat Lotion", "label_flags": {"front_panel_baby_words": ["KIDS"]}}) == (True, "front_panel")
    assert M.baby_kids({"product_name": "Banana Boat Lotion", "label_flags": {"front_panel_baby_words": ["PEDIATRIC"]}}) == (False, None)
    assert M.baby_kids({"product_name": "HYDRATING GLOW MIST SPF 50 SPRAY",
                        "title": "HYDRATING GLOW MIST SPF 50 SPRAY [WILD CHILD LABORATORIES PTY LTD]"}) == (False, None)


def test_spray():
    assert M.SPRAY.search("SPRAY") and M.SPRAY.search("Sunscreen Spray150Ml") and M.SPRAY.search("AEROSOL")
    assert not M.SPRAY.search("Mistine UV Defense Cream")


def test_ledger_version_rule():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "l.jsonl")
        L.append([{"setid": "a", "spl_version": "3", "status": "text_confirms_current"},
                  {"setid": "a", "spl_version": "3", "status": "confirmed", "inactives": ["WATER"]},
                  {"setid": "b", "spl_version": "1", "status": "confirmed", "inactives": ["X"]}], p)
        led = L.load(p)
        assert L.current(led, "a", "3")["status"] == "confirmed"        # last row wins
        assert L.current(led, "b", "2") is None                          # label changed: old check not applied
        assert L.stale(led, "b", "2")


def test_recall_match():
    rec = [{"recall_number": "D-1", "spl_set_id": ["s1"], "product_ndc": [], "product_description": "x",
            "recalling_firm": "Acme Inc", "reason_for_recall": "Benzene contamination"},
           {"recall_number": "D-2", "spl_set_id": [], "product_ndc": [],
            "product_description": "Acme Glow Shield Velvet Mineral Sunscreen Spray", "recalling_firm": "Acme Inc",
            "reason_for_recall": "cGMP"}]
    idx = M.RecallIndex(rec)
    m = idx.match({"setid": "s1", "labeler": "Acme Inc"}, "Acme Glow Shield Velvet Mineral Sunscreen Lotion")
    assert {x["recall_number"]: x["status"] for x in m} == {"D-1": "matched", "D-2": "needs_review"}
    assert m[0]["hazards"] == ["benzene", "contamination"]
    m2 = idx.match({"setid": "s9", "labeler": "Other Co"}, "Acme Glow Shield Velvet Mineral Sunscreen Lotion")
    assert m2 == []


def test_scope_rules():
    out = {
        "KISS MY FACE SPF 30 LIP BALM (AVOBENZONE) STICK [KISS MY FACE]": "spf_lip_balm",
        "MINERAL LIP SUNSCREEN STICK (ZINC OXIDE) STICK [X]": "spf_lip_balm",
        "PIPETTE DIAPER RASH (ZINC OXIDE) CREAM [PIPETTE LLC]": "diaper_cream",
        "HYDRO SPLASH BB SPF20 PA (TITANIUM DIOXIDE) CREAM [THEFACESHOP CO., LTD.]": "spf_makeup",
        "DAYDREAM CUSHION GENTLE LIGHT (AVOBENZONE) CREAM [EM COSMETICS LLC]": "spf_makeup",
        "NATURAL FINISH PRESSED FOUNDATION SPF 20 SUNSCREEN (TITANIUM DIOXIDE) POWDER [X]": "spf_makeup",
        "NARS RADIANCE PRIMER BROAD SPECTRUM SPF 35 SUNSCREEN (OCTISALATE) LOTION [NARS]": "spf_makeup",
        "3CE TRIPLE SHADOW SPF 15 (TITANIUM DIOXIDE) POWDER [X]": "spf_makeup",
        "SPF 15 FAIR (TITANIUM DIOXIDE) POWDER [MELALEUCA]": "spf_makeup",
    }
    keep = ["SUN BUM ROAD TRIPPER MINERAL SUNSCREEN FACE STICK (ZINC OXIDE) STICK [SUN BUM]",
            "JUST A TINT 3-IN-1 TINTED SKIN CONDITIONER (OCTINOXATE) CREAM [THE LIP BAR]",
            "GOONGBE MOISTURE SUN CUSHION MILD SPF 50 (ZINC OXIDE) LOTION [X]",
            "HELLO SUNDAY THE INVISIBLE ONE SUNSCREEN PLUS PRIMER SPF 50 (AVOBENZONE) EMULSION [X]",
            "ETHICAL ZINC DAILY WEAR TINTED FACIAL SUNSCREEN SPF-50 (ZINC OXIDE) LOTION [X]",
            "SUNSCREEN SETTING SPRITZ, SPF 45 (AVOBENZONE) LIQUID [X]",
            "TARTE AMAZONIAN CLAY BB TINTED MOISTURIZER BROAD SPECTRUM SPF 20 SUNSCREEN (A) CREAM [TARTE]",
            "MINERAL SPF 30 BRUSH-ON SUN DEFENSE (TITANIUM DIOXIDE) POWDER [X]",
            "BRUSH ON BLOCK SPF 30 MINERAL POWDER TOUCH OF TAN ZINC ONLY (ZINC OXIDE) POWDER [X]"]
    for t, why in out.items():
        assert S.scope_reason(t) == why, t
    for t in keep:
        assert S.scope_reason(t) is None, t
    assert S.named_sunscreen("SUNSCREEN SETTING SPRITZ, SPF 45 (AVOBENZONE) LIQUID [X]")


def test_title_actives():
    got = M.title_actives({"title": "YOUNIQUE ROYALTY DAY CREAM SPF 20 (AVOBENZONE, HOMOSALATE AND OCTISALATE) CREAM [Y]"})
    assert [a["name"] for a in got] == ["AVOBENZONE", "HOMOSALATE", "OCTISALATE"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
