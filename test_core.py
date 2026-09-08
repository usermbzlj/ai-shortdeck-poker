import unittest
from unittest.mock import patch

import core


def card(text: str) -> core.Card:
    return core.parse_card(text)


class FakeResponse:
    status_code = 200
    text = '{"choices":[{"message":{"content":"ok"}}]}'

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "ok"}}]}


class FakeClient:
    def __init__(self, calls: list[dict]):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url: str, headers: dict, json: dict):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse()


class CoreRulesTest(unittest.TestCase):
    def test_short_deck_flush_beats_full_house(self):
        flush = core.evaluate_5([card(x) for x in ["As", "Ks", "Qs", "Ts", "8s"]])
        full_house = core.evaluate_5([card(x) for x in ["Ah", "Ad", "Ac", "Ks", "Kh"]])
        self.assertGreater(flush, full_house)

    def test_short_deck_wheel_straight(self):
        rank = core.evaluate_5([card(x) for x in ["As", "6h", "7d", "8c", "9s"]])
        self.assertEqual(rank[:2], (4, 9))

    def test_rejects_invalid_new_match_blinds(self):
        hand = core.HandState("AI_A", "AI_B")
        hand.sb_cents = 600
        hand.bb_cents = 500
        with self.assertRaises(core.UserFacingError):
            hand.new_match(1000)

        hand = core.HandState("AI_A", "AI_B")
        with self.assertRaises(core.UserFacingError):
            hand.new_match(499)

    def test_short_small_blind_all_in_posts_and_stops_action(self):
        hand = core.HandState("AI_A", "AI_B")
        hand.stacks = {"AI_A": 200, "AI_B": 1000}
        hand.start_hand()

        self.assertIsNone(hand.next_to_act)
        self.assertEqual(hand.current_bet_cents, 200)
        self.assertEqual(hand.pot_cents, 400)
        self.assertEqual(hand.stacks, {"AI_A": 0, "AI_B": 800})
        self.assertEqual(hand.legal_actions("AI_A")["actions"], [])

    def test_short_big_blind_all_in_leaves_only_call_decision(self):
        hand = core.HandState("AI_A", "AI_B")
        hand.stacks = {"AI_A": 1000, "AI_B": 300}
        hand.start_hand()

        self.assertEqual(hand.next_to_act, "AI_A")
        legal = hand.legal_actions("AI_A")
        self.assertEqual(legal["to_call_cents"], 50)
        self.assertIn("fold", legal["actions"])
        self.assertIn("call", legal["actions"])
        self.assertNotIn("raise", legal["actions"])

        hand.apply_action("AI_A", "call", None)
        self.assertIsNone(hand.next_to_act)
        self.assertEqual(hand.pot_cents, 600)
        self.assertEqual(hand.stacks, {"AI_A": 700, "AI_B": 0})

    def test_short_small_blind_all_in_call_refunds_excess(self):
        hand = core.HandState("AI_A", "AI_B")
        hand.stacks = {"AI_A": 300, "AI_B": 1000}
        hand.start_hand()

        self.assertEqual(hand.next_to_act, "AI_A")
        self.assertEqual(hand.legal_actions("AI_A")["to_call_cents"], 250)

        hand.apply_action("AI_A", "call", None)
        self.assertIsNone(hand.next_to_act)
        self.assertEqual(hand.current_bet_cents, 300)
        self.assertEqual(hand.pot_cents, 600)
        self.assertEqual(hand.contributed_total, {"AI_A": 300, "AI_B": 300})
        self.assertEqual(hand.stacks, {"AI_A": 0, "AI_B": 700})


class ParsingTest(unittest.TestCase):
    def test_optional_float_and_positive_int_helpers(self):
        self.assertIsNone(core.parse_optional_float("none", "0.2"))
        self.assertEqual(core.parse_optional_float("", "0.7"), 0.7)
        self.assertEqual(core.parse_optional_float("bad", "0.3"), 0.3)
        self.assertEqual(core.parse_positive_int("bad", 8000), 8000)
        self.assertEqual(core.parse_positive_int("0", 8000), 8000)
        self.assertEqual(core.parse_positive_int("200000", 8000, max_value=100000), 100000)


class LLMClientTest(unittest.TestCase):
    def test_omits_thinking_when_disabled(self):
        calls: list[dict] = []
        with patch.object(core.httpx, "Client", lambda **_: FakeClient(calls)):
            result = core.LLMClient("https://example.test/v1", "sk-test", "model").chat(
                [{"role": "user", "content": "hi"}],
                temperature=None,
                thinking_enabled=False,
            )

        self.assertEqual(result["content"], "ok")
        self.assertNotIn("thinking", calls[0]["json"])
        self.assertNotIn("temperature", calls[0]["json"])

    def test_sends_thinking_when_enabled(self):
        calls: list[dict] = []
        with patch.object(core.httpx, "Client", lambda **_: FakeClient(calls)):
            core.LLMClient("https://example.test/v1", "sk-test", "model").chat(
                [{"role": "user", "content": "hi"}],
                temperature=0.2,
                thinking_enabled=True,
                thinking_budget=1234,
            )

        payload = calls[0]["json"]
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(payload["thinking"], {"type": "enabled", "budget_tokens": 1234})


class ControllerConfigTest(unittest.TestCase):
    def test_load_env_uses_safe_defaults(self):
        from controller import GameController

        ctrl = GameController()
        ctrl.load_env(
            {
                "TEMPERATURE": "none",
                "A_THINKING_BUDGET": "bad",
                "B_THINKING_BUDGET": "0",
                "COMMENTATOR_THINKING_BUDGET": "200000",
            }
        )

        self.assertIsNone(ctrl.profile["AI_A"].temperature)
        self.assertEqual(ctrl.profile["AI_A"].thinking_budget, 8000)
        self.assertEqual(ctrl.profile["AI_B"].thinking_budget, 8000)
        self.assertEqual(ctrl.commentator.temperature, 0.7)
        self.assertEqual(ctrl.commentator.thinking_budget, 100000)

    def test_load_env_invalid_temperature_falls_back(self):
        from controller import GameController

        ctrl = GameController()
        ctrl.load_env({"TEMPERATURE": "bad", "A_TEMPERATURE": "also-bad"})

        self.assertEqual(ctrl.profile["AI_A"].temperature, 0.2)
        self.assertEqual(ctrl.profile["AI_B"].temperature, 0.2)


if __name__ == "__main__":
    unittest.main()
