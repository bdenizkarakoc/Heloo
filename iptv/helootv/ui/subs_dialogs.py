"""Altyazı pencereleri: internetten altyazı (OpenSubtitles) ve yapay zekâ ile konuşmadan altyazı (faster-whisper)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout)

from .. import ai_subs, subs_online
from .workers import run_task

LANGS = (("tr,en", "Türkçe + İngilizce"), ("tr", "Türkçe"), ("en", "İngilizce"), ("de", "Almanca"),
         ("ar", "Arapça"), ("fr", "Fransızca"), ("es", "İspanyolca"), ("ru", "Rusça"))


class OnlineSubsDialog(QDialog):
    """Başlıktan (S02E05 dahil) arar; seçilen altyazı indirilir ve `chosen(yol, başlık, dil)` yayılır."""
    chosen = Signal(str, str, str)
    key_changed = Signal()

    def __init__(self, settings: dict, title: str, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("İnternetten altyazı bul (OpenSubtitles)")
        self.setMinimumSize(640, 460)
        lay = QVBoxLayout(self)
        info = QLabel('Altyazılar <a style="color:#38bdf8" href="https://www.opensubtitles.com">opensubtitles.com</a> üzerinden aranır. '
                      'Ücretsiz API anahtarı: <a style="color:#38bdf8" href="https://www.opensubtitles.com/consumers">'
                      'opensubtitles.com/consumers</a> (hesap aç → "New consumer" → anahtarı buraya yapıştır).')
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        info.setObjectName("Muted")
        lay.addWidget(info)
        form = QFormLayout()
        self.key = QLineEdit(settings["subtitles"].get("opensubtitles_key", ""))
        self.key.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.key.setPlaceholderText("API anahtarı")
        q, season, ep = subs_online.clean_title(title)
        self.query = QLineEdit(q)
        row = QHBoxLayout()
        self.season = QSpinBox()
        self.season.setRange(0, 99)
        self.season.setSpecialValueText("—")
        self.season.setValue(season or 0)
        self.episode = QSpinBox()
        self.episode.setRange(0, 999)
        self.episode.setSpecialValueText("—")
        self.episode.setValue(ep or 0)
        row.addWidget(QLabel("Sezon"))
        row.addWidget(self.season)
        row.addWidget(QLabel("Bölüm"))
        row.addWidget(self.episode)
        row.addStretch(1)
        self.lang = QComboBox()
        for val, text in LANGS:
            self.lang.addItem(text, val)
        form.addRow("API anahtarı", self.key)
        form.addRow("Ad", self.query)
        form.addRow("Dizi", row)
        form.addRow("Dil", self.lang)
        lay.addLayout(form)
        b = QHBoxLayout()
        self.search_btn = QPushButton("Ara")
        self.search_btn.setObjectName("Primary")
        self.search_btn.clicked.connect(self.search)
        b.addWidget(self.search_btn)
        b.addStretch(1)
        lay.addLayout(b)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(lambda _i: self.download())
        lay.addWidget(self.results, 1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bb = QHBoxLayout()
        self.dl_btn = QPushButton("İndir ve göster")
        self.dl_btn.setObjectName("Primary")
        self.dl_btn.clicked.connect(self.download)
        close = QPushButton("Kapat")
        close.clicked.connect(self.reject)
        bb.addStretch(1)
        bb.addWidget(close)
        bb.addWidget(self.dl_btn)
        lay.addLayout(bb)
        self.query.returnPressed.connect(self.search)

    def _key(self) -> str:
        k = self.key.text().strip()
        if k != self.settings["subtitles"].get("opensubtitles_key", ""):
            self.settings["subtitles"]["opensubtitles_key"] = k
            self.key_changed.emit()
        return k

    def search(self) -> None:
        self.results.clear()
        self.status.setText("Aranıyor…")
        self.search_btn.setEnabled(False)

        def done(rows):
            self.search_btn.setEnabled(True)
            for r in rows:
                flag = {"tr": "TR", "en": "EN"}.get(r["lang"], r["lang"].upper())
                text = f"[{flag}] {r['release'] or r['title']}  ·  {r['downloads']} indirme" + ("  · işitme engelli" if r["hi"] else "")
                it = QListWidgetItem(text)
                it.setData(Qt.UserRole, r)
                self.results.addItem(it)
            if rows:
                self.results.setCurrentRow(0)
            self.status.setText(f"{len(rows)} altyazı bulundu. Çift tıklayın ya da 'İndir ve göster'." if rows
                                else "Altyazı bulunamadı. Adı kısaltmayı ya da İngilizce adını deneyin.")

        def fail(err):
            self.search_btn.setEnabled(True)
            self.status.setText(f"⚠ {err}")

        run_task(subs_online.search, self._key(), self.query.text().strip(), self.lang.currentData(),
                 self.season.value() or None, self.episode.value() or None, on_done=done, on_error=fail)

    def download(self) -> None:
        it = self.results.currentItem()
        if not it:
            return
        r = it.data(Qt.UserRole)
        self.status.setText("İndiriliyor…")
        self.dl_btn.setEnabled(False)

        def done(path):
            self.dl_btn.setEnabled(True)
            self.chosen.emit(path, f"OpenSubtitles · {r['lang']}", r["lang"])
            self.status.setText("Altyazı eklendi ✓")
            self.accept()

        def fail(err):
            self.dl_btn.setEnabled(True)
            self.status.setText(f"⚠ {err}")

        run_task(subs_online.download, self._key(), r["file_id"], self.query.text().strip() or "altyazi",
                 on_done=done, on_error=fail)


class AiSubsDialog(QDialog):
    """Yapay zekâ altyazı seçenekleri; Başlat → `start(model, dil, çevir)`."""
    start = Signal(str, str, bool)
    install = Signal()

    MODELS = (("base", "Hızlı (base)"), ("small", "Dengeli (small) — önerilen"), ("medium", "Doğru (medium)"),
              ("large-v3-turbo", "En doğru (large-v3-turbo, RTX önerilir)"))
    SPOKEN = (("", "Otomatik algıla"), ("tr", "Türkçe"), ("en", "İngilizce"), ("de", "Almanca"), ("ar", "Arapça"),
              ("fr", "Fransızca"), ("es", "İspanyolca"), ("ru", "Rusça"), ("ja", "Japonca"), ("ko", "Korece"))

    def __init__(self, settings: dict, running: bool = False, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Yapay zekâ ile altyazı (konuşmadan)")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        ok = ai_subs.available()
        info = QLabel("Oyunlardaki canlı altyazı gibi: altyazısı olmayan film/dizi/videonun konuşması yapay zekâ "
                      "(Whisper) ile yazıya dökülür. İzlediğiniz yerden başlar, birkaç saniyede ilk satırlar gelir ve "
                      "ilerledikçe dolar. NVIDIA ekran kartında çalışır (yoksa işlemcide, daha yavaş).")
        info.setWordWrap(True)
        info.setObjectName("Muted")
        lay.addWidget(info)
        form = QFormLayout()
        self.model = QComboBox()
        for val, text in self.MODELS:
            self.model.addItem(text, val)
        self.model.setCurrentIndex(max(0, self.model.findData(settings["subtitles"].get("ai_model", "small"))))
        self.spoken = QComboBox()
        for val, text in self.SPOKEN:
            self.spoken.addItem(text, val)
        self.translate = QCheckBox("İngilizceye çevirerek yaz (Whisper yalnız İngilizceye çevirebilir)")
        form.addRow("Model", self.model)
        form.addRow("Konuşma dili", self.spoken)
        form.addRow("", self.translate)
        lay.addLayout(form)
        self.note = QLabel("" if ok else "Bileşen kurulu değil: 'Kur' ile bir kez indirilir (~200 MB + seçilen model).")
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        bb = QHBoxLayout()
        bb.addStretch(1)
        close = QPushButton("Kapat")
        close.clicked.connect(self.reject)
        bb.addWidget(close)
        if not ok:
            inst = QPushButton("Kur")
            inst.setObjectName("Primary")
            inst.clicked.connect(lambda: (self.install.emit(), self.accept()))
            bb.addWidget(inst)
        else:
            go = QPushButton("Durdur ve yeniden başlat" if running else "Başlat")
            go.setObjectName("Primary")
            go.clicked.connect(self._go)
            bb.addWidget(go)
        lay.addLayout(bb)

    def _go(self) -> None:
        self.settings["subtitles"]["ai_model"] = self.model.currentData()
        self.start.emit(self.model.currentData(), self.spoken.currentData(), self.translate.isChecked())
        self.accept()
