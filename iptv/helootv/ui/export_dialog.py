"""4K olarak kaydet penceresi: seçilen videoları/fotoğrafları yapay zekâ ile büyütüp dosyaya yazar (upscale.py)."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QProgressBar, QPushButton, QVBoxLayout)

from .. import shaders, upscale


class _Worker(QThread):
    message = Signal(str)
    percent = Signal(float)
    file_done = Signal(str)
    failed = Signal(str)

    def __init__(self, files: list[str], opts: dict):
        super().__init__()
        self.files, self.opts, self.stop = files, opts, False

    def run(self) -> None:
        caps = None
        for i, f in enumerate(self.files, 1):
            if self.stop:
                break
            try:
                if caps is None:
                    self.message.emit("Ekran kartı ve kodlayıcılar denetleniyor…")
                    ff = upscale.find_ffmpeg()
                    if not ff:
                        raise upscale.UpscaleError("ffmpeg bulunamadı (Ayarlar → Sistem → mpv bileşenlerini indir).")
                    caps = upscale.capabilities(ff)
                out = upscale.export(f, caps=caps, progress=lambda m, i=i: self.message.emit(f"[{i}/{len(self.files)}] {m}"),
                                     percent=self.percent.emit, cancelled=lambda: self.stop, **self.opts)
                self.file_done.emit(out)
            except Exception as e:  # noqa: BLE001
                self.failed.emit(f"{Path(f).name}: {e}")


class ExportDialog(QDialog):
    finished_file = Signal(str)

    def __init__(self, settings: dict, files: list[str], parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("4K olarak kaydet — yapay zekâ ile büyüt")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        info = QLabel("Video ya da fotoğraf yapay zekâ ile 4K'ya büyütülür, sıkıştırma kusurları yumuşatılır ve "
                      "NVIDIA NVENC ile kaydedilir (dikey videolar 2160×3840). Not: RTX Video Super Resolution yalnız "
                      "oynatırken çalışır; kayıtta GitHub'dan indirilen FSRCNNX/ArtCNN modeli kullanılır.")
        info.setWordWrap(True)
        info.setObjectName("Muted")
        lay.addWidget(info)
        self.list = QListWidget()
        self.list.setMinimumHeight(120)
        for f in files:
            if f:
                self.list.addItem(f)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        add = QPushButton("Dosya ekle…")
        add.clicked.connect(self._add)
        clear = QPushButton("Listeyi temizle")
        clear.clicked.connect(self.list.clear)
        row.addWidget(add)
        row.addWidget(clear)
        row.addStretch(1)
        lay.addLayout(row)
        ex = settings.setdefault("export", {})
        form = QFormLayout()
        self.target = QComboBox()
        self.target.addItem("4K — 3840×2160 (dikeyde 2160×3840)", "2160")
        self.target.addItem("1440p — 2560×1440", "1440")
        self.model = QComboBox()
        for key, meta in shaders.SHADERS.items():
            have = shaders.resolve(key) is not None and shaders.resolve(key).name == meta["file"]
            self.model.addItem(meta["label"] + ("" if have else "  (indirilmemiş)"), key)
        self.model.addItem("Kapalı (yalnız ewa_lanczossharp)", "off")
        self.quality = QComboBox()
        for label, val in (("Yüksek (önerilen)", "high"), ("En yüksek (büyük dosya)", "max"), ("Hızlı", "fast")):
            self.quality.addItem(label, val)
        self.folder = QLineEdit(ex.get("folder", ""))
        self.folder.setPlaceholderText("boş: kaynak dosyanın yanına")
        pick = QPushButton("Seç…")
        pick.clicked.connect(lambda: self.folder.setText(QFileDialog.getExistingDirectory(self, "Kayıt klasörü")
                                                         or self.folder.text()))
        frow = QHBoxLayout()
        frow.addWidget(self.folder, 1)
        frow.addWidget(pick)
        for combo, key in ((self.target, "target"), (self.model, "model"), (self.quality, "quality")):
            i = combo.findData(ex.get(key))
            if i >= 0:
                combo.setCurrentIndex(i)
        form.addRow("Hedef", self.target)
        form.addRow("Yapay zekâ", self.model)
        form.addRow("Kalite", self.quality)
        form.addRow("Klasör", frow)
        lay.addLayout(form)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        self.open_dir = QPushButton("Klasörü aç")
        self.open_dir.hide()
        self.start_btn = QPushButton("4K'ya yükselt ve kaydet")
        self.start_btn.setObjectName("Primary")
        self.start_btn.clicked.connect(self._start)
        self.close_btn = QPushButton("Kapat")
        self.close_btn.clicked.connect(self._close)
        btns.addWidget(self.open_dir)
        btns.addStretch(1)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.close_btn)
        lay.addLayout(btns)
        self.worker: _Worker | None = None
        self.outputs: list[str] = []

    def _add(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(upscale.VIDEO_EXTS | upscale.IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "4K'ya yükseltilecek dosyalar", "", f"Video ve fotoğraf ({exts})")
        for f in files:
            self.list.addItem(f)

    def _files(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def _start(self) -> None:
        files = self._files()
        if not files:
            self.status.setText("Önce dosya ekleyin.")
            return
        opts = {"target": self.target.currentData(), "model": self.model.currentData(),
                "quality": self.quality.currentData(), "folder": self.folder.text().strip()}
        self.settings["export"].update(opts)
        self.outputs = []
        self.start_btn.setEnabled(False)
        self.close_btn.setText("İptal")
        self.worker = _Worker(files, opts)
        self.worker.message.connect(self.status.setText)
        self.worker.percent.connect(lambda p: self.bar.setValue(int(p * 10)))
        self.worker.file_done.connect(self._done_one)
        self.worker.failed.connect(lambda e: self.status.setText(f"⚠ {e}"))
        self.worker.finished.connect(self._all_done)
        self.worker.start()

    def _done_one(self, path: str) -> None:
        self.outputs.append(path)
        self.finished_file.emit(path)

    def _all_done(self) -> None:
        self.start_btn.setEnabled(True)
        self.close_btn.setText("Kapat")
        if self.outputs:
            self.status.setText("✔ Kaydedildi:\n" + "\n".join(self.outputs))
            self.open_dir.show()
            folder = str(Path(self.outputs[-1]).parent)
            try:
                self.open_dir.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.open_dir.clicked.connect(lambda: _open_folder(folder))

    def _close(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.stop = True
            self.status.setText("İptal ediliyor…")
            return
        self.accept()

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.stop = True
            self.worker.wait(5000)
        super().closeEvent(event)


def _open_folder(folder: str) -> None:
    if os.name == "nt":
        os.startfile(folder)  # type: ignore[attr-defined]
    else:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
