"""Heloo TV başlatıcı (pythonw ile, konsolsuz). Kısayol, "Gönder" ve "Birlikte aç" bunu kullanır:
    pythonw.exe HelooTV.pyw [dosya ya da bağlantı ...]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helootv.app import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
