# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
GUI Module – Encrypted P2P Chat Interface

A dark, terminal-inspired Tkinter interface for the P2P group chat.
Aesthetic: industrial / cypherpunk — monospace type, sharp edges,
high-contrast neon accent on matte dark backgrounds.
"""

import asyncio
import queue
import threading
import time
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as mb
import tkinter.simpledialog as sd
from tkinter import ttk
from typing import Optional

# ---------------------------------------------------------------------------
# Colour / font palette
# ---------------------------------------------------------------------------

C = {
    "bg":        "#0d0f13",   # near-black background
    "panel":     "#141720",   # slightly lighter panel
    "border":    "#1e2330",   # subtle borders
    "accent":    "#00e5a0",   # neon mint – primary accent
    "accent2":   "#0099ff",   # electric blue – secondary
    "warn":      "#ff4d6a",   # error / warning red
    "muted":     "#4a5070",   # de-emphasised text
    "fg":        "#c8d0e0",   # main text
    "fg_dim":    "#6a7590",   # timestamps, labels
    "bubble_me": "#0f2a1e",   # own message bubble
    "bubble_ot": "#131a2a",   # other's message bubble
    "input_bg":  "#0a0c10",   # message input background
    "scrollbar": "#1e2330",
}

FONT_MONO  = ("Courier New", 11)
FONT_MONO_S = ("Courier New", 9)
FONT_HEAD  = ("Courier New", 14, "bold")
FONT_LABEL = ("Courier New", 10)
FONT_SMALL = ("Courier New", 8)


# ---------------------------------------------------------------------------
# Helper widgets
# ---------------------------------------------------------------------------

class _Scrollable(tk.Frame):
    """A Frame with a vertical scrollbar wired up."""

    def __init__(self, master, **kw):
        super().__init__(master, bg=C["bg"])
        self.canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0,
                                bd=0, **kw)
        self.sb = tk.Scrollbar(self, orient="vertical",
                               command=self.canvas.yview,
                               bg=C["scrollbar"],
                               troughcolor=C["panel"])
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=C["bg"])
        self._win = self.canvas.create_window((0, 0), window=self.inner,
                                               anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_inner_configure(self, _):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self._win, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def scroll_to_bottom(self):
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)


# ---------------------------------------------------------------------------
# Message bubble
# ---------------------------------------------------------------------------

class MessageBubble(tk.Frame):
    """
    Renders a single chat message with sender, timestamp, and body text.
    Own messages are right-aligned with a green tint; others left/blue.
    """

    def __init__(self, parent, text: str, sender: str,
                 ts: int, is_own: bool = False):
        super().__init__(parent, bg=C["bg"])

        bubble_bg = C["bubble_me"] if is_own else C["bubble_ot"]
        accent    = C["accent"]    if is_own else C["accent2"]
        anchor    = "e"            if is_own else "w"
        side      = "right"        if is_own else "left"

        outer = tk.Frame(self, bg=C["bg"])
        outer.pack(anchor=anchor, padx=10, pady=3)

        # Accent bar on the left / right
        bar = tk.Frame(outer, bg=accent, width=3)
        bar.pack(side=side, fill="y")

        # Inner content
        bubble = tk.Frame(outer, bg=bubble_bg, padx=10, pady=6)
        bubble.pack(side=side)

        # Header row
        hdr = tk.Frame(bubble, bg=bubble_bg)
        hdr.pack(fill="x")

        ts_str = time.strftime("%H:%M:%S", time.localtime(ts))
        sender_short = sender[:20] + "…" if len(sender) > 20 else sender

        tk.Label(
            hdr, text=sender_short, fg=accent, bg=bubble_bg,
            font=FONT_SMALL, anchor="w"
        ).pack(side="left")

        tk.Label(
            hdr, text=ts_str, fg=C["fg_dim"], bg=bubble_bg,
            font=FONT_SMALL, anchor="e"
        ).pack(side="right", padx=(8, 0))

        # Message body
        tk.Label(
            bubble, text=text, fg=C["fg"], bg=bubble_bg,
            font=FONT_MONO, wraplength=480, justify="left", anchor="w"
        ).pack(fill="x", pady=(4, 0))


# ---------------------------------------------------------------------------
# Setup / settings dialog
# ---------------------------------------------------------------------------

class SetupDialog(tk.Toplevel):
    """
    Modal dialog shown on first launch (or via Settings).
    Collects: display name, group password.
    """

    def __init__(self, parent, current: dict):
        super().__init__(parent)
        self.title("⚙  Node Setup")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.grab_set()

        self.result: Optional[dict] = None

        # ── Title ──────────────────────────────────────────────────────
        tk.Label(
            self, text="NODE SETUP", fg=C["accent"], bg=C["bg"],
            font=FONT_HEAD
        ).pack(pady=(20, 4))
        tk.Label(
            self, text="Configure your identity and group credentials.",
            fg=C["muted"], bg=C["bg"], font=FONT_SMALL
        ).pack(pady=(0, 16))

        frame = tk.Frame(self, bg=C["bg"], padx=30)
        frame.pack(fill="x")

        def _field(label: str, default: str, show: str = "") -> tk.Entry:
            tk.Label(frame, text=label, fg=C["fg_dim"], bg=C["bg"],
                     font=FONT_SMALL, anchor="w").pack(fill="x", pady=(8, 2))
            e = tk.Entry(frame, font=FONT_MONO, bg=C["input_bg"],
                         fg=C["fg"], insertbackground=C["accent"],
                         relief="flat", bd=6, show=show)
            e.insert(0, default)
            e.pack(fill="x", ipady=6)
            return e

        self._name_entry = _field("DISPLAY NAME", current.get("name", "Anonymous"))
        self._pass_entry = _field(
            "GROUP PASSWORD (shared secret)", current.get("password", ""), show="●"
        )

        # ── Buttons ────────────────────────────────────────────────────
        btn_row = tk.Frame(self, bg=C["bg"], padx=30)
        btn_row.pack(fill="x", pady=20)

        tk.Button(
            btn_row, text="CANCEL", command=self.destroy,
            bg=C["panel"], fg=C["muted"], font=FONT_LABEL,
            relief="flat", bd=0, padx=16, pady=8,
            activebackground=C["border"], activeforeground=C["fg"]
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            btn_row, text="CONNECT", command=self._confirm,
            bg=C["accent"], fg=C["bg"], font=("Courier New", 10, "bold"),
            relief="flat", bd=0, padx=16, pady=8,
            activebackground="#00b880", activeforeground=C["bg"]
        ).pack(side="right")

        self.wait_window()

    def _confirm(self):
        name = self._name_entry.get().strip()
        password = self._pass_entry.get().strip()
        if not name:
            mb.showerror("Error", "Display name cannot be empty.", parent=self)
            return
        if not password:
            mb.showerror("Error", "Group password cannot be empty.", parent=self)
            return
        self.result = {"name": name, "password": password}
        self.destroy()


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class ChatApp(tk.Tk):
    """
    Root window for the encrypted P2P chat.

    Architecture notes
    ------------------
    * The asyncio event loop runs in a dedicated daemon thread.
    * The GUI communicates with the async layer through two thread-safe
      queues: ``_in_queue`` (messages arriving from the network) and
      ``_out_queue`` (outgoing messages). A Tk ``after`` polling loop
      drains ``_in_queue`` and updates widgets on the main thread.
    * The actual ``node.P2PGroupNode`` and ``network.P2PNetwork``
      are imported lazily so the GUI starts immediately even if
      cryptography/libp2p are unavailable.
    """

    POLL_MS = 100  # how often to drain the incoming queue

    def __init__(self):
        super().__init__()

        # State
        self._config     = None   # ConfigManager
        self._node       = None   # P2PGroupNode
        self._network    = None   # P2PNetwork
        self._db         = None   # sqlite3 connection
        self._name       = "Anonymous"
        self._password   = ""
        self._in_queue: queue.Queue  = queue.Queue()
        self._out_queue: queue.Queue = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._message_widgets: list = []

        # Window chrome
        self.title("ThaOTP – Encrypted P2P Messenger")
        self.configure(bg=C["bg"])
        self.geometry("860x640")
        self.minsize(600, 400)

        self._build_ui()
        self._start_config()
        self.after(self.POLL_MS, self._poll_incoming)

    # ── UI construction ────────────────────────────────────────────────

    def _build_ui(self):
        """Assemble all widgets."""
        self._build_header()
        paned = tk.PanedWindow(self, orient="horizontal",
                               bg=C["border"], sashwidth=3,
                               sashrelief="flat")
        paned.pack(fill="both", expand=True)

        self._build_sidebar(paned)
        self._build_chat_panel(paned)

    def _build_header(self):
        hdr = tk.Frame(self, bg=C["panel"], height=46)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)

        tk.Label(
            hdr, text="◈ ThaOTP", fg=C["accent"], bg=C["panel"],
            font=FONT_HEAD
        ).pack(side="left", padx=14, pady=8)

        # Status indicator
        self._status_dot = tk.Label(hdr, text="●", fg=C["warn"],
                                    bg=C["panel"], font=FONT_LABEL)
        self._status_dot.pack(side="left")

        self._status_label = tk.Label(hdr, text="offline", fg=C["muted"],
                                      bg=C["panel"], font=FONT_SMALL)
        self._status_label.pack(side="left", padx=4)

        # Menu buttons (right side)
        for (txt, cmd) in [
            ("⚙ Settings", self._open_settings),
            ("✕ Quit",     self.quit),
        ]:
            tk.Button(
                hdr, text=txt, command=cmd,
                bg=C["panel"], fg=C["muted"], font=FONT_SMALL,
                relief="flat", bd=0, padx=10, pady=10,
                activebackground=C["border"],
                activeforeground=C["fg"],
            ).pack(side="right")

    def _build_sidebar(self, paned):
        sb = tk.Frame(paned, bg=C["panel"], width=200)
        sb.pack_propagate(False)
        paned.add(sb, minsize=160)

        def section(title: str) -> tk.Frame:
            tk.Label(sb, text=title, fg=C["accent"], bg=C["panel"],
                     font=FONT_SMALL, anchor="w",
                     padx=12, pady=6).pack(fill="x")
            tk.Frame(sb, bg=C["border"], height=1).pack(fill="x")
            f = tk.Frame(sb, bg=C["panel"])
            f.pack(fill="x")
            return f

        # Identity section
        id_frame = section("IDENTITY")
        self._name_label = tk.Label(
            id_frame, text="—", fg=C["fg"], bg=C["panel"],
            font=FONT_MONO_S, wraplength=170, justify="left",
            padx=12, pady=4, anchor="w"
        )
        self._name_label.pack(fill="x")

        self._pubkey_label = tk.Label(
            id_frame, text="pubkey: —", fg=C["fg_dim"], bg=C["panel"],
            font=FONT_SMALL, wraplength=170, justify="left",
            padx=12, pady=2, anchor="w"
        )
        self._pubkey_label.pack(fill="x")

        # Group section
        grp_frame = section("GROUP")
        self._group_label = tk.Label(
            grp_frame, text="not connected", fg=C["muted"], bg=C["panel"],
            font=FONT_SMALL, padx=12, pady=4, anchor="w"
        )
        self._group_label.pack(fill="x")

        self._topic_label = tk.Label(
            grp_frame, text="topic: —", fg=C["fg_dim"], bg=C["panel"],
            font=FONT_SMALL, wraplength=170, justify="left",
            padx=12, pady=2, anchor="w"
        )
        self._topic_label.pack(fill="x")

        # Peers section
        peer_frame = section("PEERS")
        self._peer_list = tk.Text(
            peer_frame, bg=C["panel"], fg=C["muted"],
            font=FONT_SMALL, height=8, relief="flat",
            state="disabled", padx=10, pady=4,
            cursor="arrow"
        )
        self._peer_list.pack(fill="x")

        # Encryption info
        section("ENCRYPTION")
        tk.Label(
            sb, text="AES-256-GCM\nEd25519 signatures\nSHA-256 integrity",
            fg=C["muted"], bg=C["panel"], font=FONT_SMALL,
            justify="left", padx=12, pady=6
        ).pack(fill="x")

    def _build_chat_panel(self, paned):
        panel = tk.Frame(paned, bg=C["bg"])
        paned.add(panel, minsize=400)

        # ── Scrollable message area ────────────────────────────────────
        self._msg_area = _Scrollable(panel)
        self._msg_area.pack(fill="both", expand=True)

        # Placeholder shown until first message arrives
        self._placeholder = tk.Label(
            self._msg_area.inner,
            text="No messages yet.\nSend the first one.",
            fg=C["muted"], bg=C["bg"], font=FONT_MONO
        )
        self._placeholder.pack(pady=40)

        # ── Input bar ─────────────────────────────────────────────────
        bar = tk.Frame(panel, bg=C["panel"], pady=8)
        bar.pack(fill="x", side="bottom")

        # Attach button
        tk.Button(
            bar, text="📎", command=self._attach_file,
            bg=C["panel"], fg=C["muted"], font=FONT_HEAD,
            relief="flat", bd=0, padx=10,
            activebackground=C["border"],
            activeforeground=C["accent"]
        ).pack(side="left", padx=(8, 0))

        # Text entry
        self._input = tk.Text(
            bar, font=FONT_MONO, bg=C["input_bg"], fg=C["fg"],
            insertbackground=C["accent"], relief="flat", bd=6,
            height=3, wrap="word"
        )
        self._input.pack(side="left", fill="x", expand=True, padx=8)
        self._input.bind("<Return>",       self._on_enter)
        self._input.bind("<Shift-Return>", lambda e: None)  # allow newline

        # Send button
        tk.Button(
            bar, text="SEND\n▶", command=self._send_message,
            bg=C["accent"], fg=C["bg"],
            font=("Courier New", 9, "bold"),
            relief="flat", bd=0, padx=14, pady=4,
            activebackground="#00b880", activeforeground=C["bg"]
        ).pack(side="right", padx=(0, 8))

        # Attachment path label
        self._attach_label = tk.Label(
            panel, text="", fg=C["muted"], bg=C["panel"],
            font=FONT_SMALL, anchor="w"
        )
        self._attach_label.pack(fill="x", side="bottom", padx=10)

        self._attachment_path: Optional[str] = None

    # ── Initialisation / settings ──────────────────────────────────────

    def _start_config(self):
        """Load config and show setup dialog if credentials are missing."""
        try:
            from config_manager import ConfigManager
            self._config = ConfigManager("ThaOTP", "config.json")
            name     = self._config.get("name", "")
            password = self._config.get("password", "")
        except Exception:
            name, password = "", ""

        if not name or not password:
            self._open_settings(first_run=True)
        else:
            self._name     = name
            self._password = password
            self._connect()

    def _open_settings(self, first_run: bool = False):
        dlg = SetupDialog(self, {
            "name":     self._name,
            "password": self._password,
        })
        if dlg.result:
            self._name     = dlg.result["name"]
            self._password = dlg.result["password"]
            if self._config:
                self._config.set("name",     self._name)
                self._config.set("password", self._password)
                self._config.save()
            self._connect()
        elif first_run:
            self.quit()

    def _connect(self):
        """Initialise node, storage, and network; update UI labels."""
        try:
            from storage import init_db
            from node import P2PGroupNode
            from network import P2PNetwork
            from crypto import topic_id_from_password

            self._db   = init_db("p2p_storage.db")
            self._node = P2PGroupNode(self._password)

            topic = topic_id_from_password(self._password)
            self._network = P2PNetwork(
                self._password,
                on_message=self._on_network_message,
            )

            # Update sidebar
            self._name_label.configure(text=self._name)
            pk = self._node.public_key_hex
            self._pubkey_label.configure(text=f"pubkey: {pk[:8]}…{pk[-6:]}")
            self._group_label.configure(text="connected", fg=C["accent"])
            self._topic_label.configure(text=f"topic: {topic}")

            # Start network in background thread
            self._loop = asyncio.new_event_loop()
            t = threading.Thread(
                target=self._run_async_loop, daemon=True, name="p2p-network"
            )
            t.start()

            self._set_status(online=True, peer_id=self._node.public_key_hex[:10])
            self._load_stored_messages()

        except ImportError as e:
            self._set_status(online=False)
            self._add_system_message(
                f"⚠  Dependency missing: {e}\n"
                "Running in local-only mode."
            )
        except Exception as e:
            self._set_status(online=False)
            self._add_system_message(f"⚠  Startup error: {e}")

    def _run_async_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._network.start())

    # ── Status bar ────────────────────────────────────────────────────

    def _set_status(self, online: bool, peer_id: str = ""):
        if online:
            self._status_dot.configure(fg=C["accent"])
            self._status_label.configure(
                text=f"online  id:{peer_id}…", fg=C["fg_dim"]
            )
        else:
            self._status_dot.configure(fg=C["warn"])
            self._status_label.configure(text="offline", fg=C["muted"])

    # ── Message handling ───────────────────────────────────────────────

    def _load_stored_messages(self):
        """Re-render all persisted messages after startup."""
        if self._db is None or self._node is None:
            return
        try:
            from storage import get_all_messages
            for row in get_all_messages(self._db):
                # Re-decrypt for display
                inner = self._node.crypto.decrypt(row)
                if inner:
                    sender = row.get("creator_pubkey", "?")[:12] + "…"
                    is_own = (row.get("creator_pubkey", "") ==
                               self._node.public_key_hex)
                    self._render_message(
                        text=inner.get("text", ""),
                        sender=self._name if is_own else sender,
                        ts=inner.get("timestamp", 0),
                        is_own=is_own,
                    )
        except Exception as e:
            self._add_system_message(f"Could not load history: {e}")

    async def _on_network_message(self, packet: dict):
        """Called from the async thread; route to main thread via queue."""
        self._in_queue.put(packet)

    def _poll_incoming(self):
        """Drain the incoming queue on the Tk main thread."""
        while not self._in_queue.empty():
            packet = self._in_queue.get_nowait()
            self._handle_incoming(packet)
        self.after(self.POLL_MS, self._poll_incoming)

    def _handle_incoming(self, packet: dict):
        if self._node is None or self._db is None:
            return
        inner = self._node.receive_message(self._db, packet)
        if inner is None:
            return  # invalid / rejected
        sender = packet.get("creator_pubkey", "?")[:12] + "…"
        self._render_message(
            text=inner.get("text", ""),
            sender=sender,
            ts=inner.get("timestamp", int(time.time())),
            is_own=False,
        )

    def _send_message(self):
        text = self._input.get("1.0", "end-1c").strip()
        if not text:
            return
        if self._node is None:
            self._add_system_message("⚠  Not connected. Configure in Settings.")
            return

        # Build packet
        packet = self._node.prepare_message(text, self._attachment_path)

        # Render locally immediately
        self._render_message(
            text=text,
            sender=self._name,
            ts=packet.get("timestamp", int(time.time())),
            is_own=True,
        )

        # Persist locally (merge into own DB)
        if self._db is not None:
            try:
                from storage import merge_message
                merge_message(self._db, packet)
            except Exception:
                pass

        # Publish over network (async)
        if self._loop and self._network:
            asyncio.run_coroutine_threadsafe(
                self._network.publish(packet), self._loop
            )

        self._input.delete("1.0", "end")
        self._attachment_path = None
        self._attach_label.configure(text="")

    def _on_enter(self, event):
        """Send on plain Enter; Shift+Enter inserts newline."""
        if not (event.state & 0x1):  # Shift not held
            self._send_message()
            return "break"

    def _attach_file(self):
        path = fd.askopenfilename(title="Attach file")
        if path:
            self._attachment_path = path
            fname = path.split("/")[-1].split("\\")[-1]
            self._attach_label.configure(
                text=f"📎 {fname}", fg=C["accent2"]
            )

    # ── Rendering ─────────────────────────────────────────────────────

    def _render_message(self, text: str, sender: str, ts: int, is_own: bool):
        if self._placeholder.winfo_exists():
            try:
                self._placeholder.destroy()
            except Exception:
                pass

        bubble = MessageBubble(
            self._msg_area.inner,
            text=text, sender=sender, ts=ts, is_own=is_own,
        )
        bubble.pack(fill="x")
        self._message_widgets.append(bubble)
        self._msg_area.scroll_to_bottom()

    def _add_system_message(self, text: str):
        lbl = tk.Label(
            self._msg_area.inner,
            text=f"── {text} ──",
            fg=C["muted"], bg=C["bg"], font=FONT_SMALL,
            wraplength=580, justify="center", pady=6,
        )
        lbl.pack(fill="x")
        self._msg_area.scroll_to_bottom()


# ---------------------------------------------------------------------------
# Entry point (also called from main.py)
# ---------------------------------------------------------------------------

def run():
    app = ChatApp()
    app.mainloop()


if __name__ == "__main__":
    run()
