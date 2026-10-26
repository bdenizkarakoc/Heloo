"""Basit masaüstü arayüzü (Tkinter). Klip ekle, efekt uygula, dışa aktar, önerileri onayla."""
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import config, project, render
from .effects import load_registry
from .evolve import daemon, engine, store


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SelfEdit Studio")
        self.geometry("820x560")
        self.proj = project.new_project()
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self.edit_tab, self.evo_tab = ttk.Frame(nb), ttk.Frame(nb)
        nb.add(self.edit_tab, text="Düzenle")
        nb.add(self.evo_tab, text="Kendini geliştirme")
        self._build_edit()
        self._build_evo()
        self.refresh_all()

    # ---- Düzenle ----
    def _build_edit(self):
        f = self.edit_tab
        left = ttk.Frame(f); left.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        ttk.Label(left, text="Klipler").pack(anchor="w")
        self.clips = tk.Listbox(left, exportselection=False)
        self.clips.pack(fill="both", expand=True)
        self.clips.bind("<<ListboxSelect>>", lambda e: self.refresh_fx())
        row = ttk.Frame(left); row.pack(fill="x", pady=4)
        ttk.Button(row, text="Klip ekle", command=self.add_clip).pack(side="left")
        ttk.Button(row, text="Sil", command=self.del_clip).pack(side="left", padx=4)
        ttk.Button(row, text="Projeyi kaydet", command=self.save_proj).pack(side="left")
        ttk.Button(row, text="Projeyi aç", command=self.open_proj).pack(side="left", padx=4)

        right = ttk.Frame(f); right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        ttk.Label(right, text="Seçili klibin efektleri").pack(anchor="w")
        self.fxlist = tk.Listbox(right, height=8); self.fxlist.pack(fill="x")
        self.fx_name = ttk.Combobox(right, state="readonly"); self.fx_name.pack(fill="x", pady=(8, 0))
        self.fx_params = ttk.Entry(right); self.fx_params.pack(fill="x", pady=4)
        ttk.Label(right, text="Parametreler: ad=değer ad2=değer (boş bırakılabilir)").pack(anchor="w")
        ttk.Button(right, text="Efekt ekle", command=self.add_fx).pack(anchor="w", pady=4)
        ttk.Button(right, text="Dışa aktar (render)", command=self.do_render).pack(anchor="w", pady=12)
        self.status = ttk.Label(right, text=""); self.status.pack(anchor="w")

    def refresh_all(self):
        reg = load_registry()
        self.fx_name["values"] = reg.names()
        self.refresh_clips()
        self.refresh_props()

    def refresh_clips(self):
        self.clips.delete(0, "end")
        for i, c in enumerate(self.proj["clips"]):
            self.clips.insert("end", f"{i}: {Path(c['src']).name}  [{c['start']}–{c['end'] or 'son'}]")

    def refresh_fx(self):
        self.fxlist.delete(0, "end")
        i = self._sel()
        if i is None:
            return
        for fx in self.proj["clips"][i]["effects"]:
            self.fxlist.insert("end", f"{fx['name']} {fx['params']}")

    def _sel(self):
        s = self.clips.curselection()
        return s[0] if s else None

    def add_clip(self):
        f = filedialog.askopenfilename(title="Video seç")
        if f:
            project.add_clip(self.proj, f)
            self.refresh_clips()

    def del_clip(self):
        i = self._sel()
        if i is not None:
            del self.proj["clips"][i]
            self.refresh_clips(); self.refresh_fx()

    def add_fx(self):
        i = self._sel()
        if i is None or not self.fx_name.get():
            messagebox.showinfo("SelfEdit", "Önce bir klip ve efekt seç.")
            return
        params = dict(p.split("=", 1) for p in self.fx_params.get().split() if "=" in p)
        project.add_effect(self.proj, i, self.fx_name.get(), params)
        self.refresh_fx()

    def save_proj(self):
        f = filedialog.asksaveasfilename(defaultextension=".json")
        if f:
            project.save(self.proj, f)

    def open_proj(self):
        f = filedialog.askopenfilename(filetypes=[("Proje", "*.json")])
        if f:
            self.proj = project.load(f)
            self.refresh_clips(); self.refresh_fx()

    def do_render(self):
        out = filedialog.asksaveasfilename(defaultextension=".mp4")
        if not out:
            return
        self.status.config(text="Render ediliyor...")

        def work():
            try:
                r = render.render_project(self.proj, out, ".")
                msg = f"Hazır ({r['seconds']} sn)"
            except Exception as e:
                msg = f"Hata: {e}"
            self.after(0, lambda: self.status.config(text=msg[:300]))
        threading.Thread(target=work, daemon=True).start()

    # ---- Kendini geliştirme ----
    def _build_evo(self):
        f = self.evo_tab
        top = ttk.Frame(f); top.pack(fill="x", padx=8, pady=8)
        ttk.Label(top, text="Mod:").pack(side="left")
        self.mode = ttk.Combobox(top, state="readonly", values=list(config.MODES), width=10)
        self.mode.set(config.load()["mode"]); self.mode.pack(side="left", padx=4)
        self.mode.bind("<<ComboboxSelected>>", lambda e: config.set_value("mode", self.mode.get()))
        ttk.Button(top, text="Şimdi geliştirme turu çalıştır", command=self.run_evolve).pack(side="left", padx=8)
        self.daemon_lbl = ttk.Label(top, text=""); self.daemon_lbl.pack(side="left")
        self.props = tk.Listbox(f, exportselection=False); self.props.pack(fill="both", expand=True, padx=8)
        self.props.bind("<<ListboxSelect>>", lambda e: self.show_prop())
        self.detail = tk.Text(f, height=10); self.detail.pack(fill="x", padx=8, pady=4)
        row = ttk.Frame(f); row.pack(fill="x", padx=8, pady=4)
        for t, fn in (("Onayla ve uygula", engine.apply), ("Reddet", engine.reject), ("Geri al", engine.rollback)):
            ttk.Button(row, text=t, command=lambda fn=fn: self.prop_action(fn)).pack(side="left", padx=2)
        self._ids = []

    def refresh_props(self):
        self.props.delete(0, "end")
        self._ids = []
        for p in reversed(store.list_all()):
            self.props.insert("end", f"[{p['status']}] {p['title']}  ({p['source']})")
            self._ids.append(p["id"])
        st = daemon.read_status()
        self.daemon_lbl.config(text="Servis: çalışıyor" if st.get("running") else "Servis: kapalı")

    def _sel_prop(self):
        s = self.props.curselection()
        return self._ids[s[0]] if s else None

    def show_prop(self):
        pid = self._sel_prop()
        if not pid:
            return
        p = store.load(pid)
        steps = "\n".join(f"{'✓' if s['ok'] else '✗'} {s['step']}: {s['detail']}"
                          for s in (p.get("validation") or {}).get("steps", []))
        self.detail.delete("1.0", "end")
        self.detail.insert("end", f"{p['rationale']}\n\n{steps}\n\n{p['code']}")

    def prop_action(self, fn):
        pid = self._sel_prop()
        if pid:
            messagebox.showinfo("SelfEdit", fn(pid)["detail"])
            self.refresh_all()

    def run_evolve(self):
        def work():
            res = engine.run_cycle(force=True)
            self.after(0, lambda: (messagebox.showinfo("SelfEdit", str(res)), self.refresh_all()))
        threading.Thread(target=work, daemon=True).start()


def main():
    App().mainloop()
