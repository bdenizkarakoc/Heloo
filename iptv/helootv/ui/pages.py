"""Sayfalar: Canlı TV, Filmler, Diziler, Favoriler + yayın akışı (EPG) paneli."""
from __future__ import annotations

import logging

import time

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFrame, QHBoxLayout,
                               QLabel, QListView, QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea,
                               QSplitter, QStackedWidget, QVBoxLayout, QWidget)  # noqa: F401

from ..store import Item
from . import theme
from .context import AppContext
from .lists import (CategoryDelegate, CategoryModel, ChannelDelegate, ItemModel, ItemRole, PosterDelegate, RowRole,
                    hhmm, make_list)
from .workers import run_task


def fmt_dur(seconds: float | None) -> str:
    s = int(seconds or 0)
    h, m = divmod(s // 60, 60)
    return f"{h} sa {m:02d} dk" if h else f"{m} dk"


def fmt_clock(seconds: float | None) -> str:
    s = int(seconds or 0)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def _category_view(model: CategoryModel) -> QListView:
    v = QListView()
    v.setModel(model)
    v.setItemDelegate(CategoryDelegate(v))
    v.setMouseTracking(True)
    v.setUniformItemSizes(True)
    v.setEditTriggers(QAbstractItemView.NoEditTriggers)
    v.setMinimumWidth(200)
    return v


log = logging.getLogger("helootv.ui")

class _BrowserBase(QWidget):
    """Kategori listesi + öğe listesi ortak davranışı (arka planda yükleme, arama, seçimi koruma)."""
    kind = "live"

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.cat_model = CategoryModel(self)
        self.cat_view = _category_view(self.cat_model)
        self.model = ItemModel(self)
        self._token = 0
        self._cat_key = "all"
        self._search = ""
        self._pending_select = None
        self.header = QLabel("")
        self.header.setObjectName("H2")
        self.sub_header = QLabel("")
        self.sub_header.setObjectName("Muted")

    # alt sınıflar: special_categories(), fetch_items(key, search), view (QListView), after_items()
    def special_categories(self) -> list[dict]:
        return []

    def reload(self) -> None:
        st = self.ctx.store
        cats = self.special_categories() + st.categories(self.kind, self.ctx.hide_adult())
        self.cat_model.set_rows(cats)
        row = self.cat_model.row_of(self._cat_key)
        if row < 0:
            self._cat_key = "all"
            row = self.cat_model.row_of("all")
        if row >= 0:
            self.cat_view.setCurrentIndex(self.cat_model.index(row))
        self.load_items()

    def _on_category(self, current, _prev=None) -> None:
        r = current.data(RowRole) if current.isValid() else None
        if not r:
            return
        if r["key"] != self._cat_key or self._search:
            self._cat_key = r["key"]
            if self._search:
                self._search = ""
                self.search_cleared()
            self.load_items()

    def search_cleared(self) -> None:
        pass

    def set_search(self, text: str) -> None:
        text = text.strip()
        if text == self._search:
            return
        self._search = text
        self.load_items()

    def fetch_items(self, key: str, search: str) -> list[Item]:
        st = self.ctx.store
        hide = self.ctx.hide_adult()
        if search:
            return st.items(self.kind, search=search, hide_adult=hide, limit=3000)
        if key == "fav":
            return st.favorites(self.kind, hide)
        if key == "all":
            return st.items(self.kind, hide_adult=hide)
        return st.items(self.kind, cat_key=key, hide_adult=hide)

    def load_items(self) -> None:
        self._token += 1
        token = self._token
        key, search = self._cat_key, self._search
        name = next((r["name"] for r in self.cat_model.rows if r["key"] == key), "")
        self.header.setText(f"Arama: “{search}”" if search else name)
        self.sub_header.setText("yükleniyor…")

        def done(items):
            if token != self._token:
                return
            self.model.set_favs(self.ctx.store.favorite_keys(self.kind))
            self.model.set_items(items)
            self.sub_header.setText(f"{len(items):,} öğe".replace(",", "."))
            self.after_items()
            if self._pending_select is not None:
                key_ = self._pending_select
                self._pending_select = None
                self.select_key(key_)

        run_task(self.fetch_items, key, search, on_done=done,
                 on_error=lambda e: self.sub_header.setText(f"Yüklenemedi: {e}"))

    def after_items(self) -> None:
        pass

    def select_key(self, key) -> bool:
        row = self.model.row_of(key)
        if row < 0:
            self._pending_select = key
            return False
        idx = self.model.index(row)
        self.view.setCurrentIndex(idx)
        self.view.scrollTo(idx, QAbstractItemView.PositionAtCenter)
        return True

    def current_item(self) -> Item | None:
        idx = self.view.currentIndex()
        return idx.data(ItemRole) if idx.isValid() else None

    def refresh_favs(self) -> None:
        self.model.set_favs(self.ctx.store.favorite_keys(self.kind))


# ---------------------------------------------------------------------- Canlı TV

class Onboarding(QWidget):
    add_xtream = Signal()
    add_m3u = Signal()
    add_free = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        card = QFrame()
        card.setObjectName("Card")
        card.setMaximumWidth(620)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(theme.draw_logo(64))
        logo.setStyleSheet("background: transparent;")
        title = QLabel("Heloo TV'ye hoş geldiniz")
        title.setObjectName("H1")
        text = QLabel("Canlı TV, film ve dizileri NVIDIA RTX Video Super Resolution ile 4K'ya yükselterek, en düşük "
                      "gecikmeyle izleyin. Başlamak için IPTV hesabınızı ya da M3U listenizi ekleyin.")
        text.setWordWrap(True)
        text.setObjectName("Muted")
        b1 = QPushButton("Xtream Codes hesabı ekle")
        b1.setObjectName("Primary")
        b2 = QPushButton("M3U / M3U8 listesi ekle (bağlantı ya da dosya)")
        b3 = QPushButton("Ücretsiz Türk kanallarıyla başla (iptv-org)")
        b1.clicked.connect(self.add_xtream.emit)
        b2.clicked.connect(self.add_m3u.emit)
        b3.clicked.connect(self.add_free.emit)
        note = QLabel("Heloo TV bir oynatıcıdır, içerik sağlamaz. Yalnızca izleme hakkınız olan listeleri ekleyin.")
        note.setWordWrap(True)
        note.setObjectName("Muted")
        for w in (logo, title, text, b1, b2, b3, note):
            lay.addWidget(w)
        outer.addWidget(card)


class LivePage(_BrowserBase):
    kind = "live"
    play_requested = Signal(object)
    channel_selected = Signal(object)
    favorite_toggled = Signal(object)
    external_requested = Signal(object)

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self.view = make_list(ChannelDelegate(ctx.images), self.model)
        self.stack = QStackedWidget()
        self.onboarding = Onboarding()
        content = QSplitter(Qt.Horizontal)
        content.setChildrenCollapsible(False)
        content.addWidget(self.cat_view)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        hl = QHBoxLayout()
        hl.addWidget(self.header)
        hl.addStretch(1)
        hl.addWidget(self.sub_header)
        rl.addLayout(hl)
        rl.addWidget(self.view, 1)
        content.addWidget(right)
        content.setStretchFactor(1, 1)
        content.setSizes([230, 520])
        self.stack.addWidget(self.onboarding)
        self.stack.addWidget(content)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 4, 10)
        lay.addWidget(self.stack)
        self.cat_view.selectionModel().currentChanged.connect(self._on_category)
        self.view.activated.connect(lambda idx: self.play_requested.emit(idx.data(ItemRole)))
        self.view.selectionModel().currentChanged.connect(
            lambda cur, _p: cur.isValid() and self.channel_selected.emit(cur.data(ItemRole)))
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self._epg_timer = QTimer(self)
        self._epg_timer.setInterval(60_000)
        self._epg_timer.timeout.connect(self.refresh_epg)
        self._epg_timer.start()

    def special_categories(self) -> list[dict]:
        st = self.ctx.store
        favs = len(st.favorites("live", self.ctx.hide_adult()))
        recent = len(st.history(("live",), limit=40))
        total = st.count_items("live", self.ctx.hide_adult())
        return [{"key": "fav", "name": "⭐  Favori kanallar", "count": favs},
                {"key": "recent", "name": "🕘  Son izlenenler", "count": recent},
                {"key": "all", "name": "📺  Tüm kanallar", "count": total}]

    def fetch_items(self, key: str, search: str) -> list[Item]:
        if key == "recent" and not search:
            out = []
            for h in self.ctx.store.history(("live",), limit=40):
                it = self.ctx.store.item(h["source_id"], "live", h["item_id"])
                if it and not (self.ctx.hide_adult() and it.adult):
                    out.append(it)
            return out
        return super().fetch_items(key, search)

    def set_has_sources(self, has: bool) -> None:
        self.stack.setCurrentIndex(1 if has else 0)

    def after_items(self) -> None:
        self.refresh_epg()

    def refresh_epg(self) -> None:
        items = list(self.model.items)
        if not items:
            return
        token = self._token
        pairs = [(i.source_id, i.epg_id) for i in items if i.epg_id]

        def done(epg):
            if token == self._token:
                self.model.set_epg(epg)

        run_task(self.ctx.store.epg_now_next, pairs, on_done=done)

    def _menu(self, pos) -> None:
        idx = self.view.indexAt(pos)
        it: Item | None = idx.data(ItemRole) if idx.isValid() else None
        if not it:
            return
        m = QMenu(self)
        m.addAction("▶  Oynat", lambda: self.play_requested.emit(it))
        fav = it.key in self.model.favs
        m.addAction("☆  Favorilerden çıkar" if fav else "★  Favorilere ekle", lambda: self.favorite_toggled.emit(it))
        m.addAction("↗  Ayrı mpv penceresinde aç", lambda: self.external_requested.emit(it))
        m.addSeparator()
        m.addAction("⧉  Yayın adresini kopyala", lambda: self._copy_url(it))
        m.exec(self.view.viewport().mapToGlobal(pos))

    def _copy_url(self, it: Item) -> None:
        from .. import catalog
        url = catalog.play_url(self.ctx.store, it, self.ctx.settings, self.ctx.source(it.source_id))
        QApplication.clipboard().setText(url)


