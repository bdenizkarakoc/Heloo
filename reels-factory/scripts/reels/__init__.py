"""Otonom AI Reels fabrikası — üretim hattı paketi."""

__version__ = "0.1.0"


def _hide_console_windows() -> None:
    """Windows: uygulama penceresiz (pythonw) çalışırken ffmpeg, git, node, claude gibi her alt süreç kendi CMD
    penceresini açar. Bütün alt süreçler varsayılan olarak penceresiz başlatılır; bilerek pencere açan çağrılar
    (ör. Claude Code kurulum penceresi) creationflags'i kendisi verir ve buna dokunulmaz."""
    import os
    import subprocess
    if os.name != "nt" or getattr(subprocess.Popen, "_rf_no_window", False):
        return
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    original = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):  # noqa: N807
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = flag
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__
    subprocess.Popen._rf_no_window = True


_hide_console_windows()
