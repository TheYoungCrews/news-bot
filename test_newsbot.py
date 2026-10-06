#!/usr/bin/env python3
"""Unit tests for newsbot.py's duplicate-detection logic. Standard library only.

Run: python3 -m unittest test_newsbot
"""
import os
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


class TestCommentaryFilter(unittest.TestCase):
    # Real titles from state.feedback, 2026-09-21 through 2026-10-04.
    DOWN_VOTED_SHOULD_CATCH = [
        "ESMA Proposes MiCA Rules for DeFi Gateways, Staking and Lending",
        "Fed Proposes Capital Charges and Bank Approval Rules for Stablecoins",
        "BlackRock Sees Stablecoins Powering AI Agent Payments",
        "Coinbase, Robinhood, Circle could be early winners of SEC's tokenized-stock push, analysts say",
        "Binance deal gives Circle a boost in stablecoin race with Tether, analysts say",
        "Trump administration weighs a global stablecoin plan to cement dollar's dominance",
        "CFTC Chairman Selig says markets must prepare for 'mass tokenization'",
        "Fed proposes reserve limits, capital standards for stablecoin issuers under GENIUS Act",
        "BitGo CEO says Clarity's failure left capital markets exposed to risk potentially worse than Lehman",
    ]
    # Real up-voted titles the filter must leave alone.
    UP_VOTED_MUST_NOT_CATCH = [
        "Aave Adds Coinbase Stock Tokens as Collateral on Base",
        "Sentora Seeks Aave V4 Markets With 50% Revenue Share for DAO",
        "Balancer Holders Approve Wind-Down, Reject Official Fork",
        "Galaxy Adds $100 Million of sUSDS to Treasury, Approves It as Loan Collateral",
        "Coinbase adds fixed-rate bitcoin-backed loans through Morpho Midnight",
        "European central banks push to expand stablecoin yield ban to crypto lending and staking",
        "Drift opens exploit recovery claims with initial payouts of just over 1% of user losses",
    ]

    def test_catches_known_down_voted_commentary_and_chatter(self):
        for title in self.DOWN_VOTED_SHOULD_CATCH:
            with self.subTest(title=title):
                self.assertTrue(newsbot.looks_like_commentary_or_chatter(title))

    def test_leaves_known_up_voted_posts_alone(self):
        for title in self.UP_VOTED_MUST_NOT_CATCH:
            with self.subTest(title=title):
                self.assertFalse(newsbot.looks_like_commentary_or_chatter(title))

    def test_claims_as_a_noun_is_not_attribution(self):
        # "exploit recovery claims" is a noun phrase, not the verb "X claims Y" --
        # regression check for the false positive this exact title triggered in testing.
        self.assertFalse(newsbot.looks_like_commentary_or_chatter(
            "Drift opens exploit recovery claims with initial payouts of just over 1% of user losses"))


class TestCollectFeedback(unittest.TestCase):
    def setUp(self):
        self._orig_slack_api = newsbot.slack_api
        self._orig_token = os.environ.get("SLACK_BOT_TOKEN")
        os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"

    def tearDown(self):
        newsbot.slack_api = self._orig_slack_api
        if self._orig_token is None:
            os.environ.pop("SLACK_BOT_TOKEN", None)
        else:
            os.environ["SLACK_BOT_TOKEN"] = self._orig_token

    def test_one_bad_message_does_not_block_later_reactions(self):
        # The middle post's reactions.get raises. Before the break -> continue fix,
        # a bare `break` would have silently lost feedback on the third post too.
        t = newsbot.now()
        posts = [
            {"title": "Post A", "source": "Test", "url": "https://example.com/a",
             "at": t - 300, "ch": "C1", "ts": "1.1"},
            {"title": "Post B", "source": "Test", "url": "https://example.com/b",
             "at": t - 200, "ch": "C1", "ts": "1.2"},
            {"title": "Post C", "source": "Test", "url": "https://example.com/c",
             "at": t - 100, "ch": "C1", "ts": "1.3"},
        ]
        state = {"posted": posts, "feedback": {}}

        def fake_slack_api(method, payload=None, params=None):
            if params["timestamp"] == "1.2":
                raise RuntimeError("Slack reactions.get: internal_error")
            return {"ok": True, "message": {"reactions": [{"name": "+1", "count": 2}]}}

        newsbot.slack_api = fake_slack_api
        newsbot.collect_feedback(state, t)

        self.assertNotIn(posts[1]["url"], state["feedback"])
        self.assertIn(posts[2]["url"], state["feedback"])
        self.assertEqual(state["feedback"][posts[2]["url"]]["up"], 2)


if __name__ == "__main__":
    unittest.main()
