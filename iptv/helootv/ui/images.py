"""Logo/afiş yükleyici: QNetworkAccessManager + disk önbelleği + bellek içi LRU, aynı anda en çok 8 indirme."""
from __future__ import annotations

import collections

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkDiskCache, QNetworkReply, QNetworkRequest

from .. import paths

MAX_PARALLEL = 8
MAX_IMAGES = 700
MAX_PIXMAPS = 2500


class ImageLoader(QObject):
    loaded = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        cache = QNetworkDiskCache(self)
        cache.setCacheDirectory(str(paths.cache_dir() / "images"))
        cache.setMaximumCacheSize(600 * 1024 * 1024)
        self.nam.setCache(cache)
        self._images: collections.OrderedDict[str, QImage] = collections.OrderedDict()
        self._pixmaps: collections.OrderedDict[tuple, QPixmap] = collections.OrderedDict()
        self._queue: collections.deque[str] = collections.deque()
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._active = 0
        self._notify: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._flush)

    def pixmap(self, url: str, size: QSize, mode: str = "fit", dpr: float = 1.0) -> QPixmap | None:
        """mode: fit (logo, oran korunur) | cover (afiş, kırpılarak doldurur). Hazır değilse None döner ve yükler."""
        if not url or url in self._failed or not url.startswith(("http://", "https://", "file:")):
            return None
        key = (url, size.width(), size.height(), mode, round(dpr, 2))
        pm = self._pixmaps.get(key)
        if pm is not None:
            self._pixmaps.move_to_end(key)
            return pm
        img = self._images.get(url)
        if img is None:
            self._request(url)
            return None
        self._images.move_to_end(url)
        target = QSize(int(size.width() * dpr), int(size.height() * dpr))
        if mode == "cover":
            scaled = img.scaled(target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = max(0, (scaled.width() - target.width()) // 2)
            y = max(0, (scaled.height() - target.height()) // 3)
            scaled = scaled.copy(x, y, target.width(), target.height())
        else:
            scaled = img.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm = QPixmap.fromImage(scaled)
        pm.setDevicePixelRatio(dpr)
        self._pixmaps[key] = pm
        while len(self._pixmaps) > MAX_PIXMAPS:
            self._pixmaps.popitem(last=False)
        return pm

    def _request(self, url: str) -> None:
        if url in self._pending:
            return
        self._pending.add(url)
        self._queue.appendleft(url)  # en son istenen (ekranda görünen) önce
        self._pump()

    def _pump(self) -> None:
        while self._active < MAX_PARALLEL and self._queue:
            url = self._queue.popleft()
            req = QNetworkRequest(QUrl(url))
            req.setAttribute(QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.PreferCache)
            req.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)
            req.setHeader(QNetworkRequest.UserAgentHeader, "Mozilla/5.0 HelooTV")
            req.setTransferTimeout(15000)
            reply = self.nam.get(req)
            self._active += 1
            reply.finished.connect(lambda r=reply, u=url: self._finished(u, r))

    def _finished(self, url: str, reply: QNetworkReply) -> None:
        self._active -= 1
        self._pending.discard(url)
        img = QImage()
        if reply.error() == QNetworkReply.NoError:
            img.loadFromData(reply.readAll())
        reply.deleteLater()
        if img.isNull():
            self._failed.add(url)
        else:
            if img.width() > 800 or img.height() > 1200:
                img = img.scaled(QSize(800, 1200), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._images[url] = img
            while len(self._images) > MAX_IMAGES:
                self._images.popitem(last=False)
            self._notify.add(url)
            if not self._timer.isActive():
                self._timer.start()
        self._pump()

    def _flush(self) -> None:
        urls, self._notify = self._notify, set()
        for u in urls:
            self.loaded.emit(u)
