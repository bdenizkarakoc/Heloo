"""Çoklu görüntü: aynı anda 2 ya da 4 kanal (TiviMate "Multi-view" / OTT Navigator gibi).

Her hücrede ayrı bir mpv (kendi yerel penceresinde). Ses yalnız etkin hücrede; hücreye tıklayınca etkin olur, çift
tıklayınca o hücre tek başına büyür (yeniden çift tık: geri). Hücreler hafif ayarlarla oynar (RTX VSR / yapay zekâ
büyütme / gürültü azaltma kapalı, keskinlik açık): dört akışı birden 4K'ya büyütmek ekran kartını boğar.
Sağlayıcının eşzamanlı bağlantı sınırı aşılırsa uyarılır (Xtream hesap bilgisi).
"""
from __future__ import annotations

import copy
import logging

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..player.engine import EngineError, MpvEngine
from . import theme
from .player_panel import MpvHost

log = logging.getLogger("helootv.ui")


def cell_settings(settings: dict) -> dict:
    """Çoklu görüntü hücresi için hafif ayarlar (dört akış birden akıcı oynasın)."""
    s = copy.deepcopy(settings)
    s["video"].update(rtx_vsr=False, rtx_hdr=False, ai_upscaler="off", hq_scaling=False, smooth_vod=False,
                      amd_fsr=False)
    s["picture"]["denoise"] = "off"
    return s


class _Bridge(QObject):
    event = Signal(int, str, dict)


class Cell(QFrame):
    def __init__(self, index: int, items: list, numbers: dict | None = None, parent=None):
        super().__init__(parent)
        self.index = index
        self.item = None
        self.engine: MpvEngine | None = None
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        head = QHBoxLayout()
        self.sound = QLabel("🔇")
        self.sound.setToolTip("Ses bu hücrede değil — hücreye tıklayın")
        self.pick = QComboBox()
        self.pick.setEditable(True)
        self.pick.setInsertPolicy(QComboBox.NoInsert)
        self.pick.lineEdit().setPlaceholderText("Kanal seçin ya da yazın…")
        self.pick.addItem("— boş —", None)
        numbers = numbers or {}
        for it in items:
            n = numbers.get(it.key)
            self.pick.addItem(f"{n}  {it.name}" if n else it.name, it)
        self.pick.completer().setFilterMode(Qt.MatchContains)
        self.pick.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self.state = QLabel("")
        self.state.setObjectName("Muted")
        head.addWidget(self.sound)
        head.addWidget(self.pick, 1)
        head.addWidget(self.state)
        lay.addLayout(head)
        self.host = MpvHost()
        self.host.setMinimumSize(200, 112)
        lay.addWidget(self.host, 1)

    def set_active(self, on: bool) -> None:
        self.sound.setText("🔊" if on else "🔇")
        self.setStyleSheet(f"QFrame#Card {{ border: 2px solid {theme.ACCENT if on else theme.LINE}; }}")


