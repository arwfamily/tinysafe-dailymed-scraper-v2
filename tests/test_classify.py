#!/usr/bin/env python3
"""
tests/test_classify.py — classifier v2 regression tests.

Every case below is a real title from the DailyMed corpus that a previous
rule set got wrong (audit 2026-10-08). If a rule change brings one back,
this file fails before any count is published.

Run:  python tests/test_classify.py      (stdlib only)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from classify import classify  # noqa: E402

ZNO = {"name": "ZINC OXIDE", "unii": "SOI2LOH54Z"}
TIO2 = {"name": "TITANIUM DIOXIDE", "unii": "15FIX9V2JP"}
AVO = {"name": "AVOBENZONE", "unii": "G63QQF2NOX"}
OCTINOXATE = {"name": "OCTINOXATE", "unii": "4Y5P7MUD51"}


def rec(title, actives=(ZNO,), inactives=("WATER", "GLYCERIN")):
    return {"title": title, "active_ingredients": [dict(a) for a in actives],
            "inactive_ingredients": [{"name": n, "unii": None} for n in inactives]}


class SunscreenOrNot(unittest.TestCase):
    def test_tinted_is_a_sunscreen_not_makeup(self):
        r = classify(rec("TINTED MINERAL SUNSCREEN BROAD SPECTRUM SPF 40 (ZINC OXIDE) LOTION [EARTH MAMA ANGEL BABY, LLC]"))
        self.assertEqual(r["product_type"], "sunscreen")
        self.assertTrue(r["is_tinted"])

    def test_foundation_with_spf_is_colour_cosmetic(self):
        r = classify(rec("FLAWLESS FINISH BARE PERFECTION MAKEUP SPF 8 MOCHA (OCTINOXATE) LOTION [ELIZABETH ARDEN, INC]", actives=(OCTINOXATE,)))
        self.assertEqual(r["product_type"], "color_cosmetic_spf")
        self.assertTrue(r["is_sunscreen"])

    def test_titanium_alone_means_sunscreen_even_without_spf_in_title(self):
        r = classify(rec("ATOBOS CENTELLA BABY SUN (TITANIUM DIOXIDE, ZINC OXIDE) CREAM [1004LABORATORY]", actives=(TIO2, ZNO)))
        self.assertEqual(r["product_type"], "sunscreen")

    def test_korean_suncream_one_word(self):
        r = classify(rec("ISNTREE HYALURONIC ACID NATURAL SUNCREAM (ZINC OXIDE) CREAM [ISNTREE INC.]"))
        self.assertEqual(r["product_type"], "sunscreen")

    def test_diaper_cream_is_skin_protectant(self):
        r = classify(rec("DESITIN MAXIMUM STRENGTH DIAPER RASH (ZINC OXIDE) PASTE [KENVUE BRANDS LLC]"))
        self.assertEqual(r["product_type"], "skin_protectant")
        self.assertFalse(r["is_sunscreen"])

    def test_sunsetter_is_not_setting_powder(self):
        r = classify(rec("SUNSETTER MINERAL SUNSCREEN SPF 30 (ZINC OXIDE) LOTION [X]"))
        self.assertEqual(r["product_type"], "sunscreen")

    def test_hydrasheer_is_not_rash(self):
        r = classify(rec("HYDRASHEER MINERAL SUNSCREEN SPF 50 (ZINC OXIDE) LOTION [X]"))
        self.assertEqual(r["product_type"], "sunscreen")

    def test_hyphenated_spf_is_parsed(self):
        self.assertEqual(classify(rec("DAILY LOTION SPF-30 (ZINC OXIDE) LOTION [X]"))["spf"], 30)

    def test_prenatal_vitamin_with_zinc_oxide_is_excluded(self):
        r = classify(rec("PRENATOL-M (MULTIVITAMIN) TABLET [PURETEK CORPORATION]"))
        self.assertIs(r["is_sunscreen"], False)

    def test_multivitamin_named_sunscreen_is_not_excluded(self):
        r = classify(rec("MULTIVITAMIN BODYBLOCK SPF 20 (AVOBENZONE, OCTINOXATE, OCTISALATE, AND OXYBENZONE) LOTION [GORDON LABORATORIES]", actives=(AVO, OCTINOXATE)))
        self.assertEqual(r["product_type"], "sunscreen")

    def test_zinc_with_no_signal_stays_unresolved(self):
        r = classify(rec("CREAM (ZINC OXIDE) CREAM [OXYGEN DEVELOPMENT LLC]"))
        self.assertIsNone(r["is_sunscreen"])
        self.assertEqual(r["product_type"], "unresolved_zinc")

    def test_monograph_id_is_decisive(self):
        r = rec("CREAM (ZINC OXIDE) CREAM [OXYGEN DEVELOPMENT LLC]")
        r["monograph_id"] = "M020"
        self.assertTrue(classify(r)["is_sunscreen"])
        r["monograph_id"] = "M016"
        self.assertFalse(classify(r)["is_sunscreen"])


class Baby(unittest.TestCase):
    def test_compound_brand_words_count(self):
        for t in ["THINKBABY SPF 50 (ZINC OXIDE) LOTION [THINKOPERATIONS,LLC]",
                  "COPPERTONE WATERBABIES PURE AND SIMPLE MINERAL SPF 50 (ZINC OXIDE 24.08%) LOTION [BEIERSDORF INC]",
                  "KIDSTICK MINERAL BROAD SPECTRUM SPF 40 SUNSCREEN (TITANIUM DIOXIDE AND ZINC OXIDE) STICK [MDSOLARSCIENCES]",
                  "ATTITUDE MINERAL SUNSCREEN LITTLE ONES - FRAGRANCE FREE (ZINC OXIDE) CREAM [BIO SPECTRA]"]:
            self.assertTrue(classify(rec(t))["baby_labeled"], t)

    def test_brand_in_labeler_counts(self):
        r = classify(rec("SPF 50 PLUS SUNSCREEN (TITANIUM DIOXIDE, OCTISALATE, AND ZINC OXIDE) LOTION [KAS DIRECT LLC DBA BABYGANICS]"))
        self.assertEqual(r["baby_signal"], "brand_name")
        self.assertTrue(r["baby_labeled"])

    def test_false_positives_are_blocked(self):
        for t in ["REPLENISHING DAILY SUNSCREEN (ZINC OXIDE) CREAM [BABYFACE LLC]",
                  "NEUROSODE (GLANDULA SUPRARENALIS SUIS, KIDNEY (SUIS)) LIQUID [X]",
                  "POOLSIDE NOT YOUR BABYS OIL. SPF 30 SUNSCREEN BODY OIL. (HOMOSALATE) OIL [X]",
                  "NEW KID ON THE BLOCK (ZINC OXIDE) LOTION [DIMPLES BATH CO. LLC]",
                  "3 CONCEPT EYES BACK TO BABY (TITANIUM DIOXIDE, OCTINOXATE) CREAM [NANDA CO., LTD.]",
                  "HYDRATING GLOW MIST SPF 50 (AVOBENZONE) SPRAY [WILD CHILD LABORATORIES]",
                  "FLORIDA BABE SPORT TINTED MINERAL SUNSCREEN (ZINC OXIDE) CREAM [TICHY ANESTHESIA]"]:
            self.assertFalse(classify(rec(t))["baby_labeled"], t)


class Mineral(unittest.TestCase):
    def test_methoxycrylene_breaks_hundred_percent_mineral(self):
        r = classify(rec("JOHNSONS BABY MINERAL SUNSCREEN SPF 30 (TITANIUM DIOXIDE, ZINC OXIDE) LOTION [X]",
                         actives=(TIO2, ZNO), inactives=("WATER", "ETHYLHEXYL METHOXYCRYLENE")))
        self.assertFalse(r["is_hundred_percent_mineral"])
        self.assertTrue(r["has_hidden_chemical_filter"])

    def test_butyloctyl_salicylate_is_detected(self):
        r = classify(rec("BABY MINERAL SPF 50 (ZINC OXIDE) LOTION [X]", inactives=("WATER", "BUTYLOCTYL SALICYLATE")))
        self.assertEqual(r["uv_absorbers_in_inactives"][0]["canonical"], "butyloctyl salicylate")

    def test_fragrance_salicylates_are_not_uv_absorbers(self):
        r = classify(rec("BABY MINERAL SPF 50 (ZINC OXIDE) LOTION [X]", inactives=("WATER", "BENZYL SALICYLATE", "METHYL SALICYLATE")))
        self.assertTrue(r["is_hundred_percent_mineral"])

    def test_titanium_only_is_mineral(self):
        r = classify(rec("MINERAL SUNSCREEN SPF 30 (TITANIUM DIOXIDE) LOTION [X]", actives=(TIO2,)))
        self.assertTrue(r["is_hundred_percent_mineral"])

    def test_non_uv_active_does_not_break_mineral(self):
        r = classify(rec("DAILY SPF 30 (ZINC OXIDE, NIACINAMIDE) LOTION [X]",
                         actives=(ZNO, {"name": "NIACINAMIDE", "unii": "25X51I8RD4"})))
        self.assertTrue(r["is_hundred_percent_mineral"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