class EpgPanel(QWidget):
    catchup_requested = Signal(object, dict)
    record_requested = Signal(object, dict)     # gelecek/şimdiki program: zamanlanmış kayıt
    remind_requested = Signal(object, dict)     # gelecek program: hatırlatıcı

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.item: Item | None = None
        self._token = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        head = QHBoxLayout()
        self.title = QLabel("Yayın akışı")
        self.title.setObjectName("H2")
        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.hint)
        lay.addLayout(head)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.itemActivated.connect(self._activated)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.marks = lambda prog: ""              # ana pencere: programın kayıt/hatırlatıcı işareti (⏺ / 🔔)
        self.list.currentItemChanged.connect(self._selected)
        lay.addWidget(self.list, 1)
        self.desc = QLabel("")
        self.desc.setWordWrap(True)
        self.desc.setObjectName("Muted")
        self.desc.setMaximumHeight(90)
        lay.addWidget(self.desc)

    def show_channel(self, item: Item | None) -> None:
        self.item = item
        self._token += 1
        token = self._token
        self.list.clear()
        self.desc.setText("")
        if item is None:
            self.title.setText("Yayın akışı")
            self.hint.setText("")
            return
        self.title.setText(f"Yayın akışı — {item.name}")
        self.hint.setText("yükleniyor…")
        archive_days = int(item.archive or 0)

        def fetch():
            now = time.time()
            start = now - (archive_days * 86400 if archive_days else 4 * 3600)
            progs = []
            if item.epg_id:
                progs = self.ctx.store.epg_for_channel(item.source_id, item.epg_id, start, now + 36 * 3600)
            if not progs:
                client = self.ctx.client(item.source_id)
                if client:
                    try:
                        progs = client.full_epg(item.item_id) if archive_days else client.short_epg(item.item_id, 30)
                    except Exception:
                        progs = []
            return progs

        def done(progs):
            if token != self._token:
                return
            self._fill(progs, archive_days)

        run_task(fetch, on_done=done, on_error=lambda e: self.hint.setText("yayın akışı alınamadı"))

    def _fill(self, progs: list[dict], archive_days: int) -> None:
        self.list.clear()
        now = time.time()
        current_row = -1
        last_day = None
        for p in progs:
            day = time.strftime("%d.%m %A", time.localtime(p["start"]))
            if day != last_day:
                last_day = day
                sep = QListWidgetItem(_turkish_day(p["start"]))
                sep.setFlags(Qt.NoItemFlags)
                sep.setForeground(QColor(theme.ACCENT_2))
                f = sep.font()
                f.setBold(True)
                sep.setFont(f)
                self.list.addItem(sep)
            past = p["stop"] <= now
            live = p["start"] <= now < p["stop"]
            can_archive = past and archive_days and p["start"] >= now - archive_days * 86400
            prefix = "⟲ " if can_archive else ("● " if live else "")
            prefix = (self.marks(p) or "") + prefix
            it = QListWidgetItem(f"{prefix}{hhmm(p['start'])}–{hhmm(p['stop'])}   {p['title']}")
            it.setData(Qt.UserRole, p)
            it.setData(Qt.UserRole + 1, bool(can_archive))
            if live:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                it.setForeground(QColor("white"))
                current_row = self.list.count()
            elif past:
                it.setForeground(QColor(theme.MUTED if not can_archive else "#9fd8f7"))
            if can_archive:
                it.setToolTip("Çift tıklayın: geri izle (catch-up)")
            self.list.addItem(it)
        if current_row >= 0:
            self.list.setCurrentRow(current_row)
            self.list.scrollToItem(self.list.item(current_row), QAbstractItemView.PositionAtTop)
        self.hint.setText("⟲ = geri izlenebilir" if archive_days else ("" if progs else "yayın akışı yok"))

    def _selected(self, cur: QListWidgetItem, _prev) -> None:
        p = cur.data(Qt.UserRole) if cur else None
        self.desc.setText(p.get("desc", "") if p else "")

    def _menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        it = self.list.itemAt(pos)
        p = it.data(Qt.UserRole) if it else None
        if not p or not self.item:
            return
        now = time.time()
        m = QMenu(self)
        if it.data(Qt.UserRole + 1):
            m.addAction("⟲ Geri izle", lambda: self.catchup_requested.emit(self.item, p))
        if p["stop"] > now:
            m.addAction("⏺ Bu programı kaydet" if p["start"] > now else "⏺ Şimdi kaydet (program bitene kadar)",
                        lambda: self.record_requested.emit(self.item, p))
        if p["start"] > now:
            m.addAction("🔔 Başlayınca hatırlat", lambda: self.remind_requested.emit(self.item, p))
        if m.actions():
            m.exec(self.list.viewport().mapToGlobal(pos))

    def refresh_marks(self) -> None:
        if self.item is not None:
            self.show_channel(self.item)

    def _activated(self, it: QListWidgetItem) -> None:
        p = it.data(Qt.UserRole)
        if p and it.data(Qt.UserRole + 1) and self.item:
            self.catchup_requested.emit(self.item, p)


