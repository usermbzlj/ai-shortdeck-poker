from dataclasses import replace
import time
import unittest
from unittest.mock import patch

from PySide6 import QtCore, QtGui, QtWidgets

import core
from controller import GameController
from table_widget import PokerTableWidget


class PokerTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.controller = GameController()
        self.controller.load_env({"SHOW_EQUITY": "false"})
        self.snapshots = []
        self.controller.viewModelChanged.connect(self.snapshots.append)
        self.controller.start_new_match(10000, 50, 100)
        self.vm = self.snapshots[-1]
        self.table = PokerTableWidget()
        self.table.resize(1000, 720)

    def tearDown(self):
        self.table.deleteLater()
        self.controller.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)

    def test_empty_back_face_and_reduced_motion_render(self):
        vm = replace(self.vm, hole_cards={"AI_A": ["??", ""], "AI_B": ["As", "Kd"]},
                     reduce_motion=True, thinking=True, thinking_started=time.monotonic() - 2)
        self.table.update_state(vm)
        self.assertEqual(1.0, self.table._progress)
        self.assertTrue(self.table._clock.isActive())
        image = QtGui.QImage(1000, 720, QtGui.QImage.Format.Format_ARGB32)
        self.table.render(image)
        self.assertFalse(image.isNull())
        self.table.update_state(replace(vm, thinking=False))
        self.assertFalse(self.table._clock.isActive())

    def test_deal_animation_and_stale_equity(self):
        self.table.update_state(self.vm)
        vm = replace(self.vm, hole_cards={"AI_A": ["As", "Ah"], "AI_B": ["Ks", "Kh"]})
        self.table.update_state(vm)
        self.assertEqual(4, len(self.table._changed_cards))
        self.assertEqual(QtCore.QAbstractAnimation.State.Running, self.table._animation.state())
        self.table._equity_key = ("current",)
        self.table._accept_equity(("old",), (1, 0, 0))
        self.assertIsNone(self.table._equity)
        self.table._accept_equity(("current",), (.6, .3, .1))
        self.assertEqual((.6, .3, .1), self.table._equity)

    def test_equity_dispatches_off_ui_thread_and_hides_when_disabled(self):
        vm = replace(self.vm, show_equity=True,
                     hole_cards={"AI_A": ["As", "Ah"], "AI_B": ["Ks", "Kh"]})
        with patch("table_widget.threading.Thread") as worker:
            self.table.update_state(vm)
            worker.return_value.start.assert_called_once()
        self.table.update_state(replace(vm, show_equity=False))
        self.assertIsNone(self.table._equity_key)
        self.assertIsNone(self.table._equity)

    def test_showdown_view_model_contains_five_and_award(self):
        c = self.controller
        s = c.state
        s.hole = {"AI_A": [core.parse_card(x) for x in ("Ah", "Kh")],
                  "AI_B": [core.parse_card(x) for x in ("As", "Ad")]}
        s.board = [core.parse_card(x) for x in ("Qh", "Jh", "Th", "6s", "7d")]
        s.contributed_total = {"AI_A": 500, "AI_B": 500}
        s.pot_cents = 1000
        s.resolve_showdown()
        c._emit_vm()
        vm = self.snapshots[-1]
        self.assertEqual(5, len(vm.best_five))
        self.assertEqual("同花顺", vm.winner_hand_desc)
        self.assertEqual(1000, vm.pot_won_cents)
        self.table.update_state(vm)
        image = QtGui.QImage(1000, 720, QtGui.QImage.Format.Format_ARGB32)
        self.table.render(image)

    def test_equity_error_and_partial_board(self):
        vm = replace(self.vm, show_equity=True,
                     hole_cards={"AI_A": ["As", "Ah"], "AI_B": ["Ks", "Kh"]})
        with patch("table_widget.threading.Thread") as worker:
            self.table.update_state(vm)
            key = self.table._equity_key
            self.assertTrue(self.table._equity_pending)
            self.table._accept_equity(key, None)
            self.assertFalse(self.table._equity_pending)
            self.assertIsNone(self.table._equity)
            worker.reset_mock()
            self.table.update_state(replace(vm, board_cards=["6s", "7s", "", "", ""]))
            worker.assert_not_called()
            self.assertIsNone(self.table._equity_key)
            self.assertFalse(self.table._equity_pending)
        image = QtGui.QImage(1000, 720, QtGui.QImage.Format.Format_ARGB32)
        self.table.render(image)

    def test_table_settings_and_metadata_are_exposed(self):
        c = self.controller
        c.load_env({"FOUR_COLOR_DECK": "false", "SHOW_EQUITY": "false",
                    "REDUCE_MOTION": "true", "A_MODEL": "model-a"})
        vm = self.snapshots[-1]
        self.assertFalse(vm.four_color_deck)
        self.assertFalse(vm.show_equity)
        self.assertTrue(vm.reduce_motion)
        self.assertEqual("model-a", vm.model_names["AI_A"])
        self.assertIn("底池", vm.status_text)
        self.assertNotIn("Street:", vm.status_text)
