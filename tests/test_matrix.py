#!/usr/bin/env python3
"""
tests/test_matrix.py — jurisdiction-matrix regression tests (2026-10-08 audit).

Each case is real wording from the TGA Permissible Ingredients Determination
or EU Annex VI that an earlier parser got wrong.

Run:  python tests/test_matrix.py   (stdlib only)
"""
import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("bak", os.path.join(ROOT, "scripts", "build_answer_keys.py"))
bak = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bak)


def au(text):
    return bak._au_cap_from_requirements({"requirements": text})


class AustralianCaps(unittest.TestCase):
    def test_both_legal_phrasings(self):
        self.assertEqual(au("The concentration in the medicine must not be more than 10%."), 10.0)   # bemotrizinol
        self.assertEqual(au("The concentration in sunscreens must be no more than 25%."), 25.0)      # titanium dioxide
        self.assertEqual(au("The concentration in a medicine must be no more than 10%."), 10.0)      # drometrizole trisiloxane

    def test_in_preparation(self):  # avobenzone
        self.assertEqual(au("Only for use as an active ingredient in sunscreens. The concentration in preparation must not be more than 5%."), 5.0)

    def test_blend_cap_is_not_the_ingredient_cap(self):
        self.assertIsNone(au("If used in a flavour the total flavour concentration in a medicine must be no more than 5%."))

    def test_constituent_cap_is_not_the_ingredient_cap(self):
        self.assertIsNone(au("Thujone is a mandatory component of Artemisia annua. The concentration of thujone in the medicine must be no more than 4%."))

    def test_conditional_cap_is_left_blank(self):
        self.assertIsNone(au("When included in a medicine for use on the lips the concentration must be no more than 0.1%."))

    def test_zinc_oxide_has_no_cap(self):
        self.assertIsNone(au("When used internally, zinc is a mandatory component of zinc oxide. When for internal use and the maximum recommended daily dose is more than 25mg"))


class NamesAndConditions(unittest.TestCase):
    def test_one_row_two_names(self):
        self.assertEqual(bak._name_parts("Benzophenone-4 / Benzophenone-5"), ["Benzophenone-4", "Benzophenone-5"])

    def test_eu_conditional_limits(self):
        got = bak._conditional_limits("a) face/hand/lip (no sprays) 6%; b) body incl. sprays 2.2%; c) other 0.5%", 6.0)
        self.assertEqual([c["max_percent"] for c in got], [6.0, 2.2, 0.5])
        self.assertEqual(got[1]["applies_to"], "body incl. sprays")

    def test_condition_without_number_keeps_the_row_max(self):
        got = bak._conditional_limits("Face products except propellant sprays", 7.34)
        self.assertEqual(got, [{"applies_to": "Face products except propellant sprays", "max_percent": 7.34}])


class BuiltMatrix(unittest.TestCase):
    """The committed matrix itself, for the 20 filters on the evidence pages."""

    @classmethod
    def setUpClass(cls):
        import json
        with open(os.path.join(ROOT, "data", "views", "jurisdiction_matrix.json"), encoding="utf-8") as f:
            cls.m = json.load(f)["matrix"]

    def lim(self, name, juris):
        return self.m[name]["limits"].get(juris, {})

    def test_split_rows_are_merged(self):
        self.assertEqual(self.lim("SULISOBENZONE", "EU").get("max_percent"), 5.0)
        self.assertEqual(self.lim("ECAMSULE", "AU").get("max_percent"), 10.0)
        self.assertEqual(self.lim("ECAMSULE", "EU").get("max_percent"), 10.0)
        self.assertNotIn("TEREPHTHALYLIDENE DICAMPHOR SULFONIC ACID", self.m)

    def test_au_caps_read_from_prose(self):
        self.assertEqual(self.lim("TITANIUM DIOXIDE", "AU").get("max_percent"), 25.0)
        self.assertEqual(self.lim("DROMETRIZOLE TRISILOXANE", "AU").get("max_percent"), 10.0)
        self.assertEqual(self.lim("AVOBENZONE", "AU").get("max_percent"), 5.0)

    def test_statuses(self):
        self.assertEqual(self.lim("ECAMSULE", "US").get("status"), "approved_product_only")
        self.assertIn(self.lim("AMINOBENZOIC ACID", "US").get("status"),
                      ("removal_finalized_not_yet_effective", "removed"))

    def test_every_filter_cell_has_a_source_url(self):
        for name in ["ZINC OXIDE", "TITANIUM DIOXIDE", "BEMOTRIZINOL", "AVOBENZONE", "OXYBENZONE",
                     "HOMOSALATE", "OCTOCRYLENE", "SULISOBENZONE", "ECAMSULE", "DROMETRIZOLE TRISILOXANE"]:
            for juris, cell in self.m[name]["limits"].items():
                if juris == "KR":
                    continue  # partial, unverified secondary source; not published
                self.assertTrue(cell.get("source_url"), f"{name} {juris}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