_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def _turkish_day(ts: float) -> str:
    t = time.localtime(ts)
    today = time.localtime()
    if t.tm_yday == today.tm_yday and t.tm_year == today.tm_year:
        label = "Bugün"
    elif (t.tm_yday - today.tm_yday) == 1 and t.tm_year == today.tm_year:
        label = "Yarın"
    elif (today.tm_yday - t.tm_yday) == 1 and t.tm_year == today.tm_year:
        label = "Dün"
    else:
        label = _DAYS[t.tm_wday]
    return f"{label}, {t.tm_mday:02d}.{t.tm_mon:02d}"


# ---------------------------------------------------------------------- Film / Dizi ortak

class _PosterBrowser(_BrowserBase):
    def __init__(self, ctx: AppContext, details: QWidget, parent=None):
        super().__init__(ctx, parent)
        self.view = make_list(PosterDelegate(ctx.images), self.model, grid=True)
        self.details = details
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self.cat_view)
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        hl = QHBoxLayout()
        hl.addWidget(self.header)
        hl.addStretch(1)
        hl.addWidget(self.sub_header)
        ml.addLayout(hl)
        ml.addWidget(self.view, 1)
        split.addWidget(mid)
        split.addWidget(details)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 760, 380])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(split)
        self.cat_view.selectionModel().currentChanged.connect(self._on_category)
        self.view.selectionModel().currentChanged.connect(
            lambda cur, _p: cur.isValid() and self.on_item_selected(cur.data(ItemRole)))
        ctx.images.loaded.connect(lambda _u: self.view.viewport().update())

    def special_categories(self) -> list[dict]:
        st = self.ctx.store
        return [{"key": "fav", "name": "⭐  Favoriler", "count": len(st.favorites(self.kind, self.ctx.hide_adult()))},
                {"key": "all", "name": "🎬  Tümü" if self.kind == "movie" else "🎞  Tümü",
                 "count": st.count_items(self.kind, self.ctx.hide_adult())}]

    def after_items(self) -> None:
        prog = {}
        if self.kind == "movie":
            for h in self.ctx.store.history(("movie",), limit=400):
                if h["duration"]:
                    prog[(h["source_id"], "movie", h["item_id"])] = h["position"] / h["duration"]
        self.model.set_progress(prog)
        if not self.view.currentIndex().isValid() and self.model.items:
            self.view.setCurrentIndex(self.model.index(0))

    def on_item_selected(self, item: Item) -> None:
        self.details.show_item(item)


