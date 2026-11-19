"""Oynatıcı paneli: mpv'nin gömüldüğü yerel pencere + bekleme ekranı + alt denetim çubuğu."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QStackedWidget,
                               QVBoxLayout, QWidget)

from . import theme


# Videonun üstündeki tuşlar → mpv input.conf'taki eylem adları (aynı `_on_key` yolu). Ctrl/Alt'li kısayollar
# QShortcut'larda kalır.
_KEYS = {
    Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right",
    Qt.Key_PageUp: "pgup", Qt.Key_PageDown: "pgdn", Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
    Qt.Key_Escape: "esc", Qt.Key_Backspace: "last", Qt.Key_F11: "fullscreen", Qt.Key_Home: "home",
    Qt.Key_Space: "pause", Qt.Key_MediaPlay: "pause", Qt.Key_MediaPause: "pause", Qt.Key_MediaTogglePlayPause: "pause",
    Qt.Key_MediaNext: "next", Qt.Key_MediaPrevious: "prev", Qt.Key_MediaStop: "stop",
    Qt.Key_ChannelUp: "ch_next", Qt.Key_ChannelDown: "ch_prev",
}
_LETTERS = {"f": "fullscreen", "k": "pause", "p": "pause", "g": "goto", "t": "theater", "i": "info", "e": "epg",
            "l": "live", "j": "j", "q": "stop", "m": "mute", "a": "audio", "v": "subvis"}
_SHIFT_LETTERS = {"J": "back10", "L": "fwd10", "K": "pause", "Q": "stop", "F": "fullscreen"}


def key_action(key: int, text: str, mods=Qt.NoModifier) -> tuple[str, list] | None:
    """Qt tuşu → (eylem, argümanlar). Videonun penceresi odaktayken tuşlar mpv'ye değil uygulamaya gelir."""
    if mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
        return None
    if Qt.Key_0 <= key <= Qt.Key_9:
        return "digit", [str(key - Qt.Key_0)]
    if key in _KEYS:
        return _KEYS[key], []
    t = text or ""
    if len(t) == 1:
        if t in _SHIFT_LETTERS:
            return _SHIFT_LETTERS[t], []
        if t.lower() in _LETTERS and (t.islower() or not (mods & Qt.ShiftModifier)):
            return _LETTERS[t.lower()], []
    return None


class MpvHost(QWidget):
    """mpv'nin `wid` ile içine çizdiği yerel (native) pencere. Asla başka üst öğeye taşınmaz.

    Windows'ta mpv'nin kendi alt penceresi devre dışı bırakılır (`MainWindow._capture_video_input`): fare ve klavye
    doğrudan buraya gelir — tık, çift tık, tekerlek ve tuşlar Qt olayı olarak işlenir (mpv'nin iletmesine bağlı değil).
    Oynarken imleç fare durunca gizlenir."""
    clicked = Signal(float, float)           # x, genişlik
    double_clicked = Signal(float, float)
    wheel_steps = Signal(int)                # +1 yukarı (ileri), −1 aşağı (geri)
    middle_clicked = Signal()
    key_action = Signal(str, list)

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
        self.autohide = False                # oynarken imleci gizle
        self._press = None
        self._wheel = 0
        self._hide_timer = QTimer(self, singleShot=True, interval=1600, timeout=self._hide_cursor)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("black"))

    def native_id(self) -> int:
        return int(self.winId())

    # ---------------------------------------------------------------- fare / klavye
    def _hide_cursor(self) -> None:
        if self.autohide and self.underMouse():
            self.setCursor(Qt.BlankCursor)

    def _show_cursor(self) -> None:
        if self.cursor().shape() == Qt.BlankCursor:
            self.unsetCursor()
        if self.autohide:
            self._hide_timer.start()

    def mouseMoveEvent(self, event) -> None:
        self._show_cursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hide_timer.stop()
        self.unsetCursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._show_cursor()
        if event.button() == Qt.LeftButton:
            self._press = event.position()
            self.setFocus(Qt.MouseFocusReason)
        elif event.button() == Qt.MiddleButton:
            self.middle_clicked.emit()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        press, self._press = self._press, None
        if event.button() == Qt.LeftButton and press is not None:
            d = event.position() - press
            if abs(d.x()) + abs(d.y()) <= 8:             # sürükleme değil
                self.clicked.emit(float(event.position().x()), float(self.width()))
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press = None
            self.double_clicked.emit(float(event.position().x()), float(self.width()))
        event.accept()

    def wheelEvent(self, event) -> None:
        self._show_cursor()
        self._wheel += event.angleDelta().y()
        steps = int(self._wheel / 120)
        if steps:
            self._wheel -= steps * 120
            self.wheel_steps.emit(steps)
        event.accept()

    def keyPressEvent(self, event) -> None:
        act = key_action(event.key(), event.text(), event.modifiers())
        if act is None:
            super().keyPressEvent(event)
            return
        self.key_action.emit(act[0], act[1])
        event.accept()


