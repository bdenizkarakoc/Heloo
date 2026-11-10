"""Ayarlar sayfası ve kaynak ekleme/düzenleme penceresi."""
from __future__ import annotations

import copy
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QRadioButton, QScrollArea, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QHeaderView)

from .. import catalog, gpu
from ..m3u import parse_m3u, xtream_from_m3u_url
from ..player import options as opt
from ..xtream import XtreamClient
from . import theme
from .workers import run_task

UA_PRESETS = [
    ("VLC (önerilen)", "VLC/3.0.21 LibVLC/3.0.21"),
    ("IPTV Smarters", "IPTVSmarters/1.0.3 (iPad; iOS 16.6; Scale/2.00)"),
    ("Kodi", "Kodi/21.1 (Windows NT 10.0; Win64; x64) App_Bitness/64 Version/21.1-(21.1.0)-Git:20240804"),
    ("TiviMate", "TiviMate/5.1.6 (Android 12)"),
    ("Chrome", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/142.0.0.0 Safari/537.36"),
]


def _fmt_time(ts) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts)) if ts else "—"


class SourceDialog(QDialog):
    """M3U (bağlantı/dosya) ya da Xtream Codes kaynağı ekler/düzenler; 'Bağlantıyı test et' ile doğrular."""

    def __init__(self, parent=None, source: dict | None = None, kind: str = "xtream", settings: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Kaynağı düzenle" if source else "Kaynak ekle")
        self.setMinimumWidth(560)
        self.settings = settings or {}
        self.source = source or {}
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        # Xtream
        xt = QWidget()
        xf = QFormLayout(xt)
        self.x_name = QLineEdit()
        self.x_server = QLineEdit()
        self.x_server.setPlaceholderText("http://sunucu.adresi:8080")
        self.x_user = QLineEdit()
        self.x_pass = QLineEdit()
        self.x_pass.setEchoMode(QLineEdit.Password)
        show = QCheckBox("şifreyi göster")
        show.toggled.connect(lambda on: self.x_pass.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        xf.addRow("Ad", self.x_name)
        xf.addRow("Sunucu", self.x_server)
        xf.addRow("Kullanıcı adı", self.x_user)
        xf.addRow("Şifre", self.x_pass)
        xf.addRow("", show)
        # M3U
        m3 = QWidget()
        mf = QFormLayout(m3)
        self.m_name = QLineEdit()
        self.m_url = QLineEdit()
        self.m_url.setPlaceholderText("https://.../liste.m3u  ya da dosya yolu")
        pick = QPushButton("Dosya seç…")
        pick.clicked.connect(self._pick_file)
        row = QHBoxLayout()
        row.addWidget(self.m_url, 1)
        row.addWidget(pick)
        mf.addRow("Ad", self.m_name)
        mf.addRow("Liste", row)
        tip = QLabel("İpucu: 'get.php?username=…&password=…' biçimindeki bağlantı otomatik olarak Xtream hesabına "
                     "çevrilir (film/dizi ayrıntıları ve EPG için daha iyi).")
        tip.setWordWrap(True)
        tip.setObjectName("Muted")
        mf.addRow("", tip)
        self.tabs.addTab(xt, "Xtream Codes")
        self.tabs.addTab(m3, "M3U / M3U8")
        lay.addWidget(self.tabs)
        # ortak
        common = QGroupBox("İsteğe bağlı")
        cf = QFormLayout(common)
        self.epg = QLineEdit()
        self.epg.setPlaceholderText("XMLTV adresi (boşsa: Xtream'in kendi EPG'si / listedeki url-tvg)")
        self.ua = QComboBox()
        self.ua.setEditable(True)
        self.ua.addItem("(Genel ayar)", "")
        for label, val in UA_PRESETS:
            self.ua.addItem(label, val)
        cf.addRow("EPG (XMLTV)", self.epg)
        cf.addRow("User-Agent", self.ua)
        lay.addWidget(common)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        lay.addWidget(self.result)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Kaydet")
        btns.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        self.test_btn = btns.addButton("Bağlantıyı test et", QDialogButtonBox.ActionRole)
        self.test_btn.clicked.connect(self._test)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        # doldur
        if self.source:
            kind = self.source.get("kind", kind)
            if kind == "xtream":
                self.x_name.setText(self.source.get("name", ""))
                self.x_server.setText(self.source.get("url", ""))
                self.x_user.setText(self.source.get("username", ""))
                self.x_pass.setText(self.source.get("password", ""))
            else:
                self.m_name.setText(self.source.get("name", ""))
                self.m_url.setText(self.source.get("url", ""))
            self.epg.setText(self.source.get("epg_url", ""))
            ua = self.source.get("user_agent", "")
            if ua:
                i = self.ua.findData(ua)
                if i >= 0:
                    self.ua.setCurrentIndex(i)
                else:
                    self.ua.setEditText(ua)
        self.tabs.setCurrentIndex(0 if kind == "xtream" else 1)

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "M3U dosyası seç", "", "Oynatma listeleri (*.m3u *.m3u8 *.txt);;Tümü (*)")
        if path:
            self.m_url.setText(path)

    def _user_agent(self) -> str:
        data = self.ua.currentData()
        text = self.ua.currentText().strip()
        if data is not None and self.ua.itemText(self.ua.currentIndex()) == text:
            return data
        return "" if text == "(Genel ayar)" else text

    def values(self) -> dict:
        if self.tabs.currentIndex() == 0:
            server = self.x_server.text().strip()
            v = {"kind": "xtream", "url": server, "username": self.x_user.text().strip(),
                 "password": self.x_pass.text().strip(), "name": self.x_name.text().strip()}
            if not v["name"]:
                v["name"] = server.split("//")[-1].split("/")[0] or "Xtream"
        else:
            url = self.m_url.text().strip()
            xt = xtream_from_m3u_url(url)
            if xt:
                v = {"kind": "xtream", "url": xt[0], "username": xt[1], "password": xt[2]}
            else:
                v = {"kind": "m3u", "url": url, "username": "", "password": ""}
            v["name"] = self.m_name.text().strip() or (url.split("/")[-1] or "M3U listesi")
        v["epg_url"] = self.epg.text().strip()
        v["user_agent"] = self._user_agent()
        return v

    def _validate(self, v: dict) -> str:
        if v["kind"] == "xtream" and not (v["url"] and v["username"] and v["password"]):
            return "Sunucu, kullanıcı adı ve şifre gerekli."
        if v["kind"] == "m3u" and not v["url"]:
            return "Liste bağlantısı ya da dosya yolu gerekli."
        return ""

    def _test(self) -> None:
        v = self.values()
        err = self._validate(v)
        if err:
            self.result.setText(f"⚠ {err}")
            return
        self.result.setText("Bağlanılıyor…")
        self.test_btn.setEnabled(False)
        settings = self.settings

        def work():
            if v["kind"] == "xtream":
                client = catalog.client_for(v, settings)
                acc = XtreamClient.account_summary(client.authenticate())
                exp = time.strftime("%d.%m.%Y", time.localtime(acc["expires"])) if acc["expires"] else "süresiz"
                return (f"✔ Bağlantı başarılı — durum: {acc['status'] or 'Active'}, bitiş: {exp}, bağlantı: "
                        f"{acc['active_connections']}/{acc['max_connections'] or '∞'}"
                        + (f", biçimler: {', '.join(acc['formats'])}" if acc["formats"] else ""))
            pl = parse_m3u(catalog.load_m3u_text(v, settings))
            c = pl.counts()
            return f"✔ Liste okundu — {c['live']} canlı kanal, {c['movie']} film, {c['series']} dizi bölümü."

        def done(msg):
            self.test_btn.setEnabled(True)
            self.result.setText(msg)

        def fail(e):
            self.test_btn.setEnabled(True)
            self.result.setText(f"✖ {e}")

        run_task(work, on_done=done, on_error=fail)

    def _accept(self) -> None:
        err = self._validate(self.values())
        if err:
            self.result.setText(f"⚠ {err}")
            return
        self.accept()


class SettingsPage(QScrollArea):
    settings_changed = Signal()
    sources_changed = Signal()
    refresh_requested = Signal(object)       # kaynak kimliği ya da None (hepsi)
    epg_refresh_requested = Signal(object)
    fetch_mpv_requested = Signal()
    vsr_test_requested = Signal()
    update_requested = Signal()
    clear_history_requested = Signal()
    picture_requested = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWidgetResizable(True)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(18, 14, 18, 24)
        self.body.setSpacing(14)
        self._loading = False
        self._build_sources()
        self._build_video()
        self._build_lossless()
        self._build_latency()
        self._build_audio_subs()
        self._build_network_ui()
        self._build_system()
        self.body.addStretch(1)
        self.setWidget(body)
        self.load()

    # ------------------------------------------------------------------ kaynaklar
    def _build_sources(self) -> None:
        g = QGroupBox("Kaynaklar (IPTV hesapları ve listeler)")
        lay = QVBoxLayout(g)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Ad", "Tür", "İçerik", "Son yenileme", "Durum"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setMinimumHeight(170)
        self.table.doubleClicked.connect(lambda _i: self._edit())
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for text, slot, primary in (("+ Xtream hesabı", lambda: self.add_source("xtream"), True),
                                    ("+ M3U listesi", lambda: self.add_source("m3u"), False),
                                    ("Ücretsiz Türk kanalları", self.add_free, False),
                                    ("Düzenle", self._edit, False),
                                    ("Etkin/devre dışı", self._toggle, False),
                                    ("Yenile", lambda: self.refresh_requested.emit(self._selected_id()), False),
                                    ("EPG yenile", lambda: self.epg_refresh_requested.emit(self._selected_id()), False),
                                    ("Sil", self._delete, False)):
            b = QPushButton(text)
            if primary:
                b.setObjectName("Primary")
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.body.addWidget(g)

    def reload_sources(self) -> None:
        sources = self.ctx.store.list_sources()
        self.table.setRowCount(len(sources))
        for r, s in enumerate(sources):
            counts = (s.get("info") or {}).get("counts") or self.ctx.store.counts(s["id"])
            acc = (s.get("info") or {}).get("account") or {}
            status = s.get("last_error") or ("Etkin" if s["enabled"] else "Devre dışı")
            if acc.get("expires") and not s.get("last_error"):
                status += f" · bitiş {time.strftime('%d.%m.%Y', time.localtime(acc['expires']))}"
            if acc.get("max_connections") and not s.get("last_error"):
                status += f" · {acc['max_connections']} bağlantı"
            cells = [s["name"], "Xtream" if s["kind"] == "xtream" else "M3U",
                     f"{counts.get('live', 0)} kanal · {counts.get('movie', 0)} film · {counts.get('series', 0)} dizi",
                     _fmt_time(s.get("last_refresh")), status]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(str(text))
                it.setData(Qt.UserRole, s["id"])
                if c == 4 and s.get("last_error"):
                    it.setForeground(Qt.red)
                if not s["enabled"]:
                    it.setForeground(Qt.gray)
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

    def _selected_id(self):
        items = self.table.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def add_source(self, kind: str) -> None:
        dlg = SourceDialog(self, kind=kind, settings=self.ctx.settings)
        if dlg.exec() == QDialog.Accepted:
            v = dlg.values()
            sid = self.ctx.store.add_source(**v)
            self.ctx.invalidate()
            self.reload_sources()
            self.sources_changed.emit()
            self.refresh_requested.emit(sid)

    def add_free(self) -> None:
        sid = catalog.add_free_turkish_channels(self.ctx.store)
        self.ctx.invalidate()
        self.reload_sources()
        self.sources_changed.emit()
        self.refresh_requested.emit(sid)

    def _edit(self) -> None:
        sid = self._selected_id()
        src = self.ctx.store.get_source(sid) if sid else None
        if not src:
            return
        dlg = SourceDialog(self, source=src, settings=self.ctx.settings)
        if dlg.exec() == QDialog.Accepted:
            self.ctx.store.update_source(sid, **dlg.values())
            self.ctx.invalidate()
            self.reload_sources()
            self.refresh_requested.emit(sid)

    def _toggle(self) -> None:
        sid = self._selected_id()
        src = self.ctx.store.get_source(sid) if sid else None
        if src:
            self.ctx.store.update_source(sid, enabled=0 if src["enabled"] else 1)
            self.ctx.invalidate()
            self.reload_sources()
            self.sources_changed.emit()

    def _delete(self) -> None:
        sid = self._selected_id()
        src = self.ctx.store.get_source(sid) if sid else None
        if not src:
            return
        if QMessageBox.question(self, "Kaynağı sil", f"“{src['name']}” ve tüm kanal/film/dizi kayıtları, favorileri "
                                "ve geçmişi silinsin mi?") == QMessageBox.Yes:
            self.ctx.store.delete_source(sid)
            self.ctx.invalidate()
            self.reload_sources()
            self.sources_changed.emit()

    # ------------------------------------------------------------------ görüntü
    def _build_video(self) -> None:
        g = QGroupBox("Görüntü — NVIDIA RTX Video (4K süper çözünürlük)")
        lay = QGridLayout(g)
        self.vsr = QCheckBox("RTX Video Super Resolution (yapay zekâ ile büyütme + sıkıştırma kusurlarını temizleme)")
        self.target = QComboBox()
        for label, val in (("Ekran çözünürlüğü — 4K ekranda 4K (önerilen, akıcı)", "screen"),
                           ("Her zaman 4K (1080p ekranda gereksiz GPU yükü)", "2160"), ("1440p — 2560×1440", "1440")):
            self.target.addItem(label, val)
        self.hdr = QCheckBox("RTX Video HDR (SDR yayını HDR'ye çevirir — Windows HDR açık bir ekran gerekir)")
        self.deint = QComboBox()
        for label, val in (("Otomatik — yalnız geçmeli (1080i/576i) yayınlarda, GPU ile", "auto"),
                           ("Her zaman", "yes"), ("Kapalı", "no")):
            self.deint.addItem(label, val)
        self.deband = QCheckBox("Renk bantlarını yumuşat (deband) — sıkıştırılmış IPTV'de gökyüzü/gölge geçişleri")
        self.hq = QCheckBox("Yüksek kaliteli ölçekleyici (ewa_lanczossharp) — VSR'nin olmadığı durumlar için")
        self.smooth = QCheckBox("Film/dizide akıcı oynatma (ekrana eşitleme + interpolasyon)")
        self.ai = QComboBox()
        from .. import shaders as _sh
        for key, meta in _sh.SHADERS.items():
            self.ai.addItem(meta["label"], key)
        self.ai.addItem("Kapalı", "off")
        self.amd_fsr = QCheckBox("AMD / Intel ekran kartında AMD FSR ile büyüt (canlı yayın dahil; NVIDIA'da RTX VSR)")
        self.ai.setToolTip("RTX VSR'nin büyütmediği durumlarda (fotoğraf, VSR kapalı, NVIDIA olmayan kart) 2 kat "
                           "yapay zekâ büyütmesi. GitHub'dan 'mpv bileşenlerini indir' ile gelir.")
        self.sharpen = QComboBox()
        for label, val in (("Kapalı", "off"), ("Hafif (önerilen)", "light"), ("Orta", "medium"), ("Güçlü", "strong")):
            self.sharpen.addItem(label, val)
        self.denoise = QComboBox()
        for label, val in (("Otomatik — SD/720p/1080p yayınlarda açık", "auto"), ("Kapalı", "off"), ("Hafif", "light"),
                           ("Orta", "medium"), ("Güçlü — çok karıncalı yayınlar", "strong")):
            self.denoise.addItem(label, val)
        self.denoise.setToolTip("Karıncalanma/kumlanma (gürültü) azaltma. Gecikme eklemez: yalnız önceki kareyi kullanır.")
        self.low_boost = QCheckBox("Düşük kaliteli (≤576p) yayınlarda daha güçlü iyileştir (deband + keskinlik)")
        self.pic_btn = QPushButton("🎨 Görüntü ayarları… (parlaklık, kontrast, renk, hazır ayarlar)")
        self.pic_btn.clicked.connect(self.picture_requested.emit)
        self.hwdec = QComboBox()
        for label, val in (("Otomatik (Windows: d3d11va — VSR için gerekli)", "auto"), ("d3d11va", "d3d11va"),
                           ("nvdec (CUDA)", "nvdec"), ("auto-copy", "auto-copy"), ("Kapalı (yazılım)", "no")):
            self.hwdec.addItem(label, val)
        r = 0
        lay.addWidget(self.vsr, r, 0, 1, 2); r += 1
        lay.addWidget(QLabel("Hedef çözünürlük"), r, 0); lay.addWidget(self.target, r, 1); r += 1
        lay.addWidget(self.hdr, r, 0, 1, 2); r += 1
        lay.addWidget(QLabel("Deinterlace"), r, 0); lay.addWidget(self.deint, r, 1); r += 1
        lay.addWidget(self.deband, r, 0, 1, 2); r += 1
        lay.addWidget(self.hq, r, 0, 1, 2); r += 1
        lay.addWidget(self.smooth, r, 0, 1, 2); r += 1
        lay.addWidget(QLabel("Yapay zekâ büyütücü"), r, 0); lay.addWidget(self.ai, r, 1); r += 1
        lay.addWidget(self.amd_fsr, r, 0, 1, 2); r += 1
        lay.addWidget(QLabel("Keskinlik (CAS)"), r, 0); lay.addWidget(self.sharpen, r, 1); r += 1
        lay.addWidget(QLabel("Karıncalanma azaltma"), r, 0); lay.addWidget(self.denoise, r, 1); r += 1
        lay.addWidget(self.low_boost, r, 0, 1, 2); r += 1
        lay.addWidget(self.pic_btn, r, 0, 1, 2); r += 1
        lay.addWidget(QLabel("Donanım çözme"), r, 0); lay.addWidget(self.hwdec, r, 1); r += 1
        note = QLabel("RTX VSR'nin çalışması için NVIDIA App → Sistem → Video → RTX Video Enhancement → "
                      "'Super Resolution' açık olmalı (kalite: Otomatik ya da 4). Heloo TV, mpv'nin d3d11vpp "
                      "filtresiyle her kaynağı hedef çözünürlüğe göre ölçekler (720p ×3, 1080p ×2, SD ×3,75).")
        note.setWordWrap(True)
        note.setObjectName("Muted")
        lay.addWidget(note, r, 0, 1, 2)
        lay.setColumnStretch(1, 1)
        for w in (self.vsr, self.hdr, self.deband, self.hq, self.smooth, self.low_boost, self.amd_fsr):
            w.toggled.connect(self._changed)
        for w in (self.target, self.deint, self.hwdec, self.ai, self.sharpen, self.denoise):
            w.currentIndexChanged.connect(self._changed)
        self.body.addWidget(g)

    # ------------------------------------------------------------------ Lossless Scaling
    def _build_lossless(self) -> None:
        from .. import lossless
        g = QGroupBox("Lossless Scaling — kare üretimi (Steam'de ücretli, kuruluysa)")
        lay = QGridLayout(g)
        exe = lossless.find_exe(self.ctx.settings["lossless"].get("exe", ""))
        self.ls_status = QLabel(f"✓ Bulundu: {exe}" if exe else
                                "Kurulu değil. Steam: Lossless Scaling (993090). Heloo TV yalnızca çalıştırır ve "
                                "kısayolunu gönderir; programı içermez.")
        self.ls_status.setWordWrap(True)
        self.ls_status.setObjectName("Muted")
        self.ls_mode = QComboBox()
        for label, val in (("Tam ekranda otomatik — canlı yayın dahil (önerilen)", "fullscreen"),
                           ("Her zaman — pencere kipinde de (listelerle birlikte büyütür)", "always"),
                           ("Elle (Ctrl+G)", "manual")):
            self.ls_mode.addItem(label, val)
        self.ls_hotkey = QLineEdit()
        self.ls_hotkey.setPlaceholderText(lossless.DEFAULT_HOTKEY)
        self.ls_hotkey.setToolTip("Lossless Scaling'deki 'Ölçekle' kısayolu ile aynı olmalı (örn. Ctrl+Alt+S)")
        self.ls_exe = QLineEdit()
        self.ls_exe.setPlaceholderText("Boş: Steam kütüphanelerinde aranır")
        note = QLabel(lossless.TIPS + "\nOynarken: Görüntü menüsü → ⚡ Lossless Scaling ya da Ctrl+G.")
        note.setWordWrap(True)
        note.setObjectName("Muted")
        r = 0
        lay.addWidget(self.ls_status, r, 0, 1, 2); r += 1
        lay.addWidget(QLabel("Kare üretimi"), r, 0); lay.addWidget(self.ls_mode, r, 1); r += 1
        lay.addWidget(QLabel("Kısayol"), r, 0); lay.addWidget(self.ls_hotkey, r, 1); r += 1
        lay.addWidget(QLabel("Program yolu"), r, 0); lay.addWidget(self.ls_exe, r, 1); r += 1
        lay.addWidget(note, r, 0, 1, 2)
        lay.setColumnStretch(1, 1)
        self.ls_mode.currentIndexChanged.connect(self._changed)
        self.ls_hotkey.editingFinished.connect(self._changed)
        self.ls_exe.editingFinished.connect(self._changed)
        self.body.addWidget(g)

    # ------------------------------------------------------------------ gecikme
    def _build_latency(self) -> None:
        g = QGroupBox("Canlı yayın gecikmesi")
        lay = QVBoxLayout(g)
        self.lat_group = QButtonGroup(self)
        self.lat_buttons = {}
        for key, mode in opt.LATENCY_MODES.items():
            rb = QRadioButton(f"{mode['label']} — {mode['desc']}")
            self.lat_group.addButton(rb)
            self.lat_buttons[key] = rb
            rb.toggled.connect(self._changed)
            lay.addWidget(rb)
        self.chase = QCheckBox("Canlıya yetiş: gecikme birikirse oynatmayı %8 hızlandırıp yayına geri yetiş "
                               "(ses perdesi korunur)")
        self.chase.toggled.connect(self._changed)
        lay.addWidget(self.chase)
        row = QHBoxLayout()
        row.addWidget(QLabel("Xtream canlı yayın biçimi"))
        self.live_fmt = QComboBox()
        self.live_fmt.addItem("MPEG-TS (.ts) — en düşük gecikme", "ts")
        self.live_fmt.addItem("HLS (.m3u8) — bazı sağlayıcılarda daha kararlı", "m3u8")
        self.live_fmt.currentIndexChanged.connect(self._changed)
        row.addWidget(self.live_fmt, 1)
        lay.addLayout(row)
        self.body.addWidget(g)

    # ------------------------------------------------------------------ ses / altyazı
    def _build_audio_subs(self) -> None:
        g = QGroupBox("Ses ve altyazı")
        lay = QGridLayout(g)
        self.aprefer = QComboBox()
        self.aprefer.addItem("Türkçe ses (dublaj) öncelikli", "tr")
        self.aprefer.addItem("Özgün dil", "original")
        self.normalize = QCheckBox("Ses seviyesini dengele (film/dizi; canlıda gecikme eklememek için kapalı)")
        self.spdif = QCheckBox("Dolby/DTS sesini amfiye aktar (S/PDIF-HDMI passthrough)")
        self.sprefer = QComboBox()
        self.sprefer.addItem("Türkçe altyazı (Türkçe seste yalnız zorunlu altyazılar)", "tr")
        self.sprefer.addItem("Kapalı", "off")
        self.ssize = QSpinBox()
        self.ssize.setRange(20, 90)
        self.sstyle = QComboBox()
        self.sstyle.addItem("Kalın kenarlı yazı", "outline")
        self.sstyle.addItem("Yarı saydam kutu içinde (en okunaklı)", "box")
        self.scolor = QComboBox()
        self.scolor.addItem("Beyaz", "white")
        self.scolor.addItem("Sarı", "yellow")
        self.saimodel = QComboBox()
        for label, val in (("Hızlı (base)", "base"), ("Dengeli (small) — önerilen", "small"),
                           ("Doğru (medium)", "medium"), ("En doğru (large-v3-turbo)", "large-v3-turbo")):
            self.saimodel.addItem(label, val)
        self.oskey = QLineEdit()
        self.oskey.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.oskey.setPlaceholderText("opensubtitles.com/consumers adresinden ücretsiz")
        self.oskey.editingFinished.connect(self._changed)
        self.tmdbkey = QLineEdit()
        self.tmdbkey.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.tmdbkey.setPlaceholderText("themoviedb.org/settings/api — ücretsiz; film/dizi açıklaması, poster, oyuncular")
        self.tmdbkey.editingFinished.connect(self._changed)
        lay.addWidget(QLabel("Ses dili"), 0, 0); lay.addWidget(self.aprefer, 0, 1)
        lay.addWidget(self.normalize, 1, 0, 1, 2)
        lay.addWidget(self.spdif, 2, 0, 1, 2)
        lay.addWidget(QLabel("Altyazı"), 3, 0); lay.addWidget(self.sprefer, 3, 1)
        lay.addWidget(QLabel("Altyazı boyutu"), 4, 0); lay.addWidget(self.ssize, 4, 1)
        lay.addWidget(QLabel("Altyazı biçimi"), 5, 0); lay.addWidget(self.sstyle, 5, 1)
        lay.addWidget(QLabel("Altyazı rengi"), 6, 0); lay.addWidget(self.scolor, 6, 1)
        lay.addWidget(QLabel("Yapay zekâ altyazı modeli"), 7, 0); lay.addWidget(self.saimodel, 7, 1)
        lay.addWidget(QLabel("OpenSubtitles API anahtarı"), 8, 0); lay.addWidget(self.oskey, 8, 1)
        lay.addWidget(QLabel("TMDB anahtarı (film/dizi bilgisi)"), 9, 0); lay.addWidget(self.tmdbkey, 9, 1)
        lay.setColumnStretch(1, 1)
        for w in (self.normalize, self.spdif):
            w.toggled.connect(self._changed)
        for w in (self.aprefer, self.sprefer, self.sstyle, self.scolor, self.saimodel):
            w.currentIndexChanged.connect(self._changed)
        self.ssize.valueChanged.connect(self._changed)
        self.body.addWidget(g)

    # ------------------------------------------------------------------ ağ + arayüz
    def _build_network_ui(self) -> None:
        g = QGroupBox("Ağ ve arayüz")
        lay = QGridLayout(g)
        self.ua = QComboBox()
        self.ua.setEditable(True)
        for label, val in UA_PRESETS:
            self.ua.addItem(f"{label}", val)
        self.timeout = QSpinBox()
        self.timeout.setRange(3, 120)
        self.timeout.setSuffix(" sn")
        self.reconnect = QCheckBox("Canlı yayın koparsa otomatik yeniden bağlan")
        self.tls = QCheckBox("HTTPS sertifikalarını doğrula")
        self.resume_last = QCheckBox("Açılışta son kanalı oynat")
        self.auto_next = QCheckBox("Dizide sonraki bölüme otomatik geç")
        self.hide_adult = QCheckBox("Yetişkin içerikli kategorileri gizle")
        self.pin_btn = QPushButton("🔒 Ebeveyn kilidi (PIN)…")
        self.pin_btn.setToolTip("PIN belirlenirse yetişkin içerik yalnız PIN ile görünür; her açılışta yeniden kilitlenir")
        self.pin_btn.clicked.connect(self._pin_dialog)
        self.translate = QCheckBox("İngilizce grup adlarını Türkçeye çevir (News → Haber)")
        self.epg_shift = QDoubleSpinBox()
        self.epg_shift.setRange(-14, 14)
        self.epg_shift.setSingleStep(0.5)
        self.epg_shift.setSuffix(" saat")
        self.auto_refresh = QSpinBox()
        self.auto_refresh.setRange(0, 168)
        self.auto_refresh.setSuffix(" saatte bir (0 = kapalı)")
        r = 0
        lay.addWidget(QLabel("User-Agent"), r, 0); lay.addWidget(self.ua, r, 1); r += 1
        lay.addWidget(QLabel("Zaman aşımı"), r, 0); lay.addWidget(self.timeout, r, 1); r += 1
        for w in (self.reconnect, self.tls, self.resume_last, self.auto_next, self.hide_adult, self.translate):
            lay.addWidget(w, r, 0, 1, 2)
            r += 1
            w.toggled.connect(self._changed)
        lay.addWidget(self.pin_btn, r, 0, 1, 2); r += 1
        lay.addWidget(QLabel("EPG saat kaydırma"), r, 0); lay.addWidget(self.epg_shift, r, 1); r += 1
        lay.addWidget(QLabel("Listeleri yenile"), r, 0); lay.addWidget(self.auto_refresh, r, 1); r += 1
        lay.setColumnStretch(1, 1)
        self.ua.currentTextChanged.connect(self._changed)
        self.timeout.valueChanged.connect(self._changed)
        self.epg_shift.valueChanged.connect(self._changed)
        self.auto_refresh.valueChanged.connect(self._changed)
        self.body.addWidget(g)

    # ------------------------------------------------------------------ sistem
    def _build_system(self) -> None:
        g = QGroupBox("Sistem")
        lay = QVBoxLayout(g)
        self.sys_label = QLabel("Ekran kartı denetleniyor…")
        self.sys_label.setWordWrap(True)
        self.sys_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.sys_label)
        row = QHBoxLayout()
        b0 = QPushButton("RTX VSR'yi test et")
        b0.setObjectName("Primary")
        b0.setToolTip("Küçük bir test penceresinde 720p → 4K ölçekler ve NVIDIA sürücüsünün VSR'yi açıp açmadığını gösterir")
        b0.clicked.connect(self.vsr_test_requested.emit)
        row.addWidget(b0)
        bu = QPushButton("🔄 Güncellemeleri denetle")
        bu.setToolTip("Heloo TV'nin yeni sürümünü GitHub'dan denetler ve kurar (ayarlar, listeler korunur)")
        bu.clicked.connect(self.update_requested.emit)
        row.addWidget(bu)
        b1 = QPushButton("mpv bileşenlerini indir / güncelle (GitHub)")
        b1.clicked.connect(self.fetch_mpv_requested.emit)
        b2 = QPushButton("NVIDIA ayarlarını aç")
        b2.clicked.connect(lambda: gpu.open_nvidia_settings() or QMessageBox.information(
            self, "NVIDIA", "NVIDIA App bulunamadı. Masaüstüne sağ tıklayıp NVIDIA Denetim Masası'nı açın: "
                            "Video → Video görüntü ayarlarını yapın → RTX video geliştirme."))
        b3 = QPushButton("İzleme geçmişini temizle")
        b3.clicked.connect(self.clear_history_requested.emit)
        b4 = QPushButton("Varsayılan ayarlara dön")
        b4.clicked.connect(self._reset)
        for b in (b1, b2, b3, b4):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.body.addWidget(g)

    def set_system_info(self, html: str) -> None:
        self.sys_label.setText(html)

    # ------------------------------------------------------------------ ayar <-> denetimler
    def load(self) -> None:
        self._loading = True
        s = self.ctx.settings
        v, la, a, sub, n, ui = s["video"], s["latency"], s["audio"], s["subtitles"], s["network"], s["ui"]
        self.vsr.setChecked(v["rtx_vsr"])
        self.target.setCurrentIndex(max(0, self.target.findData(v["vsr_target"])))
        self.hdr.setChecked(v["rtx_hdr"])
        self.deint.setCurrentIndex(max(0, self.deint.findData(v["deinterlace"])))
        self.deband.setChecked(int(s.get("picture", {}).get("deband", 1)) > 0)
        self.hq.setChecked(v["hq_scaling"])
        self.smooth.setChecked(v["smooth_vod"])
        self.hwdec.setCurrentIndex(max(0, self.hwdec.findData(v["hwdec"])))
        self.ai.setCurrentIndex(max(0, self.ai.findData(v.get("ai_upscaler", "fsrcnnx"))))
        self.lat_buttons.get(la["mode"], self.lat_buttons["auto"]).setChecked(True)
        self.chase.setChecked(la["chase"])
        self.live_fmt.setCurrentIndex(max(0, self.live_fmt.findData(la["live_format"])))
        self.aprefer.setCurrentIndex(max(0, self.aprefer.findData(a["prefer"])))
        self.normalize.setChecked(a["normalize"])
        self.spdif.setChecked(a["spdif"])
        self.sprefer.setCurrentIndex(max(0, self.sprefer.findData(sub["prefer"])))
        self.ssize.setValue(int(sub["size"]))
        self.sstyle.setCurrentIndex(max(0, self.sstyle.findData(sub["style"])))
        self.scolor.setCurrentIndex(max(0, self.scolor.findData(sub["color"])))
        self.saimodel.setCurrentIndex(max(0, self.saimodel.findData(sub["ai_model"])))
        self.oskey.setText(sub.get("opensubtitles_key", ""))
        self.tmdbkey.setText(s["metadata"].get("tmdb_key", ""))
        self.sharpen.setCurrentIndex(max(0, self.sharpen.findData(v["sharpen"])))
        self.denoise.setCurrentIndex(max(0, self.denoise.findData(s["picture"]["denoise"])))
        self.low_boost.setChecked(bool(v["low_boost"]))
        self.amd_fsr.setChecked(bool(v["amd_fsr"]))
        ls = s["lossless"]
        self.ls_mode.setCurrentIndex(max(0, self.ls_mode.findData(ls["mode"])))
        self.ls_hotkey.setText(ls["hotkey"])
        self.ls_exe.setText(ls["exe"])
        i = self.ua.findData(n["user_agent"])
        if i >= 0:
            self.ua.setCurrentIndex(i)
        else:
            self.ua.setEditText(n["user_agent"])
        self.timeout.setValue(int(n["timeout"]))
        self.reconnect.setChecked(n["reconnect"])
        self.tls.setChecked(n["tls_verify"])
        self.resume_last.setChecked(ui["resume_last_channel"])
        self.auto_next.setChecked(ui["auto_next_episode"])
        self.hide_adult.setChecked(ui["hide_adult"])
        self._update_pin_btn()
        self.translate.setChecked(ui["translate_groups"])
        self.epg_shift.setValue(float(ui["epg_shift_hours"]))
        self.auto_refresh.setValue(int(ui["auto_refresh_hours"]))
        self.reload_sources()
        self._loading = False

    def _changed(self, *_a) -> None:
        if self._loading:
            return
        s = self.ctx.settings
        v, la, a, sub, n, ui = s["video"], s["latency"], s["audio"], s["subtitles"], s["network"], s["ui"]
        v["rtx_vsr"] = self.vsr.isChecked()
        v["vsr_target"] = self.target.currentData()
        v["rtx_hdr"] = self.hdr.isChecked()
        v["deinterlace"] = self.deint.currentData()
        pic = s.setdefault("picture", {})
        pic["deband"] = (max(1, int(pic.get("deband", 1))) if self.deband.isChecked() else 0)
        v["hq_scaling"] = self.hq.isChecked()
        v["smooth_vod"] = self.smooth.isChecked()
        v["hwdec"] = self.hwdec.currentData()
        v["ai_upscaler"] = self.ai.currentData()
        la["mode"] = next((k for k, b in self.lat_buttons.items() if b.isChecked()), "auto")
        la["chase"] = self.chase.isChecked()
        la["live_format"] = self.live_fmt.currentData()
        a["prefer"] = self.aprefer.currentData()
        a["normalize"] = self.normalize.isChecked()
        a["spdif"] = self.spdif.isChecked()
        sub["prefer"] = self.sprefer.currentData()
        sub["size"] = self.ssize.value()
        sub["style"] = self.sstyle.currentData()
        sub["color"] = self.scolor.currentData()
        sub["ai_model"] = self.saimodel.currentData()
        sub["opensubtitles_key"] = self.oskey.text().strip()
        s["metadata"]["tmdb_key"] = self.tmdbkey.text().strip()
        if v["sharpen"] != self.sharpen.currentData() or pic.get("denoise") != self.denoise.currentData():
            pic["preset"] = "custom"
        v["sharpen"] = self.sharpen.currentData()
        pic["denoise"] = self.denoise.currentData()
        v["low_boost"] = self.low_boost.isChecked()
        v["amd_fsr"] = self.amd_fsr.isChecked()
        from .. import lossless
        ls = s["lossless"]
        ls["mode"] = self.ls_mode.currentData()
        hk = self.ls_hotkey.text().strip() or lossless.DEFAULT_HOTKEY
        try:
            lossless.parse_hotkey(hk)
            ls["hotkey"] = hk
            self.ls_hotkey.setStyleSheet("")
        except ValueError:
            self.ls_hotkey.setStyleSheet("border: 1px solid #ff5c7a;")
        ls["exe"] = self.ls_exe.text().strip()
        ua_data = self.ua.currentData()
        text = self.ua.currentText().strip()
        n["user_agent"] = ua_data if (ua_data and self.ua.itemText(self.ua.currentIndex()) == text) else (text or n["user_agent"])
        n["timeout"] = self.timeout.value()
        n["reconnect"] = self.reconnect.isChecked()
        n["tls_verify"] = self.tls.isChecked()
        ui["resume_last_channel"] = self.resume_last.isChecked()
        ui["auto_next_episode"] = self.auto_next.isChecked()
        if not self.hide_adult.isChecked() and ui["hide_adult"] and ui.get("pin_hash"):
            # ebeveyn kilidi: yetişkin içeriği göstermek PIN ister
            from .. import parental
            pin = self.ask_pin("Ebeveyn kilidi", "Yetişkin içeriği göstermek için PIN:")
            if pin is None or not parental.verify_pin(pin, ui["pin_hash"]):
                self.hide_adult.blockSignals(True)
                self.hide_adult.setChecked(True)
                self.hide_adult.blockSignals(False)
                if pin is not None:
                    QMessageBox.warning(self, "Ebeveyn kilidi", "PIN yanlış.")
        ui["hide_adult"] = self.hide_adult.isChecked()
        ui["translate_groups"] = self.translate.isChecked()
        ui["epg_shift_hours"] = self.epg_shift.value()
        ui["auto_refresh_hours"] = self.auto_refresh.value()
        self.settings_changed.emit()

    def ask_pin(self, title: str, label: str) -> str | None:
        from PySide6.QtWidgets import QInputDialog
        pin, ok = QInputDialog.getText(self, title, label, QLineEdit.Password)
        return pin.strip() if ok else None

    def _pin_dialog(self) -> None:
        from .. import parental
        ui = self.ctx.settings["ui"]
        if ui.get("pin_hash"):
            old = self.ask_pin("Ebeveyn kilidi", "Şu anki PIN (kaldırmak ya da değiştirmek için):")
            if old is None:
                return
            if not parental.verify_pin(old, ui["pin_hash"]):
                QMessageBox.warning(self, "Ebeveyn kilidi", "PIN yanlış.")
                return
        new = self.ask_pin("Ebeveyn kilidi", "Yeni PIN (4–8 rakam; boş bırakırsanız kilit kaldırılır):")
        if new is None:
            return
        if not new:
            ui["pin_hash"] = ""
            QMessageBox.information(self, "Ebeveyn kilidi", "Ebeveyn kilidi kaldırıldı.")
        elif not parental.valid_pin(new):
            QMessageBox.warning(self, "Ebeveyn kilidi", "PIN 4–8 rakamdan oluşmalı.")
            return
        else:
            again = self.ask_pin("Ebeveyn kilidi", "Yeni PIN'i tekrar yazın:")
            if again != new:
                QMessageBox.warning(self, "Ebeveyn kilidi", "PIN'ler aynı değil.")
                return
            ui["pin_hash"] = parental.hash_pin(new)
            ui["hide_adult"] = True
            self.hide_adult.setChecked(True)
            QMessageBox.information(self, "Ebeveyn kilidi", "PIN belirlendi: yetişkin içerik gizlendi.")
        self._update_pin_btn()
        self.settings_changed.emit()

    def _update_pin_btn(self) -> None:
        on = bool(self.ctx.settings["ui"].get("pin_hash"))
        self.pin_btn.setText("🔒 Ebeveyn kilidi: açık (PIN değiştir / kaldır)…" if on else "🔓 Ebeveyn kilidi (PIN belirle)…")

    def _reset(self) -> None:
        from ..settings import merged_defaults
        if QMessageBox.question(self, "Varsayılanlar", "Tüm ayarlar en iyi varsayılanlara dönsün mü? "
                                "(Kaynaklar ve favoriler korunur.)") != QMessageBox.Yes:
            return
        keep_ui = {k: self.ctx.settings["ui"].get(k) for k in ("last_channel", "last_tab", "geometry", "pin_hash")}
        fresh = merged_defaults()
        self.ctx.settings.clear()
        self.ctx.settings.update(copy.deepcopy(fresh))
        self.ctx.settings["ui"].update({k: v for k, v in keep_ui.items() if v is not None})
        self.load()
        self.settings_changed.emit()


__all__ = ["SettingsPage", "SourceDialog", "theme"]
