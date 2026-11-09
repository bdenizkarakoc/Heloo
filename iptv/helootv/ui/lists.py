"""Liste modelleri ve çizim temsilcileri: kategoriler, kanallar (logo + EPG ilerlemesi), afiş ızgarası."""
from __future__ import annotations

import time

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from ..store import Item
from . import theme

ItemRole = Qt.UserRole + 1
RowRole = Qt.UserRole + 2


def hhmm(ts: float | None) -> str:
    return time.strftime("%H:%M", time.localtime(ts)) if ts else ""


class CategoryModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict] = []

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        r = self.rows[index.row()]
        if role == Qt.DisplayRole:
            return r["name"]
        if role == RowRole:
            return r
        if role == Qt.ToolTipRole:
            return f"{r['name']} — {r.get('count', 0)} öğe" if r.get("count") is not None else r["name"]
        return None

    def row_of(self, key) -> int:
        for i, r in enumerate(self.rows):
            if r.get("key") == key:
                return i
        return -1


class ItemModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[Item] = []
        self.epg: dict = {}
        self.favs: set = set()
        self.progress: dict = {}
        self.playing_key = None

    def set_items(self, items: list[Item]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def set_epg(self, epg: dict) -> None:
        self.epg = epg
        self._changed_all()

    def set_favs(self, favs: set) -> None:
        self.favs = favs
        self._changed_all()

    def set_progress(self, progress: dict) -> None:
        self.progress = progress
        self._changed_all()

    def set_playing(self, key) -> None:
        self.playing_key = key
        self._changed_all()

    def _changed_all(self) -> None:
        if self.items:
            self.dataChanged.emit(self.index(0), self.index(len(self.items) - 1))

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def item(self, row: int) -> Item | None:
        return self.items[row] if 0 <= row < len(self.items) else None

    def row_of(self, key) -> int:
        for i, it in enumerate(self.items):
            if it.key == key:
                return i
        return -1

    def now_next(self, item: Item):
        return self.epg.get((item.source_id, item.epg_id), (None, None)) if item.epg_id else (None, None)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.items):
            return None
        it = self.items[index.row()]
        if role == Qt.DisplayRole:
            return it.name
        if role == ItemRole:
            return it
        if role == Qt.ToolTipRole:
            cur, nxt = self.now_next(it)
            lines = [it.name]
            if cur:
                lines.append(f"Şimdi: {cur['title']} ({hhmm(cur['start'])}–{hhmm(cur['stop'])})")
            if nxt:
                lines.append(f"Sonra: {nxt['title']} ({hhmm(nxt['start'])})")
            return "\n".join(lines)
        return None


def _rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _initials(name: str) -> str:
    words = [w for w in name.replace("-", " ").split() if w[:1].isalnum()]
    return "".join(w[0] for w in words[:2]).upper() or "TV"


class CategoryDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 36)

    def paint(self, p: QPainter, option, index) -> None:
        r = index.data(RowRole) or {}
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect.adjusted(2, 1, -2, -1))
        if option.state & QStyle.State_Selected:
            p.fillPath(_rounded(rect, 8), QColor(theme.ACCENT))
        elif option.state & QStyle.State_MouseOver:
            p.fillPath(_rounded(rect, 8), QColor("#1a2131"))
        selected = bool(option.state & QStyle.State_Selected)
        count = r.get("count")
        count_txt = f"{count:,}".replace(",", ".") if isinstance(count, int) else ""
        fm = QFontMetrics(option.font)
        cw = fm.horizontalAdvance(count_txt) + 10 if count_txt else 0
        p.setPen(QColor("white" if selected else theme.TEXT))
        text_rect = rect.adjusted(10, 0, -(cw + 8), 0)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, fm.elidedText(r.get("name", ""), Qt.ElideRight,
                                                                             int(text_rect.width())))
        if count_txt:
            p.setPen(QColor("#e0dcff" if selected else theme.MUTED))
            p.drawText(rect.adjusted(0, 0, -10, 0), Qt.AlignVCenter | Qt.AlignRight, count_txt)
        p.restore()


