
import asyncio
import csv
import os
import re
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import urlparse

import aiohttp


@dataclass
class Channel:
    name: str
    url: str
    extinf: str = ""
    group: str = ""
    status: str = "Waiting"
    response_ms: int = 0
    http_status: str = ""
    error: str = ""
    final_url: str = ""
    checked: bool = False


class M3UCheckerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("M3U Stream Checker V2")
        self.geometry("1320x780")
        self.minsize(1020, 620)

        self.channels = []
        self.visible_indices = []
        self.running = False
        self.stop_requested = False
        self.pause_requested = False
        self.async_loop = None
        self.pause_event = None

        self.timeout_var = tk.IntVar(value=10)
        self.workers_var = tk.IntVar(value=60)
        self.slow_var = tk.IntVar(value=2500)
        self.dedupe_var = tk.BooleanVar(value=True)
        self.follow_redirects_var = tk.BooleanVar(value=True)
        self.view_filter_var = tk.StringVar(value="All")
        self.checked_only_var = tk.BooleanVar(value=False)

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        buttons = [
            ("Open M3U / M3U8", self.open_playlist),
            ("Start Check", self.start_check),
            ("Pause", self.pause_check),
            ("Resume", self.resume_check),
            ("Stop", self.stop_check),
            ("Save Working Only", self.save_working),
            ("Save Selected", self.save_selected),
        ]
        for text, cmd in buttons:
            ttk.Button(top, text=text, command=cmd).pack(side="left", padx=4)

        settings = ttk.LabelFrame(self, text="Settings and view", padding=8)
        settings.pack(fill="x", padx=10, pady=(0, 8))

        ttk.Label(settings, text="Timeout").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(settings, from_=2, to=60, textvariable=self.timeout_var, width=6).grid(row=0, column=1, padx=(4, 12))

        ttk.Label(settings, text="Workers").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(settings, from_=1, to=300, textvariable=self.workers_var, width=6).grid(row=0, column=3, padx=(4, 12))

        ttk.Label(settings, text="Slow over ms").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(settings, from_=100, to=30000, increment=100, textvariable=self.slow_var, width=8).grid(row=0, column=5, padx=(4, 12))

        ttk.Checkbutton(settings, text="Merge duplicate URLs", variable=self.dedupe_var).grid(row=0, column=6, padx=8)
        ttk.Checkbutton(settings, text="Follow redirects", variable=self.follow_redirects_var).grid(row=0, column=7, padx=8)

        ttk.Label(settings, text="Show").grid(row=0, column=8, padx=(16, 4))
        view_box = ttk.Combobox(
            settings,
            textvariable=self.view_filter_var,
            values=["All", "Working", "Slow", "Failed", "Working + Slow", "Waiting", "Checking"],
            state="readonly",
            width=16,
        )
        view_box.grid(row=0, column=9, padx=4)
        view_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_tree())

        ttk.Checkbutton(
            settings,
            text="Only checked/scanned",
            variable=self.checked_only_var,
            command=self.refresh_tree,
        ).grid(row=0, column=10, padx=10)

        actions = ttk.Frame(self, padding=(10, 0, 10, 8))
        actions.pack(fill="x")
        for text, cmd in [
            ("Sort Green First", lambda: self.sort_status_order(["Working", "Slow", "Failed", "Checking", "Waiting"])),
            ("Sort Red First", lambda: self.sort_status_order(["Failed", "Slow", "Working", "Checking", "Waiting"])),
            ("Copy Selected Link(s)", self.copy_selected_links),
            ("Copy Selected M3U", self.copy_selected_m3u),
            ("Edit Selected", self.edit_selected),
            ("Delete Selected", self.delete_selected),
            ("Select All Visible", self.select_all_visible),
        ]:
            ttk.Button(actions, text=text, command=cmd).pack(side="left", padx=4)

        body = ttk.Frame(self, padding=(10, 0, 10, 0))
        body.pack(fill="both", expand=True)

        columns = ("status", "name", "group", "url", "http", "time", "final", "error")
        self.tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="extended")

        labels = {
            "status": "Status", "name": "Channel name", "group": "Group",
            "url": "Stream URL", "http": "HTTP", "time": "Response",
            "final": "Final URL", "error": "Error"
        }
        widths = {
            "status": 105, "name": 190, "group": 130, "url": 340,
            "http": 65, "time": 90, "final": 290, "error": 230
        }
        for col in columns:
            self.tree.heading(col, text=labels[col], command=lambda c=col: self.sort_by(c, False))
            self.tree.column(col, width=widths[col], anchor="w")

        ybar = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(body, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.tree.tag_configure("working", background="#d9f7d9", foreground="#116611")
        self.tree.tag_configure("slow", background="#fff3b0", foreground="#6b5600")
        self.tree.tag_configure("failed", background="#ffd6d6", foreground="#8b0000")
        self.tree.tag_configure("waiting", background="#f2f2f2", foreground="#555555")
        self.tree.tag_configure("checking", background="#dbeafe", foreground="#1e3a8a")

        self.tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.tree.bind("<Control-c>", lambda e: self.copy_selected_links())

        footer = ttk.Frame(self, padding=10)
        footer.pack(fill="x")
        self.progress = ttk.Progressbar(footer, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.summary_var = tk.StringVar(value="Open an M3U or M3U8 playlist.")
        ttk.Label(footer, textvariable=self.summary_var).pack(side="right")

    def parse_extinf(self, line):
        name = line.split(",", 1)[1].strip() if "," in line else "Unnamed channel"
        group_match = re.search(r'group-title="([^"]*)"', line, re.I)
        group = group_match.group(1).strip() if group_match else ""
        tvg_name = re.search(r'tvg-name="([^"]*)"', line, re.I)
        if tvg_name and tvg_name.group(1).strip():
            name = tvg_name.group(1).strip()
        return name or "Unnamed channel", group

    def open_playlist(self):
        path = filedialog.askopenfilename(
            title="Open M3U playlist",
            filetypes=[("M3U playlists", "*.m3u *.m3u8"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            lines = Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))
            return

        channels = []
        extinf = name = group = ""
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            if line.upper().startswith("#EXTINF"):
                extinf = line
                name, group = self.parse_extinf(line)
            elif line.startswith("#"):
                continue
            elif self.looks_like_url(line):
                channels.append(Channel(name or self.guess_name(line), line, extinf, group))
                extinf = name = group = ""

        self.channels = self.merge_duplicates(channels) if self.dedupe_var.get() else channels
        self.progress["maximum"] = max(1, len(self.channels))
        self.progress["value"] = 0
        self.refresh_tree()
        self.update_summary()
        self.title(f"M3U Stream Checker V2 - {os.path.basename(path)}")

    def looks_like_url(self, value):
        return value.lower().startswith(("http://", "https://", "rtsp://", "rtmp://"))

    def guess_name(self, url):
        parsed = urlparse(url)
        leaf = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        return leaf or parsed.netloc or "Unnamed channel"

    def normalize_url(self, url):
        return url.strip().rstrip("/").lower()

    def merge_duplicates(self, channels):
        merged = {}
        for ch in channels:
            key = self.normalize_url(ch.url)
            if key not in merged:
                merged[key] = ch
            else:
                old = merged[key]
                if self.name_score(ch.name) > self.name_score(old.name):
                    old.name = ch.name
                if not old.group and ch.group:
                    old.group = ch.group
                if not old.extinf and ch.extinf:
                    old.extinf = ch.extinf
        return list(merged.values())

    def name_score(self, name):
        return 0 if name.strip().lower() in {"", "unknown", "channel", "unnamed channel"} else len(name.strip())

    def channel_visible(self, ch):
        if self.checked_only_var.get() and not ch.checked:
            return False
        vf = self.view_filter_var.get()
        if vf == "All":
            return True
        if vf == "Working + Slow":
            return ch.status in ("Working", "Slow")
        return ch.status == vf

    def refresh_tree(self):
        selected_models = self.get_selected_model_indices()
        self.tree.delete(*self.tree.get_children())
        self.visible_indices = []
        for model_index, ch in enumerate(self.channels):
            if self.channel_visible(ch):
                iid = f"row_{model_index}"
                self.visible_indices.append(model_index)
                self.tree.insert("", "end", iid=iid, values=self.row_values(ch), tags=(self.tag_for(ch.status),))
                if model_index in selected_models:
                    self.tree.selection_add(iid)
        self.update_summary()

    def row_values(self, ch):
        return (
            self.status_text(ch.status), ch.name, ch.group, ch.url,
            ch.http_status, f"{ch.response_ms} ms" if ch.response_ms else "",
            ch.final_url, ch.error
        )

    def status_text(self, status):
        return {
            "Working": "● Working", "Slow": "● Slow", "Failed": "● Failed",
            "Checking": "● Checking", "Waiting": "○ Waiting"
        }.get(status, status)

    def tag_for(self, status):
        return {
            "Working": "working", "Slow": "slow", "Failed": "failed",
            "Checking": "checking", "Waiting": "waiting"
        }.get(status, "waiting")

    def insert_or_update(self, model_index):
        ch = self.channels[model_index]
        iid = f"row_{model_index}"
        visible = self.channel_visible(ch)
        exists = self.tree.exists(iid)
        if visible and exists:
            self.tree.item(iid, values=self.row_values(ch), tags=(self.tag_for(ch.status),))
        elif visible and not exists:
            self.tree.insert("", "end", iid=iid, values=self.row_values(ch), tags=(self.tag_for(ch.status),))
        elif not visible and exists:
            self.tree.delete(iid)

    def get_selected_model_indices(self):
        result = []
        for iid in self.tree.selection():
            if iid.startswith("row_"):
                try:
                    result.append(int(iid.split("_", 1)[1]))
                except ValueError:
                    pass
        return result

    def start_check(self):
        if self.running:
            return
        if not self.channels:
            messagebox.showinfo("No playlist", "Open an M3U or M3U8 file first.")
            return
        self.running = True
        self.stop_requested = False
        self.pause_requested = False
        self.progress["value"] = 0
        for i, ch in enumerate(self.channels):
            ch.status = "Waiting"
            ch.checked = False
            ch.response_ms = 0
            ch.http_status = ""
            ch.error = ""
            ch.final_url = ""
            self.insert_or_update(i)
        threading.Thread(target=self._run_async_check, daemon=True).start()

    def pause_check(self):
        if self.running:
            self.pause_requested = True
            self.summary_var.set(self.summary_var.get() + "   PAUSED")

    def resume_check(self):
        if self.running:
            self.pause_requested = False
            if self.async_loop and self.pause_event:
                self.async_loop.call_soon_threadsafe(self.pause_event.set)

    def stop_check(self):
        self.stop_requested = True
        self.pause_requested = False
        if self.async_loop and self.pause_event:
            self.async_loop.call_soon_threadsafe(self.pause_event.set)

    def _run_async_check(self):
        try:
            asyncio.run(self.check_all())
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("Checker error", str(exc)))
        finally:
            self.running = False
            self.after(0, self.update_summary)

    async def wait_if_paused(self):
        while self.pause_requested and not self.stop_requested:
            self.pause_event.clear()
            await self.pause_event.wait()

    async def check_all(self):
        self.async_loop = asyncio.get_running_loop()
        self.pause_event = asyncio.Event()
        self.pause_event.set()
        timeout = aiohttp.ClientTimeout(total=max(2, self.timeout_var.get()))
        connector = aiohttp.TCPConnector(
            limit=max(1, self.workers_var.get()),
            ssl=False,
            enable_cleanup_closed=True
        )
        headers = {"User-Agent": "Mozilla/5.0 M3U-Stream-Checker/2.0", "Accept": "*/*"}

        sem = asyncio.Semaphore(max(1, self.workers_var.get()))
        async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
            tasks = [asyncio.create_task(self.check_one(session, sem, i)) for i in range(len(self.channels))]
            for future in asyncio.as_completed(tasks):
                if self.stop_requested:
                    for task in tasks:
                        task.cancel()
                    break
                try:
                    await future
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

    async def check_one(self, session, sem, index):
        async with sem:
            await self.wait_if_paused()
            if self.stop_requested:
                return
            ch = self.channels[index]
            ch.status = "Checking"
            self.after(0, lambda: self.insert_or_update(index))
            started = time.perf_counter()

            try:
                async with session.get(
                    ch.url,
                    allow_redirects=self.follow_redirects_var.get(),
                    headers={"Range": "bytes=0-2047"}
                ) as response:
                    data = await response.content.read(2048)
                    ch.response_ms = int((time.perf_counter() - started) * 1000)
                    ch.http_status = str(response.status)
                    ch.final_url = str(response.url)
                    ctype = response.headers.get("Content-Type", "").lower()
                    ok = 200 <= response.status < 400 and bool(data)

                    if ok:
                        ch.status = "Slow" if ch.response_ms >= self.slow_var.get() else "Working"
                    else:
                        ch.status = "Failed"
                        ch.error = f"HTTP {response.status}" if not (200 <= response.status < 400) else "No stream data"

                    sample = data.lstrip().lower()
                    if "text/html" in ctype and sample.startswith((b"<!doctype html", b"<html")):
                        ch.status = "Failed"
                        ch.error = "Returned a web page, not a stream"

            except asyncio.TimeoutError:
                ch.status = "Failed"
                ch.error = "Connection timed out"
                ch.response_ms = int((time.perf_counter() - started) * 1000)
            except Exception as exc:
                ch.status = "Failed"
                ch.error = str(exc)
                ch.response_ms = int((time.perf_counter() - started) * 1000)

            ch.checked = True
            self.after(0, lambda: self.on_checked(index))

    def on_checked(self, index):
        self.insert_or_update(index)
        self.progress["value"] = min(len(self.channels), self.progress["value"] + 1)
        self.update_summary()

    def update_summary(self):
        total = len(self.channels)
        working = sum(ch.status == "Working" for ch in self.channels)
        slow = sum(ch.status == "Slow" for ch in self.channels)
        failed = sum(ch.status == "Failed" for ch in self.channels)
        checked = sum(ch.checked for ch in self.channels)
        visible = len([ch for ch in self.channels if self.channel_visible(ch)])
        paused = "   PAUSED" if self.pause_requested else ""
        self.summary_var.set(
            f"Total: {total}   Checked: {checked}   Visible: {visible}   Green: {working}   Yellow: {slow}   Red: {failed}{paused}"
        )

    def sort_status_order(self, order):
        rank = {name: i for i, name in enumerate(order)}
        self.channels.sort(key=lambda ch: (rank.get(ch.status, 99), ch.name.lower()))
        self.refresh_tree()

    def sort_by(self, column, reverse):
        keymap = {
            "status": lambda ch: ch.status,
            "name": lambda ch: ch.name.lower(),
            "group": lambda ch: ch.group.lower(),
            "url": lambda ch: ch.url.lower(),
            "http": lambda ch: int(ch.http_status) if ch.http_status.isdigit() else 9999,
            "time": lambda ch: ch.response_ms if ch.response_ms else 10**9,
            "final": lambda ch: ch.final_url.lower(),
            "error": lambda ch: ch.error.lower(),
        }
        self.channels.sort(key=keymap[column], reverse=reverse)
        self.refresh_tree()
        self.tree.heading(column, command=lambda: self.sort_by(column, not reverse))

    def select_all_visible(self):
        self.tree.selection_set(self.tree.get_children())

    def copy_selected_links(self):
        indices = self.get_selected_model_indices()
        if not indices:
            return
        text = "\n".join(self.channels[i].url for i in indices)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()

    def copy_selected_m3u(self):
        indices = self.get_selected_model_indices()
        if not indices:
            return
        lines = ["#EXTM3U"]
        for i in indices:
            ch = self.channels[i]
            lines.append(ch.extinf or f'#EXTINF:-1 group-title="{ch.group}",{ch.name}')
            lines.append(ch.url)
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.update()

    def edit_selected(self):
        indices = self.get_selected_model_indices()
        if len(indices) != 1:
            messagebox.showinfo("Edit", "Select exactly one row to edit.")
            return
        i = indices[0]
        ch = self.channels[i]
        new_name = simpledialog.askstring("Edit channel", "Channel name:", initialvalue=ch.name, parent=self)
        if new_name is None:
            return
        new_url = simpledialog.askstring("Edit channel", "Stream URL:", initialvalue=ch.url, parent=self)
        if new_url is None:
            return
        new_group = simpledialog.askstring("Edit channel", "Group:", initialvalue=ch.group, parent=self)
        if new_group is None:
            return

        ch.name = new_name.strip() or ch.name
        ch.url = new_url.strip() or ch.url
        ch.group = new_group.strip()
        ch.extinf = f'#EXTINF:-1 group-title="{ch.group}",{ch.name}'
        ch.status = "Waiting"
        ch.checked = False
        ch.error = ""
        ch.http_status = ""
        ch.response_ms = 0
        ch.final_url = ""
        self.refresh_tree()

    def delete_selected(self):
        indices = sorted(self.get_selected_model_indices(), reverse=True)
        for i in indices:
            if 0 <= i < len(self.channels):
                del self.channels[i]
        self.refresh_tree()

    def save_working(self):
        good = [ch for ch in self.channels if ch.status in ("Working", "Slow")]
        if not good:
            messagebox.showinfo("Nothing to save", "No working or slow streams are available.")
            return
        self.save_m3u(good, "working_streams.m3u")

    def save_selected(self):
        indices = self.get_selected_model_indices()
        if not indices:
            messagebox.showinfo("Save selected", "Select one or more rows first.")
            return
        self.save_m3u([self.channels[i] for i in indices], "selected_streams.m3u")

    def save_m3u(self, channels, default_name):
        path = filedialog.asksaveasfilename(
            title="Save playlist",
            initialfile=default_name,
            defaultextension=".m3u",
            filetypes=[("M3U playlist", "*.m3u"), ("M3U8 playlist", "*.m3u8")]
        )
        if not path:
            return
        self.write_m3u(path, channels)
        messagebox.showinfo("Saved", f"Saved {len(channels)} stream(s) to:\n{path}")

    def write_m3u(self, path, channels):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("#EXTM3U\n")
            for ch in channels:
                f.write((ch.extinf or f'#EXTINF:-1 group-title="{ch.group}",{ch.name}') + "\n")
                f.write(ch.url + "\n")


if __name__ == "__main__":
    M3UCheckerApp().mainloop()