class _DetailsBase(QScrollArea):
    def _tmdb(self, kind: str, item: Item, have: dict, apply) -> None:
        """Sağlayıcı bilgisi eksikse TMDB'den tamamlar (kullanıcının anahtarı varsa). apply(tmdb_bilgisi) çağrılır."""
        key = (self.ctx.settings.get("metadata") or {}).get("tmdb_key", "").strip()
        if not key or (have.get("plot") and have.get("cast") and (have.get("poster") or item.logo)):
            return
        cache_key = (item.key, "tmdb")
        if cache_key in self.ctx.vod_info_cache:
            apply(self.ctx.vod_info_cache[cache_key])
            return
        token = self._token
        from .. import tmdb

        def done(extra):
            self.ctx.vod_info_cache[cache_key] = extra
            if token == self._token and extra:
                apply(extra)

        run_task(tmdb.lookup, key, kind, item.name, item.year or "", on_done=done,
                 on_error=lambda e: log.info("TMDB: %s", e))

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.item: Item | None = None
        self._token = 0
        self.setWidgetResizable(True)
        self.setMinimumWidth(330)
        body = QWidget()
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(14, 6, 10, 14)
        self.lay.setSpacing(10)
        self.poster = QLabel()
        self.poster.setFixedSize(220, 330)
        self.poster.setAlignment(Qt.AlignCenter)
        self.poster.setStyleSheet(f"background: {theme.PANEL_2}; border-radius: 12px;")
        self.title = QLabel("")
        self.title.setObjectName("H1")
        self.title.setWordWrap(True)
        self.meta = QLabel("")
        self.meta.setObjectName("Muted")
        self.meta.setWordWrap(True)
        self.plot = QLabel("")
        self.plot.setWordWrap(True)
        self.plot.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.people = QLabel("")
        self.people.setObjectName("Muted")
        self.people.setWordWrap(True)
        self.lay.addWidget(self.poster, 0, Qt.AlignHCenter)
        self.lay.addWidget(self.title)
        self.lay.addWidget(self.meta)
        self.buttons = QHBoxLayout()
        self.lay.addLayout(self.buttons)
        self.lay.addWidget(self.plot)
        self.lay.addWidget(self.people)
        self.setWidget(body)
        ctx.images.loaded.connect(self._image_loaded)
        self._poster_url = ""

    def _set_poster(self, url: str) -> None:
        self._poster_url = url or ""
        dpr = self.devicePixelRatioF()
        pm = self.ctx.images.pixmap(self._poster_url, QSize(220, 330), "cover", dpr)
        if pm is not None:
            self.poster.setPixmap(pm)
        else:
            self.poster.setPixmap(theme.draw_logo(72))

    def _image_loaded(self, url: str) -> None:
        if url == self._poster_url:
            self._set_poster(url)