class ChannelDelegate(QStyledItemDelegate):
    ROW_H = 60

    def __init__(self, images, parent=None, numbered: bool = True):
        super().__init__(parent)
        self.images = images
        self.numbered = numbered

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, p: QPainter, option, index) -> None:
        model: ItemModel = index.model()
        it: Item = index.data(ItemRole)
        if it is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(option.rect.adjusted(3, 2, -3, -2))
        playing = model.playing_key == it.key
        if option.state & QStyle.State_Selected:
            p.fillPath(_rounded(rect, 9), QColor(theme.PANEL_2))
            p.setPen(QPen(QColor(theme.ACCENT), 1.4))
            p.drawPath(_rounded(rect.adjusted(0.7, 0.7, -0.7, -0.7), 9))
        elif option.state & QStyle.State_MouseOver:
            p.fillPath(_rounded(rect, 9), QColor("#171d2a"))
        if playing:
            p.fillRect(QRectF(rect.left(), rect.top() + 10, 3, rect.height() - 20), QColor(theme.ACCENT_2))
        x = rect.left() + 8
        base_font = QFont(option.font)
        if self.numbered:
            p.setPen(QColor(theme.MUTED))
            small = QFont(base_font)
            small.setPointSizeF(base_font.pointSizeF() * 0.9)
            p.setFont(small)
            p.drawText(QRectF(x, rect.top(), 34, rect.height()), Qt.AlignVCenter | Qt.AlignRight, str(index.row() + 1))
            x += 42
        logo_rect = QRectF(x, rect.top() + 8, 68, rect.height() - 16)
        p.fillPath(_rounded(logo_rect, 7), QColor("#0b0e14"))
        dpr = p.device().devicePixelRatioF() if p.device() else 1.0
        pm = self.images.pixmap(it.logo, QSize(int(logo_rect.width() - 8), int(logo_rect.height() - 6)), "fit", dpr)
        if pm is not None:
            w, h = pm.width() / pm.devicePixelRatio(), pm.height() / pm.devicePixelRatio()
            p.drawPixmap(QRectF(logo_rect.center().x() - w / 2, logo_rect.center().y() - h / 2, w, h), pm,
                         QRectF(pm.rect()))
        else:
            p.setPen(QColor(theme.MUTED))
            f = QFont(base_font)
            f.setBold(True)
            p.setFont(f)
            p.drawText(logo_rect, Qt.AlignCenter, _initials(it.name))
        x = logo_rect.right() + 12
        right_pad = 30 if (it.key in model.favs or it.archive) else 8
        text_w = rect.right() - x - right_pad
        cur, _nxt = model.now_next(it)
        name_font = QFont(base_font)
        name_font.setBold(True)
        p.setFont(name_font)
        p.setPen(QColor("white" if playing else theme.TEXT))
        fm = QFontMetrics(name_font)
        if cur:
            p.drawText(QRectF(x, rect.top() + 7, text_w, 20), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(it.name, Qt.ElideRight, int(text_w)))
            sub = QFont(base_font)
            sub.setPointSizeF(base_font.pointSizeF() * 0.9)
            p.setFont(sub)
            p.setPen(QColor(theme.MUTED))
            fm2 = QFontMetrics(sub)
            t = f"{hhmm(cur['start'])}  {cur['title']}"
            p.drawText(QRectF(x, rect.top() + 26, text_w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       fm2.elidedText(t, Qt.ElideRight, int(text_w)))
            now = time.time()
            frac = min(1.0, max(0.0, (now - cur["start"]) / max(1, cur["stop"] - cur["start"])))
            bar = QRectF(x, rect.bottom() - 9, min(text_w, 220), 3)
            p.fillPath(_rounded(bar, 1.5), QColor(theme.LINE))
            p.fillPath(_rounded(QRectF(bar.left(), bar.top(), bar.width() * frac, 3), 1.5), QColor(theme.ACCENT))
        else:
            p.drawText(QRectF(x, rect.top(), text_w, rect.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(it.name, Qt.ElideRight, int(text_w)))
        icons = []
        if it.key in model.favs:
            icons.append(("★", theme.WARN))
        if it.archive:
            icons.append(("⟲", theme.ACCENT_2))
        if icons:
            p.setFont(base_font)
            yy = rect.top() + 8
            for ch, color in icons:
                p.setPen(QColor(color))
                p.drawText(QRectF(rect.right() - 26, yy, 20, 20), Qt.AlignCenter, ch)
                yy += 20
        p.restore()


class PosterDelegate(QStyledItemDelegate):
    CELL = QSize(178, 304)
    POSTER = QSize(162, 240)

    def __init__(self, images, parent=None):
        super().__init__(parent)
        self.images = images

    def sizeHint(self, option, index) -> QSize:
        return self.CELL

    def paint(self, p: QPainter, option, index) -> None:
        model: ItemModel = index.model()
        it: Item = index.data(ItemRole)
        if it is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        cell = QRectF(option.rect)
        poster = QRectF(cell.left() + (cell.width() - self.POSTER.width()) / 2, cell.top() + 6,
                        self.POSTER.width(), self.POSTER.height())
        path = _rounded(poster, 10)
        dpr = p.device().devicePixelRatioF() if p.device() else 1.0
        pm = self.images.pixmap(it.logo, self.POSTER, "cover", dpr)
        if pm is not None:
            p.setClipPath(path)
            p.drawPixmap(poster, pm, QRectF(pm.rect()))
            p.setClipping(False)
        else:
            grad = QLinearGradient(poster.topLeft(), poster.bottomRight())
            grad.setColorAt(0, QColor("#2a2350"))
            grad.setColorAt(1, QColor("#14324a"))
            p.fillPath(path, grad)
            f = QFont(option.font)
            f.setPointSizeF(option.font.pointSizeF() * 2.2)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 170))
            p.drawText(poster, Qt.AlignCenter, _initials(it.name))
        frac = model.progress.get(it.key)
        if frac:
            bar = QRectF(poster.left() + 8, poster.bottom() - 10, poster.width() - 16, 4)
            p.fillPath(_rounded(bar, 2), QColor(0, 0, 0, 160))
            p.fillPath(_rounded(QRectF(bar.left(), bar.top(), bar.width() * min(1.0, frac), 4), 2), QColor(theme.ACCENT))
        if it.key in model.favs:
            badge = QRectF(poster.right() - 30, poster.top() + 6, 24, 24)
            p.fillPath(_rounded(badge, 12), QColor(0, 0, 0, 150))
            p.setPen(QColor(theme.WARN))
            p.drawText(badge, Qt.AlignCenter, "★")
        if it.rating:
            badge = QRectF(poster.left() + 6, poster.top() + 6, 44, 20)
            p.fillPath(_rounded(badge, 10), QColor(0, 0, 0, 160))
            p.setPen(QColor("#ffd166"))
            small = QFont(option.font)
            small.setPointSizeF(option.font.pointSizeF() * 0.85)
            small.setBold(True)
            p.setFont(small)
            p.drawText(badge, Qt.AlignCenter, f"★ {it.rating:.1f}")
        if option.state & QStyle.State_Selected:
            p.setPen(QPen(QColor(theme.ACCENT), 3))
            p.drawPath(_rounded(poster.adjusted(1.5, 1.5, -1.5, -1.5), 9))
        elif option.state & QStyle.State_MouseOver:
            p.setPen(QPen(QColor(theme.ACCENT_2), 1.5))
            p.drawPath(_rounded(poster.adjusted(0.75, 0.75, -0.75, -0.75), 10))
        title_font = QFont(option.font)
        title_font.setBold(True)
        title_font.setPointSizeF(option.font.pointSizeF() * 0.95)
        p.setFont(title_font)
        p.setPen(QColor(theme.TEXT))
        fm = QFontMetrics(title_font)
        title_rect = QRectF(cell.left() + 8, poster.bottom() + 6, cell.width() - 16, fm.height() * 2 + 2)
        text = it.name
        lines = []
        for _ in range(2):
            if not text:
                break
            n = len(text)
            while n > 0 and fm.horizontalAdvance(text[:n]) > title_rect.width():
                cut = text.rfind(" ", 0, n)
                n = cut if cut > 0 else n - 1
            if len(lines) == 1 and n < len(text):
                lines.append(fm.elidedText(text, Qt.ElideRight, int(title_rect.width())))
                text = ""
                break
            lines.append(text[:n])
            text = text[n:].lstrip()
        p.drawText(title_rect, Qt.AlignHCenter | Qt.AlignTop, "\n".join(lines))
        meta = " · ".join(x for x in (it.year,) if x)
        if meta:
            p.setPen(QColor(theme.MUTED))
            small = QFont(option.font)
            small.setPointSizeF(option.font.pointSizeF() * 0.85)
            p.setFont(small)
            top = title_rect.top() + fm.height() * max(1, len(lines)) + 2
            p.drawText(QRectF(cell.left(), top, cell.width(), 18), Qt.AlignHCenter | Qt.AlignTop, meta)
        p.restore()


def make_list(delegate: QStyledItemDelegate, model, grid: bool = False) -> QListView:
    view = QListView()
    view.setModel(model)
    view.setItemDelegate(delegate)
    view.setMouseTracking(True)
    view.setUniformItemSizes(True)
    view.setSelectionMode(QAbstractItemView.SingleSelection)
    view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    view.setEditTriggers(QAbstractItemView.NoEditTriggers)
    if grid:
        view.setViewMode(QListView.IconMode)
        view.setResizeMode(QListView.Adjust)
        view.setMovement(QListView.Static)
        view.setWrapping(True)
        view.setSpacing(4)
        view.setLayoutMode(QListView.Batched)
        view.setBatchSize(300)
        view.verticalScrollBar().setSingleStep(40)
    else:
        view.verticalScrollBar().setSingleStep(24)
    return view


__all__ = ["CategoryModel", "ItemModel", "CategoryDelegate", "ChannelDelegate", "PosterDelegate", "make_list",
           "ItemRole", "RowRole", "hhmm", "QRect"]
