"""Ana pencere: sekmeler, oynatma akışı, kanal geçişi, tam ekran/sinema modu, yenileme ve durum çubuğu."""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog, QMenu, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, catalog, epg, gpu, paths, upscale, weburl
from ..player import options as opt
from ..player.engine import EngineError, MpvEngine, PlayRequest, launch_external
from ..settings import save_settings
from ..store import Item, Store
from . import theme
from .context import AppContext
from .images import ImageLoader
from .pages import EpgPanel, FavoritesPage, LivePage, MoviesPage, SeriesPage, fmt_clock
from .player_panel import PlayerPanel
from .settings_page import SettingsPage
from .workers import run_task

log = logging.getLogger("helootv.ui")
TABS = [("live", "📺  Canlı TV"), ("movie", "🎬  Filmler"), ("series", "🎞  Diziler"), ("fav", "⭐  Favoriler"),
        ("settings", "⚙  Ayarlar")]


def fmt_clock_secs(sec: float) -> str:
    s = int(sec)
    h, rem = divmod(s, 3600)
    m, x = divmod(rem, 60)
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}"


class EngineBridge(QObject):
    event = Signal(str, dict)


class MainWindow(QMainWindow):
    def __init__(self, store: Store, settings: dict, debug: bool = False, headless: bool = False):
        super().__init__()
        self.store = store
        self.settings = settings
        if settings["ui"].get("pin_hash"):
            settings["ui"]["hide_adult"] = True        # ebeveyn kilidi: her açılışta yeniden kilitlenir
        self.debug = debug
        self.headless = headless
        self.images = ImageLoader(self)
        self.ctx = AppContext(store, settings, self.images)
        self.engine: MpvEngine | None = None
        self.bridge = EngineBridge()
        self.bridge.event.connect(self._on_engine_event)
        self.current_req: PlayRequest | None = None
        self.current_item: Item | None = None
        self.prev_item: Item | None = None
        self._episode_ctx: dict | None = None
        self._fs = False
        self._theater = False
        self._pre_fs: dict = {}
        self._digits = ""
        self._last_save = 0.0
        self._refresh_jobs: list[tuple[str, int]] = []
        self._refreshing = False
        self._gpu: dict | None = None
        self._gpu_assess: dict = {}
        self._file_queue: list[str] = []
        self._file_index = 0
        self._ai_task: dict | None = None
        self._ls_active = False
        self._pip = False
        self._pre_pip: dict = {}
        from ..recorder import Recorder, Scheduler
        self.recorder = Recorder(folder=self.settings["record"].get("folder") or None,
                                 user_agent=self.settings["network"]["user_agent"])
        self.scheduler = Scheduler()
        self._rec_current: str | None = None      # şu an oynayan yayının kaydının kimliği
        self._ls_pending = False
        self._ls_tries = 0
        self._picture_dlg = None
        self._build_ui()
        self._wire()
        self.setAcceptDrops(True)
        self._save_timer = QTimer(self, singleShot=True, interval=600, timeout=self._save_settings)
        self._search_timer = QTimer(self, singleShot=True, interval=280, timeout=self._apply_search)
        self._digit_timer = QTimer(self, singleShot=True, interval=1600, timeout=self._commit_digits)
        self._tick_timer = QTimer(self, interval=500, timeout=self._tick)
        self._tick_timer.start()
        QTimer.singleShot(0, self._post_show)

    # ================================================================== kurulum
    def _build_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(theme.app_icon())
        self.resize(1520, 920)
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.topbar = QFrame()
        self.topbar.setObjectName("TopBar")
        h = QHBoxLayout(self.topbar)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(6)
        logo = QLabel()
        logo.setPixmap(theme.draw_logo(30))
        logo.setStyleSheet("background: transparent;")
        brand = QLabel(APP_NAME)
        brand.setObjectName("Brand")
        h.addWidget(logo)
        h.addWidget(brand)
        self.nav = QButtonGroup(self)
        for i, (_key, label) in enumerate(TABS):
            b = QPushButton(label)
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.nav.addButton(b, i)
            h.addWidget(b)
        h.addStretch(1)
        self.gpu_badge = QLabel("")
        self.gpu_badge.setObjectName("Badge")
        self.gpu_badge.hide()
        h.addWidget(self.gpu_badge)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Ara: kanal, film, dizi…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        h.addWidget(self.search)
        self.open_btn = QPushButton("📂  Aç")
        self.open_btn.setObjectName("Nav")
        self.open_btn.setToolTip("Kendi videonuzu, fotoğrafınızı ya da bir bağlantıyı 4K'ya yükselterek açın")
        self.open_menu = QMenu(self.open_btn)
        self.open_btn.setMenu(self.open_menu)
        self.open_menu.aboutToShow.connect(self._fill_open_menu)
        h.addWidget(self.open_btn)
        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setObjectName("Flat")
        self.refresh_btn.setToolTip("Listeleri ve yayın akışını yenile (F5)")
        self.guide_btn = QPushButton("📅 Rehber")
        self.guide_btn.setObjectName("Flat")
        self.guide_btn.setToolTip("TV Rehberi: kanallar × saatler (F2)")
        self.guide_btn.setCursor(Qt.PointingHandCursor)
        self.guide_btn.clicked.connect(self.open_guide)
        h.addWidget(self.guide_btn)
        self.update_btn = QPushButton("⬆ Güncelleme var")
        self.update_btn.setObjectName("Primary")
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(lambda: self.check_updates(manual=True))
        self.update_btn.hide()
        h.addWidget(self.update_btn)
        h.addWidget(self.refresh_btn)
        v.addWidget(self.topbar)

        self.body = QSplitter(Qt.Horizontal)
        self.body.setChildrenCollapsible(False)
        self.pages = QStackedWidget()
        self.live_page = LivePage(self.ctx)
        self.movies_page = MoviesPage(self.ctx)
        self.series_page = SeriesPage(self.ctx)
        self.fav_page = FavoritesPage(self.ctx)
        self.settings_page = SettingsPage(self.ctx)
        for p in (self.live_page, self.movies_page, self.series_page, self.fav_page, self.settings_page):
            self.pages.addWidget(p)
        self.right = QSplitter(Qt.Vertical)
        self.right.setChildrenCollapsible(False)
        self.player = PlayerPanel()
        self.epg_panel = EpgPanel(self.ctx)
        self.right.addWidget(self.player)
        self.right.addWidget(self.epg_panel)
        self.right.setStretchFactor(0, 1)
        self.right.setSizes([560, 280])
        self.body.addWidget(self.pages)
        self.body.addWidget(self.right)
        self.body.setStretchFactor(0, 1)
        self.body.setStretchFactor(1, 1)
        self.body.setSizes([800, 700])
        v.addWidget(self.body, 1)
        self.setCentralWidget(central)
        self.status_msg = QLabel("")
        self.status_stats = QLabel("")
        self.statusBar().addWidget(self.status_msg, 1)
        self.statusBar().addPermanentWidget(self.status_stats)

    def _wire(self) -> None:
        self.nav.idClicked.connect(self._on_tab)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.refresh_btn.clicked.connect(lambda: self.refresh(None))
        lp, mp, sp, fp, st = self.live_page, self.movies_page, self.series_page, self.fav_page, self.settings_page
        lp.play_requested.connect(self.play_live)
        lp.channel_selected.connect(lambda it: self.epg_panel.show_channel(it) if it else None)
        lp.favorite_toggled.connect(self.toggle_favorite)
        lp.external_requested.connect(self.open_external)
        lp.onboarding.add_xtream.connect(lambda: self._add_source("xtream"))
        lp.onboarding.add_m3u.connect(lambda: self._add_source("m3u"))
        lp.onboarding.add_free.connect(self.settings_page.add_free)
        mp.play_requested.connect(self.play_movie)
        mp.favorite_toggled.connect(self.toggle_favorite)
        mp.external_requested.connect(self.open_external)
        sp.play_episode.connect(self.play_episode)
        sp.favorite_toggled.connect(self.toggle_favorite)
        fp.play_live.connect(self.play_live)
        fp.play_movie.connect(lambda it, start: self.play_movie(it, self._resume_of(it)))
        fp.open_series.connect(self.open_series)
        fp.play_history.connect(self.play_history)
        self.epg_panel.catchup_requested.connect(self.play_catchup)
        self.epg_panel.record_requested.connect(self.schedule_record)
        self.epg_panel.remind_requested.connect(self.schedule_reminder)
        self.epg_panel.marks = self._prog_mark
        st.settings_changed.connect(self._on_settings_changed)
        st.sources_changed.connect(self._on_sources_changed)
        st.refresh_requested.connect(lambda sid: self.refresh(sid))
        st.epg_refresh_requested.connect(lambda sid: self.refresh(sid, epg_only=True))
        st.fetch_mpv_requested.connect(self.fetch_mpv)
        st.update_requested.connect(lambda: self.check_updates(manual=True))
        st.vsr_test_requested.connect(self.test_vsr)
        st.clear_history_requested.connect(self._clear_history)
        st.picture_requested.connect(self.picture_dialog)
        pl = self.player
        pl.pause_clicked.connect(lambda: self.engine and self.engine.toggle_pause())
        pl.stop_clicked.connect(self.stop)
        pl.live_clicked.connect(lambda: self.engine and self.engine.go_live())
        pl.theater_clicked.connect(lambda: self._set_theater(not self._theater))
        pl.fullscreen_clicked.connect(lambda: self._set_fullscreen(not self._fs))
        pl.external_clicked.connect(lambda: self.open_external(None))
        pl.volume_changed.connect(self._on_volume)
        pl.prev_clicked.connect(lambda: self._on_key("prev", []))
        pl.next_clicked.connect(lambda: self._on_key("next", []))
        pl.record_clicked.connect(self.toggle_record)
        pl.pip_clicked.connect(lambda: self._set_pip(not self._pip))
        pl.seek_to.connect(lambda sec: self.engine and self.engine.seek_abs(sec))
        pl.seek_by.connect(lambda d: self.engine and self.engine.seek(d))
        pl.menus["audio"].aboutToShow.connect(self._fill_audio_menu)
        pl.menus["sub"].aboutToShow.connect(self._fill_sub_menu)
        pl.menus["picture"].aboutToShow.connect(self._fill_picture_menu)
        shortcuts = [
            ("F11", lambda: self._set_fullscreen(not self._fs)),
            ("Esc", lambda: self._on_key("esc", [])),
            ("Ctrl+F", self._focus_search),
            ("F5", lambda: self.refresh(None)),
            ("Ctrl+Up", lambda: self.zap(-1)),
            ("Ctrl+Down", lambda: self.zap(1)),
            ("Ctrl+Space", lambda: self.engine and self.engine.toggle_pause()),
            ("Ctrl+L", lambda: self.engine and self.engine.go_live()),
            ("Ctrl+I", self._show_info),
            ("Ctrl+T", lambda: self._set_theater(not self._theater)),
            ("Ctrl+D", lambda: self.current_item and self.toggle_favorite(self.current_item)),
            ("Ctrl+P", self.picture_dialog),
            ("Ctrl+G", self.toggle_lossless),
            ("Ctrl+R", self.toggle_record),
            ("F2", self.open_guide),
            ("Ctrl+M", lambda: self._set_pip(not self._pip)),
        ]
        shortcuts += [("Ctrl+O", self.open_file_dialog), ("Ctrl+U", self.open_url_dialog),
                      ("Ctrl+E", lambda: self.export_dialog())]
        shortcuts += [(f"Ctrl+{i + 1}", (lambda i=i: self._select_tab(i))) for i in range(len(TABS))]
        for keys, fn in shortcuts:
            sc = QShortcut(QKeySequence(keys), self)
            sc.activated.connect(fn)

    def _post_show(self) -> None:
        tab = next((i for i, (k, _l) in enumerate(TABS) if k == self.settings["ui"].get("last_tab")), 0)
        self._select_tab(tab if tab != 4 else 0)
        self._reload_pages()
        if not self.headless:
            self._init_engine()
            handle = self.windowHandle()
            if handle is not None:
                handle.screenChanged.connect(lambda _s: self._update_screen())
        run_task(gpu.query_gpus, on_done=self._on_gpu)
        self._schedule_auto_refresh()
        QTimer.singleShot(300, self._resume_last_channel)
        ui = self.settings["ui"]
        if ui.get("update_check", True) and not self.headless and time.time() - float(ui.get("last_update_check") or 0) > 86400:
            QTimer.singleShot(8000, lambda: self.check_updates(manual=False))
        self._sched_timer = QTimer(self, interval=15000, timeout=self._sched_tick)
        self._sched_timer.start()
        QTimer.singleShot(2000, self._sched_tick)

    # ================================================================== motor
    def _init_engine(self) -> None:
        wid = self.player.host.native_id()
        eng = MpvEngine(self.settings, wid=wid, debug=self.debug,
                        on_event=lambda n, d: self.bridge.event.emit(n, d))
        try:
            eng.start()
        except EngineError as e:
            self.engine = None
            log.error("oynatıcı başlatılamadı: %s", e)
            self.player.set_idle("Oynatıcı bileşeni (libmpv) eksik",
                                 "Ayarlar → Sistem → 'mpv bileşenlerini indir' ile GitHub'dan indirin ya da "
                                 f"install.ps1'i çalıştırın.\n\n{e}")
            self._status(f"Oynatıcı başlatılamadı: {e}")
            return
        self.engine = eng
        self._update_screen()
        self._status(f"mpv {eng.version} hazır")
        self._update_system_info()

    def _update_screen(self) -> None:
        handle = self.windowHandle()
        screen = handle.screen() if handle else QGuiApplication.primaryScreen()
        if screen and self.engine:
            dpr = screen.devicePixelRatio()
            size = screen.size()
            self.engine.set_screen(int(size.width() * dpr), int(size.height() * dpr))

    def _on_engine_event(self, name: str, data: dict) -> None:
        req = self.current_req
        if name == "loading":
            self.player.show_video()
            self._status(f"Açılıyor: {data.get('title', '')}…")
        elif name in ("file-loaded", "playing"):
            if req:
                self._status(f"Oynatılıyor: {req.title}")
                QTimer.singleShot(1200, self._lossless_auto)
        elif name == "reconnecting":
            if data.get("max") == 1:     # bekçi: takılan yayın yeniden açılıyor (motor ekrana kendisi yazdı)
                self._status(f"{data.get('error') or 'Yayın takıldı'} — yeniden açılıyor…")
            else:
                msg = f"Bağlantı koptu — yeniden bağlanılıyor ({data['attempt']}/{data['max']})…"
                if data.get("error"):
                    msg += f"  {data['error']}"
                self._status(msg)
                if self.engine:
                    self.engine.show_text(msg, 2500)
        elif name == "lightened":
            self._status(f"Bilgisayar kare atlıyordu ({data.get('rate', 0):.1f}/sn): akıcılık için iyileştirme "
                         + ("hafifletildi (gürültü azaltma kapalı)." if data.get("level") == 1 else
                            "en aza indirildi (RTX VSR/yapay zekâ kapalı). Ayarlar değişince yeniden denenir."))
        elif name == "error":
            msg = data.get("message") or "Yayın açılamadı."
            self._status(f"⚠ {msg}")
            self.player.set_idle("Yayın açılamadı", msg)
            if req:
                self.player.set_now_playing(req.title, "", False)
        elif name == "ended":
            self._on_ended()
        elif name == "stopped":
            self.player.set_idle()
        elif name == "dropped":
            self.open_paths(data.get("files") or [])
        elif name == "ai_sub":
            self._on_ai_sub(data)
        elif name == "key":
            self._on_key(data.get("action", ""), data.get("args", []))
        elif name == "fullscreen":
            if data.get("value") != self._fs:
                self._set_fullscreen(bool(data.get("value")))
        elif name == "shutdown":
            self.engine = None
            self.player.set_idle("Oynatıcı kapandı", "Uygulamayı yeniden başlatın.")

    def _tick(self) -> None:
        if not self.engine or not self.current_req:
            return
        st = self.engine.tick()
        if not st:
            return
        self.player.set_status(st)
        if st.get("volume") is not None and int(st["volume"]) != self.settings["audio"]["volume"]:
            self.settings["audio"]["volume"] = int(st["volume"])
            self._save_timer.start()
        self.status_stats.setText(self._stats_text(st))
        req = self.current_req
        now = time.time()
        if req.kind in ("movie", "episode", "file", "url") and st.get("pos") and now - self._last_save > 10:
            self._last_save = now
            self.store.save_progress(req.key, req.title, req.logo, st["pos"], st.get("duration") or 0, req.meta)

    def _stats_text(self, st: dict) -> str:
        parts = []
        plan = st.get("vsr") or {}
        if st.get("vsr_active") and plan.get("out"):
            parts.append(f"<span style='color:{theme.NVIDIA}'>● RTX VSR {st['w']}×{st['h']} → "
                         f"{plan['out'][0]}×{plan['out'][1]}</span>")
        elif st.get("vsr_driver_failed"):
            parts.append("RTX VSR sürücüde kapalı (NVIDIA App → Video)")
        elif st.get("w"):
            parts.append(f"{st['w']}×{st['h']}")
        codec = str(st.get("codec") or "").upper()
        if codec:
            parts.append(codec + (f" ({st['hwdec']})" if st.get("hwdec") and st["hwdec"] != "no" else " (yazılım)"))
        if st.get("fps"):
            try:
                parts.append(f"{float(st['fps']):.0f} fps")
            except (TypeError, ValueError):
                pass
        if st.get("bitrate"):
            parts.append(f"{float(st['bitrate']) / 1e6:.1f} Mb/s")
        if st.get("kind") == "live" and st.get("cache") is not None:
            mode = opt.LATENCY_MODES[self.settings["latency"]["mode"]]["label"]
            parts.append(f"gecikme {st['cache']:.1f} sn · {mode}")
        if st.get("dropped"):
            parts.append(f"{st['dropped']} kare atlandı")
        return "  ·  ".join(parts)

    # ================================================================== oynatma
    def _start(self, req: PlayRequest) -> bool:
        if not req.url:
            self._status("⚠ Bu öğe için yayın adresi yok.")
            return False
        if not self.engine:
            try:
                launch_external(req, self.settings)
                self._status(f"Harici mpv ile açıldı: {req.title}")
                return True
            except EngineError as e:
                QMessageBox.warning(self, APP_NAME, f"Oynatıcı hazır değil.\n\n{e}")
                return False
        self.current_req = req
        self._last_save = time.time()
        self.player.show_video()
        self.player.set_now_playing(req.title, req.subtitle, req.kind == "live")
        try:
            self.engine.play(req)
        except EngineError as e:
            self._status(f"⚠ {e}")
            return False
        self._update_layout()
        return True

    def play_live(self, item: Item | None) -> None:
        if item is None:
            return
        src = self.ctx.source(item.source_id)
        url = catalog.play_url(self.store, item, self.settings, src)
        if item.extra_dict().get("drm"):
            self._status("⚠ Bu kanal DRM korumalı olabilir; oynatılamayabilir.")
        cur, nxt = self._now_next(item)
        sub = f"Şimdi: {cur['title']}" if cur else ""
        req = PlayRequest(url=url, title=item.name, kind="live", key=item.key, logo=item.logo,
                          headers=catalog.item_headers(item, src), subtitle=sub)
        if self.current_item and self.current_item.key != item.key:
            self.prev_item = self.current_item
        self.current_item = item
        self._episode_ctx = None
        if not self._start(req):
            return
        self.store.save_progress(item.key, item.name, item.logo, 0, 0)
        self.settings["ui"]["last_channel"] = [item.source_id, item.item_id]
        self._save_timer.start()
        self.live_page.model.set_playing(item.key)
        if self.epg_panel.item is None or self.epg_panel.item.key != item.key:
            self.epg_panel.show_channel(item)
        if self._theater and not self._fs:
            self._set_theater(False)
        self._osd_channel(item, cur, nxt)

    def _now_next(self, item: Item):
        cur, nxt = self.live_page.model.now_next(item)
        if cur is None and item.epg_id:
            nn = self.store.epg_now_next([(item.source_id, item.epg_id)])
            cur, nxt = nn.get((item.source_id, item.epg_id), (None, None))
        return cur, nxt

    def _osd_channel(self, item: Item, cur, nxt) -> None:
        if not self.engine:
            return
        row = self.live_page.model.row_of(item.key)
        num = f"{row + 1}  " if row >= 0 else ""
        lines = [f"{num}{item.name}"]
        if cur:
            lines.append(f"▶ {cur['title']}  ({time.strftime('%H:%M', time.localtime(cur['start']))}–"
                         f"{time.strftime('%H:%M', time.localtime(cur['stop']))})")
        if nxt:
            lines.append(f"Sonra: {nxt['title']}  ({time.strftime('%H:%M', time.localtime(nxt['start']))})")
        self.engine.show_text("\n".join(lines), 3500)

    def play_movie(self, item: Item | None, start=None) -> None:
        if item is None:
            return
        src = self.ctx.source(item.source_id)
        title = item.name if (not item.year or item.year in item.name) else f"{item.name} ({item.year})"
        req = PlayRequest(url=catalog.play_url(self.store, item, self.settings, src), title=title, kind="movie",
                          key=item.key, logo=item.logo, headers=catalog.item_headers(item, src),
                          start=float(start or 0), subtitle="Film")
        self.current_item = None
        self._episode_ctx = None
        self.live_page.model.set_playing(None)
        if self._start(req):
            self._set_theater(True)

    def play_episode(self, series: Item, ep: dict, episodes: list, start=None) -> None:
        src = self.ctx.source(series.source_id)
        url = ep.get("url") or ""
        if not url and src and src.get("kind") == "xtream":
            url = catalog.client_for(src, self.settings).episode_url(ep["id"], ep.get("ext"))
        label = f"S{int(ep.get('season') or 1):02d}B{int(ep.get('episode') or 0):02d}"
        ep_title = (ep.get("title") or "").strip()
        title = f"{series.name} — {label}" + (f" · {ep_title}" if ep_title and series.name not in ep_title else "")
        meta = {"series_id": series.item_id, "season": ep.get("season"), "episode": ep.get("episode"),
                "ext": ep.get("ext", ""), "url": ep.get("url", ""), "ep_title": ep_title}
        headers = catalog.item_headers({"headers": ep.get("headers") or {}}, src)
        req = PlayRequest(url=url, title=title, kind="episode", key=(series.source_id, "episode", ep["id"]),
                          logo=ep.get("image") or series.logo, headers=headers, start=float(start or 0),
                          subtitle=f"{label}", meta=meta)
        self.current_item = None
        self.live_page.model.set_playing(None)
        idx = next((i for i, e in enumerate(episodes) if e["id"] == ep["id"]), 0)
        self._episode_ctx = {"series": series, "episodes": episodes, "index": idx}
        if self._start(req):
            self._set_theater(True)

    def _step_episode(self, delta: int) -> bool:
        ctx = self._episode_ctx
        if not ctx:
            return False
        i = ctx["index"] + delta
        if 0 <= i < len(ctx["episodes"]):
            self.play_episode(ctx["series"], ctx["episodes"][i], ctx["episodes"], 0)
            return True
        return False

    def play_catchup(self, item: Item, prog: dict) -> None:
        src = self.ctx.source(item.source_id) or {}
        dur_min = max(1, math.ceil((prog["stop"] - prog["start"]) / 60))
        url = None
        if src.get("kind") == "xtream":
            tz = ((src.get("info") or {}).get("account") or {}).get("timezone")
            url = catalog.client_for(src, self.settings).timeshift_url(item.item_id, prog["start"], dur_min, tz)
        else:
            catch = item.extra_dict().get("catchup") or {}
            url = epg.catchup_url(item.url, catch, prog["start"], prog["stop"])
        if not url:
            self._status("⚠ Bu kanal için geri izleme adresi oluşturulamadı.")
            return
        req = PlayRequest(url=url, title=f"{item.name} — {prog['title']}", kind="catchup",
                          key=(item.source_id, "catchup", item.item_id), logo=item.logo,
                          headers=catalog.item_headers(item, src),
                          subtitle=f"Geri izleme · {time.strftime('%d.%m %H:%M', time.localtime(prog['start']))}")
        if self._start(req):
            self.player.set_now_playing(req.title, req.subtitle, False)

    def play_history(self, h: dict | None) -> None:
        if not isinstance(h, dict):
            return
        sid, kind, item_id = h["source_id"], h["kind"], h["item_id"]
        finished = h.get("duration") and h["position"] >= h["duration"] * 0.94
        start = 0 if finished else h.get("position") or 0
        extra = h.get("extra") or {}
        if kind in ("file", "image"):
            path = extra.get("path", "")
            if not os.path.exists(path):
                self._status(f"⚠ Dosya bulunamadı: {path}")
                return
            self._file_queue = [path]
            self.play_file(path, start=start, index=0)
            return
        if kind == "url":
            self.open_url(extra.get("source_url", ""))
            return
        if kind == "live":
            self.play_live(self.store.item(sid, "live", item_id))
        elif kind == "movie":
            self.play_movie(self.store.item(sid, "movie", item_id), start)
        elif kind == "episode":
            extra = h.get("extra") or {}
            series = self.store.item(sid, "series", extra.get("series_id", ""))
            if series is None:
                self._status("⚠ Dizi artık listede yok.")
                return
            ep = {"id": item_id, "season": extra.get("season") or 1, "episode": extra.get("episode") or 0,
                  "ext": extra.get("ext") or "", "url": extra.get("url") or "", "title": extra.get("ep_title", "")}
            cached = self.ctx.series_cache.get(series.key)
            episodes = (cached or {}).get("episodes") or [ep]
            ep = next((e for e in episodes if e["id"] == item_id), ep)
            self.play_episode(series, ep, episodes if ep in episodes else [ep], start)

    # ================================================================== kendi dosyalarım / bağlantılar
    def _fill_open_menu(self) -> None:
        m = self.open_menu
        m.clear()
        m.addAction("🎞  Video ya da fotoğraf aç…   (Ctrl+O)", self.open_file_dialog)
        m.addAction("🔗  Bağlantı aç (YouTube, m3u8, mp4 …)…   (Ctrl+U)", self.open_url_dialog)
        m.addAction("⇪  4K olarak kaydet (yapay zekâ)…   (Ctrl+E)", lambda: self.export_dialog())
        recent = [h for h in self.store.history(("file", "image", "url"), limit=10)]
        if recent:
            m.addSeparator()
            for h in recent[:8]:
                m.addAction(f"🕘  {h['title']}", lambda h=h: self.play_history(h))

    def open_file_dialog(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(upscale.VIDEO_EXTS | upscale.IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Video ya da fotoğraf aç (4K'ya yükseltilir)",
                                                self.settings["ui"].get("last_dir", ""),
                                                f"Video ve fotoğraflar ({exts});;Tüm dosyalar (*)")
        if files:
            self.settings["ui"]["last_dir"] = str(Path(files[0]).parent)
            self._save_timer.start()
            self.open_paths(files)

    def open_url_dialog(self) -> None:
        text, ok = QInputDialog.getText(self, "Bağlantı aç", "Video bağlantısı (YouTube, Instagram, m3u8, mp4 …):")
        if ok and text.strip():
            self.open_paths([text.strip()])

    def open_paths(self, items: list[str]) -> None:
        """Dosya, fotoğraf, klasör, M3U listesi ya da bağlantı: hepsi aynı 4K (RTX VSR / yapay zekâ) zincirinden."""
        files: list[str] = []
        for raw in items:
            item = str(raw).strip().strip('"')
            if item.startswith("file://"):
                from urllib.parse import unquote, urlsplit
                item = unquote(urlsplit(item).path.lstrip("/") if os.name == "nt" else urlsplit(item).path)
            if weburl.is_url(item):
                self.open_url(item)
                return
            p = Path(item)
            if p.is_dir():
                files += sorted(str(f) for f in p.iterdir()
                                if f.suffix.lower() in upscale.VIDEO_EXTS | upscale.IMAGE_EXTS)
            elif p.suffix.lower() in (".m3u", ".m3u8") and p.is_file():
                sid = self.store.add_source(name=p.stem, kind="m3u", url=str(p))
                self._on_sources_changed()
                self.refresh(sid)
                self._status(f"Liste kaynak olarak eklendi: {p.name}")
            elif p.is_file():
                files.append(str(p))
        if files:
            self._file_queue = files
            self.play_file(files[0], index=0)

    def _file_key(self, path: str) -> tuple:
        return (0, "file", hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:16])

    def play_file(self, path: str, start=None, index: int | None = None) -> None:
        image = upscale.kind_of(path) == "image"
        key = self._file_key(path)
        if start is None and not image:
            prog = self.store.get_progress(key)
            start = prog[0] if prog and prog[0] > 60 and (not prog[1] or prog[0] < prog[1] * 0.94) else 0
        if index is not None:
            self._file_index = index
        queue = getattr(self, "_file_queue", [])
        sub = f"{(self._file_index or 0) + 1}/{len(queue)}" if len(queue) > 1 else ("Fotoğraf" if image else "Video")
        req = PlayRequest(url=path, title=Path(path).name, kind="image" if image else "file", key=key,
                          start=float(start or 0), subtitle=sub, meta={"path": path})
        self.current_item = None
        self._episode_ctx = None
        self.live_page.model.set_playing(None)
        if self._start(req):
            self._set_theater(True)
            self.store.save_progress(key, req.title, "", float(start or 0), 0, {"path": path})

    def _step_file(self, delta: int) -> bool:
        queue = getattr(self, "_file_queue", [])
        i = getattr(self, "_file_index", 0) + delta
        if 0 <= i < len(queue):
            self.play_file(queue[i], index=i)
            return True
        return False

    def open_url(self, url: str) -> None:
        self._status(f"Bağlantı çözülüyor: {url}")

        def done(r):
            kind = "live" if r.get("live") else "url"
            title = r.get("title") or url
            key = (0, "url", hashlib.sha1(url.encode("utf-8")).hexdigest()[:16])
            prog = self.store.get_progress(key) if kind == "url" else None
            start = prog[0] if prog and prog[0] > 60 and (not prog[1] or prog[0] < prog[1] * 0.94) else 0
            req = PlayRequest(url=r["url"], title=title, kind=kind, key=key, headers=r.get("headers") or {},
                              start=start, subtitle="Bağlantı" + (f" · {r['height']}p kaynak" if r.get("height") else ""),
                              meta={"audio": r.get("audio"), "source_url": url})
            self.current_item = None
            self._episode_ctx = None
            if self._start(req):
                self._set_theater(True)
                self.store.save_progress(key, title, "", start, 0, {"source_url": url})

        run_task(weburl.resolve, url, on_done=done,
                 on_error=lambda e: self._status(f"⚠ Bağlantı açılamadı: {e}"))

    def export_dialog(self, files: list[str] | None = None) -> None:
        from .export_dialog import ExportDialog
        if files is None and self.current_req and self.current_req.kind in ("file", "image"):
            files = [self.current_req.meta.get("path")]
        dlg = ExportDialog(self.settings, files or [], self)
        dlg.finished_file.connect(lambda path: self._status(f"✔ 4K kaydedildi: {path}"))
        dlg.exec()
        self._save_timer.start()

    def dragEnterEvent(self, event) -> None:
        md = event.mimeData()
        if md.hasUrls() or md.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        md = event.mimeData()
        items = [u.toLocalFile() if u.isLocalFile() else u.toString() for u in md.urls()] if md.hasUrls() \
            else [md.text()]
        event.acceptProposedAction()
        self.open_paths([i for i in items if i])
        self.raise_()
        self.activateWindow()

    def open_series(self, item: Item | None) -> None:
        if item is None:
            return
        self._select_tab(2)
        self.series_page.details_widget.show_item(item)
        self.series_page.select_key(item.key)

    def _on_ended(self) -> None:
        req = self.current_req
        if not req:
            return
        if req.kind in ("movie", "episode", "file", "url"):
            st_dur = self.engine.status().get("duration") if self.engine else None
            dur = st_dur or 1
            self.store.save_progress(req.key, req.title, req.logo, dur, dur, req.meta)
        if req.kind == "episode" and self.settings["ui"]["auto_next_episode"] and self._step_episode(1):
            self._status("Sonraki bölüm oynatılıyor…")
            return
        if req.kind == "file" and self._step_file(1):
            return
        self.current_req = None
        self.player.set_idle("Bitti", f"{req.title}")
        if self._fs:
            self._set_fullscreen(False)
        self._set_theater(False)
        self._refresh_progress_views()

    def stop(self) -> None:
        if self.engine:
            self.engine.stop()
        self.current_req = None
        self.current_item = None
        self.live_page.model.set_playing(None)
        if self._fs:
            self._set_fullscreen(False)
        self._set_theater(False)
        self.player.set_idle()
        self.status_stats.setText("")
        self._refresh_progress_views()

    def open_external(self, item: Item | None) -> None:
        req = self.current_req
        if item is not None:
            src = self.ctx.source(item.source_id)
            req = PlayRequest(url=catalog.play_url(self.store, item, self.settings, src), title=item.name,
                              kind="live" if item.kind == "live" else "movie", key=item.key,
                              headers=catalog.item_headers(item, src))
        if req is None:
            return
        try:
            launch_external(req, self.settings)
            self._status(f"Ayrı mpv penceresinde açıldı: {req.title}")
        except EngineError as e:
            QMessageBox.warning(self, APP_NAME, str(e))

    def _resume_of(self, item: Item | None) -> float:
        if item is None:
            return 0.0
        prog = self.store.get_progress(item.key)
        if prog and prog[0] > 60 and (not prog[1] or prog[0] < prog[1] * 0.94):
            return prog[0]
        return 0.0

    def _resume_last_channel(self) -> None:
        last = self.settings["ui"].get("last_channel")
        if not (self.settings["ui"]["resume_last_channel"] and self.engine and isinstance(last, list) and len(last) == 2):
            return
        item = self.store.item(int(last[0]), "live", str(last[1]))
        if item:
            self.play_live(item)
            self.live_page.select_key(item.key)

    # ================================================================== tuşlar
    def _on_key(self, action: str, args: list) -> None:
        req = self.current_req
        live = bool(req and req.kind == "live")
        eng = self.engine
        if req and req.kind in ("file", "image") and action in ("next", "prev", "up", "down", "pgup", "pgdn") and (
                action in ("next", "prev") or req.kind == "image"):
            self._step_file(1 if action in ("next", "down", "pgdn") else -1)
            return
        if action in ("up", "down"):
            if live:
                self.zap(-1 if action == "up" else 1)
            elif eng:
                eng.seek(60 if action == "up" else -60)
        elif action in ("next", "prev"):
            if live:
                self.zap(1 if action == "next" else -1)
            elif not self._step_episode(1 if action == "next" else -1) and eng:
                eng.seek(60 if action == "next" else -60)
        elif action in ("pgup", "pgdn"):
            if live:
                self.zap(-10 if action == "pgup" else 10)
            elif eng:
                eng.seek(600 if action == "pgup" else -600)
        elif action in ("left", "right") and eng:
            eng.seek(-10 if action == "left" else 10)
        elif action == "digit" and args:
            if live or not req:
                self._digits = (self._digits + args[0])[-4:]
                if eng:
                    eng.show_text(f"Kanal: {self._digits}_", 1700)
                self._digit_timer.start()
            elif eng:
                eng.command("seek", str(int(args[0]) * 10), "absolute-percent")
        elif action == "enter":
            if self._digits:
                self._commit_digits()
            else:
                self._show_info()
        elif action == "esc" and self._pip:
            self._set_pip(False)
        elif action == "fullscreen" and self._pip:
            self._set_pip(False)
        elif action == "esc":
            if self._fs:
                self._set_fullscreen(False)
            elif self._theater:
                self._set_theater(False)
        elif action == "fullscreen":
            self._set_fullscreen(not self._fs)
        elif action == "theater":
            self._set_theater(not self._theater)
        elif action == "last":
            if self.prev_item:
                self.play_live(self.prev_item)
        elif action == "info":
            self._show_info()
        elif action == "epg":
            self._show_epg_osd()
        elif action == "live" and eng:
            eng.go_live()
            eng.show_text("Canlı yayına dönüldü", 1500)
        elif action == "pause" and eng:
            eng.toggle_pause()
        elif action == "stop":
            self.stop()

    def zap(self, delta: int) -> None:
        items = self.live_page.model.items
        if not items:
            return
        i = self.live_page.model.row_of(self.current_item.key) if self.current_item else -1
        if i < 0:
            i = self.live_page.view.currentIndex().row()
        j = (i + delta) % len(items) if i >= 0 else 0
        item = items[j]
        self.play_live(item)
        self.live_page.select_key(item.key)

    def _commit_digits(self) -> None:
        digits, self._digits = self._digits, ""
        self._digit_timer.stop()
        if not digits:
            return
        n = int(digits)
        items = self.live_page.model.items
        if 1 <= n <= len(items):
            self.play_live(items[n - 1])
            self.live_page.select_key(items[n - 1].key)
        elif self.engine:
            self.engine.show_text(f"Kanal {n} yok (1–{len(items)})", 1800)

    def _show_info(self) -> None:
        if not self.engine or not self.current_req:
            return
        st = self.engine.status()
        plan = st.get("vsr") or {}
        lines = [self.current_req.title]
        if self.current_req.subtitle:
            lines.append(self.current_req.subtitle)
        lines.append(plan.get("reason") or "")
        tech = [str(st.get("codec") or "").upper(), st.get("hwdec") or "yazılım"]
        if st.get("fps"):
            tech.append(f"{float(st['fps']):.0f} fps")
        if st.get("bitrate"):
            tech.append(f"{float(st['bitrate']) / 1e6:.1f} Mb/s")
        lines.append(" · ".join(t for t in tech if t))
        if st.get("kind") == "live" and st.get("cache") is not None:
            lines.append(f"Gecikme: {st['cache']:.1f} sn ({opt.LATENCY_MODES[self.settings['latency']['mode']]['label']})")
        elif st.get("duration"):
            lines.append(f"{fmt_clock(st.get('pos'))} / {fmt_clock(st['duration'])}")
        self.engine.show_text("\n".join(l for l in lines if l), 5000)

    def _show_epg_osd(self) -> None:
        if not self.engine or not self.current_item:
            return
        cur, nxt = self._now_next(self.current_item)
        self._osd_channel(self.current_item, cur, nxt)

    # ================================================================== düzen
    def _select_tab(self, i: int) -> None:
        b = self.nav.button(i)
        if b:
            b.setChecked(True)
        self._on_tab(i)

    def _tab_key(self) -> str:
        return TABS[self.pages.currentIndex()][0]

    def _on_tab(self, i: int) -> None:
        self.pages.setCurrentIndex(i)
        key = TABS[i][0]
        if key != "settings":
            self.settings["ui"]["last_tab"] = key
            self._save_timer.start()
        if self._theater:
            self._set_theater(False)
        page = self._search_page()
        self.search.blockSignals(True)
        self.search.setText(getattr(page, "_search", "") if page else "")
        self.search.blockSignals(False)
        self.search.setEnabled(page is not None)
        if key == "fav":
            self.fav_page.reload()
        elif key == "settings":
            self.settings_page.reload_sources()
            self._update_system_info()
        self._update_layout()

    def _update_layout(self) -> None:
        if self._fs:
            return
        key = self._tab_key()
        playing = self.current_req is not None
        self.pages.setVisible(not self._theater)
        self.right.setVisible(key == "live" or playing or self._theater)
        self.epg_panel.setVisible(key == "live" and not self._theater)

    def _set_theater(self, on: bool) -> None:
        self._theater = bool(on)
        self.player.btn_theater.setToolTip("Listeleri göster (T)" if on else "Sinema modu: listeleri gizle (T)")
        self._update_layout()

    def _set_fullscreen(self, on: bool) -> None:
        if on == self._fs:
            return
        self._fs = on
        if on:
            self._pre_fs = {"max": self.isMaximized(), "theater": self._theater}
            for w in (self.topbar, self.pages, self.epg_panel, self.player.bar):
                w.hide()
            self.statusBar().hide()
            self.right.show()
            self.showFullScreen()
            self.player.host.setFocus()
        else:
            self.topbar.show()
            self.statusBar().show()
            self.player.bar.show()
            if self._pre_fs.get("max"):
                self.showMaximized()
            else:
                self.showNormal()
            self._theater = self._pre_fs.get("theater", False)
            self._update_layout()
        if self.engine:
            self.engine.sync_fullscreen(on)
        if self.settings["lossless"].get("mode") == "fullscreen" and self.current_req:
            QTimer.singleShot(700 if on else 0, lambda: self.toggle_lossless(quiet=True, want=on))

    def _focus_search(self) -> None:
        if self._fs:
            self._set_fullscreen(False)
        self.search.setFocus()
        self.search.selectAll()

    def _search_page(self):
        return {"live": self.live_page, "movie": self.movies_page, "series": self.series_page}.get(self._tab_key())

    def _apply_search(self) -> None:
        page = self._search_page()
        if page:
            page.set_search(self.search.text())

    # ================================================================== veri / yenileme
    def _reload_pages(self) -> None:
        has = bool(self.store.list_sources())
        self.live_page.set_has_sources(has)
        for p in (self.live_page, self.movies_page, self.series_page):
            p.reload()
        if self._tab_key() == "fav":
            self.fav_page.reload()
        self.settings_page.reload_sources()

    def _on_sources_changed(self) -> None:
        self.ctx.invalidate()
        self._reload_pages()

    def _schedule_auto_refresh(self) -> None:
        hours = self.settings["ui"]["auto_refresh_hours"]
        now = time.time()
        for s in self.store.list_sources(enabled_only=True):
            if not s.get("last_refresh") or (hours and now - s["last_refresh"] > hours * 3600):
                self._refresh_jobs.append(("catalog", s["id"]))
            elif not s.get("last_epg") or now - s["last_epg"] > 12 * 3600:
                self._refresh_jobs.append(("epg", s["id"]))
        self._run_refresh()

    def refresh(self, source_id, epg_only: bool = False) -> None:
        ids = [source_id] if source_id else [s["id"] for s in self.store.list_sources(enabled_only=True)]
        for sid in ids:
            job = ("epg" if epg_only else "catalog", sid)
            if job not in self._refresh_jobs:
                self._refresh_jobs.append(job)
        self._run_refresh()

    def _run_refresh(self) -> None:
        if self._refreshing or not self._refresh_jobs:
            return
        kind, sid = self._refresh_jobs.pop(0)
        src = self.store.get_source(sid)
        if not src:
            self._run_refresh()
            return
        self._refreshing = True
        self.refresh_btn.setEnabled(False)
        fn = catalog.refresh_epg if kind == "epg" else catalog.refresh_source

        def done(result):
            self._refreshing = False
            self.refresh_btn.setEnabled(True)
            self.ctx.invalidate()
            if kind == "catalog":
                c = result or {}
                self._status(f"✔ {src['name']}: {c.get('live', 0)} kanal, {c.get('movie', 0)} film, "
                             f"{c.get('series', 0)} dizi")
                self._reload_pages()
                if ("epg", sid) not in self._refresh_jobs and catalog.epg_url_for(src, self.settings):
                    self._refresh_jobs.append(("epg", sid))
            else:
                n_prog = (result or (0, 0))[0]
                self._status(f"✔ {src['name']}: yayın akışı güncellendi ({n_prog} program)")
                self.live_page.refresh_epg()
                if self.epg_panel.item:
                    self.epg_panel.show_channel(self.epg_panel.item)
            self._run_refresh()

        def fail(err):
            self._refreshing = False
            self.refresh_btn.setEnabled(True)
            self._status(f"⚠ {src['name']}: {err}")
            self.settings_page.reload_sources()
            self._run_refresh()

        run_task(fn, self.store, src, self.settings, on_done=done, on_error=fail, on_progress=self._status)

    def toggle_favorite(self, item: Item | None) -> None:
        if item is None:
            return
        on = self.store.toggle_favorite(item.key)
        self._status(f"{'★ Favorilere eklendi' if on else '☆ Favorilerden çıkarıldı'}: {item.name}")
        for p in (self.live_page, self.movies_page, self.series_page):
            p.refresh_favs()
        self.movies_page.details_widget.refresh_buttons()
        if self.series_page.details_widget.item and self.series_page.details_widget.item.key == item.key:
            self.series_page.details_widget.btn_fav.setText("★" if on else "☆")
        if self._tab_key() == "fav":
            self.fav_page.reload()

    def _refresh_progress_views(self) -> None:
        self.movies_page.after_items()
        self.movies_page.details_widget.refresh_buttons()
        if self._tab_key() == "fav":
            self.fav_page.reload()

    def _clear_history(self) -> None:
        if QMessageBox.question(self, APP_NAME, "İzleme geçmişi ve kaldığın yer bilgileri silinsin mi?") == QMessageBox.Yes:
            self.store.clear_history()
            self._refresh_progress_views()
            self._status("İzleme geçmişi temizlendi.")

    # ================================================================== ayarlar / sistem
    def _on_settings_changed(self) -> None:
        self._save_timer.start()
        if self.engine:
            self.engine.apply_settings(self.settings)
        hide = self.settings["ui"]["hide_adult"]
        if getattr(self, "_last_hide_adult", hide) != hide:
            self._reload_pages()
        self._last_hide_adult = hide

    def _save_settings(self) -> None:
        try:
            self.settings["ui"]["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
            save_settings(self.settings, paths.settings_path())
        except OSError as e:
            log.warning("ayarlar kaydedilemedi: %s", e)

    def restore_geometry(self) -> None:
        from PySide6.QtCore import QByteArray
        geo = self.settings["ui"].get("geometry")
        if isinstance(geo, str) and geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))

    def _on_gpu(self, gpus: list) -> None:
        self._gpu = gpus[0] if gpus else None
        self._gpu_assess = gpu.assess(self._gpu)
        vendor = self._gpu_assess.get("vendor") or ""
        if vendor != self.settings["video"].get("gpu_vendor"):
            # AMD/Intel kartta büyütücü AMD FSR olur (canlı yayın dahil); ayarlar yeniden uygulanır
            self.settings["video"]["gpu_vendor"] = vendor
            self._save_timer.start()
            if self.engine:
                self.engine.apply_settings(self.settings)
        if self.engine and opt.is_windows():
            # RTX değilse d3d11vpp'nin sıradan ölçeklemesi yerine mpv + yapay zekâ büyütücü kullanılır
            self.engine.set_vsr_available(bool(self._gpu_assess.get("vsr")))
        if self._gpu:
            ok = self._gpu_assess.get("vsr")
            self.gpu_badge.setObjectName("BadgeNv" if ok else "Badge")
            short = re.sub(r"^(NVIDIA GeForce|AMD Radeon\(TM\)|AMD Radeon|Intel\(R\))\s*", "", self._gpu["name"])
            state = ("RTX VSR hazır" if ok else "AMD FSR" if vendor in ("amd", "intel")
                     and self.settings["video"].get("amd_fsr", True) else "VSR yok")
            self.gpu_badge.setText(f"{short} · {state}")
            ok = ok or state == "AMD FSR"
            self.gpu_badge.setToolTip("\n".join(self._gpu_assess.get("notes", [])))
            self.gpu_badge.style().unpolish(self.gpu_badge)
            self.gpu_badge.style().polish(self.gpu_badge)
            self.gpu_badge.show()
        self._update_system_info()

    def _update_system_info(self) -> None:
        g = self._gpu
        a = self._gpu_assess or gpu.assess(g)
        lines = [f"<b>{APP_NAME} {__version__}</b>"]
        if g:
            lines.append(f"Ekran kartı: <b>{g['name']}</b> · sürücü {g['driver']} · {g.get('memory_mb', 0)} MB")
            lines.append(f"RTX Video Super Resolution: <b>{'kullanılabilir' if a.get('vsr') else 'kullanılamıyor'}</b> · "
                         f"RTX Video HDR: <b>{'kullanılabilir' if a.get('hdr') else 'kullanılamıyor'}</b>")
        else:
            lines.append("Ekran kartı: NVIDIA bulunamadı.")
        for n in a.get("notes", []):
            lines.append(f"• {n}")
        if self.engine:
            v = self.engine.version_tuple
            warn = "" if v >= (0, 39, 0) else " — <span style='color:#ff5c7a'>RTX VSR için mpv ≥ 0.39 gerekir; güncelleyin</span>"
            lines.append(f"Oynatıcı: {self.engine.version}{warn}")
        else:
            lines.append("Oynatıcı: libmpv yüklenemedi — 'mpv bileşenlerini indir' düğmesini kullanın.")
        screen = QGuiApplication.primaryScreen()
        if screen:
            dpr = screen.devicePixelRatio()
            lines.append(f"Ekran: {int(screen.size().width() * dpr)}×{int(screen.size().height() * dpr)} @ "
                         f"{screen.refreshRate():.0f} Hz")
        lines.append(f"Veri klasörü: {paths.data_dir()}")
        self.settings_page.set_system_info("<br>".join(lines))

    def fetch_mpv(self) -> None:
        from ..tools import fetch_mpv as fm
        self._status("mpv bileşenleri GitHub'dan indiriliyor…")

        def done(info):
            self._status(f"✔ mpv indirildi: {info.get('tag', '')}")
            if self.engine is None:
                self._init_engine()
                QMessageBox.information(self, APP_NAME, "mpv bileşenleri kuruldu." +
                                        ("" if self.engine else " Uygulamayı yeniden başlatın."))
            else:
                QMessageBox.information(self, APP_NAME, "mpv güncellendi. Yeni sürüm uygulama yeniden başlatılınca "
                                                        "kullanılır.")

        run_task(fm.install, on_done=done, on_error=lambda e: self._status(f"⚠ mpv indirilemedi: {e}"),
                 on_progress=self._status)

    def test_vsr(self) -> None:
        """Ayrı küçük bir mpv penceresinde d3d11vpp + RTX VSR denemesi; sonucu sürücü günlüğünden okur."""
        from .. import selftest
        if not opt.is_windows():
            QMessageBox.information(self, APP_NAME, "RTX Video Super Resolution yalnızca Windows'ta çalışır.")
            return
        self._status("RTX VSR testi çalışıyor (birkaç saniye bir test penceresi açılır)…")

        def done(r):
            self._status("RTX VSR testi bitti.")
            box = QMessageBox(self)
            box.setWindowTitle("RTX VSR testi")
            box.setIcon(QMessageBox.Information if r.get("vsr") == "enabled" and r.get("scaled") else QMessageBox.Warning)
            box.setText(selftest.summary(r))
            if r.get("log"):
                box.setDetailedText("\n".join(r["log"]))
            box.exec()

        run_task(selftest.run, hdr=bool(self.settings["video"]["rtx_hdr"]), on_done=done,
                 on_error=lambda e: QMessageBox.warning(self, APP_NAME, f"Test çalıştırılamadı: {e}"))

    def _on_volume(self, value: int) -> None:
        if self.engine:
            self.engine._set("volume", str(value))
        self.settings["audio"]["volume"] = int(value)
        self._save_timer.start()

    # ================================================================== ses izi / altyazı / görüntü menüleri
    @staticmethod
    def _track_label(t: dict) -> str:
        lang = (t.get("lang") or "").lower()
        names = {"tr": "Türkçe", "tur": "Türkçe", "en": "İngilizce", "eng": "İngilizce", "de": "Almanca",
                 "ger": "Almanca", "deu": "Almanca", "ar": "Arapça", "ara": "Arapça", "fr": "Fransızca",
                 "fre": "Fransızca", "fra": "Fransızca", "ru": "Rusça", "rus": "Rusça", "es": "İspanyolca",
                 "spa": "İspanyolca"}
        parts = [names.get(lang, lang.upper())] if lang else []
        if t.get("title"):
            parts.append(t["title"])
        if t.get("codec"):
            parts.append(t["codec"])
        if t.get("type") == "audio" and t.get("channels"):
            parts.append(f"{t['channels']} kanal")
        if t.get("external"):
            parts.append("dış dosya")
        return f"{t['id']}. " + (" · ".join(parts) or "İz")

    def _menu_action(self, menu: QMenu, text: str, fn, checked: bool | None = None, enabled: bool = True):
        a = menu.addAction(text)
        if checked is not None:
            a.setCheckable(True)
            a.setChecked(checked)
        a.setEnabled(enabled)
        a.triggered.connect(lambda _c=False: fn())
        return a

    def _fill_audio_menu(self) -> None:
        m = self.player.menus["audio"]
        m.clear()
        tracks = [t for t in (self.engine.tracks() if self.engine and self.current_req else []) if t["type"] == "audio"]
        if not tracks:
            m.addAction("Ses izi yok").setEnabled(False)
        for t in tracks:
            self._menu_action(m, self._track_label(t), lambda t=t: self.engine.set_track("audio", t["id"]),
                              t["selected"])
        m.addSeparator()
        sub = m.addMenu("Ses gecikmesi")
        for d, txt in ((-0.1, "−100 ms"), (0.1, "+100 ms")):
            self._menu_action(sub, txt, lambda d=d: self._nudge("audio-delay", d, "Ses gecikmesi"))
        self._menu_action(sub, "Sıfırla", lambda: self._reset_prop("audio-delay", "Ses gecikmesi"))

    def _fill_sub_menu(self) -> None:
        m = self.player.menus["sub"]
        m.clear()
        playing = bool(self.engine and self.current_req)
        tracks = [t for t in (self.engine.tracks() if playing else []) if t["type"] == "sub"]
        any_sel = any(t["selected"] for t in tracks)
        self._menu_action(m, "Kapalı", lambda: self.engine.set_track("sub", None), not any_sel, playing)
        for t in tracks:
            self._menu_action(m, self._track_label(t), lambda t=t: self.engine.set_track("sub", t["id"]), t["selected"])
        m.addSeparator()
        vod = playing and self.current_req.kind not in ("live", "image")
        self._menu_action(m, "📄 Dosyadan altyazı ekle…", self.add_sub_file, enabled=playing)
        self._menu_action(m, "🌐 İnternetten altyazı bul (OpenSubtitles)…", self.online_subs, enabled=vod)
        running = self._ai_task is not None
        self._menu_action(m, "🤖 Yapay zekâ ile altyazı (konuşmadan)…" + (" — çalışıyor" if running else ""),
                          self.ai_subs_dialog, enabled=vod or running)
        if running:
            self._menu_action(m, "■ Yapay zekâ altyazıyı durdur", self._stop_ai_subs)
        m.addSeparator()
        timing = m.addMenu("Zamanlama (senkron)")
        for d, txt in ((-0.5, "0,5 sn erken göster"), (0.5, "0,5 sn geç göster"), (-0.1, "0,1 sn erken"),
                       (0.1, "0,1 sn geç")):
            self._menu_action(timing, txt, lambda d=d: self._nudge("sub-delay", d, "Altyazı gecikmesi"), enabled=playing)
        self._menu_action(timing, "Sıfırla", lambda: self._reset_prop("sub-delay", "Altyazı gecikmesi"), enabled=playing)
        look = m.addMenu("Görünüm")
        st = self.settings["subtitles"]
        self._menu_action(look, "Büyüt  (A+)", lambda: self._sub_style("size", min(90, st["size"] + 4)))
        self._menu_action(look, "Küçült (A−)", lambda: self._sub_style("size", max(20, st["size"] - 4)))
        look.addSeparator()
        self._menu_action(look, "Kalın kenarlı yazı", lambda: self._sub_style("style", "outline"), st["style"] == "outline")
        self._menu_action(look, "Yarı saydam kutu içinde", lambda: self._sub_style("style", "box"), st["style"] == "box")
        look.addSeparator()
        self._menu_action(look, "Beyaz", lambda: self._sub_style("color", "white"), st["color"] == "white")
        self._menu_action(look, "Sarı", lambda: self._sub_style("color", "yellow"), st["color"] == "yellow")
        look.addSeparator()
        self._menu_action(look, "Yukarı taşı", lambda: self._nudge("sub-pos", -3, "Altyazı konumu"), enabled=playing)
        self._menu_action(look, "Aşağı taşı", lambda: self._nudge("sub-pos", 3, "Altyazı konumu"), enabled=playing)

    def _fill_picture_menu(self) -> None:
        m = self.player.menus["picture"]
        m.clear()
        self._menu_action(m, "🎨 Görüntü ayarları…  (Ctrl+P)", self.picture_dialog)
        m.addSeparator()
        cur = self.settings["picture"].get("preset", "natural")
        for key in ("natural", "vivid", "cinema", "sports", "noisy"):
            self._menu_action(m, opt.PRESET_LABELS[key], lambda k=key: self._apply_preset(k), cur == key)
        if cur == "custom":
            self._menu_action(m, opt.PRESET_LABELS["custom"], lambda: None, True)
        m.addSeparator()
        dn = m.addMenu("Karıncalanma azaltma")
        for val, txt in (("off", "Kapalı"), ("auto", "Otomatik"), ("light", "Hafif"), ("medium", "Orta"),
                         ("strong", "Güçlü")):
            self._menu_action(dn, txt, lambda v=val: self._set_picture("picture", "denoise", v),
                              self.settings["picture"]["denoise"] == val)
        m.addSeparator()
        self._menu_action(m, "⚡ Lossless Scaling kare üretimi" + (" — açık" if self._ls_active else "")
                          + "  (Ctrl+G)", self.toggle_lossless, self._ls_active)
        sh = m.addMenu("Keskinlik")
        for val, txt in (("off", "Kapalı"), ("light", "Hafif"), ("medium", "Orta"), ("strong", "Güçlü")):
            self._menu_action(sh, txt, lambda v=val: self._set_picture("video", "sharpen", v),
                              self.settings["video"]["sharpen"] == val)

    # ------------------------------------------------------------------ Lossless Scaling
    def toggle_lossless(self, quiet: bool = False, want: bool | None = None) -> None:
        """Lossless Scaling'i (kuruluysa) çalıştırır ve Heloo TV penceresi öndeyken "Ölçekle" kısayolunu gönderir.
        Kısayol aç/kapa çalışır; durum burada izlenir ve açıkken mpv interpolasyonu kapanır.
        want: True/False istenen durum (zaten öyleyse bir şey yapılmaz); None: tersine çevir."""
        from .. import lossless
        if want is not None and want == self._ls_active:
            return
        cfg = self.settings["lossless"]
        if os.name != "nt":
            if not quiet:
                QMessageBox.information(self, APP_NAME, "Lossless Scaling yalnız Windows'ta çalışır.")
            return
        exe = lossless.find_exe(cfg.get("exe", ""))
        if not exe:
            if not quiet and QMessageBox.question(
                    self, "Lossless Scaling bulunamadı",
                    "Lossless Scaling (Steam'de ücretli) bu bilgisayarda bulunamadı.\n\n"
                    "Kare üretimiyle 25/30 fps yayınları 50/60 fps akıcılığında gösterir. Steam sayfası açılsın mı?\n"
                    "(Başka bir klasöre kurduysanız: Ayarlar → Lossless Scaling → Program yolu)") == QMessageBox.Yes:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl(lossless.STORE_URL))
            return
        try:
            lossless.parse_hotkey(cfg.get("hotkey") or lossless.DEFAULT_HOTKEY)
        except ValueError as e:
            self._status(f"⚠ Lossless Scaling kısayolu geçersiz: {e}")
            return
        if self._ls_pending:
            return
        started = False
        if not lossless.is_running():
            lossless.launch(exe)
            started = True
            self._status("Lossless Scaling başlatılıyor…")
            if not cfg.get("tips_shown") and not quiet:
                cfg["tips_shown"] = True
                self._save_timer.start()
                QMessageBox.information(self, "Lossless Scaling", lossless.TIPS)
        self._ls_pending = True
        self._ls_tries = 0
        # pencere önde olmalı: kısayol öndeki pencereyi ölçekler
        QTimer.singleShot(5000 if started else 150, lambda: self._send_lossless_hotkey(force=not quiet))

    def _send_lossless_hotkey(self, force: bool = False) -> None:
        from .. import lossless
        if force:
            self.raise_()
            self.activateWindow()
        if not self.isActiveWindow() or self.isMinimized():
            # otomatik açılışta başka bir pencere öndeyse onu ölçeklemeyelim: Heloo TV öne gelince yeniden dene
            self._ls_tries += 1
            if self._ls_tries < 120:
                QTimer.singleShot(1000, lambda: self._send_lossless_hotkey(force))
            else:
                self._ls_pending = False
            return
        self._ls_pending = False
        self.player.host.setFocus()
        try:
            lossless.send_hotkey(self.settings["lossless"].get("hotkey") or lossless.DEFAULT_HOTKEY)
        except Exception as e:  # noqa: BLE001
            self._status(f"⚠ Lossless Scaling kısayolu gönderilemedi: {e}")
            return
        self._ls_active = not self._ls_active
        if self.engine:
            self.engine.set_external_framegen(self._ls_active)
            self.engine.show_text("Lossless Scaling kare üretimi " + ("açık" if self._ls_active else "kapalı"), 1800)
        self._status("Lossless Scaling " + ("açıldı (mpv interpolasyonu kapatıldı)" if self._ls_active else "kapatıldı"))

    def _lossless_auto(self) -> None:
        """'Her zaman' kipinde oynatma başlayınca (canlı yayın, film, dizi, dosya) kare üretimini açar."""
        mode = self.settings["lossless"].get("mode", "always")
        if (mode == "always" or (mode == "fullscreen" and self._fs)) and not self._ls_active \
                and self.current_req and self.current_req.kind != "image":
            self.toggle_lossless(quiet=True, want=True)

    # ------------------------------------------------------------------ kayıt (DVR), zamanlanmış kayıt, hatırlatıcı
    def toggle_record(self) -> None:
        """Oynayan yayını kaydet / kaydı durdur (yeniden kodlamadan, kayıpsız MPEG-TS)."""
        if self._rec_current and self._rec_current in self.recorder.active:
            rec = self.recorder.stop(self._rec_current)
            self._rec_current = None
            self.player.set_recording(None)
            if rec:
                self._status(f"Kayıt durdu: {rec.path}")
                if self.engine:
                    self.engine.show_text("Kayıt durdu", 1500)
            return
        req = self.current_req
        if not req or req.kind in ("image", "file"):
            self._status("Kaydetmek için önce bir kanal, film ya da bölüm açın.")
            return
        try:
            rec = self.recorder.start(req.url, req.title, req.headers)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Kayıt", str(e))
            return
        self._rec_current = rec.id
        self.player.set_recording("0:00")
        self._status(f"Kaydediliyor: {rec.path}")
        if self.engine:
            self.engine.show_text("⏺ Kayıt başladı", 1500)

    def _item_play_info(self, item: Item) -> tuple[str, dict]:
        src = self.ctx.source(item.source_id)
        return catalog.play_url(self.store, item, self.settings, src), catalog.item_headers(item, src)

    def schedule_record(self, item: Item, prog: dict) -> None:
        url, headers = self._item_play_info(item)
        job = self.scheduler.add("record", prog, item.name, item.key, url, headers)
        self._status(f"⏺ Kayıt zamanlandı: {job.label()}")
        self.epg_panel.refresh_marks()
        self._sched_tick()

    def schedule_reminder(self, item: Item, prog: dict) -> None:
        job = self.scheduler.add("remind", prog, item.name, item.key)
        self._status(f"🔔 Hatırlatıcı kuruldu: {job.label()}")
        self.epg_panel.refresh_marks()

    def _prog_mark(self, prog: dict) -> str:
        item = self.epg_panel.item
        if item is None:
            return ""
        if self.scheduler.find("record", item.key, prog["start"]):
            return "⏺ "
        if self.scheduler.find("remind", item.key, prog["start"]):
            return "🔔 "
        return ""

    def _sched_tick(self) -> None:
        # biten kayıtlar
        for rec, err in self.recorder.reap():
            if rec.id == self._rec_current:
                self._rec_current = None
                self.player.set_recording(None)
            self._status(f"⚠ Kayıt durdu: {rec.title} — {err}" if err else f"Kayıt tamamlandı: {rec.path}")
            for job in self.scheduler.jobs:
                if job.state == "running" and job.id == getattr(rec, "job_id", None):
                    self.scheduler.mark(job, "failed" if err else "done")
        # oynayan kaydın süresi
        if self._rec_current and self._rec_current in self.recorder.active:
            r = self.recorder.active[self._rec_current]
            self.player.set_recording(fmt_clock_secs(time.time() - r.started))
        # zamanı gelen işler
        for job in self.scheduler.due():
            if job.kind == "record":
                try:
                    rec = self.recorder.start(job.url, f"{job.channel} - {job.title}", job.headers,
                                              duration=self.scheduler.record_duration(job))
                    rec.job_id = job.id
                    self.scheduler.mark(job, "running")
                    self._status(f"⏺ Zamanlanmış kayıt başladı: {job.label()}")
                except Exception as e:  # noqa: BLE001
                    self.scheduler.mark(job, "failed")
                    self._status(f"⚠ Zamanlanmış kayıt başlatılamadı: {e}")
            else:
                self.scheduler.mark(job, "done")
                self._remind(job)

    def _remind(self, job) -> None:
        if self.engine and self.current_req:
            self.engine.show_text(f"🔔 Birazdan: {job.title} ({job.channel})", 6000)
        box = QMessageBox(QMessageBox.Information, "Hatırlatıcı",
                          f"{time.strftime('%H:%M', time.localtime(job.start))} — {job.title}\n{job.channel}",
                          parent=self)
        watch = box.addButton("Kanalı aç", QMessageBox.AcceptRole)
        box.addButton("Kapat", QMessageBox.RejectRole)
        box.setModal(False)

        def done(_r=None):
            if box.clickedButton() is watch:
                it = self.store.item(int(job.key[0]), job.key[1], str(job.key[2])) if len(job.key) == 3 else None
                if it:
                    self.play_live(it)
        box.finished.connect(done)
        box.show()
        QApplication.alert(self)

    # ------------------------------------------------------------------ uygulama içi güncelleme
    def check_updates(self, manual: bool = False) -> None:
        from .. import updater
        if manual:
            self._status("Güncellemeler denetleniyor…")

        def done(info):
            self.settings["ui"]["last_update_check"] = time.time()
            self._save_timer.start()
            if not info["behind"]:
                self.update_btn.hide()
                if manual:
                    QMessageBox.information(self, APP_NAME, f"Heloo TV güncel ({info['current']}).")
                return
            self.update_btn.setText(f"⬆ Güncelleme var ({info['behind']})")
            self.update_btn.setToolTip("\n".join("• " + c for c in info["changes"][:10]))
            self.update_btn.show()
            self._status(f"Heloo TV için {info['behind']} yenilik var.")
            if manual:
                self._offer_update(info)

        def fail(err):
            if manual:
                QMessageBox.warning(self, APP_NAME, f"Güncellemeler denetlenemedi:\n{err}")
            else:
                log.info("güncelleme denetimi: %s", err)

        run_task(updater.check, on_done=done, on_error=fail)

    def _offer_update(self, info: dict) -> None:
        from .. import updater
        changes = "\n".join("• " + c for c in info["changes"][:12])
        more = f"\n… ve {info['behind'] - 12} değişiklik daha" if info["behind"] > 12 else ""
        if QMessageBox.question(self, "Güncelleme", f"Heloo TV için {info['behind']} yenilik var:\n\n{changes}{more}"
                                "\n\nŞimdi güncellenip yeniden başlatılsın mı? (Ayarlar, listeler ve kayıtlar korunur.)"
                                ) != QMessageBox.Yes:
            return
        if self.recorder.active:
            QMessageBox.warning(self, "Güncelleme", "Kayıt sürerken güncellenemez; kayıt bitince yeniden deneyin.")
            return

        def done(res):
            self._status(f"Güncellendi: {res['from']} → {res['to']}. Yeniden başlatılıyor…")
            QTimer.singleShot(600, self._restart)

        run_task(updater.apply, on_done=done, on_progress=self._status,
                 on_error=lambda e: QMessageBox.warning(self, "Güncelleme", f"Güncellenemedi:\n{e}"))

    def _restart(self) -> None:
        from PySide6.QtCore import QProcess
        import sys
        if QProcess.startDetached(sys.executable, ["-m", "helootv"], str(Path(__file__).resolve().parents[2]))[0]:
            self.close()
            QApplication.quit()
        else:
            QMessageBox.information(self, APP_NAME, "Güncellendi. Lütfen Heloo TV'yi kapatıp yeniden açın.")

    # ------------------------------------------------------------------ TV rehberi
    def open_guide(self) -> None:
        from .guide import GuideWindow
        if getattr(self, "_guide", None) is None:
            g = self._guide = GuideWindow(self.ctx, self)
            g.play_live.connect(self.play_live)
            g.catchup.connect(self.play_catchup)
            g.record.connect(self.schedule_record)
            g.remind.connect(self.schedule_reminder)
            g.canvas.marks = lambda item, prog: ("⏺ " if self.scheduler.find("record", item.key, prog["start"])
                                                 else "🔔 " if self.scheduler.find("remind", item.key, prog["start"])
                                                 else "")
        items = list(self.live_page.model.items)
        g = self._guide
        g.canvas.playing_key = self.current_item.key if self.current_item else None
        g.load(items, self.live_page.header.text())
        g.show()
        g.raise_()

    # ------------------------------------------------------------------ resim içinde resim (mini oynatıcı)
    def _set_pip(self, on: bool) -> None:
        if on == self._pip:
            return
        if on and self._fs:
            self._set_fullscreen(False)
        self._pip = on
        if on:
            self._pre_pip = {"geom": self.saveGeometry(), "max": self.isMaximized(), "theater": self._theater}
            for w in (self.topbar, self.pages, self.epg_panel, self.player.bar):
                w.hide()
            self.statusBar().hide()
            self.right.show()
            self.showNormal()
            # gizlenen parçalar en küçük boyuttan düşsün diye yerleşim önce güncellenir
            self.centralWidget().layout().activate() if self.centralWidget().layout() else None
            self.layout().activate()
            scr = self.screen().availableGeometry() if self.screen() else None
            w, h = 512, 288
            self.setMinimumSize(320, 180)
            self.resize(w, h)
            if scr is not None:
                self.move(scr.right() - w - 24, scr.bottom() - h - 48)
            self._set_topmost(True)
            if self.engine:
                self.engine.show_text("Mini oynatıcı — çift tık ya da Esc: geri dön", 2500)
        else:
            self._set_topmost(False)
            self.setMinimumSize(0, 0)
            self.topbar.show()
            self.statusBar().show()
            self.player.bar.show()
            self.restoreGeometry(self._pre_pip.get("geom") or self.saveGeometry())
            if self._pre_pip.get("max"):
                self.showMaximized()
            self._theater = self._pre_pip.get("theater", False)
            self._update_layout()

    def _set_topmost(self, on: bool) -> None:
        """Her zaman üstte. Windows'ta pencere yeniden oluşturulmadan (SetWindowPos) — mpv'nin gömülü penceresi
        bozulmasın; diğer sistemlerde Qt bayrağı."""
        if os.name == "nt":
            try:
                import ctypes
                HWND_TOPMOST, HWND_NOTOPMOST, SWP_NOMOVE, SWP_NOSIZE = -1, -2, 0x0002, 0x0001
                ctypes.windll.user32.SetWindowPos(int(self.winId()), HWND_TOPMOST if on else HWND_NOTOPMOST,
                                                  0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
                return
            except Exception:
                pass
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()

    def _nudge(self, prop: str, delta: float, label: str) -> None:
        if not self.engine:
            return
        self.engine.add_prop(prop, delta)
        val = self.engine._get(prop)
        if isinstance(val, (int, float)):
            unit = "" if prop == "sub-pos" else " sn"
            self.engine.show_text(f"{label}: {val:+.1f}{unit}" if unit else f"{label}: {val:.0f}", 1500)

    def _reset_prop(self, prop: str, label: str) -> None:
        if self.engine:
            self.engine._set(prop, "0")
            self.engine.show_text(f"{label}: 0", 1200)

    def _sub_style(self, key: str, value) -> None:
        self.settings["subtitles"][key] = value
        self.settings_page.load()
        self._on_settings_changed()
        if self.engine:
            self.engine.show_text(f"Altyazı boyutu: {value}" if key == "size" else "Altyazı görünümü güncellendi", 1200)

    def _set_picture(self, section: str, key: str, value) -> None:
        self.settings[section][key] = value
        self.settings["picture"]["preset"] = "custom"
        self._picture_changed()

    def _apply_preset(self, name: str) -> None:
        opt.apply_preset(self.settings, name)
        self._picture_changed()
        if self.engine:
            self.engine.show_text(f"Görüntü: {opt.PRESET_LABELS[name]}", 1500)

    def _picture_changed(self) -> None:
        self.settings_page.load()
        if self.engine:
            self.engine.apply_picture(self.settings)
        if self._picture_dlg is not None and self._picture_dlg.isVisible():
            self._picture_dlg.load()
        self._save_timer.start()

    def picture_dialog(self) -> None:
        from .picture_dialog import PictureDialog
        if self._picture_dlg is None:
            self._picture_dlg = PictureDialog(self.settings, self)
            self._picture_dlg.changed.connect(self._picture_changed)
        self._picture_dlg.load()
        self._picture_dlg.show()
        self._picture_dlg.raise_()

    # ------------------------------------------------------------------ altyazı kaynakları
    def add_sub_file(self) -> None:
        start = os.path.dirname(self.current_req.url) if self.current_req and os.path.exists(self.current_req.url) else ""
        path, _ = QFileDialog.getOpenFileName(self, "Altyazı dosyası seç", start,
                                              "Altyazılar (*.srt *.ass *.ssa *.vtt *.sub *.sup *.idx);;Tüm dosyalar (*)")
        if path and self.engine:
            self.engine.sub_add(path)
            self.engine.show_text(f"Altyazı eklendi: {os.path.basename(path)}", 2000)

    def online_subs(self) -> None:
        if not self.current_req:
            return
        from .subs_dialogs import OnlineSubsDialog
        title = self.current_req.title
        if self.current_req.subtitle and self.current_req.kind == "episode":
            title = f"{title} {self.current_req.subtitle}"
        dlg = OnlineSubsDialog(self.settings, title, self)
        dlg.key_changed.connect(self._save_timer.start)
        dlg.chosen.connect(lambda path, t, lang: self.engine and self.engine.sub_add(path, t, lang))
        dlg.exec()

    def ai_subs_dialog(self) -> None:
        from .subs_dialogs import AiSubsDialog
        dlg = AiSubsDialog(self.settings, running=self._ai_task is not None, parent=self)
        dlg.install.connect(self._install_ai_subs)
        dlg.start.connect(self._start_ai_subs)
        dlg.exec()

    def _install_ai_subs(self) -> None:
        from .. import ai_subs

        def done(_r):
            self._status("Yapay zekâ altyazı kuruldu. Altyazı menüsünden başlatabilirsiniz.")
            QMessageBox.information(self, APP_NAME, "Yapay zekâ altyazı bileşeni kuruldu.\n"
                                    "Altyazı → Yapay zekâ ile altyazı → Başlat.")

        run_task(ai_subs.install, on_done=done, on_progress=self._status,
                 on_error=lambda e: self._status(f"⚠ {e}"))

    def _stop_ai_subs(self) -> None:
        if self._ai_task:
            self._ai_task["stop"] = True
            self._ai_task = None
            self._status("Yapay zekâ altyazı durduruldu.")

    def _start_ai_subs(self, model: str, language: str, translate: bool) -> None:
        from .. import ai_subs
        req, eng = self.current_req, self.engine
        if not req or not eng:
            return
        self._stop_ai_subs()
        st = eng.status()
        out = ai_subs.output_for(f"{req.url}|{model}|{language}|{translate}|{int(st.get('pos') or 0)}")
        job = {"stop": False, "added": False, "req": req}
        self._ai_task = job

        def update(path, count):
            # arka plan iş parçacığından: ana iş parçacığına aktar
            self.bridge.event.emit("ai_sub", {"path": path, "count": count, "job": id(job)})

        def cancelled():
            return job["stop"] or self.current_req is not job["req"]

        def finished(_r):
            if self._ai_task is job:
                self._ai_task = None

        def failed(err):
            if self._ai_task is job:
                self._ai_task = None
            self._status(f"⚠ Yapay zekâ altyazı: {err}")

        self._ai_job = job
        eng.show_text("Yapay zekâ altyazı başlıyor… ilk satırlar birkaç saniyede gelir", 3000)
        run_task(ai_subs.transcribe, req.url, out, model=model, language=language or None, translate=translate,
                 start=float(st.get("pos") or 0), duration=float(st.get("duration") or 0) or None,
                 headers=req.headers, on_update=update, cancelled=cancelled,
                 on_done=finished, on_error=failed, on_progress=self._status)

    def _on_ai_sub(self, data: dict) -> None:
        job = getattr(self, "_ai_job", None)
        if not job or data.get("job") != id(job) or job["stop"] or not self.engine or self.current_req is not job["req"]:
            return
        if not job["added"]:
            job["added"] = True
            self.engine.sub_add(data["path"], "Yapay zekâ altyazı", "")
        else:
            self.engine.sub_reload()

    def _add_source(self, kind: str) -> None:
        self.settings_page.add_source(kind)

    def _status(self, text: str) -> None:
        self.status_msg.setText(text)
        log.info(text)

    def closeEvent(self, event) -> None:
        if self.engine and self.current_req and self.current_req.kind in ("movie", "episode", "file", "url"):
            st = self.engine.status()
            if st.get("pos"):
                self.store.save_progress(self.current_req.key, self.current_req.title, self.current_req.logo,
                                         st["pos"], st.get("duration") or 0, self.current_req.meta)
        if self.recorder.active:
            names = ", ".join(r.title for r in self.recorder.active.values())
            if QMessageBox.question(self, APP_NAME, f"Kayıt sürüyor ({names}). Kapatılırsa kayıt durur "
                                    "(o ana kadarki kısım kaydedilmiş olur). Kapatılsın mı?") != QMessageBox.Yes:
                event.ignore()
                return
            self.recorder.stop_all()
        self._save_settings()
        if self.engine:
            self.engine.shutdown()
            self.engine = None
        super().closeEvent(event)
