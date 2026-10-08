"""Fingerprint v2 regression cases (real DailyMed labels, 2026-10-08)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from snapshot_and_history import formulation_fingerprint

ZNO = "SOI2LOH54Z"
INACT = [{"name": "WATER", "unii": "059QF0KO0R"}, {"name": "DIMETHICONE", "unii": "92RU3N3Y1O"}]

def rec(*acts):
    return {"active_ingredients": [dict(a, unii=a.get("unii", ZNO), name=a.get("name", "ZINC OXIDE")) for a in acts],
            "inactive_ingredients": INACT}

class T(unittest.TestCase):
    def test_same_numerator_different_percent_splits(self):  # THINKKIDS 23.4% vs THINKSPORT 20%
        a = rec({"strength": "234.0", "strength_unit": "MG", "denominator": "1.0", "denominator_unit": "G", "percent_ww": 23.4})
        b = rec({"strength": "234.0", "strength_unit": "MG", "denominator": "1.17", "denominator_unit": "G", "percent_ww": 20.0})
        self.assertNotEqual(formulation_fingerprint(a)[0], formulation_fingerprint(b)[0])

    def test_unit_typo_same_label_percent_merges(self):  # THINKBABY mg vs THINKSPORT KIDS ug, both 20%
        a = rec({"strength": "200.0", "strength_unit": "MG", "denominator": "1.0", "denominator_unit": "G", "percent_ww": 20.0})
        b = rec({"strength": "200.0", "strength_unit": "UG", "denominator": "1.0", "denominator_unit": "G", "percent_ww": 20.0})
        self.assertEqual(formulation_fingerprint(a)[0], formulation_fingerprint(b)[0])

    def test_no_percent_falls_back_to_full_fraction(self):
        a = rec({"strength": "5", "strength_unit": "G", "denominator": "100", "denominator_unit": "G"})
        b = rec({"strength": "5", "strength_unit": "G", "denominator": "50", "denominator_unit": "G"})
        self.assertNotEqual(formulation_fingerprint(a)[0], formulation_fingerprint(b)[0])

    def test_active_order_ignored_inactive_order_kept(self):
        x = {"strength": "1", "strength_unit": "G", "denominator": "100", "denominator_unit": "G", "percent_ww": 1}
        a = {"active_ingredients": [dict(x, unii="A", name="A"), dict(x, unii="B", name="B")], "inactive_ingredients": INACT}
        b = {"active_ingredients": [dict(x, unii="B", name="B"), dict(x, unii="A", name="A")], "inactive_ingredients": INACT}
        c = {"active_ingredients": a["active_ingredients"], "inactive_ingredients": INACT[::-1]}
        self.assertEqual(formulation_fingerprint(a)[0], formulation_fingerprint(b)[0])
        self.assertNotEqual(formulation_fingerprint(a)[0], formulation_fingerprint(c)[0])

if __name__ == "__main__":
    unittest.main()