class MovieDetails(_DetailsBase):
    play = Signal(object, object)
    favorite = Signal(object)
    external = Signal(object)

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self.btn_play = QPushButton("▶  Oynat")
        self.btn_play.setObjectName("Primary")
        self.btn_resume = QPushButton("⏯  Devam et")
        self.btn_fav = QPushButton("☆")
        self.btn_fav.setToolTip("Favorilere ekle/çıkar")
        self.btn_ext = QPushButton("↗")
        self.btn_ext.setToolTip("Ayrı mpv penceresinde aç")
        for b in (self.btn_play, self.btn_resume, self.btn_fav, self.btn_ext):
            self.buttons.addWidget(b)
        self.buttons.addStretch(1)
        self.btn_play.clicked.connect(lambda: self.item and self.play.emit(self.item, 0))
        self.btn_resume.clicked.connect(lambda: self.item and self.play.emit(self.item, self._resume))
        self.btn_fav.clicked.connect(lambda: self.item and self.favorite.emit(self.item))
        self.btn_ext.clicked.connect(lambda: self.item and self.external.emit(self.item))
        self._resume = 0.0
        self.lay.addStretch(1)
        self.show_item(None)

    def show_item(self, item: Item | None) -> None:
        self.item = item
        self._token += 1
        token = self._token
        for b in (self.btn_play, self.btn_resume, self.btn_fav, self.btn_ext):
            b.setEnabled(item is not None)
        if item is None:
            self.title.setText("Film seçin")
            self.meta.setText("")
            self.plot.setText("")
            self.people.setText("")
            self.btn_resume.hide()
            self._set_poster("")
            return
        self.title.setText(item.name)
        self._set_poster(item.logo)
        meta = [x for x in (item.year, f"★ {item.rating:.1f}" if item.rating else "") if x]
        self.meta.setText(" · ".join(meta))
        self.plot.setText("")
        self.people.setText("")
        self.refresh_buttons()
        client = self.ctx.client(item.source_id)
        base = {"plot": item.extra_dict().get("plot", ""), "year": item.year, "rating": item.rating}

        def with_tmdb(info):
            from .. import tmdb
            self._tmdb("movie", item, info, lambda extra: self._fill(tmdb.merge(info, extra)))

        if client is None:
            if base["plot"]:
                self._fill(base)
            with_tmdb(base)
            return
        cache_key = item.key
        if cache_key in self.ctx.vod_info_cache:
            self._fill(self.ctx.vod_info_cache[cache_key])
            with_tmdb(self.ctx.vod_info_cache[cache_key])
            return

        def done(info):
            self.ctx.vod_info_cache[cache_key] = info
            if token == self._token:
                self._fill(info)
                with_tmdb(info)

        self.plot.setText("Ayrıntılar yükleniyor…")
        run_task(client.vod_info, item.item_id, on_done=done, on_error=lambda e: self.plot.setText(""))

    def refresh_buttons(self) -> None:
        item = self.item
        if item is None:
            return
        fav = self.ctx.store.is_favorite(item.key)
        self.btn_fav.setText("★" if fav else "☆")
        prog = self.ctx.store.get_progress(item.key)
        self._resume = prog[0] if prog and prog[0] > 60 and (not prog[1] or prog[0] < prog[1] * 0.94) else 0.0
        self.btn_resume.setVisible(self._resume > 0)
        self.btn_resume.setText(f"⏯  Devam et ({fmt_clock(self._resume)})")

    def _fill(self, info: dict) -> None:
        meta = []
        item = self.item
        if info.get("year") or (item and item.year):
            meta.append(info.get("year") or item.year)
        if info.get("duration"):
            meta.append(fmt_dur(info["duration"]))
        if info.get("rating") or (item and item.rating):
            meta.append(f"★ {float(info.get('rating') or item.rating):.1f}")
        if info.get("genre"):
            meta.append(info["genre"])
        video = info.get("video") or {}
        if video.get("height"):
            meta.append(f"{video.get('height')}p kaynak")
        self.meta.setText(" · ".join(str(m) for m in meta if m))
        self.plot.setText(info.get("plot") or "")
        people = []
        if info.get("director"):
            people.append(f"Yönetmen: {info['director']}")
        if info.get("cast"):
            people.append(f"Oyuncular: {info['cast']}")
        self.people.setText("\n".join(people))
        if info.get("poster") and not (item and item.logo):
            self._set_poster(info["poster"])
        if info.get("tmdb"):
            self.people.setText((self.people.text() + "\n\nBilgiler: TMDB").strip())


