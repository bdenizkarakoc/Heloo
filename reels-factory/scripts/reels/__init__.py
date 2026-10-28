"""Otonom AI Reels fabrikası — üretim hattı paketi."""

__version__ = "0.1.0"


def _patch_popen() -> None:
    """Bütün alt süreçler için tek kanca:
    - Windows: uygulama penceresiz (pythonw) çalışırken ffmpeg, git, node, claude gibi her alt süreç kendi CMD
      penceresini açar. Alt süreçler varsayılan olarak penceresiz başlatılır; bilerek pencere açan çağrılar
      (ör. Claude Code kurulum penceresi) creationflags'i kendisi verir ve buna dokunulmaz.
    - Her işletim sistemi: iş kuyruğunun başlattığı süreçler "Durdur" için kaydedilir (reels.cancel)."""
    import os
    import subprocess
    if getattr(subprocess.Popen, "_rf_patched", False):
        return
    from . import cancel
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    original = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):  # noqa: N807
        if os.name == "nt" and not kwargs.get("creationflags"):
            kwargs["creationflags"] = flag
        original(self, *args, **kwargs)
        cancel.track(self)

    subprocess.Popen.__init__ = __init__
    subprocess.Popen._rf_patched = True


_patch_popen()
