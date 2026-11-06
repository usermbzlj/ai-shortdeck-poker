from pathlib import Path
import sqlite3
import time

from PySide6 import QtCore, QtGui, QtWidgets

import core
import theme
from analytics import TAG_LABELS
from controller import ActionAvailability, AppViewModel, AutoState
from history_export import export_json, export_text
from table_widget import PokerTableWidget


def frame_vm(hand, index):
    frame = hand["frames"][index]
    winner = frame.get("winner")
    best = []
    description = ""
    if winner and frame["reason"] == "showdown":
        hole = [core.parse_card(c) for c in frame["hole"][winner] if c]
        board = [core.parse_card(c) for c in frame["board"] if c]
        if len(hole + board) == 7:
            best = [core.card_to_text(c) for c in core.best_five_cards(hole + board)]
            description = core.best_hand_desc(hole, board)
    legal = ActionAvailability(False, False, False, False, False, False, None, None,
                               "历史复盘为只读", 0, None, None, 0, None)
    return AppViewModel(frame["hand_no"], frame["button"], frame["street"], frame["pot_cents"],
        frame["stacks"], frame["hole"], frame["board"], frame["next_to_act"], legal, frame["label"],
        [], frame["hand_over"], winner, frame["reason"], False, None, AutoState(False, "复盘", False, False),
        frame["names"], frame["contributed"], model_names=frame["models"],
        last_analysis=frame.get("analysis", {}), last_trash_talk=frame.get("speech", {}),
        trash_talk_times={p: time.monotonic() for p, text in frame.get("speech", {}).items() if text},
        winner_hand_desc=description, best_five=best, pot_won_cents=hand["pot_cents"] if frame["hand_over"] else 0,
        reduce_motion=True, show_equity=False, seats_swapped=frame["swapped"])


def share_image(hand, path):
    widget = PokerTableWidget()
    widget.resize(1600, 900)
    widget.update_state(frame_vm(hand, len(hand["frames"]) - 1))
    image = QtGui.QImage(1600, 1000, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(theme.BG))
    p = QtGui.QPainter(image)
    p.setPen(QtGui.QColor(theme.GOLD))
    p.setFont(theme.paint_font(28, True))
    p.drawText(QtCore.QRect(40, 16, 1520, 35), f'短牌竞技场 · 第 {hand["hand_no"]} 手牌谱')
    winner = hand["names"].get(hand["winner"], "双方")
    result = f'{winner} 赢下 {core.format_money(hand["pot_cents"])}' if hand["winner"] else "平局 · 平分底池"
    p.setPen(QtGui.QColor(theme.SECONDARY))
    p.setFont(theme.paint_font(18))
    p.drawText(QtCore.QRect(40, 57, 1520, 30), result + "   ·   " + " / ".join(TAG_LABELS[t] for t in hand.get("tags", [])))
    widget.render(p, QtCore.QPoint(0, 100))
    p.end()
    widget.deleteLater()
    if not image.save(str(path)):
        raise OSError("分享图无法写入，请检查路径和权限")
    return image


