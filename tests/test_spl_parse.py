#!/usr/bin/env python3
"""
tests/test_spl_parse.py — scripts/spl_parse.py on real DailyMed SPL files
(tests/fixtures/spl). Each case is a label whose structured data and printed
Drug Facts disagree, verified by hand on 2026-10-08.
"""
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
from spl_parse import label_fields, parse_spl, split_ingredient_list, match_inactives  # noqa: E402


def fx(prefix):
    return open(glob.glob(os.path.join(HERE, "fixtures", "spl", prefix + "*.xml"))[0], encoding="utf-8").read()


def types(lf):
    return {i["type"] for i in lf["label_checks"]}


class LabelVsStructured(unittest.TestCase):
    def test_coppertone_kids_wrong_active_in_structured_table(self):
        lf = label_fields(fx("08147940"))
        self.assertIn("printed_active_missing_from_structured", types(lf))
        self.assertEqual([(a["name"], a["percent_ww"]) for a in lf["label_actives_proposal"]], [("ZINC OXIDE", 24.08)])

    def test_wegmans_kids_homosalate_filed_as_inactive(self):
        lf = label_fields(fx("5205fcfb"))
        names = {a["name"]: a["percent_ww"] for a in lf["label_actives_proposal"]}
        self.assertEqual(names.get("HOMOSALATE"), 15.0)
        self.assertEqual(len(names), 4)

    def test_peter_island_kids_octocrylene_vs_octisalate(self):
        lf = label_fields(fx("2db243d3"))
        names = {a["name"] for a in lf["label_actives_proposal"]}
        self.assertEqual(names, {"AVOBENZONE", "OCTOCRYLENE", "OXYBENZONE"})

    def test_rounding_in_grams_is_not_a_mismatch(self):
        lf = label_fields(fx("a8ffc32b"))  # 0.09 g / 4.25 g printed as 2.0%
        self.assertNotIn("percent_mismatch", types(lf))
        self.assertNotIn("label_actives_proposal", lf)

    def test_no_correction_without_printed_percentages(self):
        lf = label_fields(fx("ca9df950"))  # Kroger Kids stick prints names only
        self.assertNotIn("label_actives_proposal", lf)

    def test_fragrance_printed_but_not_filed(self):
        self.assertIn("fragrance_printed_not_structured", types(label_fields(fx("f11650bb"))))


class PrintedFullIngredientList(unittest.TestCase):
    def test_printed_list_kept_in_label_order(self):
        lf = label_fields(fx("08147940"))
        self.assertEqual(lf["printed_inactives"][:3], ["water", "C12-15 alkyl benzoate", "isopropyl palmitate"])
        self.assertIn("1,2-hexanediol", lf["printed_inactives"])

    def test_second_language_copy_is_not_a_second_list(self):
        self.assertIsNotNone(label_fields(fx("3aa6550e"))["printed_inactives"])

    def test_split_keeps_brackets_and_numbers(self):
        self.assertEqual(split_ingredient_list("Inactive ingredients: water, 1,2-hexanediol, extract (calendula, chamomile); BHT"),
                         ["water", "1,2-hexanediol", "extract (calendula, chamomile)", "BHT"])

    def test_headings_trailers_and_junk_are_not_ingredients(self):
        self.assertEqual(split_ingredient_list("Inactive Ingrdients Ethylhexyl Palmitate, Water, etc. MADE IN U.S.A. DISTRIBUTED BY: X"),
                         ["Ethylhexyl Palmitate", "Water"])
        self.assertEqual(split_ingredient_list("Non-medicinal Ingredients/ Ingrédients non médicinaux : Aqua, Glycerin, 01-01-2018"),
                         ["Aqua", "Glycerin"])

    def test_inci_to_spl_names(self):
        pairs, un_p, _ = match_inactives(["triethanolamine", "disodium EDTA", "cyclopentasiloxane", "Aqua"],
                                         ["TROLAMINE", "EDETATE DISODIUM", "CYCLOMETHICONE 5", "WATER"])
        self.assertEqual(un_p, [])


class Listing(unittest.TestCase):
    def test_metadata(self):
        lf = label_fields(fx("08147940"))
        self.assertEqual((lf["labeler"], lf["dosage_form"], lf["monograph_id"], lf["spl_version"], lf["effective_date"]),
                         ("Beiersdorf Inc", "LOTION", "M020", "3", "20251231"))
        self.assertEqual(lf["label_flags"]["water_resistant_minutes"], 80)
        self.assertTrue(lf["label_flags"]["under_6_months_ask_doctor"])

    def test_multi_product_listings_are_flagged_not_compared(self):
        for pre, n in (("247aae3d", 2), ("c5d52f13", 9)):
            lf = label_fields(fx(pre))
            self.assertEqual(lf["product_count"], n)
            self.assertIn("multi_product", types(lf))
            self.assertNotIn("label_actives_proposal", lf)

    def test_boilerplate_is_not_a_broad_spectrum_claim(self):
        self.assertFalse(label_fields(fx("369f449f"))["label_flags"]["broad_spectrum_claim"])

    def test_every_fixture_parses(self):
        for f in glob.glob(os.path.join(HERE, "fixtures", "spl", "*.xml")):
            parse_spl(open(f, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
