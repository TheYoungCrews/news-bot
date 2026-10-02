#!/usr/bin/env python3
"""Unit tests for newsbot.py's duplicate-detection logic. Standard library only.

Run: python3 -m unittest test_newsbot
"""
import unittest
from datetime import datetime

import newsbot


def ts_on(date_str):
    """Epoch seconds for noon ET on the given YYYY-MM-DD, for same-calendar-day tests."""
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=12, tzinfo=newsbot.EASTERN)
    return d.timestamp()


class TestDuplicateDetection(unittest.TestCase):
    def test_925_fed_stablecoin_pair_is_a_duplicate(self):
        # The Block and The Defiant, both posted and thumbs-downed on 9/25. Word
        # overlap alone scores 0.29 (shares only "proposes"/"capital") against the
        # 0.42 threshold, so this only merges via the same-day + entity check.
        block = "Fed proposes reserve limits, capital standards for stablecoin issuers"
        defiant = "Fed Proposes Capital Charges and Bank Approval Rules for Stablecoins"
        t = ts_on("2026-09-25")

        self.assertLess(newsbot.title_overlap(block, defiant), 0.42)
        self.assertGreaterEqual(len(newsbot.shared_capitalized_entities(block, defiant)), 2)
        self.assertTrue(newsbot.is_duplicate(block, t, defiant, t, 0.42))

    def test_single_shared_entity_does_not_merge(self):
        # Shares only "Fed" -- one capitalized entity, below the >=2 bar -- and no
        # meaningful word overlap, so this must NOT be flagged a duplicate even
        # though it posted the same day as the pair above.
        block = "Fed proposes reserve limits, capital standards for stablecoin issuers"
        other = "Fed signals openness to faster bank merger approvals"
        t = ts_on("2026-09-25")

        self.assertEqual(newsbot.title_overlap(block, other), 0.0)
        self.assertEqual(len(newsbot.shared_capitalized_entities(block, other)), 1)
        self.assertFalse(newsbot.is_duplicate(block, t, other, t, 0.42))

    def test_shared_entities_require_same_day(self):
        # Same pair as the real duplicate, but a week apart: must not merge just
        # because of the entity overlap once the calendar-day check fails.
        block = "Fed proposes reserve limits, capital standards for stablecoin issuers"
        defiant = "Fed Proposes Capital Charges and Bank Approval Rules for Stablecoins"
        self.assertFalse(newsbot.is_duplicate(block, ts_on("2026-09-25"), defiant, ts_on("2026-10-02"), 0.42))


if __name__ == "__main__":
    unittest.main()