class ReplayViewer(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.hand = None
        self.index = 0
        root = QtWidgets.QVBoxLayout(self)
        self.title = QtWidgets.QLabel("选择一手牌开始复盘")
        self.title.setObjectName("sectionTitle")
        root.addWidget(self.title)
        split = QtWidgets.QSplitter()
        self.table = PokerTableWidget()
        split.addWidget(self.table)
        side = QtWidgets.QWidget()
        side.setMinimumWidth(220)
        side.setMaximumWidth(260)
        detail = QtWidgets.QVBoxLayout(side)
        detail.addWidget(QtWidgets.QLabel("这一刻 · 推理 / 喊话 / 解说"))
        self.context = QtWidgets.QPlainTextEdit()
        self.context.setReadOnly(True)
        detail.addWidget(self.context)
        split.addWidget(side)
        split.setStretchFactor(0, 1)
        root.addWidget(split, 1)
        transport = QtWidgets.QHBoxLayout()
        self.back = QtWidgets.QPushButton("← 上一步")
        self.play = QtWidgets.QPushButton("播放")
        self.forward = QtWidgets.QPushButton("下一步 →")
        self.position = QtWidgets.QLabel()
        for widget in (self.back, self.play, self.forward, self.position):
            transport.addWidget(widget)
        root.addLayout(transport)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        root.addWidget(self.slider)
        self.clock = QtCore.QTimer(self)
        self.clock.setInterval(1000)
        self.clock.timeout.connect(self.next_frame)
        self.back.clicked.connect(lambda: self.set_frame(self.index - 1))
        self.forward.clicked.connect(self.next_frame)
        self.play.clicked.connect(self.toggle)
        self.slider.valueChanged.connect(self.set_frame)
        self.setEnabled(False)

    def load_hand(self, hand, final=False):
        self.clock.stop()
        self.play.setText("播放")
        self.hand = hand
        self.setEnabled(True)
        self.slider.setRange(0, len(hand["frames"]) - 1)
        self.set_frame(len(hand["frames"]) - 1 if final else 0)

    def clear(self):
        self.clock.stop()
        self.hand = None
        self.table.vm = None
        self.table._clock.stop()
        self.table.update()
        self.context.clear()
        self.title.setText("选择一手牌开始复盘")
        self.position.clear()
        self.setEnabled(False)

    def set_frame(self, index):
        if not self.hand:
            return
        self.index = max(0, min(index, len(self.hand["frames"]) - 1))
        frame = self.hand["frames"][self.index]
        self.table.update_state(frame_vm(self.hand, self.index))
        self.title.setText(f'第 {self.hand["hand_no"]} 手 · {frame["label"]}')
        self.title.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.position.setText(f"{self.index + 1} / {len(self.hand['frames'])}")
        self.slider.blockSignals(True)
        self.slider.setValue(self.index)
        self.slider.blockSignals(False)
        self.back.setEnabled(self.index > 0)
        self.forward.setEnabled(self.index < len(self.hand["frames"]) - 1)
        lines = []
        decision = frame.get("decision")
        if decision:
            lines.append(f'思考用时 {decision["think_seconds"]:.2f}s')
            if decision.get("tokens"):
                lines.append("Token 用量：" + str(decision["tokens"].get("total_tokens", "未提供总量")))
        for p in ("AI_A", "AI_B"):
            name = self.hand["names"][p]
            if frame.get("analysis", {}).get(p):
                lines.extend([name + " · 内心 OS", frame["analysis"][p], ""])
            if frame.get("speech", {}).get(p):
                lines.extend([name + " · 喊话", "「" + frame["speech"][p] + "」", ""])
        commentary = [c["text"] for c in self.hand.get("commentary", []) if c["frame"] <= self.index]
        if commentary:
            lines += ["解说"] + commentary
        self.context.setPlainText("\n".join(lines) or "这一刻还没有解说或模型推理。")
        if not self.forward.isEnabled():
            self.clock.stop()
            self.play.setText("重播")

    def next_frame(self):
        self.set_frame(self.index + 1)

    def toggle(self):
        if self.clock.isActive():
            self.clock.stop()
            self.play.setText("播放")
        elif self.hand:
            if self.index == len(self.hand["frames"]) - 1:
                self.set_frame(0)
            self.clock.start()
            self.play.setText("暂停")

    def hideEvent(self, event):
        self.clock.stop()
        self.play.setText("播放")
        super().hideEvent(event)


class HistoryWindow(QtWidgets.QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("牌谱 · 历史与复盘")
        self.resize(1600, 1000)
        self.rows = []
        root = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("牌谱 · 历史与复盘")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        filters = QtWidgets.QHBoxLayout()
        self.matches = QtWidgets.QComboBox()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("搜索选手、牌面、推理或标记…")
        filters.addWidget(self.matches, 1)
        filters.addWidget(self.search, 1)
        self.focus_button = QtWidgets.QPushButton("专注复盘")
        self.focus_button.setCheckable(True)
        filters.addWidget(self.focus_button)
        root.addLayout(filters)
        self.splitter = QtWidgets.QSplitter()
        self.list = QtWidgets.QTableWidget(0, 4)
        self.list.setHorizontalHeaderLabels(["手牌", "结果", "底池", "标记"])
        self.list.verticalHeader().hide()
        self.list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.list.horizontalHeader().setStretchLastSection(True)
        self.list.verticalHeader().setDefaultSectionSize(52)
        self.splitter.addWidget(self.list)
        self.replay = ReplayViewer()
        self.splitter.addWidget(self.replay)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([420, 1160])
        root.addWidget(self.splitter, 1)
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        footer = QtWidgets.QHBoxLayout()
        self.scope = QtWidgets.QComboBox()
        self.scope.addItems(["已选手牌", "当前比赛全部手牌"])
        footer.addWidget(self.scope)
        footer.addStretch()
        for label, kind in (("导出文本", "text"), ("导出 JSON", "json"), ("分享图 PNG", "png")):
            b = QtWidgets.QPushButton(label)
            b.setProperty("variant", "primary" if kind == "png" else "secondary")
            b.clicked.connect(lambda checked=False, k=kind: self.export(k))
            footer.addWidget(b)
        root.addLayout(footer)
        self.matches.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)
        self.list.itemSelectionChanged.connect(self.selection_changed)
        self.focus_button.toggled.connect(lambda focus: self.list.setVisible(not focus))

    def open_history(self, hand=None):
        self.matches.blockSignals(True)
        selected = hand["match_id"] if hand else self.matches.currentData()
        self.matches.clear()
        self.matches.addItem("全部比赛", None)
        try:
            for match in self.store.list_matches():
                meta = match["metadata"]
                label = f'{meta["created_at"][:16]} · {meta["names"]["AI_A"]} vs {meta["names"]["AI_B"]} · {match["hands"]} 手'
                self.matches.addItem(label, match["id"])
            self.matches.setCurrentIndex(max(0, self.matches.findData(selected)))
            self.matches.blockSignals(False)
            self.search.clear()
            self.refresh()
            if hand:
                for i, candidate in enumerate(self.rows):
                    if candidate["match_id"] == hand["match_id"] and candidate["hand_no"] == hand["hand_no"]:
                        self.list.selectRow(i)
                        self.replay.load_hand(candidate, final=True)
                        break
            self.show()
            self.raise_()
        except (OSError, sqlite3.Error, ValueError) as error:
            self.matches.blockSignals(False)
            self.message.setText("读取牌谱失败：" + str(error))
            self.show()

    def refresh(self):
        try:
            self.rows = self.store.list_hands(self.matches.currentData(), self.search.text())
        except (OSError, sqlite3.Error, ValueError) as error:
            self.message.setText("读取牌谱失败：" + str(error))
            return
        self.list.blockSignals(True)
        self.list.setRowCount(len(self.rows))
        for row, hand in enumerate(self.rows):
            result = hand["names"].get(hand["winner"], "双方战平")
            texts = (f'第 {hand["hand_no"]} 手', result, core.format_money(hand["pot_cents"]),
                     " · ".join(TAG_LABELS[t] for t in hand.get("tags", [])) or "—")
            for col, text in enumerate(texts):
                item = QtWidgets.QTableWidgetItem(text)
                item.setToolTip(text)
                if col == 3:
                    item.setForeground(QtGui.QColor(theme.GOLD))
                self.list.setItem(row, col, item)
        self.list.blockSignals(False)
        self.message.setText(f"已记录 {len(self.rows)} 手 · 大底池 ≥20BB · 诈唬标记需主动下注且成牌低于一对 · 全部数据仅保存在本机" if self.rows else "暂无符合条件的牌谱，完成一手对局后会自动保存。")
        if self.rows:
            self.list.selectRow(0)
        else:
            self.replay.clear()

    def selection_changed(self):
        rows = self.list.selectionModel().selectedRows()
        if rows:
            self.replay.load_hand(self.rows[rows[0].row()], final=True)

    def export(self, kind):
        if self.scope.currentIndex() == 1:
            if not self.matches.currentData():
                self.message.setText("请先选择一场比赛，再导出整场。")
                return
            hands = self.store.list_hands(self.matches.currentData())
        else:
            hands = [self.rows[index.row()] for index in self.list.selectionModel().selectedRows()]
        if not hands:
            self.message.setText("请先选择要导出的手牌。")
            return
        try:
            if kind == "png" and len(hands) > 1:
                folder = QtWidgets.QFileDialog.getExistingDirectory(self, "选择分享图保存目录")
                if not folder:
                    return
                for hand in hands:
                    share_image(hand, Path(folder) / f'hand_{hand["match_id"][:8]}_{hand["hand_no"]}.png')
            else:
                suffix = {"png": "png", "json": "json", "text": "txt"}[kind]
                path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "导出牌谱", "shortdeck." + suffix,
                                                               f"牌谱 (*.{suffix})")
                if not path:
                    return
                if kind == "png":
                    share_image(hands[0], path)
                else:
                    Path(path).write_text(export_json(hands) if kind == "json" else export_text(hands), encoding="utf-8")
            self.message.setText(f"已导出 {len(hands)} 手牌谱。")
        except (OSError, ValueError) as error:
            self.message.setText("导出失败：" + str(error))
