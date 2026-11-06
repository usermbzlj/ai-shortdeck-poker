import math

from PySide6 import QtCore, QtGui, QtWidgets

import core
import theme
from analytics import PLAYERS, adjusted_net, aggregate, curve_points, net_results


class StackChart(QtWidgets.QWidget):
    handClicked = QtCore.Signal(object)

    def __init__(self, players=PLAYERS, parent=None):
        super().__init__(parent)
        self.players = players
        self.points = []
        self.hover = -1
        self.setMinimumHeight(130)
        self.setMouseTracking(True)

    def set_points(self, points):
        self.points = points
        self.hover = -1
        self.update()

    def plot_rect(self):
        return QtCore.QRectF(16, 18, max(1, self.width() - 32), max(1, self.height() - 46))

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        area = self.plot_rect()
        p.setPen(QtGui.QPen(QtGui.QColor("#253448"), 1))
        for i in range(4):
            y = area.top() + i * area.height() / 3
            p.drawLine(QtCore.QPointF(area.left(), y), QtCore.QPointF(area.right(), y))
        p.setFont(theme.paint_font(10))
        if not self.points:
            p.setPen(QtGui.QColor(theme.SECONDARY))
            p.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "完成第一手后，筹码曲线将在这里出现")
            return
        values = [point["stacks"][pid] for point in self.points for pid in self.players]
        low, high = min(values), max(values)
        padding = max(100, (high - low) * .12)
        low, high = low - padding, high + padding
        for pid in self.players:
            color = theme.PLAYER_A if pid == "AI_A" else theme.PLAYER_B
            path = QtGui.QPainterPath()
            for i, point in enumerate(self.points):
                x = area.left() + i / max(1, len(self.points) - 1) * area.width()
                y = area.bottom() - (point["stacks"][pid] - low) / (high - low) * area.height()
                if i:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
            p.setPen(QtGui.QPen(QtGui.QColor(color), 2.5))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setBrush(QtGui.QColor(color))
            p.drawEllipse(path.currentPosition(), 3, 3)
        if self.hover >= 0:
            x = area.left() + self.hover / max(1, len(self.points) - 1) * area.width()
            p.setPen(QtGui.QPen(QtGui.QColor(theme.GOLD), 1, QtCore.Qt.PenStyle.DashLine))
            p.drawLine(QtCore.QPointF(x, area.top()), QtCore.QPointF(x, area.bottom()))
        p.setPen(QtGui.QColor(theme.SECONDARY))
        p.drawText(QtCore.QRectF(area.left(), area.bottom() + 7, area.width(), 18),
                   QtCore.Qt.AlignmentFlag.AlignLeft, "开局")
        p.drawText(QtCore.QRectF(area.left(), area.bottom() + 7, area.width(), 18),
                   QtCore.Qt.AlignmentFlag.AlignRight, f'第 {self.points[-1]["hand_no"]} 手')

    def mouseMoveEvent(self, event):
        if self.points:
            fraction = (event.position().x() - self.plot_rect().left()) / self.plot_rect().width()
            self.hover = max(0, min(len(self.points) - 1, round(fraction * (len(self.points) - 1))))
            point = self.points[self.hover]
            names = (point.get("record") or {}).get("names", {})
            text = f'第 {point["hand_no"]} 手\n' + "\n".join(
                f'{names.get(p, "选手 " + p[-1])}  {core.format_money(point["stacks"][p])}' for p in self.players)
            QtWidgets.QToolTip.showText(event.globalPosition().toPoint(), text, self)
            self.update()

    def leaveEvent(self, event):
        self.hover = -1
        self.update()

    def mousePressEvent(self, event):
        self.mouseMoveEvent(event)
        if self.hover >= 0 and self.points[self.hover].get("record"):
            self.handClicked.emit(self.points[self.hover]["record"])


class LuckChart(StackChart):
    def set_hands(self, hands, player="AI_A"):
        self.players = PLAYERS
        self.points = [dict(hand_no=0, stacks=dict(AI_A=0, AI_B=0), record=None)]
        actual = ev = 0
        for hand in sorted(hands, key=lambda h: h["hand_no"]):
            actual += net_results(hand)[player]
            ev += adjusted_net(hand)[player]
            self.points.append(dict(hand_no=hand["hand_no"], stacks=dict(AI_A=ev, AI_B=actual - ev), record=hand))
        if not hands:
            self.points = []
        self.update()

    def mouseMoveEvent(self, event):
        if not self.points:
            return
        super().mouseMoveEvent(event)
        point = self.points[self.hover]
        QtWidgets.QToolTip.showText(event.globalPosition().toPoint(),
            f'第 {point["hand_no"]} 手\n实力（全押EV）：{core.format_money(point["stacks"]["AI_A"])}\n运气差额：{core.format_money(point["stacks"]["AI_B"])}', self)


