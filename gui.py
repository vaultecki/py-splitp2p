# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
GUI – Dezentrales Splitwise

Beim Start: Gruppenpasswort eingeben.
Alle Ausgaben werden mit diesem Passwort AES-verschlüsselt gespeichert.
Verschiedene Gruppen (verschiedene Passwörter) sehen nichts voneinander.
"""

import os
import subprocess
import sys
import time
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as mb
from tkinter import ttk
from typing import Optional

# ---------------------------------------------------------------------------
# Design-System
# ---------------------------------------------------------------------------

BG       = "#111318"
PANEL    = "#191c24"
BORDER   = "#252a36"
FG       = "#dde2ee"
FG_DIM   = "#5a6080"
FG_MUTED = "#8890a8"
GREEN    = "#2ecc8f"
RED      = "#e05c6a"
BLUE     = "#4d9de0"
AMBER    = "#e0a03a"

FONT       = ("Segoe UI", 10)
FONT_BOLD  = ("Segoe UI", 10, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_LARGE = ("Segoe UI", 13, "bold")
FONT_MONO  = ("Courier New", 9)


def _btn(parent, text, cmd, bg=GREEN, fg=BG, font=FONT_BOLD, **kw):
    return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                     font=font, relief="flat", bd=0, padx=14, pady=7,
                     activebackground=bg, activeforeground=fg,
                     cursor="hand2", **kw)


def _ghost(parent, text, cmd):
    return tk.Button(parent, text=text, command=cmd,
                     bg=PANEL, fg=FG_MUTED, font=FONT,
                     relief="flat", bd=0, padx=10, pady=6,
                     activebackground=BORDER, activeforeground=FG,
                     cursor="hand2")


def _lbl(parent, text, fg=FG, font=FONT, **kw):
    return tk.Label(parent, text=text, fg=fg,
                    bg=kw.pop("bg", BG), font=font, **kw)


def _div(parent):
    return tk.Frame(parent, bg=BORDER, height=1)


# ---------------------------------------------------------------------------
# Gruppen-Login-Dialog
# ---------------------------------------------------------------------------

class GroupLoginDialog(tk.Toplevel):
    """
    Wird beim Start gezeigt. Erwartet Gruppenname + Passwort.
    Das Passwort wird NICHT gespeichert — nur im RAM gehalten.
    """

    def __init__(self, parent, saved_group: str = ""):
        super().__init__(parent)
        self.title("Gruppe wählen")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.result: Optional[dict] = None
        self._build(saved_group)
        self.wait_window()

    def _build(self, saved_group):
        pad = dict(padx=28)

        _lbl(self, "GRUPPE BEITRETEN", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(24, 4), **pad)
        _lbl(self, "Alle Mitglieder der Gruppe teilen dasselbe Passwort.",
             fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", **pad)
        _div(self).pack(fill="x", padx=28, pady=10)

        frm = tk.Frame(self, bg=BG, padx=28)
        frm.pack(fill="x")

        _lbl(frm, "GRUPPENNAME (lokal, nur zur Anzeige)", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._name = tk.StringVar(value=saved_group)
        tk.Entry(frm, textvariable=self._name, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=GREEN, relief="flat", bd=6).pack(fill="x", pady=4)

        _lbl(frm, "GRUPPENPASSWORT", fg=FG_DIM, font=FONT_SMALL).pack(
            anchor="w", pady=(10, 0))
        self._pw = tk.Entry(frm, show="●", font=FONT, bg=PANEL, fg=FG,
                            insertbackground=GREEN, relief="flat", bd=6)
        self._pw.pack(fill="x", pady=4)
        self._pw.bind("<Return>", lambda _: self._confirm())

        _lbl(frm,
             "⚠  Das Passwort wird nicht gespeichert.\n"
             "Alle Mitglieder müssen dasselbe Passwort eingeben.",
             fg=FG_DIM, font=FONT_SMALL, justify="left").pack(
            anchor="w", pady=(8, 0))

        btn_row = tk.Frame(self, bg=BG, padx=28, pady=20)
        btn_row.pack(fill="x")
        _btn(btn_row, "BEITRETEN", self._confirm, width=18).pack(side="right")

    def _confirm(self):
        name = self._name.get().strip()
        pw   = self._pw.get().strip()
        if not name:
            mb.showerror("Fehler", "Gruppenname fehlt.", parent=self)
            return
        if not pw:
            mb.showerror("Fehler", "Passwort fehlt.", parent=self)
            return
        self.result = {"group_name": name, "password": pw}
        self.destroy()


# ---------------------------------------------------------------------------
# Anhang-Vorschau-Dialog
# ---------------------------------------------------------------------------

class AttachmentViewer(tk.Toplevel):
    """Zeigt ein Bild oder öffnet PDF im System-Viewer."""

    def __init__(self, parent, sha256: str, filename: str):
        from storage import attachment_path
        path = attachment_path(sha256)
        if not path:
            mb.showerror("Nicht gefunden",
                         "Die Datei ist lokal nicht vorhanden.\n"
                         "(Noch nicht synchronisiert?)", parent=parent)
            return

        # PDF: im System öffnen
        if filename.lower().endswith(".pdf"):
            self._open_external(path)
            return

        # Bild: in Tkinter anzeigen
        super().__init__(parent)
        self.title(filename)
        self.configure(bg=BG)
        self.grab_set()
        self._build(path, filename)

    def _open_external(self, path):
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])

    def _build(self, path, filename):
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail((800, 600))
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(self, image=photo, bg=BG)
            lbl.image = photo  # ref halten
            lbl.pack(padx=10, pady=10)
            _lbl(self, filename, fg=FG_DIM, font=FONT_SMALL).pack(pady=(0, 10))
        except ImportError:
            # Pillow nicht installiert: extern öffnen
            self._open_external(path)
            try:
                self.destroy()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Ausgabe-Dialog
# ---------------------------------------------------------------------------

class ExpenseDialog(tk.Toplevel):
    def __init__(self, parent, members, own_pubkey: str, expense=None):
        super().__init__(parent)
        self.title("Ausgabe bearbeiten" if expense else "Ausgabe hinzufügen")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.members    = members
        self.own_pubkey = own_pubkey
        self.result     = None
        self._attachment_path: Optional[str] = None
        self._attachment_data: Optional[bytes] = None
        self._build(expense)
        self.wait_window()

    def _build(self, expense):
        pad = dict(padx=24)
        _lbl(self, "AUSGABE BEARBEITEN" if expense else "NEUE AUSGABE",
             fg=GREEN, font=FONT_LARGE).pack(anchor="w", pady=(20, 2), **pad)
        _div(self).pack(fill="x", **pad)

        frm = tk.Frame(self, bg=BG, padx=24, pady=12)
        frm.pack(fill="x")

        # Beschreibung
        _lbl(frm, "BESCHREIBUNG", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._desc = tk.StringVar(value=expense.description if expense else "")
        tk.Entry(frm, textvariable=self._desc, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=GREEN, relief="flat", bd=6).pack(fill="x", pady=(2, 8))

        # Betrag
        _lbl(frm, "BETRAG", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        amt_row = tk.Frame(frm, bg=BG)
        amt_row.pack(fill="x", pady=(2, 8))
        self._amount = tk.StringVar(value=str(expense.amount) if expense else "")
        tk.Entry(amt_row, textvariable=self._amount, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=GREEN, relief="flat", bd=6, width=14).pack(side="left")
        _lbl(amt_row, "EUR", fg=FG_DIM, font=FONT_SMALL, bg=BG, padx=6).pack(side="left")

        # Bezahlt von
        _lbl(frm, "BEZAHLT VON", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._payer_var = tk.StringVar()
        payer_names = [m.display_name for m in self.members]
        default = next(
            (m.display_name for m in self.members if m.pubkey == self.own_pubkey),
            (payer_names[0] if payer_names else "")
        )
        if expense:
            default = next(
                (m.display_name for m in self.members if m.pubkey == expense.payer_pubkey),
                default,
            )
        self._payer_var.set(default)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL,
                        foreground=FG, selectbackground=BORDER, arrowcolor=FG_DIM)
        ttk.Combobox(frm, textvariable=self._payer_var, values=payer_names,
                     state="readonly", font=FONT).pack(fill="x", pady=(2, 8))

        # Aufteilung
        _lbl(frm, "AUFTEILUNG", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._split_mode = tk.StringVar(value="equal")
        mode_row = tk.Frame(frm, bg=BG)
        mode_row.pack(anchor="w")
        for val, txt in [("equal", "Gleich"), ("custom", "Individuell")]:
            tk.Radiobutton(mode_row, text=txt, variable=self._split_mode, value=val,
                           bg=BG, fg=FG_MUTED, selectcolor=BG,
                           activebackground=BG, activeforeground=FG,
                           font=FONT_SMALL, command=self._update_splits).pack(
                side="left", padx=(0, 12))

        self._split_frame = tk.Frame(frm, bg=BG)
        self._split_frame.pack(fill="x", pady=4)
        self._member_vars: dict[str, tk.BooleanVar] = {}
        self._amount_vars: dict[str, tk.StringVar]  = {}
        self._split_widgets: list = []
        for m in self.members:
            self._member_vars[m.pubkey] = tk.BooleanVar(value=True)
            self._amount_vars[m.pubkey] = tk.StringVar(value="")
        self._update_splits()

        # ── Dateianhang ───────────────────────────────────────────────
        _div(frm).pack(fill="x", pady=8)
        _lbl(frm, "DATEIANHANG", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        att_row = tk.Frame(frm, bg=BG)
        att_row.pack(fill="x", pady=(2, 4))

        self._att_label = _lbl(att_row,
            f"📎 {expense.attachment.filename} ({expense.attachment.size_str()})"
            if (expense and expense.attachment) else "Kein Anhang",
            fg=FG_DIM if not (expense and expense.attachment) else BLUE,
            font=FONT_SMALL, bg=BG)
        self._att_label.pack(side="left")

        _ghost(att_row, "Datei wählen", self._pick_file).pack(side="left", padx=8)

        if expense and expense.attachment:
            _ghost(att_row, "Entfernen", self._remove_attachment).pack(side="left")
            self._existing_attachment = expense.attachment
        else:
            self._existing_attachment = None

        # Buttons
        btn_row = tk.Frame(self, bg=BG, padx=24, pady=16)
        btn_row.pack(fill="x")
        _ghost(btn_row, "Abbrechen", self.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Speichern", self._save).pack(side="right")

    def _update_splits(self):
        for w in self._split_widgets:
            w.destroy()
        self._split_widgets.clear()
        mode = self._split_mode.get()
        for m in self.members:
            row = tk.Frame(self._split_frame, bg=BG)
            row.pack(fill="x", pady=1)
            self._split_widgets.append(row)
            tk.Checkbutton(row, text=m.display_name,
                           variable=self._member_vars[m.pubkey],
                           bg=BG, fg=FG, selectcolor=BG,
                           activebackground=BG, activeforeground=FG,
                           font=FONT, width=18, anchor="w").pack(side="left")
            if mode == "custom":
                tk.Entry(row, textvariable=self._amount_vars[m.pubkey],
                         font=FONT, bg=PANEL, fg=FG,
                         insertbackground=GREEN, relief="flat", bd=4, width=10).pack(side="left", padx=6)
                _lbl(row, "EUR", fg=FG_DIM, font=FONT_SMALL, bg=BG).pack(side="left")

    def _pick_file(self):
        path = fd.askopenfilename(
            title="Anhang wählen",
            filetypes=[
                ("Bilder & PDFs", "*.jpg *.jpeg *.png *.gif *.webp *.pdf"),
                ("Alle Dateien", "*.*"),
            ],
            parent=self,
        )
        if not path:
            return
        with open(path, "rb") as f:
            self._attachment_data = f.read()
        self._attachment_path = path
        fname = os.path.basename(path)
        size  = len(self._attachment_data)
        size_str = f"{size/1024:.1f} KB" if size >= 1024 else f"{size} B"
        self._att_label.configure(text=f"📎 {fname} ({size_str})", fg=BLUE)
        self._existing_attachment = None

    def _remove_attachment(self):
        self._attachment_path = None
        self._attachment_data = None
        self._existing_attachment = None
        self._att_label.configure(text="Kein Anhang", fg=FG_DIM)

    def _save(self):
        from models import Expense, Attachment, split_equally, split_custom
        from crypto import hash_bytes, mime_type_from_path
        from storage import save_attachment

        desc = self._desc.get().strip()
        if not desc:
            mb.showerror("Fehler", "Beschreibung fehlt.", parent=self)
            return
        try:
            amount = float(self._amount.get().replace(",", "."))
            if amount <= 0:
                raise ValueError
        except ValueError:
            mb.showerror("Fehler", "Ungültiger Betrag.", parent=self)
            return

        payer = next((m for m in self.members if m.display_name == self._payer_var.get()), None)
        if not payer:
            mb.showerror("Fehler", "Zahler nicht gefunden.", parent=self)
            return

        selected = [m for m in self.members if self._member_vars[m.pubkey].get()]
        if not selected:
            mb.showerror("Fehler", "Mindestens ein Mitglied auswählen.", parent=self)
            return

        mode = self._split_mode.get()
        if mode == "equal":
            splits = split_equally(amount, [m.pubkey for m in selected])
        else:
            try:
                custom = {
                    m.pubkey: float(self._amount_vars[m.pubkey].get().replace(",", "."))
                    for m in selected
                }
            except ValueError:
                mb.showerror("Fehler", "Individuelle Beträge ungültig.", parent=self)
                return
            splits = split_custom(custom)

        # Anhang verarbeiten
        attachment = None
        if self._attachment_data and self._attachment_path:
            sha = hash_bytes(self._attachment_data)
            save_attachment(self._attachment_data, sha)
            attachment = Attachment(
                sha256=sha,
                filename=os.path.basename(self._attachment_path),
                size=len(self._attachment_data),
                mime_type=mime_type_from_path(self._attachment_path),
            )
        elif self._existing_attachment:
            attachment = self._existing_attachment

        self.result = {
            "description": desc,
            "amount": amount,
            "currency": "EUR",
            "payer_pubkey": payer.pubkey,
            "splits": splits,
            "attachment": attachment,
        }
        self.destroy()


# ---------------------------------------------------------------------------
# Mitglied hinzufügen
# ---------------------------------------------------------------------------

class AddMemberDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Mitglied hinzufügen")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        self._build()
        self.wait_window()

    def _build(self):
        pad = dict(padx=24)
        _lbl(self, "MITGLIED", fg=GREEN, font=FONT_LARGE).pack(anchor="w", pady=(20, 2), **pad)
        _div(self).pack(fill="x", **pad)
        frm = tk.Frame(self, bg=BG, padx=24, pady=12)
        frm.pack(fill="x")

        _lbl(frm, "NAME", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._name = tk.Entry(frm, font=FONT, bg=PANEL, fg=FG,
                              insertbackground=GREEN, relief="flat", bd=6)
        self._name.pack(fill="x", pady=4)

        _lbl(frm, "PUBLIC KEY (leer = neuer temporärer Key)", fg=FG_DIM, font=FONT_SMALL).pack(
            anchor="w", pady=(8, 0))
        self._pk = tk.Entry(frm, font=FONT_MONO, bg=PANEL, fg=FG_MUTED,
                            insertbackground=GREEN, relief="flat", bd=6)
        self._pk.pack(fill="x", pady=4)

        btn_row = tk.Frame(self, bg=BG, padx=24, pady=16)
        btn_row.pack(fill="x")
        _ghost(btn_row, "Abbrechen", self.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Hinzufügen", self._save).pack(side="right")

    def _save(self):
        name = self._name.get().strip()
        if not name:
            mb.showerror("Fehler", "Name fehlt.", parent=self)
            return
        pk = self._pk.get().strip() or None
        self.result = {"name": name, "pubkey": pk}
        self.destroy()


# ---------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()  # erst nach Login zeigen
        self.title("SplitP2P")
        self.configure(bg=BG)
        self.geometry("980x700")
        self.minsize(720, 500)

        self._db           = None
        self._own_key      = None
        self._own_pubkey   = ""
        self._own_name     = ""
        self._group_name   = ""
        self._group_pw     = ""   # nur im RAM

        self._build_ui()
        self._init_identity()

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        paned = tk.PanedWindow(self, orient="horizontal",
                               bg=BORDER, sashwidth=1, sashrelief="flat")
        paned.pack(fill="both", expand=True)
        self._build_sidebar(paned)
        self._build_main(paned)

    def _build_header(self):
        hdr = tk.Frame(self, bg=PANEL, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        _lbl(hdr, "SplitP2P", fg=GREEN, font=("Segoe UI", 14, "bold"), bg=PANEL).pack(
            side="left", padx=16, pady=12)

        self._group_badge = _lbl(hdr, "", fg=AMBER, font=FONT_BOLD, bg=PANEL)
        self._group_badge.pack(side="left", padx=4)

        self._identity_label = _lbl(hdr, "", fg=FG_DIM, font=FONT_SMALL, bg=PANEL)
        self._identity_label.pack(side="left", padx=4)

        _ghost(hdr, "⚙ Einstellungen", self._open_settings).pack(side="right", padx=8)
        _ghost(hdr, "🔑 Gruppe wechseln", self._switch_group).pack(side="right", padx=4)

    def _build_sidebar(self, paned):
        sb = tk.Frame(paned, bg=PANEL, width=240)
        sb.pack_propagate(False)
        paned.add(sb, minsize=200)

        _lbl(sb, "MITGLIEDER", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14, pady=8).pack(fill="x")
        _div(sb).pack(fill="x")
        self._members_frame = tk.Frame(sb, bg=PANEL)
        self._members_frame.pack(fill="x", padx=12, pady=6)
        _btn(sb, "+ Mitglied", self._add_member, width=18).pack(padx=12, pady=4)

        _div(sb).pack(fill="x", pady=8)
        _lbl(sb, "SCHULDEN", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14).pack(fill="x")
        self._debt_frame = tk.Frame(sb, bg=PANEL)
        self._debt_frame.pack(fill="x", padx=12, pady=6)

    def _build_main(self, paned):
        main = tk.Frame(paned, bg=BG)
        paned.add(main, minsize=500)

        toolbar = tk.Frame(main, bg=PANEL)
        toolbar.pack(fill="x")
        _lbl(toolbar, "AUSGABEN", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=16, pady=10).pack(side="left")
        _btn(toolbar, "+ Ausgabe", self._add_expense).pack(side="right", padx=8, pady=6)

        _div(main).pack(fill="x")

        container = tk.Frame(main, bg=BG)
        container.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
        sb_scroll = tk.Scrollbar(container, orient="vertical", command=self._canvas.yview,
                                 bg=PANEL, troughcolor=BG)
        self._canvas.configure(yscrollcommand=sb_scroll.set)
        sb_scroll.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._expense_list = tk.Frame(self._canvas, bg=BG)
        self._win = self._canvas.create_window((0, 0), window=self._expense_list, anchor="nw")
        self._expense_list.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(
            self._win, width=e.width))
        self._canvas.bind_all("<MouseWheel>", lambda e: self._canvas.yview_scroll(
            int(-1*(e.delta/120)), "units"))

        self._statusbar = tk.Frame(main, bg=PANEL, height=36)
        self._statusbar.pack(fill="x", side="bottom")
        self._statusbar.pack_propagate(False)
        self._total_label = _lbl(self._statusbar, "", fg=FG_MUTED, font=FONT_SMALL, bg=PANEL)
        self._total_label.pack(side="right", padx=16, pady=8)

    # ── Identität & Gruppe ────────────────────────────────────────────

    def _init_identity(self):
        from config_manager import ConfigManager
        from crypto import generate_private_key, private_key_from_bytes, get_public_key_hex, private_key_to_bytes
        from storage import init_db, save_member
        from models import Member

        self._cfg = ConfigManager("SplitP2P", "config.json")
        self._db  = init_db("splitp2p.db")

        raw = self._cfg.get("private_key_hex")
        if raw:
            self._own_key = private_key_from_bytes(bytes.fromhex(raw))
        else:
            self._own_key = generate_private_key()
            self._cfg.set("private_key_hex", private_key_to_bytes(self._own_key).hex())
            self._cfg.save()

        self._own_pubkey = get_public_key_hex(self._own_key)
        self._own_name   = self._cfg.get("display_name", "")

        if not self._own_name:
            self._open_settings(first_run=True)
        else:
            self._do_group_login()

    def _do_group_login(self):
        saved_group = self._cfg.get("last_group", "")
        dlg = GroupLoginDialog(self, saved_group)
        if not dlg.result:
            self.quit()
            return
        self._group_name = dlg.result["group_name"]
        self._group_pw   = dlg.result["password"]
        self._cfg.set("last_group", self._group_name)
        self._cfg.save()

        self._group_badge.configure(text=f"[{self._group_name}]")
        self._identity_label.configure(
            text=f"{self._own_name}  ·  {self._own_pubkey[:12]}…")

        from storage import save_member, get_member
        from models import Member
        me = get_member(self._db, self._own_pubkey)
        if not me or me.display_name != self._own_name:
            save_member(self._db, Member(self._own_pubkey, self._own_name))

        self.deiconify()
        self._refresh()

    def _switch_group(self):
        self.withdraw()
        self._group_pw = ""
        self._do_group_login()

    def _open_settings(self, first_run=False):
        dlg = tk.Toplevel(self)
        dlg.title("Einstellungen")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        _lbl(dlg, "IDENTITÄT", fg=GREEN, font=FONT_LARGE).pack(anchor="w", pady=(20, 2), padx=24)
        _div(dlg).pack(fill="x", padx=24)

        frm = tk.Frame(dlg, bg=BG, padx=24, pady=12)
        frm.pack(fill="x")
        _lbl(frm, "ANZEIGENAME", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        name_var = tk.StringVar(value=self._own_name)
        tk.Entry(frm, textvariable=name_var, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=GREEN, relief="flat", bd=6).pack(fill="x", pady=4)

        if self._own_pubkey:
            _lbl(frm, "DEIN PUBLIC KEY", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", pady=(8, 0))
            _lbl(frm, self._own_pubkey, fg=FG_DIM, font=FONT_MONO,
                 wraplength=340, justify="left").pack(anchor="w", pady=2)

        def save():
            n = name_var.get().strip()
            if not n:
                mb.showerror("Fehler", "Name darf nicht leer sein.", parent=dlg)
                return
            self._own_name = n
            self._cfg.set("display_name", n)
            self._cfg.save()
            from storage import save_member
            from models import Member
            save_member(self._db, Member(self._own_pubkey, self._own_name))
            self._identity_label.configure(
                text=f"{self._own_name}  ·  {self._own_pubkey[:12]}…")
            dlg.destroy()
            if first_run:
                self._do_group_login()
            else:
                self._refresh()

        btn_row = tk.Frame(dlg, bg=BG, padx=24, pady=16)
        btn_row.pack(fill="x")
        if not first_run:
            _ghost(btn_row, "Abbrechen", dlg.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Speichern", save).pack(side="right")
        dlg.wait_window()

    # ── Mitglieder ────────────────────────────────────────────────────

    def _add_member(self):
        dlg = AddMemberDialog(self)
        if not dlg.result:
            return
        from storage import save_member
        from models import Member
        from crypto import generate_private_key, get_public_key_hex

        pk = dlg.result["pubkey"]
        if not pk:
            tmp = generate_private_key()
            pk  = get_public_key_hex(tmp)
            mb.showinfo("Key generiert",
                        f"Temporärer Public Key für '{dlg.result['name']}':\n\n{pk}",
                        parent=self)
        save_member(self._db, Member(pubkey=pk, display_name=dlg.result["name"]))
        self._refresh()

    # ── Ausgaben ──────────────────────────────────────────────────────

    def _load_expenses(self):
        from storage import load_all_expense_blobs
        from crypto import decrypt_expense
        expenses = []
        for eid, blob in load_all_expense_blobs(self._db):
            exp = decrypt_expense(blob, self._group_pw)
            if exp is None:
                # falsches Passwort oder Korruption
                continue
            expenses.append(exp)
        return expenses

    def _save_expense(self, expense):
        from crypto import sign_expense, encrypt_expense
        from storage import save_expense_blob
        expense.signature = sign_expense(expense, self._own_key)
        blob = encrypt_expense(expense, self._group_pw)
        save_expense_blob(self._db, expense.id, blob, expense.timestamp)

    def _add_expense(self):
        from storage import load_all_members
        members = load_all_members(self._db)
        if not members:
            mb.showwarning("Keine Mitglieder",
                           "Bitte erst Mitglieder zur Gruppe hinzufügen.", parent=self)
            return
        dlg = ExpenseDialog(self, members, self._own_pubkey)
        if not dlg.result:
            return
        from models import Expense
        exp = Expense.create(**dlg.result)
        self._save_expense(exp)
        self._refresh()

    def _edit_expense(self, expense):
        from storage import load_all_members
        members = load_all_members(self._db)
        dlg = ExpenseDialog(self, members, self._own_pubkey, expense)
        if not dlg.result:
            return
        import time as _time
        from models import Expense
        updated = Expense(
            id=expense.id,
            description=dlg.result["description"],
            amount=dlg.result["amount"],
            currency=dlg.result["currency"],
            payer_pubkey=dlg.result["payer_pubkey"],
            splits=dlg.result["splits"],
            timestamp=int(_time.time()),
            signature="",
            attachment=dlg.result.get("attachment"),
        )
        self._save_expense(updated)
        self._refresh()

    def _delete_expense(self, expense):
        if not mb.askyesno("Löschen", f"'{expense.description}' wirklich löschen?", parent=self):
            return
        import time as _time
        from crypto import sign_expense, encrypt_expense
        from storage import soft_delete_expense_blob
        expense.is_deleted = True
        expense.timestamp  = int(_time.time())
        expense.signature  = sign_expense(expense, self._own_key)
        blob = encrypt_expense(expense, self._group_pw)
        soft_delete_expense_blob(self._db, expense.id, blob, expense.timestamp)
        self._refresh()

    # ── Refresh / Render ──────────────────────────────────────────────

    def _refresh(self):
        from storage import load_all_members
        members  = load_all_members(self._db)
        expenses = self._load_expenses()
        self._render_members(members)
        self._render_expenses(expenses, members)
        self._render_debts(expenses, members)
        total = sum(e.amount for e in expenses)
        self._total_label.configure(
            text=f"Gesamt: {total:.2f} EUR  ·  {len(expenses)} Ausgaben")

    def _render_members(self, members):
        for w in self._members_frame.winfo_children():
            w.destroy()
        if not members:
            _lbl(self._members_frame, "Noch keine Mitglieder",
                 fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(anchor="w")
            return
        for m in members:
            row = tk.Frame(self._members_frame, bg=PANEL)
            row.pack(fill="x", pady=1)
            dot = GREEN if m.pubkey == self._own_pubkey else FG_DIM
            _lbl(row, "●", fg=dot, font=("Segoe UI", 8), bg=PANEL).pack(side="left")
            _lbl(row, m.display_name, fg=FG, font=FONT_SMALL, bg=PANEL).pack(side="left", padx=4)
            if m.pubkey == self._own_pubkey:
                _lbl(row, "(du)", fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(side="left")

    def _render_expenses(self, expenses, members):
        for w in self._expense_list.winfo_children():
            w.destroy()
        pk_to_name = {m.pubkey: m.display_name for m in members}
        if not expenses:
            _lbl(self._expense_list, "Noch keine Ausgaben.",
                 fg=FG_DIM, font=FONT).pack(pady=40)
            return
        for exp in reversed(expenses):
            self._render_row(exp, pk_to_name)

    def _render_row(self, exp, pk_to_name):
        def name(pk): return pk_to_name.get(pk, pk[:8] + "…")

        row = tk.Frame(self._expense_list, bg=PANEL, padx=16, pady=10)
        row.pack(fill="x", pady=1)

        left = tk.Frame(row, bg=PANEL)
        left.pack(side="left", fill="x", expand=True)

        _lbl(left, exp.description, fg=FG, font=FONT_BOLD, bg=PANEL).pack(anchor="w")
        ts = time.strftime("%d.%m.%Y", time.localtime(exp.timestamp))
        _lbl(left, f"{name(exp.payer_pubkey)} hat bezahlt  ·  {ts}",
             fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(anchor="w")
        splits_txt = "  ".join(f"{name(s.pubkey)}: {s.amount:.2f}€" for s in exp.splits)
        _lbl(left, splits_txt, fg=FG_MUTED, font=FONT_SMALL, bg=PANEL).pack(anchor="w")

        # Anhang
        if exp.attachment:
            att = exp.attachment
            from storage import attachment_exists
            exists = attachment_exists(att.sha256)
            att_color = BLUE if exists else FG_DIM
            att_text  = f"📎 {att.filename} ({att.size_str()})" + ("" if exists else "  ⚠ fehlt lokal")
            att_btn = tk.Button(
                left, text=att_text, fg=att_color, bg=PANEL,
                font=FONT_SMALL, relief="flat", bd=0, cursor="hand2",
                activebackground=PANEL, activeforeground=FG,
                command=lambda a=att: AttachmentViewer(self, a.sha256, a.filename),
            )
            att_btn.pack(anchor="w")

        right = tk.Frame(row, bg=PANEL)
        right.pack(side="right")
        _lbl(right, f"{exp.amount:.2f} {exp.currency}",
             fg=GREEN, font=FONT_LARGE, bg=PANEL).pack(anchor="e")

        btn_row = tk.Frame(right, bg=PANEL)
        btn_row.pack(anchor="e")
        if exp.payer_pubkey == self._own_pubkey:
            _ghost(btn_row, "✎", lambda e=exp: self._edit_expense(e)).pack(side="left", padx=2)
        _ghost(btn_row, "✕", lambda e=exp: self._delete_expense(e)).pack(side="left", padx=2)

        _div(self._expense_list).pack(fill="x")

    def _render_debts(self, expenses, members):
        from ledger import get_settlements
        for w in self._debt_frame.winfo_children():
            w.destroy()
        settlements = get_settlements(expenses)
        pk_to_name  = {m.pubkey: m.display_name for m in members}

        def name(pk): return pk_to_name.get(pk, pk[:8] + "…")

        if not settlements:
            _lbl(self._debt_frame, "Alle quitt ✓",
                 fg=GREEN, font=FONT_SMALL, bg=PANEL).pack(anchor="w")
            return
        for s in settlements:
            is_me_d = s.debtor   == self._own_pubkey
            is_me_c = s.creditor == self._own_pubkey
            color = RED if is_me_d else (GREEN if is_me_c else FG_MUTED)
            f = tk.Frame(self._debt_frame, bg=PANEL)
            f.pack(fill="x", pady=2)
            _lbl(f, f"{name(s.debtor)} → {name(s.creditor)}",
                 fg=color, font=FONT_SMALL, bg=PANEL,
                 wraplength=180, justify="left").pack(anchor="w")
            _lbl(f, f"{s.amount:.2f} EUR", fg=color, font=FONT_BOLD, bg=PANEL).pack(anchor="w")


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def run():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    run()
