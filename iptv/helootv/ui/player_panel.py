"""Oynatıcı paneli: mpv'nin gömüldüğü yerel pencere + bekleme ekranı + alt denetim çubuğu."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QStackedWidget,
                               QVBoxLayout, QWidget)

from . import theme


class MpvHost(QWidget):
    """mpv'nin `wid` ile içine çizdiği yerel (native) pencere. Asla başka üst öğeye taşınmaz."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WA_NativeWindow)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("black"))

    def native_id(self) -> int:
        return int(self.winId())


class Placeholder(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        logo = QLabel()
        logo.setPixmap(theme.draw_logo(84))
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("background: transparent;")
        self.title = QLabel("Heloo TV")
        self.title.setObjectName("H1")
        self.title.setAlignment(Qt.AlignCenter)
        self.text = QLabel("Bir kanal, film ya da bölüm seçin.\nRTX Video Super Resolution ile 4K'ya yükseltilir.")
        self.text.setObjectName("Muted")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setWordWrap(True)
        for w in (logo, self.title, self.text):
            lay.addWidget(w)
            w.setStyleSheet("background: transparent;")
        self.setObjectName("Placeholder")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#Placeholder { background: #07090d; }")

    def set_message(self, title: str, text: str) -> None:
        self.title.setText(title)
        self.text.setText(text)


class PlayerPanel(QWidget):
    pause_clicked = Signal()
    stop_clicked = Signal()
    live_clicked = Signal()
    theater_clicked = Signal()
    fullscreen_clicked = Signal()
    external_clicked = Signal()
    volume_changed = Signal(int)
    prev_clicked = Signal()
    next_clicked = Signal()
    seek_to = Signal(float)          # mutlak saniye
    seek_by = Signal(float)          # göreli saniye

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QStackedWidget()
        self.placeholder = Placeholder()
        self.host = MpvHost()
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(self.host)
        lay.addWidget(self.stack, 1)

        self.bar = QFrame()
        self.bar.setObjectName("PlayerBar")
        bl = QVBoxLayout(self.bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(6)
        top = QHBoxLayout()
        self.title = QLabel("—")
        self.title.setObjectName("H2")
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("Muted")
        top.addWidget(self.title, 0)
        top.addWidget(self.subtitle, 1)
        self.live_badge = QLabel("● CANLI")
        self.live_badge.setObjectName("BadgeLive")
        self.vsr_badge = QLabel("")
        self.vsr_badge.setObjectName("BadgeNv")
        self.info_badge = QLabel("")
        self.info_badge.setObjectName("Badge")
        for b in (self.live_badge, self.vsr_badge, self.info_badge):
            b.hide()
            top.addWidget(b)
        bl.addLayout(top)
        # ilerleme çubuğu (film/dizi/dosya; canlıda zaman kaydırma tamponu)
        seek_row = QHBoxLayout()
        self.pos_label = QLabel("0:00")
        self.pos_label.setObjectName("Muted")
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 10000)
        self.seek.setToolTip("Sürükleyin ya da tıklayın: istediğiniz yere atlayın")
        self.seek.setPageStep(100)
        self.dur_label = QLabel("0:00")
        self.dur_label.setObjectName("Muted")
        self._duration = 0.0
        self._seeking = False
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._seek_release)
        self.seek.actionTriggered.connect(self._seek_action)
        self.seek.sliderMoved.connect(lambda v: self.pos_label.setText(_clock(v / 10000 * self._duration)))
        seek_row.addWidget(self.pos_label)
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.dur_label)
        self.seek_box = QWidget()
        self.seek_box.setLayout(seek_row)
        seek_row.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.seek_box)
        row = QHBoxLayout()
        row.setSpacing(6)

        def btn(text, tip, sig, obj="Flat"):
            b = QPushButton(text)
            b.setObjectName(obj)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(sig.emit)
            row.addWidget(b)
            return b

        self.btn_prev = btn("⏮", "Önceki kanal / bölüm (Yukarı ok)", self.prev_clicked)
        self.btn_pause = btn("⏯", "Duraklat / sürdür (Boşluk)", self.pause_clicked)
        self.btn_next = btn("⏭", "Sonraki kanal / bölüm (Aşağı ok)", self.next_clicked)
        for text, delta, tip in (("−1 dk", -60, "1 dakika geri"), ("−10", -10, "10 saniye geri (Sol ok)"),
                                 ("+10", 10, "10 saniye ileri (Sağ ok)"), ("+1 dk", 60, "1 dakika ileri")):
            b = QPushButton(text)
            b.setObjectName("Flat")
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, d=delta: self.seek_by.emit(float(d)))
            row.addWidget(b)
        self.btn_stop = btn("⏹", "Durdur", self.stop_clicked)
        self.btn_live = btn("⦿ Canlıya dön", "Zaman kaydırmadan çık, canlı yayına atla (L)", self.live_clicked)
        row.addStretch(1)
        # Ses izi / Altyazı / Görüntü menüleri (içerikleri ana pencere doldurur)
        from PySide6.QtWidgets import QMenu, QToolButton
        self.menus = {}
        for key, text, tip in (("audio", "🔈 Ses", "Ses izi (dublaj / özgün dil)"),
                               ("sub", "💬 Altyazı", "Altyazı seç, dosyadan ekle, internetten bul, yapay zekâ ile çıkar"),
                               ("picture", "🎨 Görüntü", "Parlaklık, kontrast, keskinlik, karıncalanma (gürültü) azaltma")):
            tb = QToolButton()
            tb.setText(text)
            tb.setToolTip(tip)
            tb.setPopupMode(QToolButton.InstantPopup)
            tb.setCursor(Qt.PointingHandCursor)
            tb.setStyleSheet("QToolButton { background: transparent; border: none; padding: 6px 8px; }"
                             "QToolButton:hover { color: white; } QToolButton::menu-indicator { image: none; }")
            m = QMenu(tb)
            tb.setMenu(m)
            row.addWidget(tb)
            self.menus[key] = m
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 150)
        self.vol.setFixedWidth(110)
        self.vol.setToolTip("Ses (fare tekerleği)")
        self.vol.valueChanged.connect(self.volume_changed.emit)
        row.addWidget(QLabel("🔊"))
        row.addWidget(self.vol)
        self.btn_external = btn("↗", "Ayrı mpv penceresinde aç (aynı RTX ayarlarıyla)", self.external_clicked)
        self.btn_theater = btn("▭ Sinema", "Sinema modu (T)", self.theater_clicked)
        self.btn_fs = btn("⛶ Tam ekran", "Tam ekran (F / çift tık)", self.fullscreen_clicked)
        bl.addLayout(row)
        lay.addWidget(self.bar)
        self.set_idle()

    # ------------------------------------------------------------------ durum
    def show_video(self) -> None:
        self.stack.setCurrentWidget(self.host)

    def set_idle(self, title: str = "Heloo TV", text: str | None = None) -> None:
        self.stack.setCurrentWidget(self.placeholder)
        if hasattr(self, "seek_box"):
            self.seek_box.hide()
        self.placeholder.set_message(title, text or "Bir kanal, film ya da bölüm seçin.\n"
                                     "RTX Video Super Resolution ile 4K'ya yükseltilir.")
        self.title.setText("—")
        self.subtitle.setText("")
        for b in (self.live_badge, self.vsr_badge, self.info_badge):
            b.hide()
        self.btn_live.hide()

    def set_now_playing(self, title: str, subtitle: str, live: bool) -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.live_badge.setVisible(live)
        self.btn_live.setVisible(live)

    def _seek_release(self) -> None:
        self._seeking = False
        if self._duration > 0:
            self.seek_to.emit(self.seek.value() / 10000 * self._duration)

    def _seek_action(self, action: int) -> None:
        # çubuğa tıklama (sürükleme değil): tıklanan yere atla
        from PySide6.QtWidgets import QAbstractSlider
        if action in (QAbstractSlider.SliderPageStepAdd, QAbstractSlider.SliderPageStepSub) and self._duration > 0:
            from PySide6.QtGui import QCursor
            x = self.seek.mapFromGlobal(QCursor.pos()).x()
            frac = min(1.0, max(0.0, x / max(1, self.seek.width())))
            self.seek.setSliderPosition(int(frac * 10000))
            self.seek_to.emit(frac * self._duration)

    def set_status(self, st: dict) -> None:
        dur = st.get("duration") or 0
        pos = st.get("pos") or 0
        seekable = bool(dur) and st.get("kind") not in ("live", "image")
        self.seek_box.setVisible(seekable)
        if seekable and not self._seeking:
            self._duration = float(dur)
            self.seek.blockSignals(True)
            self.seek.setValue(int(min(1.0, pos / dur) * 10000))
            self.seek.blockSignals(False)
            self.pos_label.setText(_clock(pos))
            self.dur_label.setText(_clock(dur))
        plan = st.get("vsr") or {}
        if st.get("vsr_active") and plan.get("out"):
            self.vsr_badge.setText(f"RTX VSR {st.get('h')}p → {plan['out'][1]}p" + (" · HDR" if plan.get("hdr") else ""))
            self.vsr_badge.setToolTip(plan.get("reason", ""))
            self.vsr_badge.show()
        else:
            self.vsr_badge.hide()
        parts = []
        if st.get("w"):
            parts.append(f"{st['w']}×{st['h']}")
        if st.get("fps"):
            try:
                parts.append(f"{float(st['fps']):.0f} fps")
            except (TypeError, ValueError):
                pass
        if st.get("kind") == "live" and st.get("cache") is not None:
            if st.get("user_paused"):
                parts.append(f"zaman kaydırma −{st['cache']:.0f} sn")
            else:
                parts.append(f"gecikme {st['cache']:.1f} sn" + (" ⇢" if st.get("boost") else ""))
        if st.get("buffering"):
            parts.append("arabelleğe alınıyor…")
        self.info_badge.setText("  ·  ".join(parts))
        self.info_badge.setVisible(bool(parts))
        if st.get("volume") is not None and not self.vol.isSliderDown():
            self.vol.blockSignals(True)
            self.vol.setValue(int(st["volume"]))
            self.vol.blockSignals(False)


def _clock(sec) -> str:
    s = int(sec or 0)
    h, rem = divmod(s, 3600)
    m, x = divmod(rem, 60)
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}"
