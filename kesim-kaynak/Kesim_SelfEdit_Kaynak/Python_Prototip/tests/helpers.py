import os
import shutil
import tempfile
from pathlib import Path


class TempHome:
    """SELFEDIT_HOME'u geçici bir klasöre yönlendirir; plugins/ gerçek eklentilerin kopyasıdır."""

    def __init__(self):
        from selfedit import paths
        self.old = os.environ.get("SELFEDIT_HOME")
        self.old_pl = os.environ.pop("SELFEDIT_PLUGINS", None)
        self.dir = Path(tempfile.mkdtemp(prefix="selfedit_test_"))
        src = paths.plugins() if self.old is None else Path(self.old) / "plugins"
        shutil.copytree(src, self.dir / "plugins", ignore=shutil.ignore_patterns("__pycache__"))
        os.environ["SELFEDIT_HOME"] = str(self.dir)

    def close(self):
        if self.old is None:
            os.environ.pop("SELFEDIT_HOME", None)
        else:
            os.environ["SELFEDIT_HOME"] = self.old
        if self.old_pl:
            os.environ["SELFEDIT_PLUGINS"] = self.old_pl
        shutil.rmtree(self.dir, ignore_errors=True)