class MoviesPage(_PosterBrowser):
    kind = "movie"
    play_requested = Signal(object, object)
    favorite_toggled = Signal(object)
    external_requested = Signal(object)

    def __init__(self, ctx: AppContext, parent=None):
        self.details_widget = MovieDetails(ctx)
        super().__init__(ctx, self.details_widget, parent)
        self.details_widget.play.connect(self.play_requested.emit)
        self.details_widget.favorite.connect(self.favorite_toggled.emit)
        self.details_widget.external.connect(self.external_requested.emit)
        self.view.activated.connect(lambda idx: self._activate(idx.data(ItemRole)))

    def _activate(self, item: Item) -> None:
        self.details_widget.show_item(item)
        self.play_requested.emit(item, self.details_widget._resume or 0)


class SeriesDetails(_DetailsBase):
    play_episode = Signal(object, dict, list, object)
    favorite = Signal(object)

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self.poster.setFixedSize(180, 270)
        self.btn_play = QPushButton("▶  Bölümü oynat")
        self.btn_play.setObjectName("Primary")
        self.btn_resume = QPushButton("⏯  Kaldığın yer")
        self.btn_fav = QPushButton("☆")
        self.btn_fav.setToolTip("Favorilere ekle/çıkar")
        for b in (self.btn_play, self.btn_resume, self.btn_fav):
            self.buttons.addWidget(b)
        self.buttons.addStretch(1)
        self.season = QComboBox()
        self.episodes = QListWidget()
        self.episodes.setMinimumHeight(260)
        self.lay.addWidget(self.season)
        self.lay.addWidget(self.episodes, 1)
        self.season.currentIndexChanged.connect(self._fill_episodes)
        self.episodes.itemActivated.connect(lambda it: self._play_row(self.episodes.row(it)))
        self.btn_play.clicked.connect(lambda: self._play_row(max(0, self.episodes.currentRow())))
        self.btn_resume.clicked.connect(self._play_resume)
        self.btn_fav.clicked.connect(lambda: self.item and self.favorite.emit(self.item))
        self.all_eps: list[dict] = []
        self._resume_ep: tuple[dict, float] | None = None
        self.show_item(None)

    def _set_poster(self, url: str) -> None:
        self._poster_url = url or ""
        pm = self.ctx.images.pixmap(self._poster_url, QSize(180, 270), "cover", self.devicePixelRatioF())
        self.poster.setPixmap(pm if pm is not None else theme.draw_logo(64))

    def show_item(self, item: Item | None) -> None:
        self.item = item
        self._token += 1
        token = self._token
        self.all_eps = []
        self.season.clear()
        self.episodes.clear()
        for b in (self.btn_play, self.btn_resume, self.btn_fav):
            b.setEnabled(item is not None)
        self.btn_resume.hide()
        if item is None:
            self.title.setText("Dizi seçin")
            self.meta.setText("")
            self.plot.setText("")
            self.people.setText("")
            self._set_poster("")
            return
        self.title.setText(item.name)
        self._set_poster(item.logo)
        extra = item.extra_dict()
        meta = [x for x in (item.year, f"★ {item.rating:.1f}" if item.rating else "", extra.get("genre", "")) if x]
        self.meta.setText(" · ".join(meta))
        self.plot.setText(extra.get("plot", ""))
        self.people.setText(f"Oyuncular: {extra['cast']}" if extra.get("cast") else "")
        self.btn_fav.setText("★" if self.ctx.store.is_favorite(item.key) else "☆")
        client = self.ctx.client(item.source_id)
        cache_key = item.key

        def fetch():
            if client is None:
                return {"episodes": self.ctx.store.episodes(item.source_id, item.item_id), "info": {}}
            return client.series_info(item.item_id)

        def done(info):
            self.ctx.series_cache[cache_key] = info
            if token != self._token:
                return
            self.all_eps = info.get("episodes") or []
            inf = info.get("info") or {}
            if inf.get("plot") and not self.plot.text():
                self.plot.setText(inf["plot"])
            if inf.get("cast") and not self.people.text():
                self.people.setText(f"Oyuncular: {inf['cast']}")

            def apply_tmdb(extra):
                if not self.plot.text() and extra.get("plot"):
                    self.plot.setText(extra["plot"])
                if not self.people.text() and extra.get("cast"):
                    self.people.setText(f"Oyuncular: {extra['cast']}")
                if not self.meta.text().strip() and (extra.get("year") or extra.get("rating")):
                    self.meta.setText(" · ".join(x for x in (extra.get("year"), f"★ {extra['rating']:.1f}"
                                                             if extra.get("rating") else "", extra.get("genre")) if x))
                if extra.get("poster") and not item.logo:
                    self._set_poster(extra["poster"])
            self._tmdb("tv", item, {"plot": self.plot.text(), "cast": self.people.text(), "poster": item.logo},
                       apply_tmdb)
            seasons = sorted({e["season"] for e in self.all_eps})
            self.season.blockSignals(True)
            for s in seasons:
                n = sum(1 for e in self.all_eps if e["season"] == s)
                self.season.addItem(f"{s}. Sezon  ({n} bölüm)", s)
            self.season.blockSignals(False)
            self._compute_resume()
            if self._resume_ep:
                idx = self.season.findData(self._resume_ep[0]["season"])
                self.season.setCurrentIndex(max(0, idx))
            self._fill_episodes()
            if not self.all_eps:
                self.plot.setText((self.plot.text() + "\n\nBölüm bulunamadı.").strip())

        if cache_key in self.ctx.series_cache:
            done(self.ctx.series_cache[cache_key])
        else:
            self.episodes.addItem("Bölümler yükleniyor…")
            run_task(fetch, on_done=done, on_error=lambda e: (self.episodes.clear(),
                                                               self.episodes.addItem(f"Bölümler alınamadı: {e}")))

    def _compute_resume(self) -> None:
        """Bu dizide en son izlenen bölüm: yarımsa kaldığı yer, bittiyse sıradaki bölüm."""
        self._resume_ep = None
        if not self.item:
            return
        rows = self.ctx.store.history(("episode",), limit=400)
        ids = {e["id"]: e for e in self.all_eps}
        for r in rows:
            if r["source_id"] == self.item.source_id and r["item_id"] in ids:
                ep = ids[r["item_id"]]
                finished = r["duration"] and r["position"] >= r["duration"] * 0.94
                if finished:
                    i = self.all_eps.index(ep)
                    if i + 1 < len(self.all_eps):
                        self._resume_ep = (self.all_eps[i + 1], 0.0)
                else:
                    self._resume_ep = (ep, r["position"])
                break
        if self._resume_ep:
            ep, pos = self._resume_ep
            label = f"S{ep['season']:02d}B{ep['episode']:02d}"
            self.btn_resume.setText(f"⏯  {label} " + (f"({fmt_clock(pos)})" if pos > 60 else "(sıradaki)"))
            self.btn_resume.show()

    def _season_eps(self) -> list[dict]:
        s = self.season.currentData()
        return [e for e in self.all_eps if e["season"] == s] if s is not None else list(self.all_eps)

    def _fill_episodes(self, *_a) -> None:
        self.episodes.clear()
        if not self.item:
            return
        for e in self._season_eps():
            prog = self.ctx.store.get_progress((self.item.source_id, "episode", e["id"]))
            mark = ""
            if prog and prog[1]:
                mark = "  ✓" if prog[0] >= prog[1] * 0.94 else f"  ◔ {int(100 * prog[0] / prog[1])}%"
            dur = f"  · {fmt_dur(e['duration'])}" if e.get("duration") else ""
            title = e.get("title") or ""
            row = QListWidgetItem(f"{e['episode']:>2}. Bölüm   {title}{dur}{mark}")
            row.setToolTip(e.get("plot") or title)
            self.episodes.addItem(row)
        if self.episodes.count():
            self.episodes.setCurrentRow(0)

    def _play_row(self, row: int) -> None:
        eps = self._season_eps()
        if self.item and 0 <= row < len(eps):
            ep = eps[row]
            prog = self.ctx.store.get_progress((self.item.source_id, "episode", ep["id"]))
            start = prog[0] if prog and prog[0] > 60 and (not prog[1] or prog[0] < prog[1] * 0.94) else 0
            self.play_episode.emit(self.item, ep, self.all_eps, start)

    def _play_resume(self) -> None:
        if self.item and self._resume_ep:
            ep, pos = self._resume_ep
            self.play_episode.emit(self.item, ep, self.all_eps, pos)


