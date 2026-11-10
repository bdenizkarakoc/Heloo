"""TV Rehberi (EPG ızgarası): kanallar × saatler, TiviMate'teki gibi.

Geçmiş programda (arşivi olan kanalda) çift tık → geri izle; şu an yayındaki → kanalı aç; gelecektekinde sağ tık →
kaydet / hatırlat. Yüzlerce kanalda hızlı olsun diye çizim tek bir kendi çizen bileşende yapılır; kanal sütunu ve
saat şeridi kaydırmada yerinde kalır.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from . import theme
from .workers import run_task

ROW_H, CH_W, HEAD_H = 50, 190, 30
PX_PER_MIN = 4.0                       # 1 saat = 240 piksel
BEFORE_H, AFTER_H = 3, 24              # şimdiden 3 saat önce … 24 saat sonra


def _hhmm(ts: float) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


class GuideCanvas(QWidget):
    clicked = Signal(object, object)          # (Item, program ya da None)
    activated = Signal(object, object)
    menu_requested = Signal(object, object, QPoint)

    def __init__(self, scroll: QScrollArea, parent=None):
        super().__init__(parent)
        self.scroll = scroll
        self.items: list = []
        self.progs: dict = {}
        self.t0 = 0.0
        self.t1 = 0.0
        self.sel: tuple[int, dict | None] | None = None
        self.marks = lambda item, prog: ""        # ⏺ / 🔔 işareti (ana pencere verir)
        self.playing_key = None
        self.numbers: dict = {}                   # kanal anahtarı → listede gösterilen numara
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------------ veri
    def set_data(self, items: list, progs: dict, t0: float, t1: float) -> None:
        self.items, self.progs, self.t0, self.t1 = items, progs, t0, t1
        w = CH_W + int((t1 - t0) / 60 * PX_PER_MIN)
        self.setFixedSize(QSize(w, HEAD_H + ROW_H * len(items)))
        self.update()

    def x_of(self, ts: float) -> int:
        return CH_W + int((ts - self.t0) / 60 * PX_PER_MIN)

    def ts_of(self, x: int) -> float:
        return self.t0 + (x - CH_W) / PX_PER_MIN * 60

    def progs_of(self, item) -> list:
        return self.progs.get((item.source_id, item.epg_id), []) if item.epg_id else []

    def hit(self, pos: QPoint):
        row = (pos.y() - HEAD_H) // ROW_H
        if pos.y() < HEAD_H or not (0 <= row < len(self.items)):
            return None, None, -1
        item = self.items[row]
        hs = self.scroll.horizontalScrollBar().value()
        if pos.x() < hs + CH_W:
            return item, None, row
        ts = self.ts_of(pos.x())
        prog = next((p for p in self.progs_of(item) if p["start"] <= ts < p["stop"]), None)
        return item, prog, row

    # ------------------------------------------------------------------ çizim
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        vis = ev.rect()
        hs = self.scroll.horizontalScrollBar().value()
        vs = self.scroll.verticalScrollBar().value()
        p.fillRect(vis, QColor(theme.BG))
        now = time.time()
        fm = QFontMetrics(self.font())
        bold = QFont(self.font())
        bold.setBold(True)
        first = max(0, (vis.top() - HEAD_H) // ROW_H)
        last = min(len(self.items), (vis.bottom() - HEAD_H) // ROW_H + 2)
        for r in range(first, last):
            item = self.items[r]
            y = HEAD_H + r * ROW_H
            for prog in self.progs_of(item):
                x0, x1 = max(self.x_of(prog["start"]), CH_W), self.x_of(prog["stop"])
                if x1 < vis.left() or x0 > vis.right():
                    continue
                rect = QRect(x0 + 1, y + 2, max(2, x1 - x0 - 2), ROW_H - 4)
                live = prog["start"] <= now < prog["stop"]
                past = prog["stop"] <= now
                selected = self.sel is not None and self.sel[0] == r and self.sel[1] is prog
                bg = theme.ACCENT if selected else ("#2a2350" if live else (theme.PANEL if past else theme.PANEL_2))
                p.fillRect(rect, QColor(bg))
                p.setPen(QColor(theme.LINE))
                p.drawRect(rect)
                p.setPen(QColor("white" if (live or selected) else (theme.MUTED if past else theme.TEXT)))
                mark = self.marks(item, prog)
                arch = "⟲ " if past and item.archive and prog["start"] >= now - item.archive * 86400 else ""
                text = f"{mark}{arch}{prog['title']}"
                inner = rect.adjusted(8, 4, -6, -4)
                # metin, programın görünen kısmında başlasın (uzun program sola kaydırılmışsa da okunur)
                if inner.left() < hs + CH_W + 6:
                    inner.setLeft(hs + CH_W + 6)
                p.setFont(bold if live else self.font())
                p.drawText(inner, Qt.AlignLeft | Qt.AlignTop, fm.elidedText(text, Qt.ElideRight, max(0, inner.width())))
                p.setFont(self.font())
                p.setPen(QColor(theme.MUTED))
                p.drawText(inner, Qt.AlignLeft | Qt.AlignBottom, f"{_hhmm(prog['start'])}–{_hhmm(prog['stop'])}")
            if not self.progs_of(item):
                p.setPen(QColor(theme.MUTED))
                p.drawText(QRect(hs + CH_W + 10, y, 400, ROW_H), Qt.AlignVCenter, "yayın akışı yok")
            p.setPen(QColor(theme.LINE))
            p.drawLine(vis.left(), y + ROW_H - 1, vis.right(), y + ROW_H - 1)
        # şimdi çizgisi
        xn = self.x_of(now)
        p.setPen(QPen(QColor(theme.DANGER), 2))
        p.drawLine(xn, vs + HEAD_H, xn, vs + self.scroll.viewport().height())
        # yapışkan kanal sütunu
        for r in range(first, last):
            item = self.items[r]
            y = HEAD_H + r * ROW_H
            cell = QRect(hs, y, CH_W, ROW_H)
            p.fillRect(cell, QColor(theme.PANEL))
            p.setPen(QColor(theme.LINE))
            p.drawLine(hs + CH_W - 1, y, hs + CH_W - 1, y + ROW_H)
            p.drawLine(hs, y + ROW_H - 1, hs + CH_W, y + ROW_H - 1)
            playing = self.playing_key == item.key
            p.setPen(QColor(theme.ACCENT_2 if playing else theme.TEXT))
            p.setFont(bold)
            n = self.numbers.get(item.key)
            num = f"{n}  " if n else ""
            p.drawText(cell.adjusted(10, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(("▶ " if playing else "") + num + item.name, Qt.ElideRight, CH_W - 18))
            p.setFont(self.font())
        # yapışkan saat şeridi
        head = QRect(hs, vs, self.scroll.viewport().width(), HEAD_H)
        p.fillRect(head, QColor(theme.PANEL))
        p.setPen(QColor(theme.LINE))
        p.drawLine(head.left(), vs + HEAD_H - 1, head.right(), vs + HEAD_H - 1)
        t = (int(self.t0) // 1800 + 1) * 1800
        while t < self.t1:
            x = self.x_of(t)
            if x > hs + CH_W and not (0 <= xn - x < 64):   # "şimdi" etiketiyle çakışmasın
                p.setPen(QColor(theme.MUTED))
                p.drawLine(x, vs + HEAD_H - 6, x, vs + HEAD_H)
                p.setPen(QColor(theme.TEXT if t % 3600 == 0 else theme.MUTED))
                p.drawText(QRect(x + 4, vs, 80, HEAD_H), Qt.AlignVCenter, _hhmm(t))
            t += 1800
        if hs + CH_W <= xn:
            p.setPen(QColor(theme.DANGER))
            p.drawText(QRect(xn + 4, vs, 70, HEAD_H), Qt.AlignVCenter, f"şimdi {_hhmm(now)}")
        p.fillRect(QRect(hs, vs, CH_W, HEAD_H), QColor(theme.PANEL))
        p.setPen(QColor(theme.MUTED))
        from .pages import _turkish_day
        p.drawText(QRect(hs + 10, vs, CH_W - 10, HEAD_H), Qt.AlignVCenter, _turkish_day(now))
        p.end()

    # ------------------------------------------------------------------ fare
    def mousePressEvent(self, ev) -> None:
        item, prog, row = self.hit(ev.position().toPoint())
        if item is None:
            return
        self.sel = (row, prog)
        self.update()
        self.clicked.emit(item, prog)
        if ev.button() == Qt.RightButton:
            self.menu_requested.emit(item, prog, ev.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, ev) -> None:
        item, prog, _row = self.hit(ev.position().toPoint())
        if item is not None:
            self.activated.emit(item, prog)


class GuideWindow(QDialog):
    play_live = Signal(object)
    catchup = Signal(object, dict)
    record = Signal(object, dict)
    remind = Signal(object, dict)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("TV Rehberi")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1280, 760)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.title = QLabel("TV Rehberi")
        self.title.setObjectName("H2")
        top.addWidget(self.title)
        top.addStretch(1)
        self.hint = QLabel("Çift tık: şimdi → izle, geçmiş → geri izle, gelecek → hatırlat · Sağ tık: kaydet")
        self.hint.setObjectName("Muted")
        top.addWidget(self.hint)
        now_btn = QPushButton("Şimdi")
        now_btn.clicked.connect(self.scroll_to_now)
        top.addWidget(now_btn)
        lay.addLayout(top)
        self.area = QScrollArea()
        self.area.setWidgetResizable(False)
        self.canvas = GuideCanvas(self.area)
        self.area.setWidget(self.canvas)
        self.area.horizontalScrollBar().valueChanged.connect(lambda _v: self.canvas.update())
        self.area.verticalScrollBar().valueChanged.connect(lambda _v: self.canvas.update())
        lay.addWidget(self.area, 1)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setObjectName("Muted")
        self.info.setMinimumHeight(48)
        lay.addWidget(self.info)
        self.canvas.clicked.connect(self._clicked)
        self.canvas.activated.connect(self._activated)
        self.canvas.menu_requested.connect(self._menu)
        self._timer = QTimer(self, interval=60_000, timeout=self.canvas.update)
        self._timer.start()

    def load(self, items: list, title: str = "", numbers: dict | None = None) -> None:
        items = [it for it in items if it is not None][:400]
        self.canvas.numbers = numbers or {}
        self.title.setText(f"TV Rehberi — {title}" if title else "TV Rehberi")
        now = time.time()
        t0 = (int(now) // 1800) * 1800 - BEFORE_H * 3600
        t1 = t0 + (BEFORE_H + AFTER_H) * 3600
        self.info.setText("Yayın akışı yükleniyor…")

        def fetch():
            return self.ctx.store.epg_grid([(it.source_id, it.epg_id) for it in items], t0, t1)

        def done(progs):
            self.canvas.set_data(items, progs, t0, t1)
            n = sum(1 for it in items if progs.get((it.source_id, it.epg_id)))
            self.info.setText(f"{len(items)} kanal, {n} kanalın yayın akışı var. "
                              "⟲ = geri izlenebilir, ⏺ = kayıt zamanlandı, 🔔 = hatırlatıcı.")
            QTimer.singleShot(0, self.scroll_to_now)

        run_task(fetch, on_done=done, on_error=lambda e: self.info.setText(f"Yayın akışı alınamadı: {e}"))

    def scroll_to_now(self) -> None:
        x = self.canvas.x_of(time.time()) - CH_W - 120
        self.area.horizontalScrollBar().setValue(max(0, x))

    def _clicked(self, item, prog) -> None:
        if prog:
            self.info.setText(f"{item.name} · {_hhmm(prog['start'])}–{_hhmm(prog['stop'])} · {prog['title']}\n"
                              f"{(prog.get('desc') or '').strip()[:400]}")
        else:
            self.info.setText(item.name)

    def _activated(self, item, prog) -> None:
        now = time.time()
        if prog and prog["stop"] <= now:
            if item.archive and prog["start"] >= now - item.archive * 86400:
                self.catchup.emit(item, prog)
            else:
                self.info.setText("Bu kanalda geri izleme (arşiv) yok.")
        elif prog and prog["start"] > now:
            self.remind.emit(item, prog)
            self.canvas.update()
        else:
            self.play_live.emit(item)

    def _menu(self, item, prog, gpos) -> None:
        now = time.time()
        m = QMenu(self)
        m.addAction("▶ Kanalı aç", lambda: self.play_live.emit(item))
        if prog:
            if prog["stop"] <= now and item.archive and prog["start"] >= now - item.archive * 86400:
                m.addAction("⟲ Geri izle", lambda: self.catchup.emit(item, prog))
            if prog["stop"] > now:
                m.addAction("⏺ Bu programı kaydet" if prog["start"] > now else "⏺ Şimdi kaydet (bitene kadar)",
                            lambda: (self.record.emit(item, prog), self.canvas.update()))
            if prog["start"] > now:
                m.addAction("🔔 Başlayınca hatırlat", lambda: (self.remind.emit(item, prog), self.canvas.update()))
        m.exec(gpos)