class MultiViewWindow(QDialog):
    open_in_main = Signal(object)          # kapatırken etkin hücrenin kanalı ana oynatıcıda sürsün

    def __init__(self, settings: dict, items: list, make_request, max_connections: int = 0,
                 headless: bool = False, extra_options: dict | None = None, numbers: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Çoklu görüntü")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1280, 760)
        self.settings = settings
        self.items = [it for it in items if it is not None][:2000]
        self.make_request = make_request
        self.max_connections = int(max_connections or 0)
        self.headless = headless
        self.extra_options = extra_options or {}
        self.active = 0
        self.solo: int | None = None
        self.bridge = _Bridge()
        self.bridge.event.connect(self._on_event)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        title = QLabel("Çoklu görüntü")
        title.setObjectName("H2")
        top.addWidget(title)
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color: {theme.WARN};")
        top.addWidget(self.warn, 1)
        self.layout_btns = {}
        for n, text in ((2, "▯▯  2 kanal"), (4, "▦  4 kanal")):
            b = QPushButton(text)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, n=n: self.set_layout(n))
            top.addWidget(b)
            self.layout_btns[n] = b
        lay.addLayout(top)
        hint = QLabel("Tıklayın: sesi o hücreye ver · Çift tık: büyüt / geri · Kapatınca etkin kanal ana oynatıcıda sürer")
        hint.setObjectName("Muted")
        lay.addWidget(hint)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        lay.addWidget(self.grid_host, 1)
        self.cells = [Cell(i, self.items, numbers) for i in range(4)]
        for c in self.cells:
            c.pick.activated.connect(lambda _i, c=c: self._picked(c))
        self.count = 0
        self.set_layout(4 if len(self.items) >= 4 else 2)

    # ------------------------------------------------------------------ yerleşim
    def set_layout(self, n: int) -> None:
        self.count = n
        for k, b in self.layout_btns.items():
            b.setChecked(k == n)
        for c in self.cells:
            self.grid.removeWidget(c)
            c.hide()
        for i, c in enumerate(self.cells):
            if i < n:
                self.grid.addWidget(c, i // 2 if n == 4 else 0, i % 2)
                c.show()
            elif c.engine:                # gizlenen hücrenin yayını kapanır (bağlantı boşalsın)
                self._stop_cell(c)
        self.solo = None
        if self.active >= n:
            self.set_active(0)
        else:
            self.set_active(self.active)
        self._check_limit()

    def set_solo(self, index: int | None) -> None:
        self.solo = index
        for i, c in enumerate(self.cells[:self.count]):
            c.setVisible(index is None or i == index)

    # ------------------------------------------------------------------ oynatma
    def assign(self, index: int, item) -> None:
        c = self.cells[index]
        i = c.pick.findData(item) if item is not None else 0
        c.pick.setCurrentIndex(max(0, i))
        self._play(c, item)

    def _picked(self, c: Cell) -> None:
        self._play(c, c.pick.currentData())
        self.set_active(c.index)

    def _play(self, c: Cell, item) -> None:
        c.item = item
        if item is None:
            self._stop_cell(c)
            self._check_limit()
            return
        if c.engine is None:
            wid = None if self.headless else c.host.native_id()
            eng = MpvEngine(cell_settings(self.settings), wid=wid, headless=self.headless,
                            on_event=lambda n, d, i=c.index: self.bridge.event.emit(i, n, d),
                            extra_options=self.extra_options)
            try:
                eng.start()
            except EngineError as e:
                c.state.setText(f"⚠ {e}")
                return
            c.engine = eng
        c.state.setText("açılıyor…")
        c.engine.play(self.make_request(item))
        c.engine._set("mute", "no" if c.index == self.active else "yes")
        self._check_limit()

    def _stop_cell(self, c: Cell) -> None:
        if c.engine:
            c.engine.shutdown()
            c.engine = None
        c.item = None
        c.state.setText("")

    def set_active(self, index: int) -> None:
        self.active = index
        for c in self.cells:
            c.set_active(c.index == index)
            if c.engine:
                c.engine._set("mute", "no" if c.index == index else "yes")

    def _check_limit(self) -> None:
        used = sum(1 for c in self.cells[:self.count] if c.item is not None)
        if self.max_connections and used > self.max_connections:
            self.warn.setText(f"⚠ Hesabınız aynı anda {self.max_connections} bağlantıya izin veriyor; "
                              f"{used} kanal açık. Fazlası açılmayabilir.")
        else:
            self.warn.setText("")

    def _on_event(self, index: int, name: str, data: dict) -> None:
        c = self.cells[index]
        if name in ("file-loaded", "playing"):
            c.state.setText("")
        elif name == "reconnecting":
            c.state.setText("yeniden bağlanıyor…")
        elif name == "error":
            c.state.setText("⚠ açılamadı")
            c.state.setToolTip(data.get("message") or "")
        elif name == "key":
            action = data.get("action")
            if action == "click":
                self.set_active(index)
            elif action == "fullscreen":
                self.set_active(index)
                self.set_solo(None if self.solo == index else index)
            elif action == "esc" and self.solo is not None:
                self.set_solo(None)

    def tick(self) -> None:
        for c in self.cells:
            if c.engine and c.item is not None:
                c.engine.tick()        # bekçi + kare atlama koruması hücrelerde de çalışsın

    def shutdown(self) -> None:
        for c in self.cells:
            self._stop_cell(c)

    def closeEvent(self, event) -> None:
        active = self.cells[self.active].item if self.active < len(self.cells) else None
        self.shutdown()
        if active is not None:
            self.open_in_main.emit(active)
        super().closeEvent(event)
