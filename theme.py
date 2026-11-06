from pathlib import Path

from PySide6 import QtGui

BG = "#0b0f17"
SURFACE = "#121826"
ELEVATED = "#1a2233"
BORDER = "rgba(255,255,255,0.08)"
TEXT = "#e6edf7"
SECONDARY = "#94a3b8"
MUTED = "#64748b"
GOLD = "#f5c451"
PLAYER_A = "#60a5fa"
PLAYER_B = "#fb7185"
SUCCESS = "#34d399"
DANGER = "#f87171"
WARNING = "#fbbf24"
RADII = (8, 12, 16)
FONTS = ["Inter", "PingFang SC", "Microsoft YaHei UI", "Noto Sans CJK SC", "sans-serif"]
MONO_FONTS = ["JetBrains Mono", "Cascadia Mono", "Consolas", "monospace"]


def initials(name, player=""):
    normalized = name.strip().replace(" ", "")
    if normalized in ("选手A", "选手B", "AI_A", "AI_B"):
        return normalized[-1]
    return name.strip()[:1].upper() or player[-1:] or "?"


def font(size=10, weight=QtGui.QFont.Weight.Normal, mono=False):
    result = QtGui.QFont()
    result.setFamilies(MONO_FONTS if mono else FONTS)
    result.setPointSizeF(size)
    result.setWeight(weight)
    return result


def paint_font(size, bold=False, mono=False):
    result = font(weight=QtGui.QFont.Weight.DemiBold if bold else QtGui.QFont.Weight.Normal, mono=mono)
    result.setPixelSize(size)
    return result