class SeekBar(QWidget):
    """YouTube gibi ilerleme çubuğu: tıklanan yere atlar, sürüklerken konum ve süre gösterilir, fare üstündeyken
    kalınlaşır; açık renkli kısım inmiş (önbellekteki) bölüm. Değer 0..10000 (QSlider ile aynı arayüz)."""
    sliderPressed = Signal()
    sliderReleased = Signal()
    sliderMoved = Signal(int)
    MAX = 10000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._buffered = 0.0
        self._hover_x: float | None = None
        self._down = False
        self.duration = 0.0
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)       # ← → tuşları videoya gitsin
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(26)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # QSlider uyumlu
    def value(self) -> int:
        return self._value

    def setValue(self, v: int) -> None:
        v = max(0, min(self.MAX, int(v)))
        if v != self._value:
            self._value = v
            self.update()

    def setSliderPosition(self, v: int) -> None:
        self.setValue(v)

    def isSliderDown(self) -> bool:
        return self._down

    def setBuffered(self, frac: float) -> None:
        frac = max(0.0, min(1.0, float(frac or 0)))
        if abs(frac - self._buffered) > 0.001:
            self._buffered = frac
            self.update()

    def _frac_at(self, x: float) -> float:
        m = 8.0
        return max(0.0, min(1.0, (x - m) / max(1.0, self.width() - 2 * m)))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._down = True
        self.sliderPressed.emit()
        self.setValue(round(self._frac_at(event.position().x()) * self.MAX))
        self.sliderMoved.emit(self._value)

    def mouseMoveEvent(self, event) -> None:
        self._hover_x = event.position().x()
        if self._down:
            self.setValue(round(self._frac_at(self._hover_x) * self.MAX))
            self.sliderMoved.emit(self._value)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._down:
            self._down = False
            self.setValue(round(self._frac_at(event.position().x()) * self.MAX))
            self.sliderReleased.emit()
            self.update()

    def leaveEvent(self, event) -> None:
        self._hover_x = None
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = 8.0
        w = max(1.0, self.width() - 2 * m)
        active = self._down or self._hover_x is not None
        th = 6.0 if active else 4.0
        y = self.height() - 9.0
        track = QRectF(m, y - th / 2, w, th)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 46))
        p.drawRoundedRect(track, th / 2, th / 2)
        frac = self._value / self.MAX
        if self._buffered > 0:
            p.setBrush(QColor(255, 255, 255, 80))
            p.drawRoundedRect(QRectF(m, track.top(), w * max(frac, self._buffered), th), th / 2, th / 2)
        if self._hover_x is not None and not self._down:
            hx = self._frac_at(self._hover_x)
            p.setBrush(QColor(255, 255, 255, 60))
            p.drawRoundedRect(QRectF(m, track.top(), w * hx, th), th / 2, th / 2)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(m, track.top(), w * frac, th), th / 2, th / 2)
        if active:
            r = 7.0
            p.setBrush(QColor(theme.ACCENT))
            p.drawEllipse(QPointF(m + w * frac, y), r, r)
        # fare üstündeyken o noktanın dakikası (çubuğun üstünde küçük etiket)
        if self._hover_x is not None and self.duration > 0:
            f = self._frac_at(self._hover_x) if not self._down else frac
            text = _clock(f * self.duration)
            font = QFont(self.font())
            font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85))
            font.setBold(True)
            p.setFont(font)
            tw = p.fontMetrics().horizontalAdvance(text) + 12
            th2 = p.fontMetrics().height() + 2
            cx = min(max(m + w * f, tw / 2), self.width() - tw / 2)
            box = QRectF(cx - tw / 2, max(0.0, y - th - th2 - 2), tw, th2)
            path = QPainterPath()
            path.addRoundedRect(box, 4, 4)
            p.fillPath(path, QColor(0, 0, 0, 200))
            p.setPen(QColor("white"))
            p.drawText(box, Qt.AlignCenter, text)


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
    record_clicked = Signal()
    goto_clicked = Signal()
    volume_step = Signal(int)        # mini oynatıcı: ses ±
    pip_clicked = Signal()
    pip_pin_toggled = Signal(bool)   # 📌 mini oynatıcıyı sabitle

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
        bl.setContentsMargins(10, 4, 10, 6)
        bl.setSpacing(2)
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
        # uzun etiketler (başlık, iyileştirme) dar pencerede kısalabilsin: pencerenin en küçük genişliğini büyütmesin
        for lab in (self.title, self.vsr_badge, self.info_badge):
            lab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)   # doğal boyut; yer yoksa küçülür
            lab.setMinimumWidth(40)
        self.title.setMinimumWidth(110)
        self.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.subtitle.setMinimumWidth(0)
        self.vsr_badge.setMaximumWidth(560)
        self._top = top
        bl.addLayout(top)
        # ilerleme çubuğu (film/dizi/dosya; canlıda zaman kaydırma tamponu)
        seek_row = QHBoxLayout()
        self.pos_label = QLabel("0:00")
        self.pos_label.setObjectName("Muted")
        self.seek = SeekBar()
        self.seek.setToolTip("Tıklayın ya da sürükleyin: istediğiniz yere atlayın")
        self.seek.setMinimumHeight(24)
        self.dur_label = QLabel("0:00")
        self.dur_label.setObjectName("Muted")
        self._duration = 0.0
        self._seeking = False
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._seek_release)
        self.seek.sliderMoved.connect(lambda v: self.pos_label.setText(_clock(v / 10000 * self._duration)))
        seek_row.addWidget(self.pos_label)
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.dur_label)
        self.btn_goto = QPushButton("⏱ Git")
        self.btn_goto.setObjectName("Flat")
        self.btn_goto.setCursor(Qt.PointingHandCursor)
        self.btn_goto.setToolTip("İstediğiniz dakikaya gidin (G ya da Ctrl+J): 45 = 45. dakika, 1:05:00 = 1 saat 5 dakika")
        self.btn_goto.clicked.connect(self.goto_clicked.emit)
        seek_row.addWidget(self.btn_goto)
        self.seek_box = QWidget()
        self.seek_box.setLayout(seek_row)
        seek_row.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.seek_box)
        row = QHBoxLayout()
        row.setSpacing(6)

        def btn(text, tip, sig, obj="Flat", where=None):
            b = QPushButton(text)
            b.setObjectName(obj)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(sig.emit)
            (where if where is not None else row).addWidget(b)
            return b

        self.btn_prev = btn("⏮", "Önceki kanal / bölüm (Yukarı ok)", self.prev_clicked)
        self.btn_pause = btn("⏯", "Duraklat / sürdür (Boşluk)", self.pause_clicked)
        self.btn_next = btn("⏭", "Sonraki kanal / bölüm (Aşağı ok)", self.next_clicked)
        self.btn_stop = btn("⏹", "Durdur", self.stop_clicked)
        self.btn_rec = btn("⏺", "Bu yayını kaydet (Ctrl+R) — yeniden kodlamadan, kayıpsız", self.record_clicked)
        self.btn_live = btn("⦿ Canlı", "Zaman kaydırmadan çık, canlı yayına atla (L)", self.live_clicked)
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
        self.vol.setFixedWidth(90)
        self.vol.setToolTip("Ses (fare tekerleği)")
        self.vol.valueChanged.connect(self.volume_changed.emit)
        # ses ve pencere düğmeleri başlık satırının sağında (alt satır dar pencereye sığsın)
        top = self._top
        top.addSpacing(8)
        top.addWidget(QLabel("🔊"))
        top.addWidget(self.vol)
        self.btn_external = btn("↗", "Ayrı mpv penceresinde aç (aynı RTX ayarlarıyla)", self.external_clicked, where=top)
        self.btn_pip = btn("⧉", "Resim içinde resim: her zaman üstte küçük pencere (Ctrl+M)", self.pip_clicked,
                           where=top)
        self.btn_theater = btn("▭", "Sinema modu: listeleri gizle (T)", self.theater_clicked, where=top)
        self.btn_fs = btn("⛶", "Tam ekran (F / çift tık)", self.fullscreen_clicked, where=top)
        bl.addLayout(row)
        lay.addWidget(self.bar)
        # mini oynatıcı (resim içinde resim) denetim şeridi: yalnız o kipte görünür, Qt düğmeleri (her zaman çalışır)
        self.pip_bar = QFrame()
        self.pip_bar.setObjectName("PlayerBar")
        pl = QHBoxLayout(self.pip_bar)
        pl.setContentsMargins(6, 3, 6, 3)
        pl.setSpacing(2)

        def pbtn(text, tip, fn):
            b = QPushButton(text)
            b.setObjectName("Flat")
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False: fn())
            pl.addWidget(b)
            return b

        self.pip_back = pbtn("⏪ 10", "10 saniye geri", lambda: self.seek_by.emit(-10.0))
        self.pip_pause = pbtn("⏯", "Duraklat / sürdür", self.pause_clicked.emit)
        self.pip_fwd = pbtn("10 ⏩", "10 saniye ileri", lambda: self.seek_by.emit(10.0))
        pl.addStretch(1)
        self.pip_vol_down = pbtn("🔉", "Sesi kıs", lambda: self.volume_step.emit(-10))
        self.pip_vol_label = QLabel("")
        self.pip_vol_label.setObjectName("Muted")
        pl.addWidget(self.pip_vol_label)
        self.pip_vol_up = pbtn("🔊", "Sesi aç", lambda: self.volume_step.emit(10))
        self.pip_pin = pbtn("📌", "Sabitle: hep burada ve en önde kalsın (oyun oynarken de)", lambda: self.pip_pin_toggled.emit(self.pip_pin.isChecked()))
        self.pip_pin.setCheckable(True)
        self.pip_expand = pbtn("⤢", "Normal pencereye dön (Esc)", self.pip_clicked.emit)
        self.pip_bar.hide()
        lay.addWidget(self.pip_bar)
        self.set_idle()

    # ------------------------------------------------------------------ durum
    def show_video(self) -> None:
        self.stack.setCurrentWidget(self.host)

    def show_loading(self, title: str, text: str = "") -> None:
        """Kanal geçişinde eski kanalın son karesi ekranda kalmasın: yeni yayının ilk karesi gelene kadar bekleme ekranı."""
        self.placeholder.set_message(f"Açılıyor: {title}" if title else "Açılıyor…", text or "Yayın bağlanıyor…")
        self.stack.setCurrentWidget(self.placeholder)

    @property
    def loading(self) -> bool:
        return self.stack.currentWidget() is self.placeholder

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

    def set_now_playing(self, title: str, subtitle: str, live: bool, replay: bool = False) -> None:
        """replay: geri izleme (tekrar) — canlı olmadığı açıkça görünsün, "Canlıya dön" ile canlı kanala geçilsin."""
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.live_badge.setText("⟲ TEKRAR" if replay else "● CANLI")
        self.live_badge.setToolTip("Bu bir tekrar (geri izleme); canlı yayın değil. Canlıya dönmek için: ⦿ Canlıya dön"
                                   if replay else "")
        self.live_badge.setVisible(live or replay)
        self.btn_live.setText("⦿ Canlıya dön" if replay else "⦿ Canlı")
        self.btn_live.setVisible(live or replay)

    def _seek_release(self) -> None:
        self._seeking = False
        if self._duration > 0:
            self.seek_to.emit(self.seek.value() / 10000 * self._duration)

    def set_status(self, st: dict) -> None:
        dur = st.get("duration") or 0
        pos = st.get("pos") or 0
        seekable = bool(dur) and st.get("kind") not in ("live", "image")
        self.seek_box.setVisible(seekable)
        if seekable and not self._seeking:
            self._duration = float(dur)
            self.seek.duration = self._duration
            self.seek.setValue(int(min(1.0, pos / dur) * 10000))
            cache = st.get("cache")
            end = st.get("cache_end") if st.get("cache_end") else (pos + cache if isinstance(cache, (int, float)) else 0)
            self.seek.setBuffered(min(1.0, float(end or 0) / dur))
            self.pos_label.setText(_clock(pos))
            self.dur_label.setText(_clock(dur))
        plan = st.get("vsr") or {}
        enh = st.get("enhance") or []
        if enh:
            # her zaman görünür: canlı yayında da hangi iyileştirmelerin çalıştığı
            self.vsr_badge.setText("✦ " + " · ".join(_short(e) for e in enh))
            self.vsr_badge.setToolTip("Görüntü iyileştirme açık (canlı yayın dahil her kaynakta):\n• "
                                      + "\n• ".join(enh) + ("\n" + plan["reason"] if plan.get("reason") else ""))
            self.vsr_badge.show()
        else:
            self.vsr_badge.hide()
        # çözünürlük/fps durum çubuğunda; burada yalnız canlı yayına özgü bilgi (gecikme, arabellek)
        parts = []
        if st.get("kind") == "live" and st.get("cache") is not None:
            if st.get("user_paused"):
                parts.append(f"zaman kaydırma −{st['cache']:.0f} sn")
            else:
                parts.append(f"gecikme {st['cache']:.1f} sn" + (" ⇢" if st.get("boost") else ""))
        if st.get("buffering"):
            parts.append("arabelleğe alınıyor…")
        self.info_badge.setText("  ·  ".join(parts))
        self.info_badge.setToolTip("\n".join(parts))
        self.info_badge.setVisible(bool(parts))
        if st.get("volume") is not None:
            self.pip_vol_label.setText(f"%{int(st['volume'])}")
        if st.get("volume") is not None and not self.vol.isSliderDown():
            self.vol.blockSignals(True)
            self.vol.setValue(int(st["volume"]))
            self.vol.blockSignals(False)


    def set_recording(self, rec_text: str | None) -> None:
        """Kayıt düğmesi: kayıt sürüyorsa kırmızı ve süre."""
        if rec_text:
            self.btn_rec.setText(f"⏺ {rec_text}")
            self.btn_rec.setStyleSheet("color: #ff5c7a; font-weight: 600;")
            self.btn_rec.setToolTip("Kaydı durdur (Ctrl+R)")
        else:
            self.btn_rec.setText("⏺")
            self.btn_rec.setStyleSheet("")
            self.btn_rec.setToolTip("Bu yayını kaydet (Ctrl+R) — yeniden kodlamadan, kayıpsız")


_SHORT = {"Gürültü azaltma": "Gürültü↓", "Keskinlik": "Keskin", "Bant yumuşatma": "Deband",
          "Lossless Scaling kare üretimi": "LSFG", "AMD FSR büyütme": "AMD FSR",
          "Yüksek kaliteli büyütme": "HQ büyütme"}


def _short(label: str) -> str:
    """Çubuktaki iyileştirme etiketinin kısa hali (tam liste ipucunda)."""
    if label.startswith("Yapay zekâ büyütme (") and label.endswith(")"):
        return label[len("Yapay zekâ büyütme ("):-1]
    return _SHORT.get(label, label)


def _clock(sec) -> str:
    s = int(sec or 0)
    h, rem = divmod(s, 3600)
    m, x = divmod(rem, 60)
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}"