class StatsPanel(QtWidgets.QWidget):
    openHand = QtCore.Signal(object)
    openHistory = QtCore.Signal()

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.hands = {}
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        header = QtWidgets.QHBoxLayout()
        self.count = QtWidgets.QLabel("本场数据 · 等待开局")
        header.addWidget(self.count, 1)
        history = QtWidgets.QPushButton("牌谱 ↗")
        history.setProperty("variant", "ghost")
        history.clicked.connect(self.openHistory)
        header.addWidget(history)
        root.addLayout(header)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        body = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(QtWidgets.QLabel("筹码轨迹 · 点击节点复盘"))
        self.chart = StackChart()
        self.chart.setFixedHeight(145)
        self.chart.handClicked.connect(self.openHand)
        layout.addWidget(self.chart)
        self.table = QtWidgets.QTableWidget(10, 3)
        self.table.setHorizontalHeaderLabels(["指标", "选手 A", "选手 B"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(25)
        self.table.setFixedHeight(292)
        layout.addWidget(self.table)
        self.player = QtWidgets.QComboBox()
        self.player.addItems(["选手 A · 运气 vs 实力", "选手 B · 运气 vs 实力"])
        self.player.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.player)
        self.luck = LuckChart()
        self.luck.setFixedHeight(100)
        self.luck.handClicked.connect(self.openHand)
        layout.addWidget(self.luck)
        self.ev_text = QtWidgets.QLabel()
        self.ev_text.setWordWrap(True)
        self.ev_text.setProperty("role", "hint")
        layout.addWidget(self.ev_text)
        note = QtWidgets.QLabel("蓝：全押 EV（实力参考） · 粉：实际−EV（运气）\n非真实实力估计 · 翻牌前 2000 次抽样，翻牌后精确。")
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        layout.addWidget(note)
        layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        controller.matchStarted.connect(self.clear)
        controller.handCompleted.connect(self.add_hand)
        self.refresh()

    def clear(self):
        self.hands = {}
        self.refresh()

    def add_hand(self, hand):
        if hand["match_id"] == self.controller.match_id:
            self.hands[hand["hand_no"]] = hand
            self.refresh()

    def refresh(self):
        hands = list(self.hands.values())
        stats = aggregate(hands)
        names = hands[-1]["names"] if hands else {"AI_A": "选手 A", "AI_B": "选手 B"}
        self.count.setText(f"本场数据 · {len(hands)} 手")
        self.table.setHorizontalHeaderLabels(["指标", names["AI_A"], names["AI_B"]])
        self.chart.set_points(curve_points(hands))
        rows = [("VPIP", "vpip"), ("PFR", "pfr"), ("3bet", "threebet"), ("AF", "af"),
                ("WTSD", "wtsd"), ("W$SD", "wsd"), ("平均思考", "think_seconds"),
                ("非法输出率", "invalid_rate"), ("兜底", "fallbacks"), ("实际净收益", "net_cents")]
        for row, (label, key) in enumerate(rows):
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(label))
            for col, p in enumerate(PLAYERS, 1):
                value = stats[p][key]
                text = "—" if value is None else "∞" if isinstance(value, float) and math.isinf(value) else (
                    core.format_money(value) if key == "net_cents" else f"{value:.2f}s" if key == "think_seconds"
                    else f"{value:.2f}" if key == "af" else str(value) if key == "fallbacks" else f"{value:.1%}")
                item = QtWidgets.QTableWidgetItem(text)
                item.setForeground(QtGui.QColor(theme.PLAYER_A if p == "AI_A" else theme.PLAYER_B))
                self.table.setItem(row, col, item)
        p = PLAYERS[self.player.currentIndex()]
        self.luck.set_hands(hands, p)
        s = stats[p]
        self.ev_text.setText(f'全押 EV 净收益 {core.format_money(s["ev_cents"])}\n运气差额 {core.format_money(s["luck_cents"])}' +
                             (f' · {s["ev_pending"]} 手正在计算' if s["ev_pending"] else ""))
