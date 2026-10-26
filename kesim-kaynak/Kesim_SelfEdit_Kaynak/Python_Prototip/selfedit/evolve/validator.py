"""Bir eklenti önerisini üç aşamada doğrular: statik tarama -> sandbox render -> test paketi.

NOT: Bu bir güvenlik duvarı değil, katmanlı bir önlemdir. Statik tarama tehlikeli kod
kalıplarını reddeder; kod ayrı bir süreçte, temizlenmiş ortamla, geçici bir kopyada ve
zaman aşımıyla çalışır. Daha sıkı yalıtım için daemon'u bir konteyner/VM içinde çalıştırın.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .. import paths

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
MAX_BYTES = 8000
ALLOWED_IMPORTS = {"math", "re"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "open", "__import__", "input", "getattr", "setattr",
                   "delattr", "globals", "locals", "vars", "breakpoint", "exit", "quit", "memoryview"}
REQUIRED_TOP = ("NAME", "DESCRIPTION", "PARAMS")


def static_check(code: str, name: str) -> list:
    """Sorunların listesini döndürür; boşsa kod temiz."""
    problems = []
    if not NAME_RE.match(name or ""):
        return ["eklenti adı geçersiz (küçük harf, rakam, _ ; 3-31 karakter)"]
    if len(code.encode("utf-8")) > MAX_BYTES:
        return [f"kod {MAX_BYTES} baytı aşıyor"]
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"sözdizimi hatası: {e}"]

    top_assigned = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                if m.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"izin verilmeyen import: {m}")
            if isinstance(node, ast.ImportFrom) and node.level:
                problems.append("göreli import yasak")
        elif isinstance(node, ast.Assign):
            try:
                ast.literal_eval(node.value)
            except Exception:
                if not (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                        and isinstance(node.value.func.value, ast.Name) and node.value.func.value.id == "re"
                        and node.value.func.attr == "compile"):
                    problems.append("üst düzey atamalar sabit değer olmalı (import anında kod çalışamaz)")
            for t in node.targets:
                if isinstance(t, ast.Name):
                    top_assigned.add(t.id)
        elif isinstance(node, ast.FunctionDef):
            pass
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            pass
        else:
            problems.append(f"üst düzeyde izin verilmeyen ifade: {type(node).__name__}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id.startswith("__") or node.id in FORBIDDEN_CALLS:
                problems.append(f"yasak ad: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"yasak öznitelik: {node.attr}")
        elif isinstance(node, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef, ast.ClassDef, ast.Await, ast.Lambda)):
            problems.append(f"izin verilmeyen yapı: {type(node).__name__}")

    for req in REQUIRED_TOP:
        if req not in top_assigned:
            problems.append(f"{req} tanımlı değil")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "video_filter" for n in tree.body):
        problems.append("video_filter fonksiyonu yok")
    try:
        declared = next(ast.literal_eval(n.value) for n in tree.body
                        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "NAME" for t in n.targets))
        if declared != name:
            problems.append(f"NAME ('{declared}') eklenti adıyla ('{name}') aynı olmalı")
    except (StopIteration, ValueError):
        pass
    return sorted(set(problems))


def _clean_env(home: Path) -> dict:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "TMPDIR": str(home),
           "TEMP": str(home), "TMP": str(home), "SELFEDIT_HOME": str(home),
           "SELFEDIT_IN_SANDBOX": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
    return env  # API anahtarları ve diğer gizli değişkenler bilerek aktarılmaz


def _limits():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
        resource.setrlimit(resource.RLIMIT_FSIZE, (500 * 1024 * 1024,) * 2)
    except Exception:
        pass


def _run(cmd, cwd, env, timeout):
    kwargs = {"preexec_fn": _limits} if os.name == "posix" else {}
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, **kwargs)
        return r.returncode, (r.stdout + r.stderr)[-1500:]
    except subprocess.TimeoutExpired:
        return 124, "zaman aşımı"


def make_sandbox(extra_plugin: tuple = None) -> Path:
    """Paketin, testlerin ve mevcut eklentilerin geçici bir kopyasını oluşturur."""
    box = Path(tempfile.mkdtemp(prefix="selfedit_box_"))
    code = paths.code_root()
    shutil.copytree(code / "selfedit", box / "selfedit",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if (code / "tests").exists():
        shutil.copytree(code / "tests", box / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(paths.plugins(), box / "plugins", ignore=shutil.ignore_patterns("__pycache__"))
    if extra_plugin:
        name, code_text = extra_plugin
        (box / "plugins" / f"{name}.py").write_text(code_text, encoding="utf-8")
    return box


def smoke(repo_root: Path, name: str, timeout: int = 120) -> dict:
    """repo_root içinde eklentiyi gerçek bir render ile dener."""
    script = repo_root / "selfedit" / "evolve" / "sandbox_check.py"
    rc, out = _run([sys.executable, "-I", str(script), str(repo_root), name],
                   cwd=repo_root, env=_clean_env(repo_root), timeout=timeout)
    last = out.strip().splitlines()[-1] if out.strip() else ""
    try:
        res = json.loads(last)
    except ValueError:
        res = {"ok": False, "detail": out[-400:] or "çıktı yok"}
    res["ok"] = bool(res.get("ok")) and rc == 0
    return res


def validate(code: str, name: str, run_suite: bool = True) -> dict:
    steps = []

    problems = static_check(code, name)
    steps.append({"step": "statik tarama", "ok": not problems, "detail": "; ".join(problems) or "temiz"})
    if problems:
        return {"ok": False, "steps": steps}

    if (paths.plugins() / f"{name}.py").exists():
        steps.append({"step": "ad çakışması", "ok": False, "detail": "bu adla bir eklenti zaten var"})
        return {"ok": False, "steps": steps}

    box = make_sandbox((name, code))
    try:
        res = smoke(box, name)
        steps.append({"step": "sandbox render", "ok": res["ok"], "detail": res.get("detail", "")})
        if not res["ok"]:
            return {"ok": False, "steps": steps}

        if run_suite and (box / "tests").exists():
            rc, out = _run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                           cwd=box, env=_clean_env(box), timeout=600)
            tail = out.strip().splitlines()[-3:]
            steps.append({"step": "test paketi", "ok": rc == 0, "detail": " | ".join(tail)})
            if rc != 0:
                return {"ok": False, "steps": steps}
    finally:
        shutil.rmtree(box, ignore_errors=True)
    return {"ok": True, "steps": steps}
