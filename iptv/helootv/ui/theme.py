"""Koyu tema: renkler, QSS ve programla çizilen uygulama simgesi."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPalette, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication

BG = "#0d1016"
PANEL = "#141924"
PANEL_2 = "#1b2130"
LINE = "#252d3f"
TEXT = "#e8ecf4"
MUTED = "#8f9ab0"
ACCENT = "#7c5cff"
ACCENT_2 = "#38bdf8"
NVIDIA = "#76b900"
DANGER = "#ff5c7a"
WARN = "#f5b041"

QSS = f"""
* {{ outline: 0; }}
QWidget {{ background: {BG}; color: {TEXT}; font-size: 10.5pt; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {LINE}; padding: 6px; }}
QFrame#TopBar {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
QLabel#Brand {{ font-size: 15pt; font-weight: 700; color: {TEXT}; background: transparent; padding-right: 14px; }}
QLabel#Muted, QLabel[muted="true"] {{ color: {MUTED}; background: transparent; }}
QLabel#H1 {{ font-size: 18pt; font-weight: 700; background: transparent; }}
QLabel#H2 {{ font-size: 12.5pt; font-weight: 600; background: transparent; }}
QLabel#Badge {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 9px; padding: 2px 9px; color: {MUTED}; }}
QLabel#BadgeNv {{ background: rgba(118,185,0,0.16); border: 1px solid {NVIDIA}; border-radius: 9px; padding: 2px 9px;
                  color: #b8f05a; font-weight: 600; }}
QLabel#BadgeLive {{ background: rgba(255,92,122,0.16); border: 1px solid {DANGER}; border-radius: 9px; padding: 2px 9px;
                    color: #ffb3c1; font-weight: 600; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {LINE}; }}
QPushButton:disabled {{ color: #59627a; border-color: {PANEL_2}; }}
QPushButton#Primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: white; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #8f74ff; }}
QPushButton#Nav {{ background: transparent; border: none; border-radius: 9px; padding: 8px 16px; color: {MUTED};
                   font-weight: 600; }}
QPushButton#Nav:hover {{ color: {TEXT}; background: {PANEL_2}; }}
QPushButton#Nav:checked {{ color: white; background: {ACCENT}; }}
QPushButton#Flat {{ background: transparent; border: none; padding: 6px 10px; color: {MUTED}; }}
QPushButton#Flat:hover {{ color: {TEXT}; }}
QPushButton#Seg {{ border-radius: 0; padding: 7px 16px; }}
QPushButton#Seg:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{ background: {PANEL_2}; border: 1px solid {LINE};
        border-radius: 8px; padding: 6px 10px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QLineEdit#Search {{ border-radius: 16px; padding: 7px 14px; min-width: 260px; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; border: 1px solid {LINE}; selection-background-color: {ACCENT}; }}
QLabel {{ background: transparent; }}
QCheckBox, QRadioButton {{ background: transparent; spacing: 9px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 2px solid #4a5570; background: {PANEL_2}; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url(@CHECK@); }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 9px; border: 2px solid #4a5570; background: {PANEL_2}; }}
QRadioButton::indicator:checked {{ border-color: {ACCENT}; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5,
        fx:0.5, fy:0.5, stop:0 {ACCENT}, stop:0.5 {ACCENT}, stop:0.62 {PANEL_2}, stop:1 {PANEL_2}); }}
QListView, QListWidget, QTableWidget, QTreeView {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px;
        padding: 4px; }}
QListView::item, QListWidget::item {{ border-radius: 7px; padding: 6px 8px; }}
QListView::item:selected, QListWidget::item:selected {{ background: {PANEL_2}; color: white; }}
QListView::item:hover, QListWidget::item:hover {{ background: #1a2131; }}
QHeaderView::section {{ background: {PANEL_2}; color: {MUTED}; border: none; padding: 6px; }}
QTableWidget {{ gridline-color: {LINE}; }}
QGroupBox {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 12px; margin-top: 18px; padding: 14px 14px 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color: {TEXT}; font-weight: 700; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2c3548; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4560; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2c3548; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: {BG}; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; color: {MUTED}; }}
QStatusBar QLabel {{ background: transparent; color: {MUTED}; padding: 0 6px; }}
QProgressBar {{ background: {PANEL_2}; border: none; border-radius: 3px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 4px; background: {LINE}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: white; }}
QFrame#PlayerBar {{ background: {PANEL}; border-top: 1px solid {LINE}; }}
QFrame#Card {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 14px; }}
QDialog {{ background: {BG}; }}
QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 10px; top: -1px; background: {PANEL}; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 16px; border: none; }}
QTabBar::tab:selected {{ color: white; border-bottom: 2px solid {ACCENT}; }}
QMenu {{ background: {PANEL_2}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT}; }}
"""


def _check_png() -> str:
    """Onay işareti (QSS 'image' için dosya gerekir); önbellek klasörüne bir kez çizilir."""
    from .. import paths
    path = paths.cache_dir() / "check-v1.png"
    if not path.exists():
        pm = QPixmap(48, 48)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtGui import QPen
        pen = QPen(QColor("white"), 7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF([QPointF(11, 25), QPointF(20, 34), QPointF(37, 14)]))
        p.end()
        pm.save(str(path), "PNG")
    return path.as_posix()


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in ((QPalette.Window, BG), (QPalette.Base, PANEL), (QPalette.AlternateBase, PANEL_2),
                        (QPalette.Text, TEXT), (QPalette.WindowText, TEXT), (QPalette.Button, PANEL_2),
                        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT), (QPalette.HighlightedText, "#ffffff"),
                        (QPalette.ToolTipBase, PANEL_2), (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, MUTED)):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    font = QFont("Segoe UI" if app.platformName() == "windows" else app.font().family())
    font.setPointSizeF(10.5)
    app.setFont(font)
    app.setStyleSheet(QSS.replace("@CHECK@", _check_png()))


def draw_logo(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    grad = QLinearGradient(r.topLeft(), r.bottomRight())
    grad.setColorAt(0, QColor(ACCENT))
    grad.setColorAt(1, QColor(ACCENT_2))
    path = QPainterPath()
    path.addRoundedRect(r, size * 0.22, size * 0.22)
    p.fillPath(path, grad)
    tri = QPolygonF([QPointF(size * 0.40, size * 0.30), QPointF(size * 0.40, size * 0.70), QPointF(size * 0.72, size * 0.50)])
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("white"))
    p.drawPolygon(tri)
    p.setBrush(QColor(NVIDIA))
    p.drawEllipse(QRectF(size * 0.70, size * 0.12, size * 0.18, size * 0.18))
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(draw_logo(s))
    return icon
