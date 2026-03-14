# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
GUI – Dezentrales Splitwise mit Währungsunterstützung
"""

import os
import subprocess
import sys
import threading
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


def _div(parent, **kw):
    return tk.Frame(parent, bg=BORDER, height=1, **kw)


def _combobox(parent, var, values, **kw):
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TCombobox", fieldbackground=PANEL, background=PANEL,
                    foreground=FG, selectbackground=BORDER, arrowcolor=FG_DIM,
                    selectforeground=FG)
    return ttk.Combobox(parent, textvariable=var, values=values,
                        state="readonly", font=FONT, **kw)


# ---------------------------------------------------------------------------
# Gruppen-Login-Dialog
# ---------------------------------------------------------------------------

class NewGroupDialog(tk.Toplevel):
    """
    Wird einmalig aufgerufen wenn eine neue Gruppe angelegt oder
    einer unbekannten Gruppe beigetreten wird.
    Danach wird das Passwort in der Config gespeichert.
    """
    def __init__(self, parent, default_name=""):
        super().__init__(parent)
        self.title("Neue Gruppe")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.result: Optional[dict] = None
        self._build(default_name)
        self.wait_window()

    def _build(self, default_name):
        from currency import SUPPORTED_CURRENCIES
        pad = dict(padx=28)

        _lbl(self, "NEUE GRUPPE", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(24, 4), **pad)
        _lbl(self,
             "Das gemeinsame Passwort identifiziert die Gruppe im P2P-Netz\n"
             "und verschlüsselt alle Ausgaben. Es wird einmalig gespeichert.",
             fg=FG_DIM, font=FONT_SMALL, justify="left").pack(anchor="w", **pad)
        _div(self).pack(fill="x", padx=28, pady=10)

        frm = tk.Frame(self, bg=BG, padx=28)
        frm.pack(fill="x")

        _lbl(frm, "GRUPPENNAME", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._name = tk.StringVar(value=default_name)
        tk.Entry(frm, textvariable=self._name, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=GREEN, relief="flat", bd=6).pack(fill="x", pady=(2, 8))

        _lbl(frm, "GEMEINSAMES GRUPPENPASSWORT", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        _lbl(frm, "Alle Mitglieder müssen dasselbe Passwort eingeben.",
             fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", pady=(0, 2))
        self._pw = tk.Entry(frm, show="●", font=FONT, bg=PANEL, fg=FG,
                            insertbackground=GREEN, relief="flat", bd=6)
        self._pw.pack(fill="x", pady=(0, 8))

        _lbl(frm, "WÄHRUNG DER GRUPPE", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._currency = tk.StringVar(value="EUR")
        _combobox(frm, self._currency, SUPPORTED_CURRENCIES, width=10).pack(
            anchor="w", pady=(2, 8))

        btn_row = tk.Frame(self, bg=BG, padx=28, pady=20)
        btn_row.pack(fill="x")
        _ghost(btn_row, "Abbrechen", self.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "ERSTELLEN / BEITRETEN", self._confirm).pack(side="right")

    def _confirm(self):
        name = self._name.get().strip()
        pw   = self._pw.get().strip()
        cur  = self._currency.get().strip()
        if not name:
            mb.showerror("Fehler", "Gruppenname fehlt.", parent=self); return
        if len(pw) < 4:
            mb.showerror("Fehler", "Passwort muss mindestens 4 Zeichen haben.", parent=self); return
        self.result = {"group_name": name, "password": pw, "group_currency": cur}
        self.destroy()


class GroupSelectDialog(tk.Toplevel):
    """
    Zeigt alle bekannten Gruppen aus der Config.
    Kein Passwort nötig — wird aus dem gespeicherten Eintrag geladen.
    Neue Gruppe: öffnet NewGroupDialog.
    """
    def __init__(self, parent, groups: dict, last_group: str):
        super().__init__(parent)
        self.title("Gruppe wählen")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.groups = groups       # {name: {password, currency}}
        self.result: Optional[dict] = None
        self._build(last_group)
        self.wait_window()

    def _build(self, last_group):
        pad = dict(padx=28)

        _lbl(self, "GRUPPE WÄHLEN", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(24, 4), **pad)
        _div(self).pack(fill="x", padx=28, pady=10)

        frm = tk.Frame(self, bg=BG, padx=28)
        frm.pack(fill="x")

        if self.groups:
            _lbl(frm, "BEKANNTE GRUPPEN", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
            self._selected = tk.StringVar(value=last_group if last_group in self.groups else
                                          next(iter(self.groups)))
            list_frame = tk.Frame(frm, bg=BORDER, padx=1, pady=1)
            list_frame.pack(fill="x", pady=(2, 12))
            inner = tk.Frame(list_frame, bg=BG)
            inner.pack(fill="x")
            for name, info in self.groups.items():
                row = tk.Frame(inner, bg=BG)
                row.pack(fill="x")
                tk.Radiobutton(
                    row, text=f"  {name}", variable=self._selected, value=name,
                    bg=BG, fg=FG, selectcolor=BG,
                    activebackground=BG, activeforeground=FG,
                    font=FONT, anchor="w",
                    command=lambda: None,
                ).pack(side="left", fill="x", expand=True)
                cur = info.get("currency", "EUR")
                _lbl(row, cur, fg=FG_DIM, font=FONT_SMALL, bg=BG, padx=8).pack(side="right")

            btn_row = tk.Frame(self, bg=BG, padx=28, pady=(0))
            btn_row.pack(fill="x")
            _ghost(btn_row, "+ Neue Gruppe", self._new_group).pack(side="left")
            _ghost(btn_row, "Entfernen", self._remove_group).pack(side="left", padx=6)
            _btn(btn_row, "ÖFFNEN", self._confirm).pack(side="right")
            tk.Frame(self, bg=BG, height=16).pack()
        else:
            _lbl(frm, "Noch keine Gruppen bekannt.",
                 fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", pady=(0, 12))
            self._selected = tk.StringVar(value="")
            _btn(frm, "+ Erste Gruppe erstellen / beitreten",
                 self._new_group, width=32).pack(anchor="w", pady=8)
            tk.Frame(self, bg=BG, height=16).pack()

    def _new_group(self):
        dlg = NewGroupDialog(self)
        if not dlg.result:
            return
        self.groups[dlg.result["group_name"]] = {
            "password": dlg.result["password"],
            "currency": dlg.result["group_currency"],
        }
        self.result = dlg.result
        self.destroy()

    def _remove_group(self):
        name = self._selected.get()
        if not name:
            return
        if mb.askyesno("Entfernen", f"Gruppe '{name}' aus der Liste entfernen?\n"
                       "(Daten bleiben erhalten)", parent=self):
            self.groups.pop(name, None)
            self.result = {"_removed": name}
            self.destroy()

    def _confirm(self):
        name = self._selected.get()
        if not name or name not in self.groups:
            mb.showerror("Fehler", "Keine Gruppe ausgewählt.", parent=self); return
        info = self.groups[name]
        self.result = {
            "group_name":     name,
            "password":       info["password"],
            "group_currency": info.get("currency", "EUR"),
        }
        self.destroy()


# ---------------------------------------------------------------------------
# Anhang-Viewer
# ---------------------------------------------------------------------------

class AttachmentViewer(tk.Toplevel):
    def __init__(self, parent, sha256: str, filename: str):
        from storage import attachment_path
        path = attachment_path(sha256)
        if not path:
            mb.showerror("Nicht gefunden",
                         "Die Datei ist lokal nicht vorhanden.\n"
                         "(Noch nicht synchronisiert?)", parent=parent)
            return
        if filename.lower().endswith(".pdf"):
            self._open_external(path); return
        super().__init__(parent)
        self.title(filename)
        self.configure(bg=BG)
        self.grab_set()
        self._show_image(path, filename)

    def _open_external(self, path):
        if sys.platform == "win32": os.startfile(path)
        elif sys.platform == "darwin": subprocess.run(["open", path])
        else: subprocess.run(["xdg-open", path])

    def _show_image(self, path, filename):
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail((800, 600))
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(self, image=photo, bg=BG)
            lbl.image = photo
            lbl.pack(padx=10, pady=10)
            _lbl(self, filename, fg=FG_DIM, font=FONT_SMALL).pack(pady=(0, 10))
        except ImportError:
            self._open_external(path)
            try: self.destroy()
            except Exception: pass


# ---------------------------------------------------------------------------
# Ausgabe-Dialog
# ---------------------------------------------------------------------------

class ExpenseDialog(tk.Toplevel):
    def __init__(self, parent, members, own_pubkey: str,
                 group_currency: str, rates: dict,
                 expense=None):
        super().__init__(parent)
        self.title("Ausgabe bearbeiten" if expense else "Neue Ausgabe")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.members         = members
        self.own_pubkey      = own_pubkey
        self.group_currency  = group_currency
        self.rates           = rates          # {target: rate} Basis = group_currency
        self.result          = None
        self._att_path: Optional[str]   = None
        self._att_data: Optional[bytes] = None
        self._existing_att   = getattr(expense, "attachment", None)
        self._build(expense)
        self.wait_window()

    def _build(self, expense):
        from currency import SUPPORTED_CURRENCIES, convert, format_rate

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

        # Betrag + Währung
        _lbl(frm, "BETRAG", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        amt_row = tk.Frame(frm, bg=BG)
        amt_row.pack(fill="x", pady=(2, 2))

        default_amt = ""
        default_cur = self.group_currency
        if expense:
            if expense.original_amount and expense.original_currency:
                default_amt = str(expense.original_amount)
                default_cur = expense.original_currency
            else:
                default_amt = str(expense.amount)

        self._amount = tk.StringVar(value=default_amt)
        self._input_currency = tk.StringVar(value=default_cur)

        amt_entry = tk.Entry(amt_row, textvariable=self._amount, font=FONT,
                             bg=PANEL, fg=FG, insertbackground=GREEN,
                             relief="flat", bd=6, width=14)
        amt_entry.pack(side="left")

        _combobox(amt_row, self._input_currency, SUPPORTED_CURRENCIES, width=8).pack(
            side="left", padx=6)

        # Umrechnungs-Vorschau
        self._conv_label = _lbl(frm, "", fg=AMBER, font=FONT_SMALL, bg=BG)
        self._conv_label.pack(anchor="w", pady=(2, 6))

        def _update_preview(*_):
            try:
                amt = float(self._amount.get().replace(",", "."))
            except ValueError:
                self._conv_label.configure(text="")
                return
            ic = self._input_currency.get()
            if ic == self.group_currency:
                self._conv_label.configure(text="")
                return
            converted = convert(amt, ic, self.group_currency, self.rates)
            if converted is not None:
                rate_str = format_rate(ic, self.group_currency, self.rates)
                self._conv_label.configure(
                    text=f"= {converted:.2f} {self.group_currency}  ({rate_str})")
            else:
                self._conv_label.configure(
                    text=f"⚠ Kurs {ic}→{self.group_currency} nicht verfügbar",
                    fg=RED)

        self._amount.trace_add("write", _update_preview)
        self._input_currency.trace_add("write", _update_preview)
        _update_preview()

        # Bezahlt von
        _lbl(frm, "BEZAHLT VON", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._payer_var = tk.StringVar()
        payer_names = [m.display_name for m in self.members]
        default_payer = next(
            (m.display_name for m in self.members if m.pubkey == self.own_pubkey),
            payer_names[0] if payer_names else "",
        )
        if expense:
            default_payer = next(
                (m.display_name for m in self.members if m.pubkey == expense.payer_pubkey),
                default_payer,
            )
        self._payer_var.set(default_payer)
        _combobox(frm, self._payer_var, payer_names).pack(fill="x", pady=(2, 8))

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

        # Anhang
        _div(frm).pack(fill="x", pady=8)
        _lbl(frm, "DATEIANHANG", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        att_row = tk.Frame(frm, bg=BG)
        att_row.pack(fill="x", pady=(2, 4))
        self._att_label = _lbl(att_row,
            f"📎 {self._existing_att.filename} ({self._existing_att.size_str()})"
            if self._existing_att else "Kein Anhang",
            fg=BLUE if self._existing_att else FG_DIM, font=FONT_SMALL, bg=BG)
        self._att_label.pack(side="left")
        _ghost(att_row, "Datei wählen", self._pick_file).pack(side="left", padx=8)
        if self._existing_att:
            _ghost(att_row, "Entfernen", self._remove_att).pack(side="left")

        # Buttons
        btn_row = tk.Frame(self, bg=BG, padx=24, pady=16)
        btn_row.pack(fill="x")
        _ghost(btn_row, "Abbrechen", self.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Speichern", self._save).pack(side="right")

    def _update_splits(self):
        for w in self._split_widgets:
            w.destroy()
        self._split_widgets.clear()
        for m in self.members:
            row = tk.Frame(self._split_frame, bg=BG)
            row.pack(fill="x", pady=1)
            self._split_widgets.append(row)
            tk.Checkbutton(row, text=m.display_name,
                           variable=self._member_vars[m.pubkey],
                           bg=BG, fg=FG, selectcolor=BG,
                           activebackground=BG, activeforeground=FG,
                           font=FONT, width=18, anchor="w").pack(side="left")
            if self._split_mode.get() == "custom":
                tk.Entry(row, textvariable=self._amount_vars[m.pubkey],
                         font=FONT, bg=PANEL, fg=FG,
                         insertbackground=GREEN, relief="flat", bd=4, width=10).pack(
                    side="left", padx=6)
                _lbl(row, self.group_currency, fg=FG_DIM, font=FONT_SMALL, bg=BG).pack(side="left")

    def _pick_file(self):
        path = fd.askopenfilename(
            title="Anhang wählen",
            filetypes=[("Bilder & PDFs", "*.jpg *.jpeg *.png *.gif *.webp *.pdf"),
                       ("Alle Dateien", "*.*")],
            parent=self,
        )
        if not path:
            return
        with open(path, "rb") as f:
            self._att_data = f.read()
        self._att_path = path
        self._existing_att = None
        fname = os.path.basename(path)
        sz = len(self._att_data)
        sz_str = f"{sz/1024:.1f} KB" if sz >= 1024 else f"{sz} B"
        self._att_label.configure(text=f"📎 {fname} ({sz_str})", fg=BLUE)

    def _remove_att(self):
        self._att_path = self._att_data = self._existing_att = None
        self._att_label.configure(text="Kein Anhang", fg=FG_DIM)

    def _save(self):
        from models import Expense, Attachment, split_equally, split_custom
        from crypto import hash_bytes, mime_type_from_path
        from storage import save_attachment
        from currency import convert

        desc = self._desc.get().strip()
        if not desc:
            mb.showerror("Fehler", "Beschreibung fehlt.", parent=self); return

        try:
            raw_amount = float(self._amount.get().replace(",", "."))
            if raw_amount <= 0:
                raise ValueError
        except ValueError:
            mb.showerror("Fehler", "Ungültiger Betrag.", parent=self); return

        input_cur = self._input_currency.get()
        original_amount   = None
        original_currency = None

        # Umrechnen falls nötig
        if input_cur != self.group_currency:
            converted = convert(raw_amount, input_cur, self.group_currency, self.rates)
            if converted is None:
                if not mb.askyesno(
                    "Kurs fehlt",
                    f"Kein Kurs für {input_cur}→{self.group_currency} verfügbar.\n"
                    "Betrag unverändert übernehmen?",
                    parent=self,
                ):
                    return
                amount = raw_amount
            else:
                original_amount   = raw_amount
                original_currency = input_cur
                amount = converted
        else:
            amount = raw_amount

        payer = next((m for m in self.members if m.display_name == self._payer_var.get()), None)
        if not payer:
            mb.showerror("Fehler", "Zahler nicht gefunden.", parent=self); return

        selected = [m for m in self.members if self._member_vars[m.pubkey].get()]
        if not selected:
            mb.showerror("Fehler", "Mindestens ein Mitglied auswählen.", parent=self); return

        if self._split_mode.get() == "equal":
            splits = split_equally(amount, [m.pubkey for m in selected])
        else:
            try:
                custom = {m.pubkey: float(self._amount_vars[m.pubkey].get().replace(",", "."))
                          for m in selected}
            except ValueError:
                mb.showerror("Fehler", "Individuelle Beträge ungültig.", parent=self); return
            splits = split_custom(custom)

        # Anhang
        attachment = None
        if self._att_data and self._att_path:
            sha = hash_bytes(self._att_data)
            save_attachment(self._att_data, sha)
            attachment = Attachment(sha256=sha, filename=os.path.basename(self._att_path),
                                    size=len(self._att_data),
                                    mime_type=mime_type_from_path(self._att_path))
        elif self._existing_att:
            attachment = self._existing_att

        self.result = {
            "description": desc,
            "amount": amount,
            "currency": self.group_currency,
            "payer_pubkey": payer.pubkey,
            "splits": splits,
            "attachment": attachment,
            "original_amount": original_amount,
            "original_currency": original_currency,
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
        _lbl(frm, "PUBLIC KEY (leer = temporärer Key)", fg=FG_DIM, font=FONT_SMALL).pack(
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
            mb.showerror("Fehler", "Name fehlt.", parent=self); return
        self.result = {"name": name, "pubkey": self._pk.get().strip() or None}
        self.destroy()


# ---------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("SplitP2P")
        self.configure(bg=BG)
        self.geometry("1000x700")
        self.minsize(740, 520)

        self._db            = None
        self._own_key       = None
        self._own_pubkey    = ""
        self._own_name      = ""
        self._group_name    = ""
        self._group_pw      = ""
        self._group_currency = "EUR"
        self._rates: dict[str, float] = {}
        self._network = None   # P2PNetwork instance

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

        net_frame = tk.Frame(hdr, bg=PANEL)
        net_frame.pack(side="left", padx=12)
        self._net_dot   = _lbl(net_frame, "●", fg=FG_DIM, font=("Segoe UI", 9), bg=PANEL)
        self._net_dot.pack(side="left")
        self._net_label = _lbl(net_frame, "offline", fg=FG_DIM, font=FONT_SMALL, bg=PANEL)
        self._net_label.pack(side="left", padx=(3, 0))

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

        _div(sb).pack(fill="x", pady=8)

        # Wechselkurse
        _lbl(sb, "WECHSELKURSE", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14).pack(fill="x")
        self._rates_frame = tk.Frame(sb, bg=PANEL)
        self._rates_frame.pack(fill="x", padx=12, pady=4)
        self._rates_age_label = _lbl(sb, "", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14)
        self._rates_age_label.pack(fill="x")
        _btn(sb, "↻ Aktualisieren", self._manual_refresh_rates,
             bg=BORDER, fg=FG_MUTED, font=FONT_SMALL, width=18).pack(padx=12, pady=4)

    def _build_main(self, paned):
        main = tk.Frame(paned, bg=BG)
        paned.add(main, minsize=500)

        toolbar = tk.Frame(main, bg=PANEL)
        toolbar.pack(fill="x")
        _lbl(toolbar, "AUSGABEN", fg=FG_DIM, font=FONT_SMALL, bg=PANEL,
             padx=16, pady=10).pack(side="left")
        _btn(toolbar, "+ Ausgabe", self._add_expense).pack(side="right", padx=8, pady=6)
        _div(main).pack(fill="x")

        container = tk.Frame(main, bg=BG)
        container.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
        sb2 = tk.Scrollbar(container, orient="vertical", command=self._canvas.yview,
                           bg=PANEL, troughcolor=BG)
        self._canvas.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
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
        self._rates_status = _lbl(self._statusbar, "", fg=FG_DIM, font=FONT_SMALL, bg=PANEL)
        self._rates_status.pack(side="left", padx=16, pady=8)

    # ── Identität & Gruppe ────────────────────────────────────────────

    def _init_identity(self):
        from config_manager import ConfigManager
        from crypto import (generate_private_key, private_key_from_bytes,
                            get_public_key_hex, private_key_to_bytes)
        from storage import init_db

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
            self._do_group_select()

    def _do_group_select(self):
        # Gespeicherte Gruppen aus Config laden
        groups    = self._cfg.get("groups", {})
        last      = self._cfg.get("last_group", "")
        dlg = GroupSelectDialog(self, groups, last)

        if not dlg.result:
            self.quit(); return

        # "Entfernen" wurde gewählt
        if dlg.result.get("_removed"):
            groups.pop(dlg.result["_removed"], None)
            self._cfg.set("groups", groups)
            self._cfg.save()
            self._do_group_select()
            return

        self._group_name     = dlg.result["group_name"]
        self._group_pw       = dlg.result["password"]
        self._group_currency = dlg.result["group_currency"]

        # Gruppe (inkl. Passwort) in Config speichern
        groups[self._group_name] = {
            "password": self._group_pw,
            "currency": self._group_currency,
        }
        self._cfg.set("groups",      groups)
        self._cfg.set("last_group",  self._group_name)
        self._cfg.save()

        self._group_badge.configure(
            text=f"[{self._group_name}  ·  {self._group_currency}]")
        self._identity_label.configure(
            text=f"{self._own_name}  ·  {self._own_pubkey[:12]}…")

        from storage import save_member, get_member
        from models import Member
        me = get_member(self._db, self._own_pubkey)
        if not me or me.display_name != self._own_name:
            save_member(self._db, Member(self._own_pubkey, self._own_name))

        self.deiconify()
        self._load_rates_async()
        self._start_network()
        self._refresh()

    def _switch_group(self):
        self.withdraw()
        self._group_pw = ""
        self._rates = {}
        if self._network:
            self._network.stop()
            self._network = None
        self._net_dot.configure(fg=FG_DIM)
        self._net_label.configure(text="offline")
        self._do_group_select()

    def _open_settings(self, first_run=False):
        dlg = tk.Toplevel(self)
        dlg.title("Einstellungen")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        _lbl(dlg, "IDENTITÄT", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(20, 2), padx=24)
        _div(dlg).pack(fill="x", padx=24)
        frm = tk.Frame(dlg, bg=BG, padx=24, pady=12)
        frm.pack(fill="x")
        _lbl(frm, "ANZEIGENAME", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        name_var = tk.StringVar(value=self._own_name)
        tk.Entry(frm, textvariable=name_var, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=GREEN, relief="flat", bd=6).pack(fill="x", pady=4)
        if self._own_pubkey:
            _lbl(frm, "PUBLIC KEY", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", pady=(8, 0))
            _lbl(frm, self._own_pubkey, fg=FG_DIM, font=FONT_MONO,
                 wraplength=340, justify="left").pack(anchor="w", pady=2)

        def save():
            n = name_var.get().strip()
            if not n:
                mb.showerror("Fehler", "Name darf nicht leer sein.", parent=dlg); return
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
                self._do_group_select()
            else:
                self._refresh()

        btn_row = tk.Frame(dlg, bg=BG, padx=24, pady=16)
        btn_row.pack(fill="x")
        if not first_run:
            _ghost(btn_row, "Abbrechen", dlg.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Speichern", save).pack(side="right")
        dlg.wait_window()

    # ── Wechselkurse ──────────────────────────────────────────────────

    def _load_rates_async(self):
        """Lädt/prüft Kurse im Hintergrund, blockiert nicht die GUI."""
        def _work():
            from currency import get_rates, rates_age_str
            rates = get_rates(self._db, self._group_currency)
            self._rates = rates
            age = rates_age_str(self._db, self._group_currency)
            self.after(0, lambda: self._update_rates_ui(age))

        threading.Thread(target=_work, daemon=True, name="rates-fetch").start()

    def _manual_refresh_rates(self):
        self._rates_status.configure(text="Kurse werden geholt…", fg=AMBER)

        def _work():
            from currency import force_refresh, rates_age_str, load_rates
            ok  = force_refresh(self._db, self._group_currency)
            self._rates = load_rates(self._db, self._group_currency)
            age = rates_age_str(self._db, self._group_currency)
            self.after(0, lambda: self._update_rates_ui(age, force=True, ok=ok))

        threading.Thread(target=_work, daemon=True, name="rates-force").start()

    def _update_rates_ui(self, age_str: str, force: bool = False, ok: bool = True):
        self._rates_age_label.configure(text=f"Stand: {age_str}")
        if force:
            msg = f"✓ Kurse aktualisiert ({age_str})" if ok else "⚠ Online-Abruf fehlgeschlagen"
            color = GREEN if ok else RED
            self._rates_status.configure(text=msg, fg=color)
        else:
            self._rates_status.configure(text="", fg=FG_DIM)
        self._render_rates_sidebar()

    def _render_rates_sidebar(self):
        for w in self._rates_frame.winfo_children():
            w.destroy()
        if not self._rates:
            _lbl(self._rates_frame, "Keine Kurse",
                 fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(anchor="w")
            return
        # Zeige nur die häufigen Währungen
        show = ["USD", "GBP", "CHF", "JPY", "CNY", "CAD", "SEK"]
        for cur in show:
            if cur == self._group_currency or cur not in self._rates:
                continue
            from currency import convert
            rate = convert(1.0, cur, self._group_currency, self._rates)
            if rate is None:
                continue
            row = tk.Frame(self._rates_frame, bg=PANEL)
            row.pack(fill="x", pady=1)
            _lbl(row, f"1 {cur}", fg=FG_MUTED, font=FONT_SMALL, bg=PANEL,
                 width=7, anchor="w").pack(side="left")
            _lbl(row, f"= {rate:.4f} {self._group_currency}",
                 fg=FG, font=FONT_SMALL, bg=PANEL).pack(side="left", padx=4)

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
            pk = get_public_key_hex(generate_private_key())
            mb.showinfo("Key generiert",
                        f"Temporärer Public Key für '{dlg.result['name']}':\n\n{pk}",
                        parent=self)
        save_member(self._db, Member(pubkey=pk, display_name=dlg.result["name"]))
        self._refresh()

    # ── Ausgaben ──────────────────────────────────────────────────────

    def _load_expenses(self):
        from storage import load_all_expense_blobs
        from crypto import decrypt_expense
        return [
            exp for _, blob in load_all_expense_blobs(self._db)
            if (exp := decrypt_expense(blob, self._group_pw)) is not None
        ]

    def _save_expense(self, expense):
        from crypto import sign_expense, encrypt_expense
        from storage import save_expense_blob
        expense.signature = sign_expense(expense, self._own_key)
        blob = encrypt_expense(expense, self._group_pw)
        save_expense_blob(self._db, expense.id, blob, expense.timestamp)
        # Direkt im Netz publizieren (falls verbunden)
        if self._network:
            self._network.publish_expense(expense.id, blob, expense.timestamp)

    def _add_expense(self):
        from storage import load_all_members
        members = load_all_members(self._db)
        if not members:
            mb.showwarning("Keine Mitglieder",
                           "Bitte erst Mitglieder hinzufügen.", parent=self); return
        dlg = ExpenseDialog(self, members, self._own_pubkey,
                            self._group_currency, self._rates)
        if not dlg.result:
            return
        from models import Expense
        exp = Expense.create(**dlg.result)
        self._save_expense(exp)
        self._refresh()

    def _edit_expense(self, expense):
        from storage import load_all_members
        members = load_all_members(self._db)
        dlg = ExpenseDialog(self, members, self._own_pubkey,
                            self._group_currency, self._rates, expense)
        if not dlg.result:
            return
        from models import Expense
        updated = Expense(
            id=expense.id,
            timestamp=int(time.time()),
            signature="",
            **{k: dlg.result[k] for k in
               ("description","amount","currency","payer_pubkey",
                "splits","attachment","original_amount","original_currency")},
        )
        self._save_expense(updated)
        self._refresh()

    def _delete_expense(self, expense):
        if not mb.askyesno("Löschen", f"'{expense.description}' löschen?", parent=self):
            return
        from crypto import sign_expense, encrypt_expense
        from storage import soft_delete_expense_blob
        expense.is_deleted = True
        expense.timestamp  = int(time.time())
        expense.signature  = sign_expense(expense, self._own_key)
        blob = encrypt_expense(expense, self._group_pw)
        soft_delete_expense_blob(self._db, expense.id, blob, expense.timestamp)
        if self._network:
            self._network.publish_expense(expense.id, blob, expense.timestamp)
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
            text=f"Gesamt: {total:.2f} {self._group_currency}  ·  {len(expenses)} Ausgaben")

    def _render_members(self, members):
        for w in self._members_frame.winfo_children():
            w.destroy()
        if not members:
            _lbl(self._members_frame, "Noch keine Mitglieder",
                 fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(anchor="w"); return
        for m in members:
            row = tk.Frame(self._members_frame, bg=PANEL)
            row.pack(fill="x", pady=1)
            _lbl(row, "●", fg=GREEN if m.pubkey == self._own_pubkey else FG_DIM,
                 font=("Segoe UI", 8), bg=PANEL).pack(side="left")
            _lbl(row, m.display_name, fg=FG, font=FONT_SMALL, bg=PANEL).pack(side="left", padx=4)
            if m.pubkey == self._own_pubkey:
                _lbl(row, "(du)", fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(side="left")

    def _render_expenses(self, expenses, members):
        for w in self._expense_list.winfo_children():
            w.destroy()
        pk_to_name = {m.pubkey: m.display_name for m in members}
        if not expenses:
            _lbl(self._expense_list, "Noch keine Ausgaben.",
                 fg=FG_DIM, font=FONT).pack(pady=40); return
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

        # Original-Währungshinweis
        if exp.original_amount and exp.original_currency:
            _lbl(left,
                 f"ursprünglich: {exp.original_amount:.2f} {exp.original_currency}",
                 fg=AMBER, font=FONT_SMALL, bg=PANEL).pack(anchor="w")

        if exp.attachment:
            from storage import attachment_exists
            exists = attachment_exists(exp.attachment.sha256)
            tk.Button(
                left,
                text=f"📎 {exp.attachment.filename} ({exp.attachment.size_str()})"
                     + ("" if exists else "  ⚠ fehlt lokal"),
                fg=BLUE if exists else FG_DIM, bg=PANEL,
                font=FONT_SMALL, relief="flat", bd=0, cursor="hand2",
                activebackground=PANEL, activeforeground=FG,
                command=lambda a=exp.attachment:
                    AttachmentViewer(self, a.sha256, a.filename),
            ).pack(anchor="w")

        right = tk.Frame(row, bg=PANEL)
        right.pack(side="right")
        _lbl(right, f"{exp.amount:.2f} {exp.currency}",
             fg=GREEN, font=FONT_LARGE, bg=PANEL).pack(anchor="e")

        btn_r = tk.Frame(right, bg=PANEL)
        btn_r.pack(anchor="e")
        if exp.payer_pubkey == self._own_pubkey:
            _ghost(btn_r, "✎", lambda e=exp: self._edit_expense(e)).pack(side="left", padx=2)
        _ghost(btn_r, "✕", lambda e=exp: self._delete_expense(e)).pack(side="left", padx=2)

        _div(self._expense_list).pack(fill="x")

    def _render_debts(self, expenses, members):
        from ledger import get_settlements
        for w in self._debt_frame.winfo_children():
            w.destroy()
        pk_to_name = {m.pubkey: m.display_name for m in members}

        def name(pk): return pk_to_name.get(pk, pk[:8] + "…")

        settlements = get_settlements(expenses)
        if not settlements:
            _lbl(self._debt_frame, "Alle quitt ✓",
                 fg=GREEN, font=FONT_SMALL, bg=PANEL).pack(anchor="w"); return
        for s in settlements:
            is_me_d = s.debtor   == self._own_pubkey
            is_me_c = s.creditor == self._own_pubkey
            color = RED if is_me_d else (GREEN if is_me_c else FG_MUTED)
            f = tk.Frame(self._debt_frame, bg=PANEL)
            f.pack(fill="x", pady=2)
            _lbl(f, f"{name(s.debtor)} → {name(s.creditor)}",
                 fg=color, font=FONT_SMALL, bg=PANEL,
                 wraplength=180, justify="left").pack(anchor="w")
            _lbl(f, f"{s.amount:.2f} {self._group_currency}",
                 fg=color, font=FONT_BOLD, bg=PANEL).pack(anchor="w")


    # ── Netzwerk ──────────────────────────────────────────────────────

    def _start_network(self):
        from network import P2PNetwork, NetworkCallbacks

        class _Callbacks(NetworkCallbacks):
            def __init__(self2, app):
                self2._app = app
            def on_expense_received(self2, expense_id, blob):
                self2._app.after(0, lambda: self2._app._on_net_expense(expense_id, blob))
            def on_peer_connected(self2, peer_id):
                self2._app.after(0, lambda: self2._app._on_peer_change())
            def on_peer_disconnected(self2, peer_id):
                self2._app.after(0, lambda: self2._app._on_peer_change())
            def on_status_changed(self2, online, peer_id):
                self2._app.after(0, lambda: self2._app._on_net_status(online, peer_id))
            def on_file_received(self2, sha256):
                self2._app.after(0, self2._app._refresh)

        self._network = P2PNetwork(self._group_pw, _Callbacks(self))
        self._network.start_in_thread()

    def _on_net_status(self, online, peer_id):
        if online:
            short = peer_id[:20] + "..." if len(peer_id) > 20 else peer_id
            self._net_dot.configure(fg=GREEN)
            self._net_label.configure(text=f"online  {short}", fg=FG_MUTED)
        else:
            self._net_dot.configure(fg=FG_DIM)
            label = "offline-mode" if peer_id == "offline-mode" else "offline"
            self._net_label.configure(text=label, fg=FG_DIM)

    def _on_peer_change(self):
        if self._network is None:
            return
        n = self._network.peer_count
        if n == 0:
            self._net_label.configure(text="online  keine Peers")
        else:
            self._net_label.configure(text=f"online  {n} Peer{'s' if n != 1 else ''}")

    def _on_net_expense(self, expense_id, blob):
        from storage import save_expense_blob
        from crypto import decrypt_expense

        expense = decrypt_expense(blob, self._group_pw)
        if expense is None:
            return  # falsches Passwort oder fremde Gruppe

        saved = save_expense_blob(
            self._db, expense.id, blob, expense.timestamp, expense.is_deleted
        )
        if not saved:
            return  # veraltet, CRDT hat verworfen

        self._refresh()

        # fehlenden Anhang beim Sender anfordern
        if expense.attachment and self._network:
            from storage import attachment_exists
            if not attachment_exists(expense.attachment.sha256):
                self._network.request_file(expense.attachment.sha256)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def run():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    run()
