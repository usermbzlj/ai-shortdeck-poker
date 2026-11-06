import unittest

import core
import equity


def cards(*texts):
    return [core.parse_card(c) for c in texts]


class EquityTests(unittest.TestCase):
    def test_river_winner_and_tie(self):
        self.assertEqual((1.0, 0.0, 0.0), equity.calculate_equity(
            ("Ah", "Kh"), ("As", "Ad"), ("Qh", "Jh", "Th", "6s", "7d")))
        self.assertEqual((0.0, 0.0, 1.0), equity.calculate_equity(
            ("As", "Ad"), ("Ks", "Kd"), ("6h", "7h", "8h", "9h", "Th")))

    def test_exact_flop_and_turn_locked_royal(self):
        for board in (("Qh", "Jh", "Th"), ("Qh", "Jh", "Th", "6s")):
            self.assertEqual((1.0, 0.0, 0.0), equity.calculate_equity(("Ah", "Kh"), ("As", "Ad"), board))

    def test_preflop_is_repeatable_and_normalized(self):
        args = (("As", "Ah"), ("Ks", "Kh"), ())
        first = equity.calculate_equity(*args)
        self.assertAlmostEqual(1, sum(first))
        self.assertGreater(first[0], .55)
        self.assertLess(first[0], .9)
        equity.calculate_equity.cache_clear()
        self.assertEqual(first, equity.calculate_equity(*args))

    def test_empty_invalid_and_duplicate_cards(self):
        for args in (((), (), ()), (("As", "Ah"), ("As", "Kh"), ()),
                     (("As", "Ah"), ("Ks", "Kh"), ("6h",)),
                     (("2s", "Ah"), ("Ks", "Kh"), ())):
            with self.assertRaises((ValueError, core.UserFacingError)):
                equity.calculate_equity(*args)
        with self.assertRaises(ValueError):
            equity.calculate_equity(("As", "Ah"), ("Ks", "Kh"), (), 0)

    def test_key_canonicalizes_card_order(self):
        self.assertEqual(equity.card_key(("As", "Ah"), ("Ks", "Kh"), ("6h", "7s", "8d")),
                         equity.card_key(("Ah", "As"), ("Kh", "Ks"), ("8d", "6h", "7s")))


class BestFiveTests(unittest.TestCase):
    def test_selects_flush_over_full_house_in_short_deck(self):
        hand = cards("Ah", "Kh", "Qh", "Jh", "9h", "As", "Ad")
        result = core.best_five_cards(hand)
        self.assertEqual(set(cards("Ah", "Kh", "Qh", "Jh", "9h")), set(result))
        self.assertEqual("同花", core.describe_hand_rank(core.evaluate_5(result)))

    def test_short_deck_wheel(self):
        result = core.best_five_cards(cards("As", "6h", "7d", "8c", "9s", "Kd", "Qd"))
        self.assertEqual({14, 6, 7, 8, 9}, {r for r, _ in result})
        self.assertEqual("顺子", core.describe_hand_rank(core.evaluate_5(result)))

    def test_empty_and_duplicates(self):
        self.assertEqual([], core.best_five_cards([]))
        self.assertEqual([], core.best_five_cards(cards("As", "Ah")))
        with self.assertRaises(ValueError):
            core.best_five_cards(cards("As", "As", "Kh", "Qh", "Jh"))
