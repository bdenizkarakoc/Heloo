"""Sayfaların paylaştığı bağlam: katalog, ayarlar, görsel yükleyici ve küçük önbellekler."""
from __future__ import annotations

import threading

from .. import catalog
from ..store import Store
from ..xtream import XtreamClient


class AppContext:
    def __init__(self, store: Store, settings: dict, images):
        self.store = store
        self.settings = settings
        self.images = images
        self._sources: dict[int, dict] = {}
        self._lock = threading.Lock()
        self.vod_info_cache: dict[tuple, dict] = {}
        self.series_cache: dict[tuple, dict] = {}

    def invalidate(self) -> None:
        with self._lock:
            self._sources.clear()

    def source(self, source_id: int) -> dict | None:
        with self._lock:
            src = self._sources.get(source_id)
        if src is None:
            src = self.store.get_source(source_id)
            if src is not None:
                with self._lock:
                    self._sources[source_id] = src
        return src

    def hide_adult(self) -> bool:
        return bool(self.settings["ui"]["hide_adult"])

    def client(self, source_id: int) -> XtreamClient | None:
        src = self.source(source_id)
        if not src or src.get("kind") != "xtream":
            return None
        return catalog.client_for(src, self.settings)
