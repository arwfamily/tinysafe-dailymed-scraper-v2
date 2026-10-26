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


def test_tidy_inactives():
    got, ch = M.tidy_inactives(["Water", "C12-15", "Alkyl Benzoate", "Panthenol (Vit", "B5)", ",", "Fragrance",
                                "ALPHA.-BISABOLOL", "(+/-)-", "S014", "(", ") CI 77891 (Titanium dioxide)",
                                "potassium cetyl phosphate", "c12", "15 alkyl benzoate", "C1 77492"])
    assert ch
    assert got == ["Water", "C12-15 Alkyl Benzoate", "Panthenol (Vit B5)", "Fragrance", "ALPHA.-BISABOLOL",
                   "CI 77891 (Titanium dioxide)", "potassium cetyl phosphate", "C12-15 alkyl benzoate", "CI 77492"], got
    assert M.tidy_inactives(["Water", "Glycerin"]) == (["Water", "Glycerin"], False)
    got, _ = M.tidy_inactives(["Iron oxides (CI 77491, CI 77492, CI 77499, OX100FP000371", "Silica"])
    assert got == ["Iron oxides (CI 77491, CI 77492, CI 77499)", "Silica"], got
    got, _ = M.tidy_inactives(["Rosmarinus Officinalis Leaf Oil (Natural Rosemary, Theobroma Cacao Seed Butter, Tocopherol"])
    assert got == ["Rosmarinus Officinalis Leaf Oil (Natural Rosemary)", "Theobroma Cacao Seed Butter", "Tocopherol"], got


