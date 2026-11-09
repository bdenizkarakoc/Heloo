"""SQLite katalog: kaynaklar, kategoriler, kanal/film/dizi kayıtları, bölümler, favoriler, izleme geçmişi ve EPG.

Her iş parçacığı kendi bağlantısını kullanır (WAL kipi: arka planda yenileme sürerken arayüz okumaya devam eder).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, NamedTuple

from .textnorm import match_key, norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  url TEXT NOT NULL DEFAULT '',
  username TEXT NOT NULL DEFAULT '',
  password TEXT NOT NULL DEFAULT '',
  epg_url TEXT NOT NULL DEFAULT '',
  user_agent TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  sort INTEGER NOT NULL DEFAULT 0,
  last_refresh REAL,
  last_epg REAL,
  last_error TEXT NOT NULL DEFAULT '',
  info TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS categories(
  source_id INTEGER NOT NULL, kind TEXT NOT NULL, cat_id TEXT NOT NULL,
  name TEXT NOT NULL, sort INTEGER NOT NULL DEFAULT 0, adult INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(source_id, kind, cat_id)
);
CREATE TABLE IF NOT EXISTS items(
  source_id INTEGER NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL,
  num INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL, norm TEXT NOT NULL DEFAULT '',
  cat_id TEXT NOT NULL DEFAULT '', logo TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '',
  epg_id TEXT NOT NULL DEFAULT '', ext TEXT NOT NULL DEFAULT '', rating REAL, year TEXT NOT NULL DEFAULT '',
  added INTEGER NOT NULL DEFAULT 0, archive INTEGER NOT NULL DEFAULT 0, adult INTEGER NOT NULL DEFAULT 0,
  extra TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(source_id, kind, item_id)
);
CREATE INDEX IF NOT EXISTS items_cat ON items(kind, source_id, cat_id, num);
CREATE INDEX IF NOT EXISTS items_added ON items(kind, added);
CREATE TABLE IF NOT EXISTS episodes(
  source_id INTEGER NOT NULL, series_id TEXT NOT NULL, item_id TEXT NOT NULL,
  season INTEGER NOT NULL DEFAULT 1, episode INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '', ext TEXT NOT NULL DEFAULT '', extra TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(source_id, series_id, item_id)
);
CREATE TABLE IF NOT EXISTS favorites(
  source_id INTEGER NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL, added REAL NOT NULL,
  PRIMARY KEY(source_id, kind, item_id)
);
CREATE TABLE IF NOT EXISTS history(
  source_id INTEGER NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '', logo TEXT NOT NULL DEFAULT '', position REAL NOT NULL DEFAULT 0,
  duration REAL NOT NULL DEFAULT 0, updated REAL NOT NULL, extra TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(source_id, kind, item_id)
);
CREATE INDEX IF NOT EXISTS history_upd ON history(kind, updated);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# EPG ayrı dosyada: büyük XMLTV içe aktarılırken (uzun yazma işlemi) katalog/geçmiş yazmaları beklemez.
EPG_SCHEMA = """
CREATE TABLE IF NOT EXISTS epg(
  source_id INTEGER NOT NULL, channel TEXT NOT NULL, start INTEGER NOT NULL, stop INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '', descr TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS epg_idx ON epg(source_id, channel, start);
CREATE TABLE IF NOT EXISTS epg_channels(
  source_id INTEGER NOT NULL, channel TEXT NOT NULL, key TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(source_id, channel, key)
);
CREATE INDEX IF NOT EXISTS epg_ch_key ON epg_channels(source_id, key);
"""

ITEM_COLS = ("source_id, kind, item_id, num, name, cat_id, logo, url, epg_id, ext, rating, year, added, "
             "archive, adult, extra")
SOURCE_FIELDS = ("name", "kind", "url", "username", "password", "epg_url", "user_agent", "enabled", "sort",
                 "last_refresh", "last_epg", "last_error", "info")


class Item(NamedTuple):
    source_id: int
    kind: str          # live | movie | series
    item_id: str
    num: int
    name: str
    cat_id: str
    logo: str
    url: str
    epg_id: str
    ext: str
    rating: float | None
    year: str
    added: int
    archive: int       # geri izleme günü (0 = yok)
    adult: int
    extra: str

    @property
    def key(self) -> tuple[int, str, str]:
        return (self.source_id, self.kind, self.item_id)

    def extra_dict(self) -> dict:
        try:
            d = json.loads(self.extra or "{}")
            return d if isinstance(d, dict) else {}
        except ValueError:
            return {}


def _like(text: str) -> str:
    return "%" + norm(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        p = Path(self.path)
        self.epg_path = str(p.with_name(p.stem + "-epg" + (p.suffix or ".db")))
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._epg_lock = threading.RLock()
        with self._write_lock:
            self.conn.executescript(SCHEMA)  # executescript kendi COMMIT'ini yapar; işlem dışında çalışmalı
        with self._epg_lock:
            self.epg_conn.executescript(EPG_SCHEMA)

    # ------------------------------------------------------------------ bağlantı
    @staticmethod
    def _open(path: str) -> sqlite3.Connection:
        c = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA temp_store=MEMORY")
        return c

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._local.conn = self._open(self.path)
        return c

    @property
    def epg_conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "epg_conn", None)
        if c is None:
            c = self._local.epg_conn = self._open(self.epg_path)
        return c

    @contextmanager
    def _tx(self, conn: sqlite3.Connection, lock) -> Iterator[sqlite3.Connection]:
        with lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def transaction(self):
        return self._tx(self.conn, self._write_lock)

    def epg_transaction(self):
        return self._tx(self.epg_conn, self._epg_lock)

    def close(self) -> None:
        for name in ("conn", "epg_conn"):
            c = getattr(self._local, name, None)
            if c is not None:
                c.close()
                setattr(self._local, name, None)

    # ------------------------------------------------------------------ kv
    def get_kv(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except ValueError:
            return default

    def set_kv(self, key: str, value) -> None:
        with self.transaction() as c:
            c.execute("INSERT OR REPLACE INTO kv(key, value) VALUES(?, ?)", (key, json.dumps(value)))

    # ------------------------------------------------------------------ kaynaklar
    @staticmethod
    def _source_row(row: sqlite3.Row) -> dict:
        d = dict(row)
        try:
            d["info"] = json.loads(d.get("info") or "{}")
        except ValueError:
            d["info"] = {}
        return d

    def list_sources(self, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM sources" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY sort, id"
        return [self._source_row(r) for r in self.conn.execute(sql)]

    def get_source(self, source_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        return self._source_row(row) if row else None

    def add_source(self, **fields) -> int:
        data = {k: v for k, v in fields.items() if k in SOURCE_FIELDS}
        if isinstance(data.get("info"), dict):
            data["info"] = json.dumps(data["info"])
        if "sort" not in data:
            data["sort"] = (self.conn.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM sources").fetchone()[0])
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self.transaction() as c:
            cur = c.execute(f"INSERT INTO sources({cols}) VALUES({marks})", tuple(data.values()))
            return int(cur.lastrowid)

    def update_source(self, source_id: int, **fields) -> None:
        data = {k: v for k, v in fields.items() if k in SOURCE_FIELDS}
        if not data:
            return
        if isinstance(data.get("info"), dict):
            data["info"] = json.dumps(data["info"])
        sets = ", ".join(f"{k}=?" for k in data)
        with self.transaction() as c:
            c.execute(f"UPDATE sources SET {sets} WHERE id=?", (*data.values(), source_id))

    def delete_source(self, source_id: int) -> None:
        with self.transaction() as c:
            for table in ("categories", "items", "episodes", "favorites", "history"):
                c.execute(f"DELETE FROM {table} WHERE source_id=?", (source_id,))
            c.execute("DELETE FROM sources WHERE id=?", (source_id,))
        with self.epg_transaction() as e:
            e.execute("DELETE FROM epg WHERE source_id=?", (source_id,))
            e.execute("DELETE FROM epg_channels WHERE source_id=?", (source_id,))

    # ------------------------------------------------------------------ katalog
    def replace_catalog(self, source_id: int, kind: str, categories: Iterable[tuple], items: Iterable[tuple],
                        episodes: Iterable[tuple] | None = None) -> int:
        """categories: (cat_id, name, sort, adult); items: (item_id, num, name, cat_id, logo, url, epg_id, ext,
        rating, year, added, archive, adult, extra_json); episodes: (series_id, item_id, season, episode, title,
        url, ext, extra_json)."""
        n = 0
        with self.transaction() as c:
            c.execute("DELETE FROM categories WHERE source_id=? AND kind=?", (source_id, kind))
            c.execute("DELETE FROM items WHERE source_id=? AND kind=?", (source_id, kind))
            c.executemany("INSERT OR REPLACE INTO categories(source_id, kind, cat_id, name, sort, adult) "
                          "VALUES(?, ?, ?, ?, ?, ?)",
                          ((source_id, kind, str(cid), name, int(sort), int(adult)) for cid, name, sort, adult in categories))
            rows = []
            for it in items:
                (item_id, num, name, cat_id, logo, url, epg_id, ext, rating, year, added, archive, adult, extra) = it
                rows.append((source_id, kind, str(item_id), int(num or 0), name, norm(name), str(cat_id or ""),
                             logo or "", url or "", epg_id or "", ext or "", rating, year or "", int(added or 0),
                             int(archive or 0), int(adult or 0), extra or "{}"))
                if len(rows) >= 5000:
                    self._insert_items(c, rows)
                    n += len(rows)
                    rows = []
            if rows:
                self._insert_items(c, rows)
                n += len(rows)
            if episodes is not None:
                c.execute("DELETE FROM episodes WHERE source_id=?", (source_id,))
                c.executemany("INSERT OR REPLACE INTO episodes(source_id, series_id, item_id, season, episode, title, "
                              "url, ext, extra) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              ((source_id, *e) for e in episodes))
        return n

    @staticmethod
    def _insert_items(c: sqlite3.Connection, rows: list[tuple]) -> None:
        c.executemany(f"INSERT OR REPLACE INTO items({ITEM_COLS.replace('name,', 'name, norm,')}) "
                      "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    def categories(self, kind: str, hide_adult: bool = True) -> list[dict]:
        """Etkin kaynakların kategorileri (öğe sayısıyla). key = 'kaynak:kategori'."""
        multi = self.conn.execute("SELECT COUNT(*) FROM sources WHERE enabled=1").fetchone()[0] > 1
        sql = ("SELECT c.source_id, c.cat_id, c.name, c.adult, s.name AS sname, "
               "(SELECT COUNT(*) FROM items i WHERE i.source_id=c.source_id AND i.kind=c.kind AND i.cat_id=c.cat_id"
               + (" AND i.adult=0" if hide_adult else "") + ") AS n "
               "FROM categories c JOIN sources s ON s.id=c.source_id "
               "WHERE c.kind=? AND s.enabled=1" + (" AND c.adult=0" if hide_adult else "") +
               " ORDER BY s.sort, s.id, c.sort, c.name")
        out = []
        for r in self.conn.execute(sql, (kind,)):
            if r["n"] == 0:
                continue
            name = r["name"] + (f"  · {r['sname']}" if multi else "")
            out.append({"key": f"{r['source_id']}:{r['cat_id']}", "name": name, "count": r["n"],
                        "source_id": r["source_id"], "cat_id": r["cat_id"]})
        return out

    def items(self, kind: str, cat_key: str | None = None, search: str | None = None, hide_adult: bool = True,
              limit: int | None = None) -> list[Item]:
        where = ["i.kind=?", "s.enabled=1"]
        params: list = [kind]
        if cat_key:
            sid, _, cat = cat_key.partition(":")
            where.append("i.source_id=? AND i.cat_id=?")
            params += [int(sid), cat]
        if search and search.strip():
            where.append("i.norm LIKE ? ESCAPE '\\'")
            params.append(_like(search))
        if hide_adult:
            where.append("i.adult=0")
        order = "s.sort, i.source_id, i.num, i.norm" if kind == "live" else "i.added DESC, i.num, i.norm"
        sql = (f"SELECT {', '.join('i.' + c.strip() for c in ITEM_COLS.split(','))} FROM items i "
               f"JOIN sources s ON s.id=i.source_id WHERE {' AND '.join(where)} ORDER BY {order}")
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [Item(*r) for r in self.conn.execute(sql, params)]

    def item(self, source_id: int, kind: str, item_id: str) -> Item | None:
        r = self.conn.execute(f"SELECT {ITEM_COLS} FROM items WHERE source_id=? AND kind=? AND item_id=?",
                              (source_id, kind, str(item_id))).fetchone()
        return Item(*r) if r else None

    def counts(self, source_id: int | None = None) -> dict:
        sql = "SELECT kind, COUNT(*) FROM items" + (" WHERE source_id=?" if source_id else "") + " GROUP BY kind"
        out = {"live": 0, "movie": 0, "series": 0}
        for kind, n in self.conn.execute(sql, (source_id,) if source_id else ()):
            out[kind] = n
        return out

    def count_items(self, kind: str, hide_adult: bool = True) -> int:
        sql = ("SELECT COUNT(*) FROM items i JOIN sources s ON s.id=i.source_id WHERE i.kind=? AND s.enabled=1"
               + (" AND i.adult=0" if hide_adult else ""))
        return self.conn.execute(sql, (kind,)).fetchone()[0]

    def episodes(self, source_id: int, series_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT item_id, season, episode, title, url, ext, extra FROM episodes "
                                 "WHERE source_id=? AND series_id=? ORDER BY season, episode, title",
                                 (source_id, str(series_id))).fetchall()
        out = []
        for r in rows:
            try:
                extra = json.loads(r["extra"] or "{}")
            except ValueError:
                extra = {}
            out.append({"id": r["item_id"], "season": r["season"], "episode": r["episode"], "title": r["title"],
                        "url": r["url"], "ext": r["ext"], **{k: v for k, v in extra.items() if k not in ("id",)}})
        return out

    # ------------------------------------------------------------------ favoriler
    def is_favorite(self, key: tuple) -> bool:
        return self.conn.execute("SELECT 1 FROM favorites WHERE source_id=? AND kind=? AND item_id=?",
                                 key).fetchone() is not None

    def toggle_favorite(self, key: tuple) -> bool:
        with self.transaction() as c:
            if c.execute("SELECT 1 FROM favorites WHERE source_id=? AND kind=? AND item_id=?", key).fetchone():
                c.execute("DELETE FROM favorites WHERE source_id=? AND kind=? AND item_id=?", key)
                return False
            c.execute("INSERT INTO favorites(source_id, kind, item_id, added) VALUES(?, ?, ?, ?)",
                      (*key, time.time()))
            return True

    def favorite_keys(self, kind: str | None = None) -> set:
        sql = "SELECT source_id, kind, item_id FROM favorites" + (" WHERE kind=?" if kind else "")
        return {tuple(r) for r in self.conn.execute(sql, (kind,) if kind else ())}

    def favorites(self, kind: str, hide_adult: bool = True) -> list[Item]:
        sql = (f"SELECT {', '.join('i.' + c.strip() for c in ITEM_COLS.split(','))} FROM favorites f "
               "JOIN items i ON i.source_id=f.source_id AND i.kind=f.kind AND i.item_id=f.item_id "
               "JOIN sources s ON s.id=i.source_id WHERE f.kind=? AND s.enabled=1"
               + (" AND i.adult=0" if hide_adult else "") + " ORDER BY f.added DESC")
        return [Item(*r) for r in self.conn.execute(sql, (kind,))]

    # ------------------------------------------------------------------ izleme geçmişi
    def save_progress(self, key: tuple, title: str, logo: str, position: float, duration: float,
                      extra: dict | None = None) -> None:
        with self.transaction() as c:
            c.execute("INSERT OR REPLACE INTO history(source_id, kind, item_id, title, logo, position, duration, "
                      "updated, extra) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (*key, title or "", logo or "", float(position or 0), float(duration or 0), time.time(),
                       json.dumps(extra or {})))

    def get_progress(self, key: tuple) -> tuple[float, float] | None:
        r = self.conn.execute("SELECT position, duration FROM history WHERE source_id=? AND kind=? AND item_id=?",
                              key).fetchone()
        return (r[0], r[1]) if r else None

    def history(self, kinds: tuple[str, ...] | None = None, limit: int = 60) -> list[dict]:
        sql = "SELECT * FROM history"
        params: tuple = ()
        if kinds:
            sql += f" WHERE kind IN ({', '.join('?' for _ in kinds)})"
            params = tuple(kinds)
        sql += f" ORDER BY updated DESC LIMIT {int(limit)}"
        out = []
        for r in self.conn.execute(sql, params):
            d = dict(r)
            try:
                d["extra"] = json.loads(d.get("extra") or "{}")
            except ValueError:
                d["extra"] = {}
            out.append(d)
        return out

    def continue_watching(self, limit: int = 40) -> list[dict]:
        rows = self.history(("movie", "episode", "file", "url"), limit=limit * 3)
        return [r for r in rows if r["position"] > 60 and (not r["duration"] or r["position"] < r["duration"] * 0.94)][:limit]

    def clear_history(self) -> None:
        with self.transaction() as c:
            c.execute("DELETE FROM history")

    # ------------------------------------------------------------------ EPG
    def replace_epg(self, source_id: int, events: Iterable[tuple], keep_past_days: float = 7) -> tuple[int, int]:
        """events: epg.iter_xmltv çıktısı. (program sayısı, kanal sayısı) döndürür."""
        cutoff = int(time.time() - keep_past_days * 86400)
        n_prog = n_chan = 0
        with self.epg_transaction() as c:
            c.execute("DELETE FROM epg WHERE source_id=?", (source_id,))
            c.execute("DELETE FROM epg_channels WHERE source_id=?", (source_id,))
            batch: list[tuple] = []
            chans: list[tuple] = []
            for ev in events:
                if ev[0] == "programme":
                    _, ch, start, stop, title, desc = ev
                    if stop < cutoff:
                        continue
                    batch.append((source_id, ch, start, stop, title, (desc or "")[:2000]))
                    if len(batch) >= 5000:
                        c.executemany("INSERT INTO epg VALUES(?, ?, ?, ?, ?, ?)", batch)
                        n_prog += len(batch)
                        batch = []
                else:
                    _, ch, names, icon = ev
                    n_chan += 1
                    keys = {match_key(n) for n in names} | {match_key(ch), "id:" + ch.lower()}
                    chans.extend((source_id, ch, k, icon or "") for k in keys if k)
            if batch:
                c.executemany("INSERT INTO epg VALUES(?, ?, ?, ?, ?, ?)", batch)
                n_prog += len(batch)
            c.executemany("INSERT OR IGNORE INTO epg_channels VALUES(?, ?, ?, ?)", chans)
        return n_prog, n_chan

    def map_epg_ids(self, source_id: int) -> int:
        """tvg-id/epg_channel_id EPG'de yoksa kanal adından eşleştirir (büyük/küçük harf ve kalite etiketleri yok sayılır)."""
        e = self.epg_conn
        known = {r[0] for r in e.execute("SELECT DISTINCT channel FROM epg_channels WHERE source_id=?", (source_id,))}
        if not known:
            return 0
        keymap = {}
        for k, ch in e.execute("SELECT key, channel FROM epg_channels WHERE source_id=?", (source_id,)):
            keymap.setdefault(k, ch)
        updates = []
        for item_id, name, epg_id in self.conn.execute(
                "SELECT item_id, name, epg_id FROM items WHERE source_id=? AND kind='live'", (source_id,)):
            if epg_id and epg_id in known:
                continue
            ch = (keymap.get("id:" + epg_id.lower()) if epg_id else None) or keymap.get(match_key(name))
            if ch and ch != epg_id:
                updates.append((ch, source_id, item_id))
        if updates:
            with self.transaction() as tx:
                tx.executemany("UPDATE items SET epg_id=? WHERE source_id=? AND kind='live' AND item_id=?", updates)
        return len(updates)

    def epg_now_next(self, pairs: Iterable[tuple[int, str]], now: float | None = None) -> dict:
        """{(kaynak, epg_id): (şimdi, sonraki)} — her biri {'start','stop','title'} ya da None."""
        now = int(now or time.time())
        by_source: dict[int, list[str]] = {}
        for sid, ch in pairs:
            if ch:
                by_source.setdefault(sid, []).append(ch)
        out: dict = {}
        for sid, chans in by_source.items():
            uniq = list(dict.fromkeys(chans))
            for i in range(0, len(uniq), 400):
                part = uniq[i:i + 400]
                marks = ", ".join("?" for _ in part)
                rows = self.epg_conn.execute(
                    f"SELECT channel, start, stop, title FROM epg WHERE source_id=? AND channel IN ({marks}) "
                    "AND stop>? AND start<? ORDER BY channel, start", (sid, *part, now, now + 6 * 3600)).fetchall()
                for ch, start, stop, title in rows:
                    cur, nxt = out.get((sid, ch), (None, None))
                    prog = {"start": start, "stop": stop, "title": title}
                    if start <= now < stop and cur is None:
                        cur = prog
                    elif start >= now and nxt is None:
                        nxt = prog
                    out[(sid, ch)] = (cur, nxt)
        return out

    def epg_grid(self, pairs: Iterable[tuple[int, str]], start: float, end: float) -> dict:
        """TV rehberi ızgarası: {(kaynak, epg_id): [program, ...]} — [start, end) aralığıyla kesişenler."""
        by_source: dict[int, list[str]] = {}
        for sid, ch in pairs:
            if ch:
                by_source.setdefault(sid, []).append(ch)
        out: dict = {}
        for sid, chans in by_source.items():
            uniq = list(dict.fromkeys(chans))
            for i in range(0, len(uniq), 400):
                part = uniq[i:i + 400]
                marks = ", ".join("?" for _ in part)
                rows = self.epg_conn.execute(
                    f"SELECT channel, start, stop, title, descr FROM epg WHERE source_id=? AND channel IN ({marks}) "
                    "AND stop>? AND start<? ORDER BY channel, start", (sid, *part, int(start), int(end))).fetchall()
                for ch, st, sp, title, desc in rows:
                    out.setdefault((sid, ch), []).append({"start": st, "stop": sp, "title": title, "desc": desc})
        return out

    def epg_for_channel(self, source_id: int, channel: str, start: float, end: float) -> list[dict]:
        rows = self.epg_conn.execute("SELECT start, stop, title, descr FROM epg WHERE source_id=? AND channel=? "
                                 "AND stop>? AND start<? ORDER BY start", (source_id, channel, int(start), int(end)))
        return [{"start": r[0], "stop": r[1], "title": r[2], "desc": r[3]} for r in rows]

    def epg_count(self, source_id: int) -> int:
        return self.epg_conn.execute("SELECT COUNT(*) FROM epg WHERE source_id=?", (source_id,)).fetchone()[0]
