#!/usr/bin/env python3
"""tests/test_printed_changes.py — printed-list change detection never hides a change."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from printed_changes import printed_list, possible_spellings  # noqa: E402

LIST = "Inactive ingredients: water, glycerin, dimethicone, fragrance, tocopherol, methylparaben, propylparaben, xanthan gum, citric acid"


class Printed(unittest.TestCase):
    def test_complete_list_is_read(self):
        items = printed_list({"sections": {"Inactive ingredients": LIST}})
        self.assertIn("FRAGRANCE", items)
        self.assertEqual(len(items), 9)

    def test_short_or_missing_list_is_not_compared(self):
        self.assertIsNone(printed_list({"sections": {"Inactive ingredients": "water, glycerin"}}))
        self.assertIsNone(printed_list({"sections": {}, "text": "PRINCIPAL DISPLAY PANEL image"}))

    def test_lookalike_names_are_flagged_not_hidden(self):
        self.assertEqual(possible_spellings(["METHYLPARABEN"], ["ETHYLPARABEN"]), [["METHYLPARABEN", "ETHYLPARABEN"]])


if __name__ == "__main__":
    unittest.main()
