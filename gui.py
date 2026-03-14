# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
GUI – Dezentrales Splitwise
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
PURPLE   = "#a78bfa"

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


def _ghost(parent, text, cmd, fg=FG_MUTED):
    return tk.Button(parent, text=text, command=cmd,
                     bg=PANEL, fg=fg, font=FONT,
                     relief="flat", bd=0, padx=10, pady=6,
                     activebackground=BORDER, activeforeground=FG,
                     cursor="hand2")


def _lbl(parent, text, fg=FG, font=FONT, **kw):
    return tk.Label(parent, text=text, fg=fg,
                    bg=kw.pop("bg", BG), font=font, **kw)


def _div(parent, **kw):
    return tk.Frame(parent, bg=BORDER, height=1, **kw)


def _combobox(parent, var, values, **kw):
    s = ttk.Style()
    s.theme_use("clam")
    s.configure("TCombobox", fieldbackground=PANEL, background=PANEL,
                foreground=FG, selectbackground=BORDER, arrowcolor=FG_DIM,
                selectforeground=FG)
    return ttk.Combobox(parent, textvariable=var, values=values,
                        state="readonly", font=FONT, **kw)


# ---------------------------------------------------------------------------
# Date-Picker-Widget
# ---------------------------------------------------------------------------

class DatePickerFrame(tk.Frame):
    """
    Kompakter Datumsauswähler mit Spinboxen für Tag/Monat/Jahr.
    get_date() → Unix-Timestamp (Mitternacht UTC des gewählten Tages)
    set_date(ts) setzt das Datum aus einem Unix-Timestamp.
    """
    def __init__(self, parent, initial_ts: int = 0, **kw):
        super().__init__(parent, bg=kw.pop("bg", BG), **kw)
        import datetime
        dt = datetime.datetime.fromtimestamp(initial_ts or time.time())

        self._day   = tk.StringVar(value=str(dt.day))
        self._month = tk.StringVar(value=str(dt.month))
        self._year  = tk.StringVar(value=str(dt.year))

        spin_kw = dict(bg=PANEL, fg=FG, font=FONT,
                       insertbackground=GREEN, relief="flat",
                       buttonbackground=PANEL, highlightthickness=0)

        tk.Spinbox(self, from_=1, to=31, textvariable=self._day,
                   width=3, **spin_kw).pack(side="left")
        _lbl(self, ".", fg=FG_MUTED, bg=BG, padx=2).pack(side="left")
        tk.Spinbox(self, from_=1, to=12, textvariable=self._month,
                   width=3, **spin_kw).pack(side="left")
        _lbl(self, ".", fg=FG_MUTED, bg=BG, padx=2).pack(side="left")
        tk.Spinbox(self, from_=2000, to=2099, textvariable=self._year,
                   width=5, **spin_kw).pack(side="left")

    def get_date(self) -> int:
        """Unix-Timestamp des gewählten Tages um 00:00 Lokalzeit."""
        import datetime
        try:
            d = int(self._day.get())
            m = int(self._month.get())
            y = int(self._year.get())
            dt = datetime.datetime(y, m, d, 0, 0, 0)
            return int(dt.timestamp())
        except (ValueError, OverflowError):
            return int(time.time())

    def set_date(self, ts: int) -> None:
        import datetime
        dt = datetime.datetime.fromtimestamp(ts)
        self._day.set(str(dt.day))
        self._month.set(str(dt.month))
        self._year.set(str(dt.year))


# ---------------------------------------------------------------------------
# Group Dialogs
# ---------------------------------------------------------------------------

class NewGroupDialog(tk.Toplevel):
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
        self._pw = tk.Entry(frm, show="●", font=FONT, bg=PANEL, fg=FG,
                            insertbackground=GREEN, relief="flat", bd=6)
        self._pw.pack(fill="x", pady=(2, 8))

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
        if not name:
            mb.showerror("Fehler", "Gruppenname fehlt.", parent=self); return
        if len(pw) < 4:
            mb.showerror("Fehler", "Passwort mind. 4 Zeichen.", parent=self); return
        self.result = {"group_name": name, "password": pw,
                       "group_currency": self._currency.get()}
        self.destroy()


class GroupSelectDialog(tk.Toplevel):
    def __init__(self, parent, groups: dict, last_group: str):
        super().__init__(parent)
        self.title("Gruppe wählen")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.groups = groups
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
            self._selected = tk.StringVar(
                value=last_group if last_group in self.groups else next(iter(self.groups)))
            inner = tk.Frame(frm, bg=BORDER, padx=1, pady=1)
            inner.pack(fill="x", pady=(2, 12))
            content = tk.Frame(inner, bg=BG)
            content.pack(fill="x")
            for name, info in self.groups.items():
                row = tk.Frame(content, bg=BG)
                row.pack(fill="x")
                tk.Radiobutton(row, text=f"  {name}", variable=self._selected,
                               value=name, bg=BG, fg=FG, selectcolor=BG,
                               activebackground=BG, font=FONT, anchor="w").pack(
                    side="left", fill="x", expand=True)
                _lbl(row, info.get("currency", "EUR"),
                     fg=FG_DIM, font=FONT_SMALL, bg=BG, padx=8).pack(side="right")
            btn_row = tk.Frame(self, bg=BG, padx=28)
            btn_row.pack(fill="x")
            _ghost(btn_row, "+ Neue Gruppe", self._new_group).pack(side="left")
            _ghost(btn_row, "Entfernen", self._remove_group).pack(side="left", padx=6)
            _btn(btn_row, "ÖFFNEN", self._confirm).pack(side="right")
            tk.Frame(self, bg=BG, height=16).pack()
        else:
            self._selected = tk.StringVar(value="")
            _lbl(frm, "Noch keine Gruppen.", fg=FG_DIM, font=FONT_SMALL).pack(
                anchor="w", pady=(0, 12))
            _btn(frm, "+ Erste Gruppe erstellen / beitreten",
                 self._new_group, width=32).pack(anchor="w", pady=8)
            tk.Frame(self, bg=BG, height=16).pack()

    def _new_group(self):
        dlg = NewGroupDialog(self)
        if not dlg.result: return
        self.groups[dlg.result["group_name"]] = {
            "password": dlg.result["password"],
            "currency": dlg.result["group_currency"],
        }
        self.result = dlg.result
        self.destroy()

    def _remove_group(self):
        name = self._selected.get()
        if name and mb.askyesno("Entfernen",
                                f"Gruppe '{name}' aus der Liste entfernen?\n"
                                "(Daten bleiben erhalten)", parent=self):
            self.groups.pop(name, None)
            self.result = {"_removed": name}
            self.destroy()

    def _confirm(self):
        name = self._selected.get()
        if not name or name not in self.groups:
            mb.showerror("Fehler", "Keine Gruppe ausgewählt.", parent=self); return
        info = self.groups[name]
        self.result = {"group_name": name, "password": info["password"],
                       "group_currency": info.get("currency", "EUR")}
        self.destroy()


# ---------------------------------------------------------------------------
# Attachment Viewer
# ---------------------------------------------------------------------------

class AttachmentViewer(tk.Toplevel):
    def __init__(self, parent, sha256: str, filename: str):
        from storage import attachment_path
        path = attachment_path(sha256)
        if not path:
            mb.showerror("Nicht gefunden",
                         "Die Datei ist lokal nicht vorhanden.", parent=parent)
            return
        if filename.lower().endswith(".pdf"):
            self._open_ext(path); return
        super().__init__(parent)
        self.title(filename)
        self.configure(bg=BG)
        self.grab_set()
        try:
            from PIL import Image, ImageTk
            img = Image.open(path); img.thumbnail((800, 600))
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(self, image=photo, bg=BG)
            lbl.image = photo; lbl.pack(padx=10, pady=10)
            _lbl(self, filename, fg=FG_DIM, font=FONT_SMALL).pack(pady=(0, 10))
        except ImportError:
            self._open_ext(path)
            try: self.destroy()
            except Exception: pass

    def _open_ext(self, path):
        if sys.platform == "win32": os.startfile(path)
        elif sys.platform == "darwin": subprocess.run(["open", path])
        else: subprocess.run(["xdg-open", path])


# ---------------------------------------------------------------------------
# Storage Setup Dialog
# ---------------------------------------------------------------------------

