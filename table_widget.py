import math
import random
import threading
import time

from PySide6 import QtCore, QtGui, QtWidgets

import core
import equity
import theme


def _color(value, *components):
    if components:
        return QtGui.QColor(value, *components)
    if isinstance(value, str) and value.startswith("#") and len(value) == 9:
        return QtGui.QColor(int(value[1:3], 16), int(value[3:5], 16),
                            int(value[5:7], 16), int(value[7:9], 16))
    return QtGui.QColor(value)


SUITS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
STREETS = ("preflop", "flop", "turn", "river")
STREET_NAMES = ("翻牌前", "翻牌", "转牌", "河牌")


class PokerTableWidget(QtWidgets.QWidget):
    equityReady = QtCore.Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(600, 440)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.vm = None
        self._equity = None
        self._equity_key = None
        self._equity_pending = False
        self._inflight = set()
        self._progress = 1.0
        self._changed_cards = set()
        self._old_bets = {}
        self._pot_slide = False
        self._texture = self._make_texture()
        self._animation = QtCore.QVariantAnimation(self)
        self._animation.setDuration(380)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._animate)
        self._clock = QtCore.QTimer(self)
        self._clock.setInterval(50)
        self._clock.timeout.connect(self._tick)
        self.equityReady.connect(self._accept_equity)

    @staticmethod
    def _make_texture():
        rng = random.Random(62)
        texture = QtGui.QImage(180, 180, QtGui.QImage.Format.Format_ARGB32)
        for y in range(180):
            for x in range(180):
                texture.setPixelColor(x, y, _color(210, 255, 237, rng.randrange(0, 12)))
        return QtGui.QPixmap.fromImage(texture)

    def _animate(self, value):
        self._progress = float(value)
        self.update()

    def _tick(self):
        if not self.vm:
            self._clock.stop()
            return
        live_bubble = any(0 <= time.monotonic() - stamp < 5 for stamp in self.vm.trash_talk_times.values())
        if not self.vm.thinking and not live_bubble:
            self._clock.stop()
        self.update()

    @staticmethod
    def _cards(vm):
        return {**{("board", i): c for i, c in enumerate(vm.board_cards)},
                **{(p, i): c for p in ("AI_A", "AI_B") for i, c in enumerate(vm.hole_cards.get(p, []))}}

    def update_state(self, vm):
        previous = self.vm
        old_cards = self._cards(previous) if previous and previous.hand_id == vm.hand_id else {}
        self._changed_cards = {key for key, card in self._cards(vm).items() if card and old_cards.get(key) != card}
        self._old_bets = (dict(previous.contributed_street_cents)
                          if previous and previous.street != vm.street and previous.hand_id == vm.hand_id else {})
        self._pot_slide = bool(previous and not previous.hand_over and vm.hand_over and vm.winner)
        self.vm = vm
        self._animation.stop()
        self._progress = 1.0
        if not vm.reduce_motion and (self._changed_cards or self._old_bets or self._pot_slide):
            self._animation.start()
        if vm.thinking or any(0 <= time.monotonic() - stamp < 5 for stamp in vm.trash_talk_times.values()):
            self._clock.start()
        else:
            self._clock.stop()
        self._request_equity()
        self.update()

    def _request_equity(self):
        vm = self.vm
        holes = [tuple(c for c in vm.hole_cards.get(p, []) if c and c != "??") for p in ("AI_A", "AI_B")]
        board = tuple(c for c in vm.board_cards if c and c != "??")
        key = (equity.card_key(*holes, board)
               if vm.show_equity and all(len(h) == 2 for h in holes) and len(board) in (0, 3, 4, 5)
               else None)
        if key == self._equity_key:
            return
        self._equity_key = key
        self._equity = None
        self._equity_pending = key is not None
        if key is None or key in self._inflight:
            return
        self._inflight.add(key)

        def worker():
            try:
                result = equity.calculate_equity(*key)
            except (ValueError, core.UserFacingError):
                result = None
            try:
                self.equityReady.emit(key, result)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _accept_equity(self, key, result):
        self._inflight.discard(key)
        if key == self._equity_key:
            self._equity = result
            self._equity_pending = False
            self.update()

    @staticmethod
    def _round(p, rect, fill, radius=12, stroke=None, width=1):
        p.setPen(QtGui.QPen(_color(stroke), width) if stroke else QtCore.Qt.PenStyle.NoPen)
        p.setBrush(_color(fill) if isinstance(fill, str) else fill)
        p.drawRoundedRect(QtCore.QRectF(*rect), radius, radius)

    @staticmethod
    def _text(p, rect, text, size=14, color=theme.TEXT, bold=False,
              align=QtCore.Qt.AlignmentFlag.AlignCenter, mono=False):
        p.setFont(theme.paint_font(size, bold, mono))
        p.setPen(_color(color))
        text = p.fontMetrics().elidedText(str(text), QtCore.Qt.TextElideMode.ElideRight, int(rect[2]))
        p.drawText(QtCore.QRectF(*rect), align | QtCore.Qt.AlignmentFlag.AlignVCenter, text)

    def _chip(self, p, x, y, color=theme.GOLD, scale=1):
        p.save()
        p.translate(x, y)
        p.scale(scale, scale)
        for i in range(3):
            self._round(p, (-16, -6 - 5 * i, 32, 12), color, 6, "#101a23")
            p.setPen(QtGui.QPen(_color("#ffffff90"), 2))
            p.drawLine(QtCore.QPointF(-9, -9 - 5 * i), QtCore.QPointF(-9, -5 - 5 * i))
            p.drawLine(QtCore.QPointF(9, -9 - 5 * i), QtCore.QPointF(9, -5 - 5 * i))
        p.restore()

    def _card(self, p, x, y, w, h, card, key, highlight=False, dim=False):
        p.save()
        progress = self._progress if key in self._changed_cards else 1.0
        if progress < 1:
            x = 500 + (x - 500) * progress
            y = 350 + (y - 350) * progress
        if dim:
            p.setOpacity(0.36)
        if not card:
            self._round(p, (x, y, w, h), "#ffffff03", 8, "#ffffff19")
            self._text(p, (x, y, w, h), "·", 24, "#ffffff20")
            p.restore()
            return
        face_down = card == "??"
        if key[0] == "board" and progress < 1:
            face_down = progress < 0.5
            flip = max(0.06, abs(progress * 2 - 1))
            p.translate(x + w / 2, y)
            p.scale(flip, 1)
            x, y = -w / 2, 0
        self._round(p, (x + 1, y + 5, w, h), "#00000060", 9)
        if highlight:
            for spread, alpha in ((5, "35"), (2, "90")):
                self._round(p, (x - spread, y - spread, w + spread * 2, h + spread * 2),
                            "#f5c451" + alpha, 11)
        if face_down:
            gradient = QtGui.QLinearGradient(x, y, x + w, y + h)
            gradient.setColorAt(0, _color("#284761"))
            gradient.setColorAt(1, _color("#101e35"))
            self._round(p, (x, y, w, h), gradient, 8, "#91a5b5")
            p.save()
            clip = QtGui.QPainterPath()
            clip.addRoundedRect(QtCore.QRectF(x + 4, y + 4, w - 8, h - 8), 5, 5)
            p.setClipPath(clip)
            p.setPen(QtGui.QPen(_color("#91a5b540"), 0.8))
            for offset in range(-int(h), int(w + h), 10):
                p.drawLine(QtCore.QPointF(x + offset, y), QtCore.QPointF(x + offset + h, y + h))
                p.drawLine(QtCore.QPointF(x + offset, y + h), QtCore.QPointF(x + offset + h, y))
            p.restore()
            self._text(p, (x, y, w, h), "6+", 20, "#d0c8aa", True)
        else:
            gradient = QtGui.QLinearGradient(x, y, x + w, y + h)
            gradient.setColorAt(0, _color("#ffffff"))
            gradient.setColorAt(1, _color("#dce5ec"))
            self._round(p, (x, y, w, h), gradient, 8, "#f5c451" if highlight else "#ffffffb0", 1.5)
            suit = card[-1]
            colors = {"s": "#142134", "h": "#c93350", "d": "#2775c9" if self.vm.four_color_deck else "#c93350",
                      "c": "#16816c" if self.vm.four_color_deck else "#142134"}
            color = colors.get(suit, "#142134")
            for rotate in (False, True):
                p.save()
                if rotate:
                    p.translate(x + w, y + h)
                    p.rotate(180)
                    cx = cy = 0
                else:
                    cx, cy = x, y
                self._text(p, (cx + 4, cy + 3, w * .32, h * .23), card[0], int(w * .27), color, True)
                self._text(p, (cx + 4, cy + h * .23, w * .32, h * .19), SUITS.get(suit, ""), int(w * .22), color)
                p.restore()
            self._text(p, (x + w * .2, y + h * .25, w * .6, h * .5), SUITS.get(suit, ""), int(w * .48), color)
        p.restore()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        vignette = QtGui.QRadialGradient(self.width() * .5, self.height() * .4, max(self.width(), self.height()) * .7)
        vignette.setColorAt(0, _color("#1b2939"))
        vignette.setColorAt(1, _color(theme.BG))
        p.fillRect(self.rect(), vignette)
        scale = min(self.width() / 1000, self.height() / 715)
        p.translate((self.width() - 1000 * scale) / 2, (self.height() - 715 * scale) / 2)
        p.scale(scale, scale)
        p.translate(0, -35)
        for grow, alpha in ((18, 10), (12, 16), (6, 28)):
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(_color(0, 0, 0, alpha))
            p.drawEllipse(QtCore.QRectF(67 - grow, 154 - grow + 14, 866 + grow * 2, 438 + grow * 2))
        rail = QtGui.QLinearGradient(0, 140, 0, 590)
        for pos, color in ((0, "#44515e"), (.12, "#202a35"), (.5, "#101923"), (1, "#263441")):
            rail.setColorAt(pos, _color(color))
        p.setBrush(rail)
        p.setPen(QtGui.QPen(_color("#526270"), 1))
        p.drawEllipse(QtCore.QRectF(65, 142, 870, 446))
        felt_rect = QtCore.QRectF(91, 164, 818, 398)
        felt = QtGui.QRadialGradient(500, 300, 450)
        felt.setColorAt(0, _color("#166c62"))
        felt.setColorAt(.55, _color("#105349"))
        felt.setColorAt(1, _color("#082d2d"))
        p.setBrush(felt)
        p.setPen(QtGui.QPen(_color("#51897a"), 1.5))
        p.drawEllipse(felt_rect)
        p.save()
        path = QtGui.QPainterPath()
        path.addEllipse(felt_rect)
        p.setClipPath(path)
        p.fillRect(felt_rect, QtGui.QBrush(self._texture))
        p.restore()
        p.setPen(QtGui.QPen(_color("#ffffff14"), 1, QtCore.Qt.PenStyle.DashLine))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawEllipse(felt_rect.adjusted(15, 14, -15, -14))
        vm = self.vm
        if not vm:
            self._text(p, (250, 300, 500, 70), "牌桌已就绪", 24, theme.SECONDARY)
            return
        if not vm.hand_over:
            self._text(p, (390, 250, 220, 20), "底  池", 12, "#a4c5b9")
            self._chip(p, 426, 288, theme.GOLD, .8)
            self._text(p, (450, 271, 165, 35), "$" + core.dollars_from_cents(vm.pot_cents), 29, "#fff0c8", True, mono=True,
                       align=QtCore.Qt.AlignmentFlag.AlignLeft)
        for i in range(5):
            card = vm.board_cards[i] if i < len(vm.board_cards) else ""
            highlight = vm.hand_over and card in vm.best_five
            self._card(p, 292 + i * 85, 318, 76, 102, card, ("board", i), highlight)
        for i, label in enumerate(STREET_NAMES):
            current = STREETS[i] == vm.street
            self._round(p, (323 + i * 91, 430, 82, 25), "#d9bb651e" if current else "#041e1e60", 12,
                        "#d4bd6860" if current else "#ffffff0a")
            self._text(p, (323 + i * 91, 430, 82, 25), label, 11, theme.GOLD if current else "#75a79c", current)
        self._text(p, (100, 340, 160, 26), f"第 {vm.hand_id} 手", 15, "#8bb9aa", True)
        self._text(p, (745, 340, 160, 26), "6+ 短牌", 14, "#8bb9aa", True)
        self._draw_equity(p)
        seats = ("AI_B", "AI_A") if vm.seats_swapped else ("AI_A", "AI_B")
        for pid, y in zip(seats, (69, 610)):
            self._seat(p, pid, y)
        if self._old_bets and self._progress < 1:
            for pid, amount in self._old_bets.items():
                if amount:
                    start_y = 222 if pid == "AI_A" else 513
                    self._chip(p, 665 + (426 - 665) * self._progress,
                               start_y + (288 - start_y) * self._progress,
                               theme.PLAYER_A if pid == "AI_A" else theme.PLAYER_B)
        if self._pot_slide and self._progress < 1:
            target = 115 if vm.winner == "AI_A" else 620
            self._chip(p, 500, 285 + (target - 285) * self._progress, theme.GOLD, 1.3)
        if vm.hand_over:
            if vm.winner:
                name = vm.player_names.get(vm.winner, vm.winner)
                detail = "对手弃牌" if vm.reason == "fold" else vm.winner_hand_desc
                title = f"{name} 赢下 $" + core.dollars_from_cents(vm.pot_won_cents)
            else:
                title, detail = "平分底池", "双方牌力相同"
            self._round(p, (245, 262, 510, 48), "#111c24f5", 12, "#d9b65b", 1.2)
            self._text(p, (260, 264, 480, 25), title, 20, theme.GOLD, True)
            self._text(p, (260, 290, 480, 16), detail, 11, "#c2b493")
        self._text(p, (30, 718, 940, 20), "上帝视角 · 双方底牌仅对观众可见     /     同花大于葫芦 · A6789 为顺子", 11, theme.MUTED)

    def _draw_equity(self, p):
        if not self.vm.show_equity:
            return
        if self._equity is None:
            status = ("计算中…" if self._equity_pending else "暂不可计算") if self._equity_key else "等待完整牌面"
            self._text(p, (320, 462, 360, 22), "观众胜率 · " + status, 10, "#92b5a8")
            return
        a, b, tie = self._equity
        self._text(p, (320, 459, 360, 18), f"A 胜 {a:.1%}     平局 {tie:.1%}     B 胜 {b:.1%}", 11, "#b8d7cb", mono=False)
        self._round(p, (330, 481, 340, 5), theme.PLAYER_B, 2.5)
        p.save()
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(QtCore.QRectF(330, 481, 340, 5), 2.5, 2.5)
        p.setClipPath(clip)
        p.fillRect(QtCore.QRectF(330, 481, 340 * a, 5), _color(theme.PLAYER_A))
        p.fillRect(QtCore.QRectF(330 + 340 * a, 481, 340 * tie, 5), _color("#a8b7c6"))
        p.restore()

    def _seat(self, p, pid, y):
        vm = self.vm
        top = y < 300
        color = theme.PLAYER_A if pid == "AI_A" else theme.PLAYER_B
        winner = vm.hand_over and vm.winner == pid
        loser = vm.hand_over and vm.winner and vm.winner != pid
        active = not vm.hand_over and vm.next_to_act == pid
        thinking = active and vm.thinking
        pulse = (math.sin(time.monotonic() * 3) + 1) / 2 if thinking and not vm.reduce_motion else .5
        p.save()
        if loser:
            p.setOpacity(.55)
        if active or winner:
            glow = _color(theme.GOLD if winner else color)
            glow.setAlpha(int(20 + 20 * pulse))
            for spread in (10, 5):
                self._round(p, (285 - spread, y - spread, 430 + spread * 2, 88 + spread * 2), glow, 22)
        gradient = QtGui.QLinearGradient(0, y, 0, y + 88)
        gradient.setColorAt(0, _color("#233043"))
        gradient.setColorAt(1, _color("#101a29"))
        self._round(p, (285, y, 430, 88), gradient, 18,
                    theme.GOLD if winner else color if active else "#3a495b", 1.4)
        p.setPen(QtGui.QPen(_color(color), 2))
        p.setBrush(_color("#192a40" if top else "#362533"))
        p.drawEllipse(QtCore.QRectF(302, y + 17, 54, 54))
        name = vm.player_names.get(pid, pid)
        initials = theme.initials(name, pid)
        self._text(p, (302, y + 17, 54, 54), initials, 24, color, True)
        self._text(p, (370, y + 12, 168, 27), name, 18, theme.TEXT, True,
                   align=QtCore.Qt.AlignmentFlag.AlignLeft)
        self._text(p, (370, y + 43, 168, 21), vm.model_names.get(pid) or "尚未选择模型", 11, theme.SECONDARY,
                   align=QtCore.Qt.AlignmentFlag.AlignLeft)
        self._text(p, (540, y + 15, 155, 30), "$" + core.dollars_from_cents(vm.stacks_cents.get(pid, 0)), 23,
                   theme.GOLD if winner else theme.TEXT, True, mono=True, align=QtCore.Qt.AlignmentFlag.AlignRight)
        elapsed = max(0, time.monotonic() - vm.thinking_started) if vm.thinking_started else 0
        status = f"思考中 {elapsed:.1f}s" if thinking else "本手获胜" if winner else "轮到行动" if active else "等待行动"
        self._text(p, (540, y + 48, 155, 20), status, 11, theme.GOLD if winner else color if active else theme.MUTED,
                   align=QtCore.Qt.AlignmentFlag.AlignRight)
        if vm.button == pid:
            p.setPen(QtGui.QPen(_color("#fff1bc"), 1))
            p.setBrush(_color(theme.GOLD))
            p.drawEllipse(QtCore.QRectF(730, y + 30, 30, 30))
            self._text(p, (730, y + 30, 30, 30), "D", 14, "#34260e", True)
        cards = vm.hole_cards.get(pid, ["", ""])
        card_y = 165 if top else 506
        for i in range(2):
            card = cards[i] if i < len(cards) else ""
            self._card(p, 426 + i * 76, card_y, 66, 88, card, (pid, i), winner and card in vm.best_five)
        known = [core.parse_card(c) for c in cards if c and c != "??"]
        board = [core.parse_card(c) for c in vm.board_cards if c and c != "??"]
        strength = core.best_hand_desc(known, board) if len(known) == 2 else ""
        if strength:
            self._round(p, (330, card_y + 32, 80, 25), "#081e25b0", 12, "#ffffff15")
            self._text(p, (330, card_y + 32, 80, 25), strength, 11, "#aac8bf")
        amount = vm.contributed_street_cents.get(pid, 0)
        if amount and not vm.hand_over:
            self._chip(p, 630, card_y + 52, color)
            self._text(p, (650, card_y + 34, 115, 25), "$" + core.dollars_from_cents(amount), 15, "#e6dcbb", True,
                       align=QtCore.Qt.AlignmentFlag.AlignLeft, mono=True)
        analysis = vm.last_analysis.get(pid, "")
        if analysis:
            self._text(p, (78, card_y + 7, 230, 22), "内心 OS", 10, theme.MUTED,
                       align=QtCore.Qt.AlignmentFlag.AlignLeft)
            p.setFont(theme.paint_font(12))
            p.setPen(_color("#93b2aa"))
            p.drawText(QtCore.QRectF(78, card_y + 32, 215, 48),
                       QtCore.Qt.TextFlag.TextWordWrap, analysis[:54])
        age = time.monotonic() - vm.trash_talk_times.get(pid, 0)
        bubble = vm.last_trash_talk.get(pid, "")
        if bubble and 0 <= age < 5:
            p.save()
            p.setOpacity(min(1.0, (5 - age) / .6))
            self._round(p, (782, y + 5, 193, 73), "#243449", 12, "#566a80")
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(_color("#243449"))
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(783, y + 37), QtCore.QPointF(772, y + 45),
                                           QtCore.QPointF(783, y + 50)]))
            p.setFont(theme.paint_font(12))
            p.setPen(_color(theme.TEXT))
            p.drawText(QtCore.QRectF(795, y + 15, 166, 53), QtCore.Qt.TextFlag.TextWordWrap, bubble[:42])
            p.restore()
        p.restore()
