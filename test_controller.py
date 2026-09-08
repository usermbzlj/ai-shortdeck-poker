import unittest

import core
from controller import GameController


class AutoFailureHandlingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = GameController()
        self.controller.start_new_match(10_000, 50, 100)
        self.controller.set_auto_running(True)
        self.errors: list[tuple[str, bool, int, bool]] = []
        self.controller.errorRaised.connect(
            lambda message: self.errors.append(
                (
                    message,
                    self.controller.auto_running,
                    self.controller.active_request_id,
                    self.controller.thinking,
                )
            )
        )

    def fail_request(self, req_id: int, error: str = "quota exceeded") -> None:
        self.controller.active_request_id = req_id
        self.controller.thinking = True
        self.controller._handle_llm_error(req_id, "AI_A", error)

    def invalid_result(self, req_id: int) -> None:
        self.controller.active_request_id = req_id
        self.controller.thinking = True
        self.controller._handle_llm_result(req_id, "AI_A", "not json", "")

    def test_auto_mode_only_shows_dialog_after_circuit_breaker_opens(self) -> None:
        self.fail_request(1)
        self.fail_request(2)

        self.assertTrue(self.controller.auto_running)
        self.assertEqual([], self.errors)

        self.fail_request(3)

        self.assertFalse(self.controller.auto_running)
        self.assertEqual(0, self.controller.active_request_id)
        self.assertFalse(self.controller.thinking)
        self.assertEqual(1, len(self.errors))
        self.assertEqual("quota exceeded", self.errors[0][0])
        self.assertEqual((False, 0, False), self.errors[0][1:])

    def test_invalid_model_output_uses_same_circuit_breaker(self) -> None:
        self.invalid_result(1)
        self.invalid_result(2)
        self.invalid_result(3)

        self.assertFalse(self.controller.auto_running)
        self.assertEqual(3, self.controller._consecutive_failures)
        self.assertEqual(1, len(self.errors))
        self.assertIn("解析出 JSON", self.errors[0][0])

    def test_auto_tick_stops_before_reporting_deal_error(self) -> None:
        self.controller.state.ensure_dealt = lambda street: (_ for _ in ()).throw(
            core.UserFacingError("deal failed")
        )

        self.controller.auto_tick()

        self.assertFalse(self.controller.auto_running)
        self.assertEqual(1, len(self.errors))
        self.assertEqual(("deal failed", False, 0, False), self.errors[0])


if __name__ == "__main__":
    unittest.main()