class SeriesPage(_PosterBrowser):
    kind = "series"
    play_episode = Signal(object, dict, list, object)
    favorite_toggled = Signal(object)

    def __init__(self, ctx: AppContext, parent=None):
        self.details_widget = SeriesDetails(ctx)
        super().__init__(ctx, self.details_widget, parent)
        self.details_widget.play_episode.connect(self.play_episode.emit)
        self.details_widget.favorite.connect(self.favorite_toggled.emit)
        self.view.activated.connect(lambda idx: self.details_widget.show_item(idx.data(ItemRole)))


# ---------------------------------------------------------------------- Favoriler

class FavoritesPage(QWidget):
    play_live = Signal(object)
    play_movie = Signal(object, object)
    open_series = Signal(object)
    play_history = Signal(dict)

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.group = QButtonGroup(self)
        self.stack = QStackedWidget()
        self.live_model = ItemModel(self)
        self.movie_model = ItemModel(self)
        self.series_model = ItemModel(self)
        self.live_view = make_list(ChannelDelegate(ctx.images, numbered=False), self.live_model)
        self.movie_view = make_list(PosterDelegate(ctx.images), self.movie_model, grid=True)
        self.series_view = make_list(PosterDelegate(ctx.images), self.series_model, grid=True)
        self.cont = QListWidget()
        self.hist = QListWidget()
        for i, (label, w) in enumerate((("Kanallar", self.live_view), ("Filmler", self.movie_view),
                                        ("Diziler", self.series_view), ("İzlemeye devam et", self.cont),
                                        ("Geçmiş", self.hist))):
            b = QPushButton(label)
            b.setObjectName("Seg")
            b.setCheckable(True)
            self.group.addButton(b, i)
            seg.addWidget(b)
            self.stack.addWidget(w)
        seg.addStretch(1)
        self.group.button(0).setChecked(True)
        self.group.idClicked.connect(self.stack.setCurrentIndex)
        lay.addLayout(seg)
        lay.addWidget(self.stack, 1)
        self.live_view.activated.connect(lambda idx: self.play_live.emit(idx.data(ItemRole)))
        self.movie_view.activated.connect(lambda idx: self.play_movie.emit(idx.data(ItemRole), None))
        self.series_view.activated.connect(lambda idx: self.open_series.emit(idx.data(ItemRole)))
        self.cont.itemActivated.connect(lambda it: self.play_history.emit(it.data(Qt.UserRole)))
        self.hist.itemActivated.connect(lambda it: self.play_history.emit(it.data(Qt.UserRole)))
        ctx.images.loaded.connect(lambda _u: (self.movie_view.viewport().update(),
                                              self.series_view.viewport().update(),
                                              self.live_view.viewport().update()))

    def reload(self) -> None:
        st, hide = self.ctx.store, self.ctx.hide_adult()
        for model, kind in ((self.live_model, "live"), (self.movie_model, "movie"), (self.series_model, "series")):
            model.set_items(st.favorites(kind, hide))
            model.set_favs(st.favorite_keys(kind))
        pairs = [(i.source_id, i.epg_id) for i in self.live_model.items if i.epg_id]
        if pairs:
            run_task(st.epg_now_next, pairs, on_done=self.live_model.set_epg)
        self.cont.clear()
        for h in st.continue_watching():
            pct = int(100 * h["position"] / h["duration"]) if h["duration"] else 0
            it = QListWidgetItem(f"⏯  {h['title']}   —  {fmt_clock(h['position'])}" + (f"  ({pct}%)" if pct else ""))
            it.setData(Qt.UserRole, h)
            self.cont.addItem(it)
        if not self.cont.count():
            self.cont.addItem("Yarım kalan film ya da bölüm yok.")
        self.hist.clear()
        for h in st.history(limit=120):
            icon = {"live": "📺", "movie": "🎬", "episode": "🎞", "catchup": "⟲", "file": "📁", "image": "🖼", "url": "🔗"}.get(h["kind"], "•")
            when = time.strftime("%d.%m %H:%M", time.localtime(h["updated"]))
            it = QListWidgetItem(f"{icon}  {h['title']}   ·  {when}")
            it.setData(Qt.UserRole, h)
            self.hist.addItem(it)


__all__ = ["LivePage", "EpgPanel", "MoviesPage", "SeriesPage", "FavoritesPage", "fmt_clock", "fmt_dur"]
