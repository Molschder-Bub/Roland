#!/usr/bin/env python3
"""YouTube to MP3 Converter"""

import sys
import subprocess
import threading
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

BG   = "#2b2b2b"
FG   = "#ffffff"
CARD = "#444444"
BTN  = "#007aff"
GRN  = "#4CAF50"


def ensure_package(package, import_name=None):
    name = import_name or package
    try:
        __import__(name)
        return True
    except ImportError:
        pass
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", package],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def check_ffmpeg():
    try:
        subprocess.check_call(["ffmpeg", "-version"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


class TextEntry(tk.Text):
    """Einzeiliges Text-Widget als Entry-Ersatz (macOS-kompatibel)."""
    def __init__(self, parent, **kw):
        kw.setdefault("height", 1)
        kw.setdefault("font", ("Helvetica", 13))
        kw.setdefault("fg", FG)
        kw.setdefault("bg", CARD)
        kw.setdefault("insertbackground", FG)
        kw.setdefault("relief", "flat")
        kw.setdefault("wrap", "none")
        kw.setdefault("bd", 6)
        super().__init__(parent, **kw)
        self.bind("<Return>", lambda e: "break")

    def get_value(self):
        return self.get("1.0", "end-1c").strip()

    def set_value(self, val):
        self.delete("1.0", "end")
        self.insert("1.0", val)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube → MP3")
        self.configure(bg=BG)
        self.geometry("540x460")
        self.resizable(False, False)
        self._has_ffmpeg = check_ffmpeg()
        self._build_ui()

    def _build_ui(self):
        def lbl(parent, text, big=False, bold=False, color=FG):
            size  = 16 if big else 12
            style = "bold" if bold else "normal"
            tk.Label(parent, text=text, font=("Helvetica", size, style),
                     fg=color, bg=BG, anchor="w").pack(fill="x", padx=24, pady=(0, 4))

        # Titel
        tk.Label(self, text="YouTube → MP3",
                 font=("Helvetica", 22, "bold"), fg=GRN, bg=BG).pack(pady=(24, 2))
        tk.Label(self, text="Audio herunterladen & konvertieren",
                 font=("Helvetica", 12), fg="#aaaaaa", bg=BG).pack(pady=(0, 20))

        # URL
        lbl(self, "YouTube-URL:", bold=True)
        url_row = tk.Frame(self, bg=BG)
        url_row.pack(fill="x", padx=24, pady=(0, 14))
        self.url_box = TextEntry(url_row)
        self.url_box.pack(side="left", fill="x", expand=True)
        tk.Button(url_row, text="Einfügen", command=self._paste,
                  font=("Helvetica", 12), fg=FG, bg="#555",
                  activebackground="#666", activeforeground=FG,
                  relief="flat", bd=0, padx=10, pady=6).pack(side="left", padx=(8, 0))

        # Speicherort
        lbl(self, "Speicherort:", bold=True)
        folder_row = tk.Frame(self, bg=BG)
        folder_row.pack(fill="x", padx=24, pady=(0, 14))
        self.folder_box = TextEntry(folder_row)
        self.folder_box.set_value(os.path.expanduser("~/Downloads"))
        self.folder_box.pack(side="left", fill="x", expand=True)
        tk.Button(folder_row, text="Ordner…", command=self._browse,
                  font=("Helvetica", 12), fg=FG, bg="#555",
                  activebackground="#666", activeforeground=FG,
                  relief="flat", bd=0, padx=10, pady=6).pack(side="left", padx=(8, 0))

        # Qualität
        lbl(self, "Qualität:", bold=True)
        q_row = tk.Frame(self, bg=BG)
        q_row.pack(anchor="w", padx=24, pady=(0, 16))
        self.quality_var = tk.StringVar(value="320")
        for q in ["128", "192", "256", "320"]:
            tk.Radiobutton(q_row, text=f"{q} kbps", variable=self.quality_var,
                           value=q, font=("Helvetica", 12),
                           fg=FG, bg=BG, selectcolor=CARD,
                           activebackground=BG, activeforeground=FG).pack(
                side="left", padx=(0, 14))

        # Warnung ffmpeg
        if not self._has_ffmpeg:
            tk.Label(self, text="⚠  ffmpeg fehlt – Ausgabe als .m4a  |  brew install ffmpeg für MP3",
                     font=("Helvetica", 11), fg="#f0c040", bg="#3a2e00",
                     anchor="w").pack(fill="x", padx=24, pady=(0, 10), ipady=7, ipadx=10)

        # Download-Button
        self.dl_btn = tk.Button(self, text="⬇  Herunterladen",
                                font=("Helvetica", 14, "bold"),
                                fg=FG, bg=BTN,
                                activebackground="#005ecb", activeforeground=FG,
                                relief="flat", bd=0, cursor="hand2",
                                command=self._start_download)
        self.dl_btn.pack(fill="x", padx=24, pady=(0, 10), ipady=12)

        # Fortschritt
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=24, pady=(0, 6))

        # Status
        self.status_var = tk.StringVar(value="Bereit")
        tk.Label(self, textvariable=self.status_var, font=("Helvetica", 11),
                 fg="#aaaaaa", bg=BG, anchor="w", wraplength=490).pack(
            fill="x", padx=24, pady=(0, 20))

    def _paste(self):
        try:
            self.url_box.set_value(self.clipboard_get())
        except tk.TclError:
            pass

    def _browse(self):
        path = filedialog.askdirectory(initialdir=self.folder_box.get_value())
        if path:
            self.folder_box.set_value(path)

    def _set_status(self, msg):
        self.status_var.set(msg)

    def _start_download(self):
        url = self.url_box.get_value()
        if not url:
            messagebox.showwarning("Fehlende URL", "Bitte eine YouTube-URL eingeben.")
            return
        self.dl_btn.config(state="disabled")
        self.progress.start(12)
        threading.Thread(target=self._download_thread, args=(url,), daemon=True).start()

    def _download_thread(self, url):
        try:
            self._set_status("Prüfe yt-dlp …")
            if not ensure_package("yt-dlp"):
                raise RuntimeError("yt-dlp konnte nicht installiert werden.")

            import yt_dlp

            output_dir = self.folder_box.get_value()
            quality    = self.quality_var.get()

            if self._has_ffmpeg:
                fmt       = "bestaudio/best"
                postprocs = [{"key": "FFmpegExtractAudio",
                              "preferredcodec": "mp3",
                              "preferredquality": quality}]
                ext       = "mp3"
            else:
                fmt       = "bestaudio[ext=m4a]/bestaudio/best"
                postprocs = []
                ext       = "m4a"

            def progress_hook(d):
                if d["status"] == "downloading":
                    pct = d.get("_percent_str", "").strip()
                    spd = d.get("_speed_str", "").strip()
                    self._set_status(f"Lade herunter … {pct}  {spd}")
                elif d["status"] == "finished":
                    self._set_status("Konvertiere Audio …")

            opts = {
                "format": fmt,
                "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
                "postprocessors": postprocs,
                "progress_hooks": [progress_hook],
                "quiet": True,
                "no_warnings": True,
            }

            self._set_status("Starte Download …")
            with yt_dlp.YoutubeDL(opts) as ydl:
                info  = ydl.extract_info(url, download=True)
                title = info.get("title", "Unbekannt")

            self._set_status(f'✓ Fertig: "{title}.{ext}"')
            messagebox.showinfo("Fertig",
                                f'"{title}.{ext}" gespeichert in:\n{output_dir}')

        except Exception as exc:
            self._set_status(f"Fehler: {exc}")
            messagebox.showerror("Fehler", str(exc))
        finally:
            self.progress.stop()
            self.dl_btn.config(state="normal")


if __name__ == "__main__":
    app = App()
    app.mainloop()
