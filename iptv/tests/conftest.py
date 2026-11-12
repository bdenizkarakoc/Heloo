"""Ortak test ayarları.

Qt + libmpv testlerinden sonra Python kapanırken nesneler rastgele sırayla silinir ve süreç ara sıra çöker
(Linux'ta "Segmentation fault", Windows'ta sıfırdan farklı çıkış kodu) — testlerin hepsi geçmiş olsa bile CI kırmızı
olur. Oturum bitince bütün pencereler Qt'de düzgünce silinir ve süreç, testlerin gerçek sonucuyla hemen kapatılır.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("HELOOTV_NO_DIALOG", "1")     # testlerde hata penceresi açılıp beklemesin

DATA = Path(__file__).resolve().parent / "data"

_status = {"code": None}


def pytest_sessionfinish(session, exitstatus):
    _status["code"] = int(exitstatus)
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except Exception:
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in list(app.topLevelWidgets()):
        try:
            w.close()
            w.deleteLater()
        except RuntimeError:
            pass
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def pytest_unconfigure(config):
    """Özet yazıldıktan sonra: yorumlayıcının çökebilen kapanış aşamasını atla (çıkış kodu = test sonucu)."""
    if _status["code"] is None or "PySide6" not in sys.modules:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_status["code"])