def test_v312_rules():
    """2026-10-24 (v3.12): rules added during the second- and third-read pass."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
    from inactive_union import same, same_display
    import sunnytime_rules as R
    # a homologue is not a spelling variant
    assert not same("METHYLPARABEN", "Ethylparaben") and not same_display("Ceteareth-10", "Ceteareth-20")
    assert same("methylparaen", "Methylparaben") and same_display("TITANIUM DIOXIDE", "Titanium Dioxide (CI 77891)")
    # a filer's placeholder is not an ingredient
    got, ch = M.polish_names(["Water", "Please kindly refer to artwork", "Refer to list provided to customer", "Glycerin"])
    assert got == ["Water", "Glycerin"] and ch, got
    # an unsure second read does not make tier A
    assert M.confirm_sure({"decision": "confirmed", "spf": 50, "broad_spectrum": True, "actives": [["Zinc Oxide", 20.0]], "notes": ""})
    assert not M.confirm_sure({"spf": "unclear"})
    assert not M.confirm_sure({"actives": [["Zinc Oxide", "unclear"]]})
    assert not M.confirm_sure({"notes": "Low-resolution artwork; list read roughly"})
    assert not M.confirm_sure({"notes": "the carton prints no inactive list"})
    # ragweed is Asteraceae; expressed lemon/lime/grapefruit/bitter orange oils are phototoxic, lemongrass is not
    assert R.RX["asteraceae"].search("AMBROSIA PERUVIANA LEAF EXTRACT")
    c = R.RX["citrus_photosensitizer"]
    assert c.search("CITRUS LIMON (LEMON) PEEL OIL") and c.search("CITRUS PARADISI (GRAPEFRUIT) PEEL OIL")
    assert not c.search("CYMBOPOGON (LEMONGRASS) OIL") and not c.search("CITRUS AURANTIUM DULCIS (ORANGE) PEEL OIL")


def test_age_limit():
    assert M.age_limit("Do not use on children under 12 years of age.") == "Do not use on children under 12 years of age"
    assert M.age_limit("For adult use only.") == "For adult use only"
    assert M.age_limit("Adults 18 years and older: apply liberally") == "Adults 18 years and older"
    assert M.age_limit("Children under 6 months: Ask a doctor") is None
    assert M.age_limit("Do not use on infants under 6 months.") is None
    assert M.age_limit("Do not use on infants less than six months of age") is None
    assert M.age_limit("Not intended for children under the age of 12.") == "Not intended for children under the age of 12"
    assert M.age_limit("Do not use on children under 12 months") == "Do not use on children under 12 months"
    assert M.age_limit("Keep out of reach of children. Age 50+ skin") is None
    # 2026-10-25 final audit: an "ask a doctor" age other than the standard 6 months
    assert M.age_limit("Children under 3 years of age: Ask a doctor.") == "Children under 3 years of age: Ask a doctor"
    assert M.age_limit("children under the age of 6: Ask a doctor") is None
    assert M.age_limit("children under 6 months of age: ask a doctor") is None


def test_lost_open_bracket_split():
    got, ch = M.polish_names(["Water", "IRON OXIDES, TITANIUM DIOXIDE, CHROMIUM OXIDE GREENS, FD&C YELLOW No. 5, "
                                       "D&C RED No. 36, FERRIC AMMONIUM FERROCYANIDE) (may contain)"])
    assert ch and len(got) == 7 and all(x.endswith("(may contain)") for x in got[1:]), got


def test_unclosed_bracket_split():
    got, ch = M.polish_names(["Citrullus Lanatus (Watermelon Extract, Daucus Carota Sativa (Carrot) Extract, Dimethicone, "
                              "Dodecane, Glycerin, Glyceryl Laurate, Glyceryl Stearate, Methylparaben"])
    assert ch and got[0] == "Citrullus Lanatus (Watermelon Extract)" and "Methylparaben" in got and len(got) == 8, got


def test_recall_parent_company_and_spec():
    # a parent company's recall of a brand it owns (S.C. Johnson recalling Babyganics, Dist. by KAS Direct)
    r1 = {"recall_number": "R1", "recalling_firm": "Johnson, S C and Son, Inc", "brand": "",
          "product_description": "Kids by babyganics SPF 50 totally tropical (titanium dioxide 3.5%, zinc oxide 7.25%) "
                                 "packaged in 6 OZ spray bottles; Dist. by KAS Direct LLC, Racine, WI"}
    # a recall filed under the old company name of the same product (J&J -> Kenvue)
    r2 = {"recall_number": "R2", "recalling_firm": "Johnson & Johnson Consumer, Inc.", "brand": "",
          "product_description": "Neutrogena Ultra Sheer body mist sunscreen BROAD SPECTRUM SPF 30, Avobenzone (3%), "
                                 "Homosalate (8%), Octisalate (5%), Octocrylene (8%), Net Wt. 5.0 OZ aerosol can"}
    idx = M.RecallIndex([r1, r2])
    bg = {"setid": "x1", "labeler": "KAS Direct LLC dba BabyGanics", "spf": 50, "dosage_form": "SPRAY"}
    got = idx.match(bg, "Kids SPF50 Plus Mineral Sunscreen Continuous Totally Tropical Spray",
                    acts=[{"name": "ZINC OXIDE", "percent": 7.25}, {"name": "TITANIUM DIOXIDE", "percent": 3.5}])
    assert [x["recall_number"] for x in got] == ["R1"], got
    acts = [{"name": "AVOBENZONE", "percent": 3}, {"name": "HOMOSALATE", "percent": 8},
            {"name": "OCTISALATE", "percent": 5}, {"name": "OCTOCRYLENE", "percent": 8}]
    ng = {"setid": "x2", "labeler": "Kenvue Brands LLC", "spf": 30, "dosage_form": "SPRAY"}
    got = idx.match(ng, "Neutrogena Ultra Sheer Body Mist Sunscreen Broad Spectrum SPF 30 Spray", acts=acts)
    assert [(x["recall_number"], x["status"]) for x in got] == [("R2", "matched")], got
    # another SPF, other strengths, or a lotion of the same line: not the recalled product
    assert not idx.match(dict(ng, spf=45), "Neutrogena Ultra Sheer Body Mist Sunscreen SPF 45 Spray", acts=acts)
    assert not idx.match(dict(ng, dosage_form="LOTION"), "Neutrogena Ultra Sheer Sunscreen SPF 30 Lotion", acts=acts)
    assert not idx.match(ng, "Neutrogena Ultra Sheer Body Mist Sunscreen SPF 30 Spray",
                         acts=acts[:3] + [{"name": "OCTOCRYLENE", "percent": 10}])



def test_essential_oils_named_on_the_label():
    import sunnytime_rules as R
    assert R.is_essential_oil("Cedarwood Essential Oils")
    assert R.is_essential_oil("fragrance (essential oils)")
    assert R.is_essential_oil("Vanilla plantifolia (Vanilla essential oil)")
    assert not R.is_essential_oil("Cocos nucifera (Coconut essential oil)")
    assert not R.is_essential_oil("Helianthus Annuus Seed Oil")
    assert not R.is_essential_oil("Lavandula Angustifolia Flower Extract")

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