QSS = """
QFrame#humanDock { background: #171f2d; border: 1px solid #ac8d3e; border-radius: 12px; }
QLabel#humanCaption { color: #f5c451; font-weight: 600; }
QTableWidget { background: #121826; alternate-background-color: #172131; border: 1px solid #29364a; border-radius: 8px; gridline-color: #273447; selection-background-color: #343127; }
QTableWidget::item { padding: 6px; }
QHeaderView::section { background: #1a2535; color: #94a3b8; padding: 8px 5px; border: none; }
QListWidget#settingsNav { border: none; background: #101722; }
QListWidget#settingsNav:focus { border: none; }
QGroupBox#drawerCard { margin-top: 0; padding: 12px 10px; }
QPushButton[variant="section"] { text-align: left; background: #162131; color: #b7c7da; border-color: #2b3b50; padding: 10px; }
QPushButton[variant="section"]:checked { color: #f5c451; border-color: #716037; background: #252a30; }
QPushButton[variant="chip"] { color: #c2d3e6; background: #213044; border-radius: 16px; padding: 7px 5px; border-color: #3b4c64; }
QPushButton[variant="chip"]:hover { color: #f5c451; border-color: #f5c451; }
QFrame#notification[tone="info"] { background: #302a1d; border-color: #91753e; }
QFrame#notification[tone="info"] QLabel { color: #ffe1a0; }
QLabel#summaryStack { font-size: 30px; font-weight: 600; color: #f5c451; padding: 12px 0; }
QTextEdit#summaryReflection { background: transparent; border: none; color: #94a3b8; padding: 0; }
QToolBox::tab { background: #121826; color: #94a3b8; border: 1px solid #263144; border-radius: 8px; min-height: 32px; padding: 0; }
QToolBox::tab:selected { background: #252a32; color: #f5c451; }
QLabel[player="A"] { color: #60a5fa; }
QLabel[player="B"] { color: #fb7185; }
QLabel[player="neutral"] { color: #f5c451; }
QFrame#appBar { background: #121826; border: 1px solid #263144; border-radius: 16px; }
QLabel#brandTitle, QLabel#pageTitle { font-size: 23px; font-weight: 600; }
QLabel#sectionTitle { color: #e6edf7; font-size: 17px; font-weight: 600; padding: 8px 10px; }
QLabel[role="eventTitle"] { font-weight: 600; }
QFrame#eventCard { background: #151e2d; border: 1px solid #29364a; border-radius: 12px; }
QFrame#eventCard[kind="speech"] { background: #20283d; border-color: #3b4661; }
QFrame#eventCard[kind="commentary"] { background: #29271f; border-color: #665532; }
QFrame#eventCard[kind="warning"] { background: #33232d; border-color: #69404c; }
QFrame#eventCard[kind="hand"], QFrame#eventCard[kind="system"] { background: #111823; border-color: #222e40; }
QFrame#emptyCard { background: #121e2c; border: 1px solid #354458; border-radius: 16px; }
QPushButton[variant="ghost"]:checked { background: #3a3220; color: #f5c451; border-color: #796033; }
QSlider::groove:horizontal { background: #263144; height: 5px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #f5c451; border-radius: 2px; }
QSlider::handle:horizontal { background: #ffe49a; width: 14px; margin: -5px 0; border-radius: 7px; }
QListWidget::item { padding: 10px; border-radius: 8px; }
QListWidget::item:selected { background: #3a3220; color: #f5c451; }
QWidget { color: #e6edf7; font-size: 13px; }
QMainWindow, QDialog { background: #0b0f17; }
QWidget#workspace, QTabWidget::pane, QScrollArea, QScrollArea > QWidget > QWidget { background: #0b0f17; }
QTabWidget::pane { border: none; padding-top: 10px; }
QTabBar::tab { background: transparent; color: #94a3b8; padding: 10px 24px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #f5c451; border-bottom: 2px solid #f5c451; background: #121826; }
QTabBar::tab:hover { color: #e6edf7; }
QGroupBox { background: #121826; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px;
    margin-top: 22px; padding: 18px 12px 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; top: 3px; color: #94a3b8; font-weight: 600; }
QPushButton { background: #1a2233; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;
    padding: 8px 12px; font-weight: 600; }
QPushButton:hover { background: #253248; border-color: #43536b; }
QPushButton:pressed { background: #0b0f17; }
QPushButton[variant="primary"] { color: #211a09; border: 1px solid #f5c451;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ffe49a,stop:1 #e7ad31); }
QPushButton[variant="primary"]:hover { background: #ffdf86; }
QPushButton[variant="primary"]:pressed { background: #d89c24; }
QPushButton[variant="danger"] { background: #33202b; color: #f87171; border-color: #633441; }
QPushButton[variant="danger"]:hover { background: #512936; }
QPushButton[variant="danger"]:pressed { background: #261921; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; color: #94a3b8; }
QPushButton[variant="ghost"]:hover { background: #1a2233; color: #e6edf7; }
QPushButton[variant="ghost"]:pressed { background: #0b0f17; }
QPushButton:disabled, QPushButton[variant="primary"]:disabled, QPushButton[variant="danger"]:disabled {
    background: #151c28; color: #4c5a70; border-color: #202a3a; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit, QListWidget {
    background: #0e1521; border: 1px solid #263144; border-radius: 8px; padding: 7px;
    selection-background-color: #735824; selection-color: #fff5db; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus,
QPlainTextEdit:focus, QListWidget:focus { border-color: #f5c451; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: #536078; background: #111722; border-color: #1b2432; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #1a2233; color: #e6edf7; selection-background-color: #334158; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 20px; border: none; background: #1a2233; }
QCheckBox { spacing: 9px; padding: 3px 0; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px; border: 1px solid #43536b; background: #0e1521; }
QCheckBox::indicator:checked { background: #f5c451; border-color: #f5c451; image: none; }
QCheckBox::indicator:disabled { background: #172030; border-color: #263144; }
QCheckBox::indicator:hover { border-color: #f5c451; }
QScrollArea { border: none; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: #344157; border-radius: 3px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #596982; }
QScrollBar:horizontal { height: 8px; background: transparent; margin: 2px; }
QScrollBar::handle:horizontal { background: #344157; border-radius: 3px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSplitter::handle { background: #0b0f17; }
QSplitter::handle:hover { background: #344157; }
QToolTip { color: #e6edf7; background: #1a2233; border: 1px solid #43536b; padding: 8px; border-radius: 8px; }
QStatusBar { color: #94a3b8; background: #101622; border-top: 1px solid #202a3a; padding: 4px 10px; }
QStatusBar::item { border: none; }
QLabel[role="hint"] { color: #64748b; }
QLabel[role="emphasis"] { color: #f5c451; font-weight: 600; }
QFrame#notification { background: #351e29; border: 1px solid #75404e; border-radius: 12px; }
QFrame#notification QLabel { color: #fecaca; }
QWidget#configBanner { background: #332b19; border: 1px solid #705a2f; border-radius: 8px; }
QWidget#configBanner QLabel { color: #f5c451; }
"""


def apply(app):
    app.setStyle("Fusion")
    app.setFont(font())
    palette = QtGui.QPalette()
    for role, color in ((QtGui.QPalette.ColorRole.Window, BG),
                        (QtGui.QPalette.ColorRole.WindowText, TEXT),
                        (QtGui.QPalette.ColorRole.Base, SURFACE),
                        (QtGui.QPalette.ColorRole.Text, TEXT),
                        (QtGui.QPalette.ColorRole.Button, ELEVATED),
                        (QtGui.QPalette.ColorRole.ButtonText, TEXT),
                        (QtGui.QPalette.ColorRole.Highlight, GOLD)):
        palette.setColor(role, QtGui.QColor(color))
    app.setPalette(palette)
    arrow = Path(__file__).with_name("chevron.svg").as_posix()
    app.setStyleSheet(QSS + f'QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 8px; }}')