class StorageSetupDialog(tk.Toplevel):
    def __init__(self, parent, defaults: dict):
        super().__init__(parent)
        self.title("Speicherort einrichten")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.result: Optional[dict] = None
        self._build(defaults)
        self.wait_window()

    def _build(self, defaults):
        pad = dict(padx=28)
        _lbl(self, "SPEICHERORT", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(24, 4), **pad)
        _lbl(self,
             "Wo sollen Datenbank und Dateianhänge gespeichert werden?\n"
             "Die Einstellung kann später in den Einstellungen geändert werden.",
             fg=FG_DIM, font=FONT_SMALL, justify="left").pack(anchor="w", **pad)
        _div(self).pack(fill="x", padx=28, pady=10)
        frm = tk.Frame(self, bg=BG, padx=28)
        frm.pack(fill="x")

        def path_row(lbl_text, var, is_dir=False):
            _lbl(frm, lbl_text, fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
            row = tk.Frame(frm, bg=BG)
            row.pack(fill="x", pady=(2, 8))
            tk.Entry(row, textvariable=var, font=FONT_MONO, bg=PANEL, fg=FG,
                     insertbackground=GREEN, relief="flat", bd=6).pack(
                side="left", fill="x", expand=True)
            def pick(v=var, d=is_dir):
                p = fd.askdirectory(title="Ordner", parent=self) if d else \
                    fd.asksaveasfilename(title="Datenbankdatei", parent=self,
                        defaultextension=".db",
                        filetypes=[("SQLite", "*.db"), ("Alle", "*.*")],
                        initialfile=os.path.basename(v.get()),
                        initialdir=os.path.dirname(os.path.abspath(v.get())))
                if p: v.set(p)
            _ghost(row, "…", pick).pack(side="left", padx=(6, 0))

        self._db_path = tk.StringVar(value=defaults.get("db_path", ""))
        self._att_dir = tk.StringVar(value=defaults.get("storage_dir", ""))
        path_row("DATENBANKDATEI (.db)", self._db_path)
        path_row("ORDNER FÜR DATEIANHÄNGE", self._att_dir, is_dir=True)

        btn_row = tk.Frame(self, bg=BG, padx=28, pady=20)
        btn_row.pack(fill="x")
        _btn(btn_row, "WEITER", self._confirm).pack(side="right")

    def _confirm(self):
        db_path = self._db_path.get().strip()
        att_dir = self._att_dir.get().strip()
        if not db_path or not att_dir:
            mb.showerror("Fehler", "Beide Pfade müssen angegeben werden.", parent=self); return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            os.makedirs(att_dir, exist_ok=True)
        except OSError as e:
            mb.showerror("Fehler", f"Ordner konnte nicht erstellt werden:\n{e}", parent=self); return
        self.result = {"db_path": db_path, "storage_dir": att_dir}
        self.destroy()


# ---------------------------------------------------------------------------
# Expense Dialog
# ---------------------------------------------------------------------------

class ExpenseDialog(tk.Toplevel):
    def __init__(self, parent, members, own_pubkey, group_currency, rates, expense=None):
        super().__init__(parent)
        self.title("Ausgabe bearbeiten" if expense else "Neue Ausgabe")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.members        = members
        self.own_pubkey     = own_pubkey
        self.group_currency = group_currency
        self.rates          = rates
        self.result         = None
        self._att_path: Optional[str]   = None
        self._att_data: Optional[bytes] = None
        self._existing_att  = getattr(expense, "attachment", None)
        self._build(expense)
        self.wait_window()

    def _build(self, exp):
        from models import CATEGORIES
        from currency import SUPPORTED_CURRENCIES

        pad = dict(padx=24)
        _lbl(self, "AUSGABE BEARBEITEN" if exp else "NEUE AUSGABE",
             fg=GREEN, font=FONT_LARGE).pack(anchor="w", pady=(20, 2), **pad)
        _div(self).pack(fill="x", **pad)

        frm = tk.Frame(self, bg=BG, padx=24, pady=12)
        frm.pack(fill="x")

        # Beschreibung
        _lbl(frm, "BESCHREIBUNG", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._desc = tk.StringVar(value=exp.description if exp else "")
        tk.Entry(frm, textvariable=self._desc, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=GREEN, relief="flat", bd=6).pack(fill="x", pady=(2, 8))

        # Betrag + Währung
        _lbl(frm, "BETRAG", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        amt_row = tk.Frame(frm, bg=BG)
        amt_row.pack(fill="x", pady=(2, 2))

        default_amt = ""
        default_cur = self.group_currency
        if exp:
            if exp.original_amount and exp.original_currency:
                default_amt = str(exp.original_amount)
                default_cur = exp.original_currency
            else:
                default_amt = str(exp.amount)

        self._amount = tk.StringVar(value=default_amt)
        self._input_currency = tk.StringVar(value=default_cur)
        tk.Entry(amt_row, textvariable=self._amount, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=GREEN, relief="flat", bd=6, width=14).pack(side="left")
        _combobox(amt_row, self._input_currency, SUPPORTED_CURRENCIES, width=8).pack(
            side="left", padx=6)

        self._conv_label = _lbl(frm, "", fg=AMBER, font=FONT_SMALL, bg=BG)
        self._conv_label.pack(anchor="w", pady=(2, 8))

        def _update_preview(*_):
            from currency import convert, format_rate
            try:
                amt = float(self._amount.get().replace(",", "."))
            except ValueError:
                self._conv_label.configure(text=""); return
            ic = self._input_currency.get()
            if ic == self.group_currency:
                self._conv_label.configure(text=""); return
            converted = convert(amt, ic, self.group_currency, self.rates)
            if converted is not None:
                self._conv_label.configure(
                    text=f"= {converted:.2f} {self.group_currency}  "
                         f"({format_rate(ic, self.group_currency, self.rates)})")
            else:
                self._conv_label.configure(
                    text=f"⚠ Kurs {ic}→{self.group_currency} nicht verfügbar", fg=RED)

        self._amount.trace_add("write", _update_preview)
        self._input_currency.trace_add("write", _update_preview)
        _update_preview()

        # Datum
        _lbl(frm, "DATUM", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        initial_ts = (exp.expense_date or exp.timestamp) if exp else int(time.time())
        self._date_picker = DatePickerFrame(frm, initial_ts=initial_ts, bg=BG)
        self._date_picker.pack(anchor="w", pady=(2, 8))

        # Kategorie
        _lbl(frm, "KATEGORIE", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._category = tk.StringVar(value=getattr(exp, "category", "Allgemein") if exp else "Allgemein")
        _combobox(frm, self._category, CATEGORIES, width=24).pack(
            anchor="w", pady=(2, 8))

        # Bezahlt von
        _lbl(frm, "BEZAHLT VON", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._payer_var = tk.StringVar()
        payer_names = [m.display_name for m in self.members]
        default_payer = next(
            (m.display_name for m in self.members if m.pubkey == self.own_pubkey),
            payer_names[0] if payer_names else "")
        if exp:
            default_payer = next(
                (m.display_name for m in self.members if m.pubkey == exp.payer_pubkey),
                default_payer)
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

        btn_row = tk.Frame(self, bg=BG, padx=24, pady=16)
        btn_row.pack(fill="x")
        _ghost(btn_row, "Abbrechen", self.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Speichern", self._save).pack(side="right")

    def _update_splits(self):
        for w in self._split_widgets: w.destroy()
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
                       ("Alle Dateien", "*.*")], parent=self)
        if not path: return
        with open(path, "rb") as f:
            self._att_data = f.read()
        self._att_path = path
        self._existing_att = None
        fname = os.path.basename(path)
        sz = len(self._att_data)
        self._att_label.configure(
            text=f"📎 {fname} ({sz/1024:.1f} KB)" if sz >= 1024 else f"📎 {fname} ({sz} B)",
            fg=BLUE)

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
            if raw_amount <= 0: raise ValueError
        except ValueError:
            mb.showerror("Fehler", "Ungültiger Betrag.", parent=self); return

        input_cur = self._input_currency.get()
        original_amount = original_currency = None
        if input_cur != self.group_currency:
            converted = convert(raw_amount, input_cur, self.group_currency, self.rates)
            if converted is None:
                if not mb.askyesno("Kurs fehlt",
                    f"Kein Kurs für {input_cur}→{self.group_currency}.\n"
                    "Betrag unverändert übernehmen?", parent=self): return
                amount = raw_amount
            else:
                original_amount, original_currency = raw_amount, input_cur
                amount = converted
        else:
            amount = raw_amount

        payer = next((m for m in self.members if m.display_name == self._payer_var.get()), None)
        if not payer:
            mb.showerror("Fehler", "Zahler nicht gefunden.", parent=self); return

        selected = [m for m in self.members if self._member_vars[m.pubkey].get()]
        if not selected:
            mb.showerror("Fehler", "Mind. ein Mitglied auswählen.", parent=self); return

        if self._split_mode.get() == "equal":
            splits = split_equally(amount, [m.pubkey for m in selected])
        else:
            try:
                custom = {m.pubkey: float(self._amount_vars[m.pubkey].get().replace(",", "."))
                          for m in selected}
            except ValueError:
                mb.showerror("Fehler", "Individuelle Beträge ungültig.", parent=self); return
            splits = split_custom(custom)

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
            "description": desc, "amount": amount, "currency": self.group_currency,
            "payer_pubkey": payer.pubkey, "splits": splits,
            "category": self._category.get(),
            "expense_date": self._date_picker.get_date(),
            "attachment": attachment,
            "original_amount": original_amount,
            "original_currency": original_currency,
        }
        self.destroy()


# ---------------------------------------------------------------------------
# Settlement Dialog
# ---------------------------------------------------------------------------

class SettlementDialog(tk.Toplevel):
    """Dialog zum Erfassen einer Ausgleichszahlung."""
    def __init__(self, parent, members, own_pubkey, group_currency, rates,
                 prefill: dict = None):
        super().__init__(parent)
        self.title("Zahlung erfassen")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.members        = members
        self.own_pubkey     = own_pubkey
        self.group_currency = group_currency
        self.rates          = rates
        self.result         = None
        self._build(prefill or {})
        self.wait_window()

    def _build(self, prefill):
        from currency import SUPPORTED_CURRENCIES

        pad = dict(padx=24)
        _lbl(self, "ZAHLUNG ERFASSEN", fg=PURPLE, font=FONT_LARGE).pack(
            anchor="w", pady=(20, 2), **pad)
        _lbl(self, "Wer hat wem wie viel gezahlt?",
             fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", **pad)
        _div(self).pack(fill="x", **pad, pady=4)

        frm = tk.Frame(self, bg=BG, padx=24, pady=12)
        frm.pack(fill="x")

        member_names = [m.display_name for m in self.members]
        default_from = next(
            (m.display_name for m in self.members
             if m.pubkey == prefill.get("from_pubkey", self.own_pubkey)),
            member_names[0] if member_names else "")
        default_to = next(
            (m.display_name for m in self.members
             if m.pubkey == prefill.get("to_pubkey", "")),
            member_names[-1] if len(member_names) > 1 else member_names[0] if member_names else "")

        _lbl(frm, "VON (wer hat gezahlt)", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._from_var = tk.StringVar(value=default_from)
        _combobox(frm, self._from_var, member_names).pack(fill="x", pady=(2, 8))

        _lbl(frm, "AN (wer hat empfangen)", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._to_var = tk.StringVar(value=default_to)
        _combobox(frm, self._to_var, member_names).pack(fill="x", pady=(2, 8))

        # Betrag + Währung
        _lbl(frm, "BETRAG", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        amt_row = tk.Frame(frm, bg=BG)
        amt_row.pack(fill="x", pady=(2, 2))
        self._amount = tk.StringVar(
            value=str(prefill.get("amount", "")))
        self._input_currency = tk.StringVar(value=self.group_currency)
        tk.Entry(amt_row, textvariable=self._amount, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=PURPLE, relief="flat", bd=6, width=14).pack(side="left")
        _combobox(amt_row, self._input_currency, SUPPORTED_CURRENCIES, width=8).pack(
            side="left", padx=6)

        self._conv_label = _lbl(frm, "", fg=AMBER, font=FONT_SMALL, bg=BG)
        self._conv_label.pack(anchor="w", pady=(2, 8))

        def _preview(*_):
            from currency import convert, format_rate
            try:
                amt = float(self._amount.get().replace(",", "."))
            except ValueError:
                self._conv_label.configure(text=""); return
            ic = self._input_currency.get()
            if ic == self.group_currency:
                self._conv_label.configure(text=""); return
            c = convert(amt, ic, self.group_currency, self.rates)
            if c is not None:
                self._conv_label.configure(
                    text=f"= {c:.2f} {self.group_currency}  "
                         f"({format_rate(ic, self.group_currency, self.rates)})")
            else:
                self._conv_label.configure(
                    text=f"⚠ Kurs {ic}→{self.group_currency} nicht verfügbar", fg=RED)

        self._amount.trace_add("write", _preview)
        self._input_currency.trace_add("write", _preview)

        # Datum
        _lbl(frm, "DATUM", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._date_picker = DatePickerFrame(frm, initial_ts=int(time.time()), bg=BG)
        self._date_picker.pack(anchor="w", pady=(2, 8))

        # Notiz
        _lbl(frm, "NOTIZ (optional)", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._note = tk.StringVar()
        tk.Entry(frm, textvariable=self._note, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=PURPLE, relief="flat", bd=6).pack(fill="x", pady=(2, 8))

        btn_row = tk.Frame(self, bg=BG, padx=24, pady=16)
        btn_row.pack(fill="x")
        _ghost(btn_row, "Abbrechen", self.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Speichern", self._save, bg=PURPLE).pack(side="right")

    def _save(self):
        from currency import convert
        frm_name = self._from_var.get()
        to_name  = self._to_var.get()
        if frm_name == to_name:
            mb.showerror("Fehler", "Von und An müssen verschieden sein.", parent=self); return

        frm_m = next((m for m in self.members if m.display_name == frm_name), None)
        to_m  = next((m for m in self.members if m.display_name == to_name),  None)
        if not frm_m or not to_m:
            mb.showerror("Fehler", "Mitglied nicht gefunden.", parent=self); return

        try:
            raw = float(self._amount.get().replace(",", "."))
            if raw <= 0: raise ValueError
        except ValueError:
            mb.showerror("Fehler", "Ungültiger Betrag.", parent=self); return

        input_cur = self._input_currency.get()
        orig_amount = orig_currency = None
        if input_cur != self.group_currency:
            converted = convert(raw, input_cur, self.group_currency, self.rates)
            if converted is None:
                if not mb.askyesno("Kurs fehlt",
                    f"Kein Kurs {input_cur}→{self.group_currency}.\n"
                    "Betrag unverändert?", parent=self): return
                amount = raw
            else:
                orig_amount, orig_currency = raw, input_cur
                amount = converted
        else:
            amount = raw

        self.result = {
            "from_pubkey":       frm_m.pubkey,
            "to_pubkey":         to_m.pubkey,
            "amount":            amount,
            "currency":          self.group_currency,
            "settlement_date":   self._date_picker.get_date(),
            "note":              self._note.get().strip(),
            "original_amount":   orig_amount,
            "original_currency": orig_currency,
        }
        self.destroy()


# ---------------------------------------------------------------------------
# Add Member Dialog
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
# App – Hauptfenster
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Charts Window
# ---------------------------------------------------------------------------

class ChartsWindow(tk.Toplevel):
    """
    Drei Diagramme in einem Fenster:
      1. Ausgaben nach Kategorie (Balken)
      2. Saldo pro Person (Balken, positiv/negativ)
      3. Kumulierte Ausgaben über Zeit (Linie)

    Nutzt matplotlib mit dem TkAgg-Backend.
    Falls matplotlib nicht installiert ist: Fehlermeldung mit Installationshinweis.
    """

    def __init__(self, parent, expenses, settlements, members,
                 group_currency, own_pubkey):
        super().__init__(parent)
        self.title(f"Charts – {group_currency}")
        self.configure(bg=BG)
        self.geometry("900x640")

        try:
            import matplotlib
            matplotlib.use("TkAgg")
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
        except ImportError:
            _lbl(self, "matplotlib nicht installiert.",
                 fg=RED, font=FONT_BOLD).pack(pady=20)
            _lbl(self, "pip install matplotlib", fg=FG_DIM, font=FONT_MONO).pack()
            return

        pk_to_name = {m.pubkey: m.display_name for m in members}
        def name(pk): return pk_to_name.get(pk, pk[:8] + "…")

        # Farben passend zum App-Theme
        DARK   = "#111318"
        PANEL_ = "#191c24"
        FG_    = "#dde2ee"
        DIM_   = "#5a6080"
        COLS   = ["#2ecc8f","#4d9de0","#e0a03a","#e05c6a","#a78bfa",
                  "#5dcaa5","#f09595","#fac775","#85b7eb","#ed93b1"]

        fig = Figure(figsize=(11, 7.5), facecolor=DARK, tight_layout=True)
        fig.patch.set_facecolor(DARK)

        def style_ax(ax, title):
            ax.set_facecolor(PANEL_)
            ax.set_title(title, color=FG_, fontsize=11, pad=8)
            ax.tick_params(colors=DIM_, labelsize=9)
            for spine in ax.spines.values():
                spine.set_edgecolor("#252a36")
            ax.title.set_fontsize(10)

        # ── 1. Ausgaben nach Kategorie ───────────────────────────────
        ax1 = fig.add_subplot(2, 2, 1)
        style_ax(ax1, "Ausgaben nach Kategorie")
        from collections import defaultdict
        by_cat = defaultdict(float)
        for e in expenses:
            by_cat[e.category] += e.amount
        if by_cat:
            cats   = list(by_cat.keys())
            vals   = [by_cat[c] for c in cats]
            colors = [COLS[i % len(COLS)] for i in range(len(cats))]
            bars   = ax1.barh(cats, vals, color=colors, height=0.6)
            ax1.set_xlabel(group_currency, color=DIM_, fontsize=9)
            ax1.xaxis.label.set_color(DIM_)
            for bar, val in zip(bars, vals):
                ax1.text(bar.get_width() + max(vals)*0.01, bar.get_y() + bar.get_height()/2,
                         f"{val:.0f}", va="center", color=FG_, fontsize=8)
        else:
            ax1.text(0.5, 0.5, "Keine Daten", transform=ax1.transAxes,
                     ha="center", va="center", color=DIM_)

        # ── 2. Saldo pro Person ──────────────────────────────────────
        ax2 = fig.add_subplot(2, 2, 2)
        style_ax(ax2, "Saldo pro Person")
        from ledger import compute_balances
        balances = compute_balances(expenses, settlements)
        if balances:
            sorted_b  = sorted(balances.items(), key=lambda x: x[1])
            pks        = [name(pk) for pk, _ in sorted_b]
            bals       = [b for _, b in sorted_b]
            bar_colors = [COLS[0] if b >= 0 else "#e05c6a" for b in bals]
            ax2.barh(pks, bals, color=bar_colors, height=0.6)
            ax2.axvline(0, color=DIM_, linewidth=0.8, linestyle="--")
            ax2.set_xlabel(group_currency, color=DIM_, fontsize=9)
            for i, (b, pk) in enumerate(zip(bals, pks)):
                ax2.text(b + (max(abs(v) for v in bals)*0.02 if b >= 0 else
                              -max(abs(v) for v in bals)*0.02),
                         i, f"{b:+.2f}", va="center",
                         ha="left" if b >= 0 else "right",
                         color=FG_, fontsize=8)
        else:
            ax2.text(0.5, 0.5, "Keine Daten", transform=ax2.transAxes,
                     ha="center", va="center", color=DIM_)

        # ── 3. Kumulierte Ausgaben über Zeit ─────────────────────────
        ax3 = fig.add_subplot(2, 1, 2)
        style_ax(ax3, "Kumulierte Ausgaben über Zeit")
        if expenses:
            import datetime
            sorted_exp = sorted(expenses, key=lambda e: e.display_date())
            dates  = [datetime.datetime.fromtimestamp(e.display_date()) for e in sorted_exp]
            cumsum = []
            total  = 0.0
            for e in sorted_exp:
                total += e.amount
                cumsum.append(total)
            ax3.plot(dates, cumsum, color=COLS[0], linewidth=2)
            ax3.fill_between(dates, cumsum, alpha=0.15, color=COLS[0])
            ax3.set_ylabel(group_currency, color=DIM_, fontsize=9)
            ax3.yaxis.label.set_color(DIM_)
            # Kategorie-Markierungen
            cat_colors = {}
            for i, cat in enumerate(set(e.category for e in sorted_exp)):
                cat_colors[cat] = COLS[i % len(COLS)]
            for e, d, cs in zip(sorted_exp, dates, cumsum):
                ax3.scatter([d], [cs], color=cat_colors.get(e.category, DIM_),
                            s=30, zorder=5)
            # Legende
            from matplotlib.patches import Patch
            legend_elements = [Patch(facecolor=c, label=cat)
                               for cat, c in cat_colors.items()]
            ax3.legend(handles=legend_elements, facecolor=PANEL_, edgecolor=DIM_,
                       labelcolor=FG_, fontsize=8, loc="upper left")
            fig.autofmt_xdate(rotation=30, ha="right")
        else:
            ax3.text(0.5, 0.5, "Keine Daten", transform=ax3.transAxes,
                     ha="center", va="center", color=DIM_)

        canvas = FigureCanvasTkAgg(fig, master=self)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", pady=6)
        def save_png():
            import tkinter.filedialog as fd2
            path = fd2.asksaveasfilename(
                title="Charts speichern", defaultextension=".png",
                filetypes=[("PNG", "*.png"), ("Alle", "*.*")], parent=self)
            if path:
                fig.savefig(path, facecolor=DARK, dpi=150)
                mb.showinfo("Gespeichert", f"Charts gespeichert:\n{path}", parent=self)
        _ghost(btn_row, "Als PNG speichern", save_png).pack(side="right", padx=12)


# ---------------------------------------------------------------------------
# Export Dialog
# ---------------------------------------------------------------------------

class ExportDialog(tk.Toplevel):
    """
    Exportiert Ausgaben und Zahlungen als CSV oder PDF.
    CSV: stdlib, keine Abhängigkeit.
    PDF: fpdf2 (pip install fpdf2). Fallback: HTML-Datei.
    """

    def __init__(self, parent, expenses, settlements, members,
                 group_currency, group_name):
        super().__init__(parent)
        self.title("Export")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.expenses    = expenses
        self.settlements = settlements
        self.members     = members
        self.currency    = group_currency
        self.group_name  = group_name
        self.pk_to_name  = {m.pubkey: m.display_name for m in members}
        self._build()
        self.wait_window()

    def _name(self, pk):
        return self.pk_to_name.get(pk, pk[:8] + "…")

    def _build(self):
        pad = dict(padx=28)
        _lbl(self, "EXPORT", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(20, 2), **pad)
        _div(self).pack(fill="x", padx=28, pady=8)

        frm = tk.Frame(self, bg=BG, padx=28)
        frm.pack(fill="x")

        _lbl(frm, "INHALT", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._incl_exp  = tk.BooleanVar(value=True)
        self._incl_set  = tk.BooleanVar(value=True)
        self._incl_debt = tk.BooleanVar(value=True)
        for var, txt in [(self._incl_exp,  "Ausgaben"),
                         (self._incl_set,  "Zahlungen"),
                         (self._incl_debt, "Schuldenübersicht")]:
            tk.Checkbutton(frm, text=txt, variable=var, bg=BG, fg=FG,
                           selectcolor=BG, activebackground=BG,
                           activeforeground=FG, font=FONT).pack(anchor="w")

        _div(frm).pack(fill="x", pady=10)
        _lbl(frm, "FORMAT", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")

        btn_row = tk.Frame(frm, bg=BG)
        btn_row.pack(fill="x", pady=6)
        _btn(btn_row, "CSV exportieren",  self._export_csv,  width=18).pack(
            side="left", padx=(0, 8))
        _btn(btn_row, "PDF exportieren",  self._export_pdf,
             bg=BLUE, width=18).pack(side="left")

        _lbl(frm, "PDF benötigt: pip install fpdf2",
             fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", pady=(4, 0))

        tk.Frame(self, bg=BG, height=16).pack()

    def _export_csv(self):
        import csv, tkinter.filedialog as fd2
        path = fd2.asksaveasfilename(
            title="CSV speichern", defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Alle", "*.*")], parent=self)
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if self._incl_exp.get():
                w.writerow(["Typ","Datum","Beschreibung","Kategorie",
                             "Betrag","Währung","Bezahlt von","Anteile",
                             "Original-Betrag","Original-Währung"])
                for e in sorted(self.expenses, key=lambda x: x.display_date()):
                    splits = "; ".join(
                        f"{self._name(s.pubkey)}:{s.amount:.2f}"
                        for s in e.splits)
                    w.writerow([
                        "Ausgabe",
                        time.strftime("%d.%m.%Y", time.localtime(e.display_date())),
                        e.description, e.category,
                        f"{e.amount:.2f}", e.currency,
                        self._name(e.payer_pubkey), splits,
                        e.original_amount or "", e.original_currency or "",
                    ])
            if self._incl_set.get():
                w.writerow([])
                w.writerow(["Typ","Datum","Von","An","Betrag","Währung","Notiz"])
                for s in sorted(self.settlements, key=lambda x: x.display_date()):
                    w.writerow([
                        "Zahlung",
                        time.strftime("%d.%m.%Y", time.localtime(s.display_date())),
                        self._name(s.from_pubkey), self._name(s.to_pubkey),
                        f"{s.amount:.2f}", s.currency, s.note or "",
                    ])
            if self._incl_debt.get():
                from ledger import get_settlements
                w.writerow([])
                w.writerow(["Schuldenübersicht","","","","","",""])
                w.writerow(["Von","An","Betrag","Währung"])
                for debt in get_settlements(self.expenses, self.settlements):
                    w.writerow([self._name(debt.debtor), self._name(debt.creditor),
                                f"{debt.amount:.2f}", self.currency])
        mb.showinfo("Exportiert", "CSV gespeichert:" + path, parent=self)

    def _export_pdf(self):
        import tkinter.filedialog as fd2
        try:
            from fpdf import FPDF
        except ImportError:
            mb.showerror("fpdf2 fehlt",
                         "Bitte installieren:\npip install fpdf2\n\n"
                         "Alternativ: CSV exportieren.", parent=self)
            return

        path = fd2.asksaveasfilename(
            title="PDF speichern", defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), ("Alle", "*.*")], parent=self)
        if not path:
            return

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Titel
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, f"SplitP2P – {self.group_name}", ln=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 6, f"Exportiert am {time.strftime('%d.%m.%Y %H:%M')}  "
                       f"· Währung: {self.currency}", ln=True)
        pdf.ln(4)

        def section(title):
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(30, 158, 117)
            pdf.cell(0, 8, title, ln=True)
            pdf.set_text_color(0, 0, 0)
            pdf.line(pdf.get_x(), pdf.get_y(),
                     pdf.get_x() + pdf.epw, pdf.get_y())
            pdf.ln(2)

        def row(*cells, bold=False, color=(0,0,0)):
            widths = [30, 55, 30, 25, 30, 35]
            pdf.set_font("Helvetica", "B" if bold else "", 8)
            pdf.set_text_color(*color)
            for txt, w in zip(cells, widths):
                pdf.cell(w, 6, str(txt)[:30], border=0)
            pdf.ln()
            pdf.set_text_color(0, 0, 0)

        if self._incl_exp.get() and self.expenses:
            section("Ausgaben")
            row("Datum", "Beschreibung", "Kategorie", "Betrag", "Bezahlt von", "", bold=True,
                color=(80,80,80))
            for e in sorted(self.expenses, key=lambda x: x.display_date()):
                row(
                    time.strftime("%d.%m.%Y", time.localtime(e.display_date())),
                    e.description, e.category,
                    f"{e.amount:.2f} {e.currency}",
                    self._name(e.payer_pubkey), "",
                )
            total = sum(e.amount for e in self.expenses)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 6, f"Gesamt: {total:.2f} {self.currency}", ln=True)
            pdf.ln(4)

        if self._incl_set.get() and self.settlements:
            section("Erfasste Zahlungen")
            row("Datum", "Von", "An", "Betrag", "", "", bold=True, color=(80,80,80))
            for s in sorted(self.settlements, key=lambda x: x.display_date()):
                row(
                    time.strftime("%d.%m.%Y", time.localtime(s.display_date())),
                    self._name(s.from_pubkey), self._name(s.to_pubkey),
                    f"{s.amount:.2f} {s.currency}", s.note or "", "",
                )
            pdf.ln(4)

        if self._incl_debt.get():
            from ledger import get_settlements
            debts = get_settlements(self.expenses, self.settlements)
            section("Offene Schulden")
            if debts:
                for d in debts:
                    row(self._name(d.debtor), "→", self._name(d.creditor),
                        f"{d.amount:.2f} {self.currency}", "", "")
            else:
                pdf.set_font("Helvetica", "", 9)
                pdf.cell(0, 6, "Alle quitt.", ln=True)

        pdf.output(path)
        mb.showinfo("Exportiert", "PDF gespeichert:" + path, parent=self)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("SplitP2P")
        self.configure(bg=BG)
        self.geometry("1020x720")
        self.minsize(760, 520)

        self._db             = None
        self._own_key        = None
        self._own_pubkey     = ""
        self._own_name       = ""
        self._group_name     = ""
        self._group_pw       = ""
        self._group_currency = "EUR"
        self._rates: dict    = {}
        self._network        = None
        # Suche / Filter
        self._search_text    = tk.StringVar()
        self._filter_cat     = tk.StringVar(value='Alle')
        self._filter_member  = tk.StringVar(value='Alle')

        self._build_ui()
        self._init_identity()

    # ── UI ──────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        paned = tk.PanedWindow(self, orient="horizontal",
                               bg=BORDER, sashwidth=1, sashrelief="flat")
        paned.pack(fill="both", expand=True)
        self._build_sidebar(paned)
        self._build_main(paned)

    def _build_header(self):
        hdr = tk.Frame(self, bg=PANEL, height=52)
        hdr.pack(fill="x"); hdr.pack_propagate(False)

        _lbl(hdr, "SplitP2P", fg=GREEN, font=("Segoe UI", 14, "bold"), bg=PANEL).pack(
            side="left", padx=16, pady=12)
        self._group_badge = _lbl(hdr, "", fg=AMBER, font=FONT_BOLD, bg=PANEL)
        self._group_badge.pack(side="left", padx=4)
        self._identity_label = _lbl(hdr, "", fg=FG_DIM, font=FONT_SMALL, bg=PANEL)
        self._identity_label.pack(side="left", padx=4)

        net_f = tk.Frame(hdr, bg=PANEL)
        net_f.pack(side="left", padx=12)
        self._net_dot   = _lbl(net_f, "●", fg=FG_DIM, font=("Segoe UI", 9), bg=PANEL)
        self._net_dot.pack(side="left")
        self._net_label = _lbl(net_f, "offline", fg=FG_DIM, font=FONT_SMALL, bg=PANEL)
        self._net_label.pack(side="left", padx=(3, 0))

        _ghost(hdr, "⚙ Einstellungen", self._open_settings).pack(side="right", padx=8)
        _ghost(hdr, "🔑 Gruppe wechseln", self._switch_group).pack(side="right", padx=4)

    def _build_sidebar(self, paned):
        sb = tk.Frame(paned, bg=PANEL, width=250)
        sb.pack_propagate(False)
        paned.add(sb, minsize=200)

        _lbl(sb, "MITGLIEDER", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14, pady=8).pack(fill="x")
        _div(sb).pack(fill="x")
        self._members_frame = tk.Frame(sb, bg=PANEL)
        self._members_frame.pack(fill="x", padx=12, pady=6)
        _btn(sb, "+ Mitglied", self._add_member, width=20).pack(padx=12, pady=4)

        _div(sb).pack(fill="x", pady=8)
        _lbl(sb, "MEIN SALDO", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14).pack(fill="x")
        self._balance_frame = tk.Frame(sb, bg=PANEL)
        self._balance_frame.pack(fill="x", padx=12, pady=6)

        _div(sb).pack(fill="x", pady=8)

        debt_hdr = tk.Frame(sb, bg=PANEL)
        debt_hdr.pack(fill="x")
        _lbl(debt_hdr, "OFFENE SCHULDEN", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14).pack(side="left")
        _ghost(debt_hdr, "+ Zahlung", self._record_settlement).pack(side="right", padx=6)
        self._debt_frame = tk.Frame(sb, bg=PANEL)
        self._debt_frame.pack(fill="x", padx=12, pady=6)

        _div(sb).pack(fill="x", pady=8)
        _lbl(sb, "WECHSELKURSE", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14).pack(fill="x")
        self._rates_frame = tk.Frame(sb, bg=PANEL)
        self._rates_frame.pack(fill="x", padx=12, pady=4)
        self._rates_age_label = _lbl(sb, "", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14)
        self._rates_age_label.pack(fill="x")
        _btn(sb, "↻ Aktualisieren", self._manual_refresh_rates,
             bg=BORDER, fg=FG_MUTED, font=FONT_SMALL, width=20).pack(padx=12, pady=4)

    def _build_main(self, paned):
        main = tk.Frame(paned, bg=BG)
        paned.add(main, minsize=500)

        toolbar = tk.Frame(main, bg=PANEL)
        toolbar.pack(fill="x")
        _lbl(toolbar, "AUSGABEN & ZAHLUNGEN",
             fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=16, pady=10).pack(side="left")
        _ghost(toolbar, "📊 Charts",  self._open_charts).pack(side="right", padx=4, pady=6)
        _ghost(toolbar, "⬇ Export",   self._open_export).pack(side="right", padx=4, pady=6)
        _ghost(toolbar, "+ Zahlung",  self._record_settlement).pack(side="right", padx=4, pady=6)
        _btn(toolbar,   "+ Ausgabe",  self._add_expense).pack(side="right", padx=8, pady=6)
        _div(main).pack(fill="x")

        # ── Suchzeile ────────────────────────────────────────────
        search_bar = tk.Frame(main, bg=PANEL, pady=5)
        search_bar.pack(fill="x")
        _lbl(search_bar, "🔍", fg=FG_DIM, font=FONT, bg=PANEL, padx=8).pack(side="left")
        tk.Entry(search_bar, textvariable=self._search_text, font=FONT,
                 bg=BORDER, fg=FG, insertbackground=GREEN, relief="flat",
                 bd=4, width=22).pack(side="left", padx=(0, 10))
        self._search_text.trace_add("write", lambda *_: self._apply_filters())

        _lbl(search_bar, "Kategorie:", fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(side="left")
        from models import CATEGORIES
        cat_cb = _combobox(search_bar, self._filter_cat,
                           ["Alle"] + CATEGORIES, width=16)
        cat_cb.pack(side="left", padx=(2, 10))
        self._filter_cat.trace_add("write", lambda *_: self._apply_filters())

        _lbl(search_bar, "Mitglied:", fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(side="left")
        self._member_filter_cb = _combobox(search_bar, self._filter_member, ["Alle"], width=14)
        self._member_filter_cb.pack(side="left", padx=(2, 10))
        self._filter_member.trace_add("write", lambda *_: self._apply_filters())

        _ghost(search_bar, "✕ Zurücksetzen", self._reset_filters).pack(side="left")
        self._result_count = _lbl(search_bar, "", fg=FG_DIM, font=FONT_SMALL, bg=PANEL)
        self._result_count.pack(side="right", padx=10)
        _div(main).pack(fill="x")

        container = tk.Frame(main, bg=BG)
        container.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
        sb2 = tk.Scrollbar(container, orient="vertical", command=self._canvas.yview,
                           bg=PANEL, troughcolor=BG)
        self._canvas.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._event_list = tk.Frame(self._canvas, bg=BG)
        self._win = self._canvas.create_window((0, 0), window=self._event_list, anchor="nw")
        self._event_list.bind("<Configure>", lambda e: self._canvas.configure(
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

    # ── Identität & Gruppe ───────────────────────────────────────────

    @staticmethod
    def _default_paths() -> dict:
        home = os.path.expanduser("~")
        base = os.path.join(home, "AppData", "Local", "SplitP2P") \
               if os.name == "nt" else \
               os.path.join(home, ".local", "share", "SplitP2P")
        return {"db_path": os.path.join(base, "splitp2p.db"),
                "storage_dir": os.path.join(base, "attachments")}

    def _init_identity(self):
        from config_manager import ConfigManager
        from crypto import (generate_private_key, private_key_from_bytes,
                            get_public_key_hex, private_key_to_bytes)
        from storage import init_db, configure_paths

        self._cfg = ConfigManager("SplitP2P", "config.json")

        defaults    = self._default_paths()
        db_path     = self._cfg.get("db_path",     defaults["db_path"])
        storage_dir = self._cfg.get("storage_dir", defaults["storage_dir"])

        if not self._cfg.has_key("db_path"):
            dlg = StorageSetupDialog(self, {"db_path": db_path, "storage_dir": storage_dir})
            if dlg.result:
                db_path     = dlg.result["db_path"]
                storage_dir = dlg.result["storage_dir"]
            self._cfg.set("db_path",     db_path)
            self._cfg.set("storage_dir", storage_dir)
            self._cfg.save()

        configure_paths(db_path, storage_dir)
        self._db = init_db()

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
        groups = self._cfg.get("groups", {})
        last   = self._cfg.get("last_group", "")
        dlg    = GroupSelectDialog(self, groups, last)
        if not dlg.result:
            self.quit(); return
        if dlg.result.get("_removed"):
            groups.pop(dlg.result["_removed"], None)
            self._cfg.set("groups", groups); self._cfg.save()
            self._do_group_select(); return

        self._group_name     = dlg.result["group_name"]
        self._group_pw       = dlg.result["password"]
        self._group_currency = dlg.result["group_currency"]
        groups[self._group_name] = {"password": self._group_pw,
                                    "currency": self._group_currency}
        self._cfg.set("groups", groups)
        self._cfg.set("last_group", self._group_name)
        self._cfg.save()

        self._group_badge.configure(text=f"[{self._group_name}  ·  {self._group_currency}]")
        self._identity_label.configure(text=f"{self._own_name}  ·  {self._own_pubkey[:12]}…")

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
        self._rates    = {}
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

        if not first_run:
            _div(dlg).pack(fill="x", padx=24, pady=(12, 0))
            _lbl(dlg, "SPEICHERORT", fg=GREEN, font=FONT_LARGE).pack(
                anchor="w", pady=(12, 2), padx=24)
            _div(dlg).pack(fill="x", padx=24)
            sfrm = tk.Frame(dlg, bg=BG, padx=24, pady=8)
            sfrm.pack(fill="x")

            def _path_row(lbl_text, var, is_dir=False):
                _lbl(sfrm, lbl_text, fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
                row = tk.Frame(sfrm, bg=BG)
                row.pack(fill="x", pady=(2, 6))
                tk.Entry(row, textvariable=var, font=FONT_MONO, bg=PANEL, fg=FG,
                         insertbackground=GREEN, relief="flat", bd=6).pack(
                    side="left", fill="x", expand=True)
                def pick(v=var, d=is_dir):
                    p = fd.askdirectory(title="Ordner", parent=dlg) if d else \
                        fd.asksaveasfilename(title="Datenbankdatei", parent=dlg,
                            defaultextension=".db",
                            filetypes=[("SQLite", "*.db"), ("Alle", "*.*")],
                            initialfile=os.path.basename(v.get()),
                            initialdir=os.path.dirname(os.path.abspath(v.get())))
                    if p: v.set(p)
                _ghost(row, "…", pick).pack(side="left", padx=(6, 0))

            db_var  = tk.StringVar(value=self._cfg.get("db_path", ""))
            att_var = tk.StringVar(value=self._cfg.get("storage_dir", ""))
            _path_row("DATENBANKDATEI",  db_var)
            _path_row("ANHANG-ORDNER",   att_var, is_dir=True)
            _lbl(sfrm, "⚠  Änderungen wirksam beim nächsten Start. Daten bitte manuell verschieben.",
                 fg=AMBER, font=FONT_SMALL, justify="left", wraplength=340).pack(anchor="w")

        def save():
            n = name_var.get().strip()
            if not n:
                mb.showerror("Fehler", "Name darf nicht leer sein.", parent=dlg); return
            self._own_name = n
            self._cfg.set("display_name", n); self._cfg.save()
            from storage import save_member
            from models import Member
            save_member(self._db, Member(self._own_pubkey, self._own_name))
            self._identity_label.configure(text=f"{self._own_name}  ·  {self._own_pubkey[:12]}…")
            if not first_run:
                new_db  = db_var.get().strip()
                new_att = att_var.get().strip()
                if new_db and new_att:
                    self._cfg.set("db_path",     new_db)
                    self._cfg.set("storage_dir", new_att)
                    self._cfg.save()
            dlg.destroy()
            if first_run: self._do_group_select()
            else: self._refresh()

        btn_row = tk.Frame(dlg, bg=BG, padx=24, pady=16)
        btn_row.pack(fill="x")
        if not first_run:
            _ghost(btn_row, "Abbrechen", dlg.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Speichern", save).pack(side="right")
        dlg.wait_window()

    # ── Wechselkurse ────────────────────────────────────────────────

    def _load_rates_async(self):
        def _work():
            from currency import get_rates, rates_age_str
            self._rates = get_rates(self._db, self._group_currency)
            age = rates_age_str(self._db, self._group_currency)
            self.after(0, lambda: self._update_rates_ui(age))
        threading.Thread(target=_work, daemon=True, name="rates-fetch").start()

    def _manual_refresh_rates(self):
        self._rates_status.configure(text="Kurse werden geholt…", fg=AMBER)
        def _work():
            from currency import force_refresh, rates_age_str, load_rates
            ok = force_refresh(self._db, self._group_currency)
            self._rates = load_rates(self._db, self._group_currency)
            age = rates_age_str(self._db, self._group_currency)
            self.after(0, lambda: self._update_rates_ui(age, force=True, ok=ok))
        threading.Thread(target=_work, daemon=True, name="rates-force").start()

    def _update_rates_ui(self, age_str, force=False, ok=True):
        self._rates_age_label.configure(text=f"Stand: {age_str}")
        if force:
            self._rates_status.configure(
                text=f"✓ Kurse aktualisiert ({age_str})" if ok else "⚠ Online-Abruf fehlgeschlagen",
                fg=GREEN if ok else RED)
        else:
            self._rates_status.configure(text="", fg=FG_DIM)
        self._render_rates_sidebar()

    def _render_rates_sidebar(self):
        for w in self._rates_frame.winfo_children(): w.destroy()
        if not self._rates:
            _lbl(self._rates_frame, "Keine Kurse", fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(anchor="w")
            return
        from currency import convert
        for cur in ["USD", "GBP", "CHF", "JPY", "CNY", "CAD", "SEK"]:
            if cur == self._group_currency or cur not in self._rates: continue
            rate = convert(1.0, cur, self._group_currency, self._rates)
            if rate is None: continue
            row = tk.Frame(self._rates_frame, bg=PANEL)
            row.pack(fill="x", pady=1)
            _lbl(row, f"1 {cur}", fg=FG_MUTED, font=FONT_SMALL, bg=PANEL, width=7, anchor="w").pack(side="left")
            _lbl(row, f"= {rate:.4f} {self._group_currency}", fg=FG, font=FONT_SMALL, bg=PANEL).pack(side="left", padx=4)

    # ── Mitglieder ──────────────────────────────────────────────────

    def _add_member(self):
        dlg = AddMemberDialog(self)
        if not dlg.result: return
        from storage import save_member
        from models import Member
        from crypto import generate_private_key, get_public_key_hex
        pk = dlg.result["pubkey"]
        if not pk:
            pk = get_public_key_hex(generate_private_key())
            mb.showinfo("Key generiert",
                        f"Temporärer Public Key für '{dlg.result['name']}':\n\n{pk}",
                        parent=self)
        m = Member(pubkey=pk, display_name=dlg.result["name"])
        save_member(self._db, m)
        if self._network:
            self._network.publish_member(pk, dlg.result["name"], m.joined_at)
        self._refresh()

    # ── Ausgaben ────────────────────────────────────────────────────

    def _load_expenses(self):
        from storage import load_all_expense_blobs
        from crypto import decrypt_expense
        return [exp for _, blob in load_all_expense_blobs(self._db)
                if (exp := decrypt_expense(blob, self._group_pw)) is not None]

    def _load_settlements(self):
        from storage import load_all_settlement_blobs
        from crypto import decrypt_settlement
        return [s for _, blob in load_all_settlement_blobs(self._db)
                if (s := decrypt_settlement(blob, self._group_pw)) is not None]

    def _save_expense(self, expense):
        from crypto import sign_expense, encrypt_expense
        from storage import save_expense_blob
        expense.signature = sign_expense(expense, self._own_key)
        blob = encrypt_expense(expense, self._group_pw)
        save_expense_blob(self._db, expense.id, blob, expense.timestamp)
        if self._network:
            self._network.publish_expense(expense.id, blob, expense.timestamp)

    def _save_settlement(self, settlement):
        from crypto import sign_settlement, encrypt_settlement
        from storage import save_settlement_blob
        settlement.signature = sign_settlement(settlement, self._own_key)
        blob = encrypt_settlement(settlement, self._group_pw)
        save_settlement_blob(self._db, settlement.id, blob, settlement.timestamp)
        if self._network:
            self._network.publish_settlement(settlement.id, blob, settlement.timestamp)

    def _add_expense(self):
        from storage import load_all_members
        members = load_all_members(self._db)
        if not members:
            mb.showwarning("Keine Mitglieder",
                           "Bitte erst Mitglieder hinzufügen.", parent=self); return
        dlg = ExpenseDialog(self, members, self._own_pubkey,
                            self._group_currency, self._rates)
        if not dlg.result: return
        from models import Expense
        self._save_expense(Expense.create(**dlg.result))
        self._refresh()

    def _edit_expense(self, expense):
        from storage import load_all_members
        dlg = ExpenseDialog(self, load_all_members(self._db),
                            self._own_pubkey, self._group_currency,
                            self._rates, expense)
        if not dlg.result: return
        from models import Expense
        updated = Expense(id=expense.id, timestamp=int(time.time()),
                          signature="", **dlg.result)
        self._save_expense(updated)
        self._refresh()

    def _delete_expense(self, expense):
        if not mb.askyesno("Löschen", f"'{expense.description}' löschen?", parent=self): return
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

    # ── Ausgleichszahlungen ─────────────────────────────────────────

    def _record_settlement(self, prefill: dict = None):
        from storage import load_all_members
        members = load_all_members(self._db)
        if len(members) < 2:
            mb.showwarning("Zu wenige Mitglieder",
                           "Mind. 2 Mitglieder nötig.", parent=self); return
        dlg = SettlementDialog(self, members, self._own_pubkey,
                               self._group_currency, self._rates, prefill)
        if not dlg.result: return
        from models import RecordedSettlement
        self._save_settlement(RecordedSettlement.create(**dlg.result))
        self._refresh()

    def _delete_settlement(self, settlement):
        if not mb.askyesno("Löschen", "Zahlung löschen?", parent=self): return
        from crypto import sign_settlement, encrypt_settlement
        from storage import soft_delete_settlement_blob
        settlement.is_deleted = True
        settlement.timestamp  = int(time.time())
        settlement.signature  = sign_settlement(settlement, self._own_key)
        blob = encrypt_settlement(settlement, self._group_pw)
        soft_delete_settlement_blob(self._db, settlement.id, blob, settlement.timestamp)
        if self._network:
            self._network.publish_settlement(settlement.id, blob, settlement.timestamp)
        self._refresh()

    # ── Refresh / Render ────────────────────────────────────────────

    def _refresh(self):
        from storage import load_all_members
        members     = load_all_members(self._db)
        expenses    = self._load_expenses()
        settlements = self._load_settlements()
        self._render_members(members)
        self._render_balance(expenses, settlements, members)
        self._render_debts(expenses, settlements, members)
        self._render_events(expenses, settlements, members)
        total = sum(e.amount for e in expenses)
        self._total_label.configure(
            text=f"Gesamt: {total:.2f} {self._group_currency}  ·  "
                 f"{len(expenses)} Ausgaben  ·  {len(settlements)} Zahlungen")

    def _render_members(self, members):
        for w in self._members_frame.winfo_children(): w.destroy()
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

    def _render_balance(self, expenses, settlements, members):
        from ledger import compute_balances, balance_summary
        for w in self._balance_frame.winfo_children(): w.destroy()
        balances = compute_balances(expenses, settlements)
        info     = balance_summary(self._own_pubkey, balances)
        net = info["net"]

        if abs(net) < 0.01:
            _lbl(self._balance_frame, "Alles quitt ✓",
                 fg=GREEN, font=FONT_SMALL, bg=PANEL).pack(anchor="w")
            return

        color = GREEN if net > 0 else RED
        sign  = "+" if net > 0 else ""
        _lbl(self._balance_frame, f"{sign}{net:.2f} {self._group_currency}",
             fg=color, font=FONT_BOLD, bg=PANEL).pack(anchor="w")
        _lbl(self._balance_frame,
             "du bekommst noch" if net > 0 else "du schuldest noch",
             fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(anchor="w")

        # Aufschlüsselung pro Person
        pk_to_name = {m.pubkey: m.display_name for m in members}
        for pk, bal in balances.items():
            if pk == self._own_pubkey or abs(bal) < 0.01: continue
            # My net vs this person
            pass  # Detailed per-person breakdown kept in debt section

    def _render_debts(self, expenses, settlements, members):
        from ledger import get_settlements
        for w in self._debt_frame.winfo_children(): w.destroy()
        pk_to_name = {m.pubkey: m.display_name for m in members}
        def name(pk): return pk_to_name.get(pk, pk[:8] + "…")

        sugg = get_settlements(expenses, settlements)
        if not sugg:
            _lbl(self._debt_frame, "Alle quitt ✓",
                 fg=GREEN, font=FONT_SMALL, bg=PANEL).pack(anchor="w"); return

        for s in sugg:
            is_me_d = s.debtor   == self._own_pubkey
            is_me_c = s.creditor == self._own_pubkey
            color = RED if is_me_d else (GREEN if is_me_c else FG_MUTED)
            f = tk.Frame(self._debt_frame, bg=PANEL)
            f.pack(fill="x", pady=2)
            _lbl(f, f"{name(s.debtor)} → {name(s.creditor)}",
                 fg=color, font=FONT_SMALL, bg=PANEL,
                 wraplength=180, justify="left").pack(anchor="w")
            amt_row = tk.Frame(f, bg=PANEL)
            amt_row.pack(fill="x")
            _lbl(amt_row, f"{s.amount:.2f} {self._group_currency}",
                 fg=color, font=FONT_BOLD, bg=PANEL).pack(side="left")
            if is_me_d:
                _ghost(amt_row, "✓ bezahlt",
                       lambda s=s: self._record_settlement(
                           {"from_pubkey": s.debtor, "to_pubkey": s.creditor,
                            "amount": s.amount})).pack(side="left", padx=6)

    def _render_events(self, expenses, settlements, members):
        """Expenses und Settlements – gefiltert – zeitlich sortiert anzeigen."""
        for w in self._event_list.winfo_children(): w.destroy()
        pk_to_name = {m.pubkey: m.display_name for m in members}

        # Mitglied-Dropdown aktualisieren
        names = ["Alle"] + [m.display_name for m in members]
        self._member_filter_cb.configure(values=names)

        # Suchbegriff + Filter auslesen
        query   = self._search_text.get().lower().strip()
        cat_f   = self._filter_cat.get()
        mbr_f   = self._filter_member.get()
        mbr_pk  = next((m.pubkey for m in members if m.display_name == mbr_f), None)

        def matches_expense(e):
            if cat_f and cat_f != "Alle" and e.category != cat_f: return False
            if mbr_pk and mbr_pk != e.payer_pubkey and \
               not any(s.pubkey == mbr_pk for s in e.splits): return False
            if query and query not in e.description.lower() and \
               query not in e.category.lower() and \
               query not in (e.note or "").lower(): return False
            return True

        def matches_settlement(s):
            if cat_f and cat_f != "Alle": return False
            if mbr_pk and s.from_pubkey != mbr_pk and s.to_pubkey != mbr_pk: return False
            if query:
                n_from = pk_to_name.get(s.from_pubkey, "")
                n_to   = pk_to_name.get(s.to_pubkey,   "")
                if query not in (s.note or "").lower() and \
                   query not in n_from.lower() and query not in n_to.lower(): return False
            return True

        events = []
        for e in expenses:
            if matches_expense(e):
                events.append(("expense", e.display_date(), e))
        for s in settlements:
            if matches_settlement(s):
                events.append(("settlement", s.display_date(), s))
        events.sort(key=lambda x: x[1], reverse=True)

        total_all = len(expenses) + len(settlements)
        if total_all > 0:
            self._result_count.configure(
                text=f"{len(events)} von {total_all}" if len(events) < total_all
                     else "")

        if not events:
            msg = "Keine Treffer." if (query or cat_f != "Alle" or mbr_f != "Alle") \
                  else "Noch keine Ausgaben."
            _lbl(self._event_list, msg, fg=FG_DIM, font=FONT).pack(pady=40); return

        for etype, _, obj in events:
            if etype == "expense":
                self._render_expense_row(obj, pk_to_name)
            else:
                self._render_settlement_row(obj, pk_to_name)

    def _render_expense_row(self, exp, pk_to_name):
        def name(pk): return pk_to_name.get(pk, pk[:8] + "…")

        row = tk.Frame(self._event_list, bg=PANEL, padx=16, pady=10)
        row.pack(fill="x", pady=1)

        left = tk.Frame(row, bg=PANEL)
        left.pack(side="left", fill="x", expand=True)

        # Kategorie-Badge + Beschreibung
        top = tk.Frame(left, bg=PANEL)
        top.pack(fill="x")
        _lbl(top, exp.category, fg=FG_DIM, font=FONT_SMALL, bg=PANEL,
             padx=0, pady=0).pack(side="left")
        _lbl(top, "  " + exp.description, fg=FG, font=FONT_BOLD, bg=PANEL).pack(side="left")

        ts_str = time.strftime("%d.%m.%Y", time.localtime(exp.display_date()))
        _lbl(left, f"{name(exp.payer_pubkey)} hat bezahlt  ·  {ts_str}",
             fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(anchor="w")
        splits_txt = "  ".join(f"{name(s.pubkey)}: {s.amount:.2f}€" for s in exp.splits)
        _lbl(left, splits_txt, fg=FG_MUTED, font=FONT_SMALL, bg=PANEL).pack(anchor="w")

        if exp.original_amount and exp.original_currency:
            _lbl(left, f"ursprünglich: {exp.original_amount:.2f} {exp.original_currency}",
                 fg=AMBER, font=FONT_SMALL, bg=PANEL).pack(anchor="w")

        if exp.attachment:
            from storage import attachment_exists
            exists = attachment_exists(exp.attachment.sha256)
            tk.Button(left,
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

        _div(self._event_list).pack(fill="x")

    def _render_settlement_row(self, s, pk_to_name):
        def name(pk): return pk_to_name.get(pk, pk[:8] + "…")

        row = tk.Frame(self._event_list, bg=BG, padx=16, pady=8)
        row.pack(fill="x", pady=1)

        left = tk.Frame(row, bg=BG)
        left.pack(side="left", fill="x", expand=True)

        ts_str = time.strftime("%d.%m.%Y", time.localtime(s.display_date()))
        _lbl(left,
             f"↔  {name(s.from_pubkey)} bezahlte {name(s.to_pubkey)}  ·  {ts_str}",
             fg=PURPLE, font=FONT_BOLD, bg=BG).pack(anchor="w")
        if s.note:
            _lbl(left, s.note, fg=FG_DIM, font=FONT_SMALL, bg=BG).pack(anchor="w")
        if s.original_amount and s.original_currency:
            _lbl(left, f"ursprünglich: {s.original_amount:.2f} {s.original_currency}",
                 fg=AMBER, font=FONT_SMALL, bg=BG).pack(anchor="w")

        right = tk.Frame(row, bg=BG)
        right.pack(side="right")
        _lbl(right, f"{s.amount:.2f} {s.currency}",
             fg=PURPLE, font=FONT_LARGE, bg=BG).pack(anchor="e")
        _ghost(right, "✕", lambda s=s: self._delete_settlement(s)).pack(anchor="e")

        _div(self._event_list).pack(fill="x")

    # ── Netzwerk ────────────────────────────────────────────────────

    def _start_network(self):
        from network import P2PNetwork, NetworkCallbacks

        class _CB(NetworkCallbacks):
            def __init__(self2, app): self2._app = app
            def on_expense_received(self2, eid, blob):
                self2._app.after(0, lambda: self2._app._on_net_expense(eid, blob))
            def on_settlement_received(self2, sid, blob):
                self2._app.after(0, lambda: self2._app._on_net_settlement(sid, blob))
            def on_member_received(self2, pubkey, data):
                self2._app.after(0, lambda: self2._app._on_net_member(pubkey, data))
            def on_peer_connected(self2, pid):
                self2._app.after(0, lambda: self2._app._on_peer_change())
            def on_peer_disconnected(self2, pid):
                self2._app.after(0, lambda: self2._app._on_peer_change())
            def on_status_changed(self2, online, pid):
                self2._app.after(0, lambda: self2._app._on_net_status(online, pid))
            def on_file_received(self2, sha256):
                self2._app.after(0, self2._app._refresh)

        self._network = P2PNetwork(self._group_pw, _CB(self))
        self._network.start_in_thread()

    def _on_net_status(self, online, peer_id):
        if online:
            short = peer_id[:20] + "..." if len(peer_id) > 20 else peer_id
            self._net_dot.configure(fg=GREEN)
            self._net_label.configure(text=f"online  {short}", fg=FG_MUTED)
            # Eigenes Member-Paket senden damit andere uns kennen
            if self._network:
                self._network.publish_member(
                    self._own_pubkey, self._own_name, int(time.time()))
        else:
            self._net_dot.configure(fg=FG_DIM)
            self._net_label.configure(
                text="offline-mode" if peer_id == "offline-mode" else "offline",
                fg=FG_DIM)

    def _on_peer_change(self):
        if not self._network: return
        n = self._network.peer_count
        self._net_label.configure(
            text=f"online  {n} Peer{'s' if n != 1 else ''}" if n else "online  keine Peers")

    def _on_net_expense(self, expense_id, blob):
        from storage import save_expense_blob
        from crypto import decrypt_expense
        exp = decrypt_expense(blob, self._group_pw)
        if exp is None: return
        if not save_expense_blob(self._db, exp.id, blob, exp.timestamp, exp.is_deleted):
            return
        self._refresh()
        if exp.attachment and self._network:
            from storage import attachment_exists
            if not attachment_exists(exp.attachment.sha256):
                self._network.request_file(exp.attachment.sha256)

    def _on_net_settlement(self, settlement_id, blob):
        from storage import save_settlement_blob
        from crypto import decrypt_settlement
        s = decrypt_settlement(blob, self._group_pw)
        if s is None: return
        if save_settlement_blob(self._db, s.id, blob, s.timestamp, s.is_deleted):
            self._refresh()

    def _on_net_member(self, pubkey, data):
        from storage import save_member, get_member
        from models import Member
        existing = get_member(self._db, pubkey)
        new_name = data.get("display_name", "?")
        if not existing or existing.display_name != new_name:
            save_member(self._db, Member(
                pubkey=pubkey,
                display_name=new_name,
                joined_at=data.get("joined_at", int(time.time())),
            ))
            self._refresh()


    # ── Filter-Helfer ────────────────────────────────────────────────

    def _apply_filters(self):
        """Wird bei jeder Änderung der Suchleiste aufgerufen."""
        from storage import load_all_members
        members     = load_all_members(self._db)
        expenses    = self._load_expenses()
        settlements = self._load_settlements()
        self._render_events(expenses, settlements, members)

    def _reset_filters(self):
        self._search_text.set("")
        self._filter_cat.set("Alle")
        self._filter_member.set("Alle")

    # ── Charts ───────────────────────────────────────────────────────

    def _open_charts(self):
        from storage import load_all_members
        members     = load_all_members(self._db)
        expenses    = self._load_expenses()
        settlements = self._load_settlements()
        ChartsWindow(self, expenses, settlements, members,
                     self._group_currency, self._own_pubkey)

    # ── Export ───────────────────────────────────────────────────────

    def _open_export(self):
        from storage import load_all_members
        members     = load_all_members(self._db)
        expenses    = self._load_expenses()
        settlements = self._load_settlements()
        ExportDialog(self, expenses, settlements, members,
                     self._group_currency, self._group_name)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def run():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    run()
