# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
GUI - Decentralized expense splitting
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
    Compact date picker with spinboxes for day/month/year.
    get_date() -> Unix timestamp of selected day at 00:00 local time
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
        """Unix timestamp of selected day at 00:00 local time."""
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

class NewGroupDialog(tk.Toplevel):  # _name_var statt _name wegen py3.14
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
        _lbl(self, "NEW GROUP", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(24, 4), **pad)
        _lbl(self,
             "Das gemeinsame Passwort identifiziert die Gruppe im P2P-Netz\n"
             "and encrypts all expenses. Stored once.",
             fg=FG_DIM, font=FONT_SMALL, justify="left").pack(anchor="w", **pad)
        _div(self).pack(fill="x", padx=28, pady=10)
        frm = tk.Frame(self, bg=BG, padx=28)
        frm.pack(fill="x")

        _lbl(frm, "GROUP NAME", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._name_var = tk.StringVar(value=default_name)
        tk.Entry(frm, textvariable=self._name_var, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=GREEN, relief="flat", bd=6).pack(fill="x", pady=(2, 8))

        _lbl(frm, "SHARED GROUP PASSWORD", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._pw = tk.Entry(frm, show="●", font=FONT, bg=PANEL, fg=FG,
                            insertbackground=GREEN, relief="flat", bd=6)
        self._pw.pack(fill="x", pady=(2, 8))

        _lbl(frm, "GROUP CURRENCY", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._currency = tk.StringVar(value="EUR")
        _combobox(frm, self._currency, SUPPORTED_CURRENCIES, width=10).pack(
            anchor="w", pady=(2, 8))

        btn_row = tk.Frame(self, bg=BG, padx=28, pady=20)
        btn_row.pack(fill="x")
        _ghost(btn_row, "Cancel", self.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "CREATE / JOIN", self._confirm).pack(side="right")

    def _confirm(self):
        name = self._name_var.get().strip()
        pw   = self._pw.get().strip()
        if not name:
            mb.showerror("Error", "Group name is required.", parent=self); return
        if len(pw) < 4:
            mb.showerror("Error", "Password must be at least 4 characters.", parent=self); return
        import os as _os
        self.result = {"group_name": name, "password": pw,
                       "group_currency": self._currency.get(),
                       "group_salt": _os.urandom(16)}
        self.destroy()


class GroupSelectDialog(tk.Toplevel):
    def __init__(self, parent, groups: dict, last_group: str):
        super().__init__(parent)
        self.title("Select group")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.groups = groups
        self.result: Optional[dict] = None
        self._build(last_group)
        self.wait_window()

    def _build(self, last_group):
        pad = dict(padx=28)
        _lbl(self, "SELECT GROUP", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(24, 4), **pad)
        _div(self).pack(fill="x", padx=28, pady=10)
        frm = tk.Frame(self, bg=BG, padx=28)
        frm.pack(fill="x")

        if self.groups:
            _lbl(frm, "KNOWN GROUPS", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
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
            _ghost(btn_row, "+ New group", self._new_group).pack(side="left")
            _ghost(btn_row, "Import QR", self._import_qr).pack(side="left", padx=6)
            _ghost(btn_row, "Remove", self._remove_group).pack(side="left", padx=6)
            _btn(btn_row, "OPEN", self._confirm).pack(side="right")
            tk.Frame(self, bg=BG, height=16).pack()
        else:
            self._selected = tk.StringVar(value="")
            _lbl(frm, "No groups yet.", fg=FG_DIM, font=FONT_SMALL).pack(
                anchor="w", pady=(0, 12))
            _btn(frm, "+ Create / join group",
                 self._new_group, width=28).pack(anchor="w", pady=(0, 8))
            _ghost(frm, "📥 Import QR code (join existing group)",
                   self._import_qr).pack(anchor="w", pady=(0, 8))
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

    def _import_qr(self):
        dlg = QRImportDialog(self)
        if not dlg.result: return
        r = dlg.result
        self.groups[r["name"]] = {
            "password": r["pw"],
            "currency": r["currency"],
            "salt":     r["salt"],
        }
        import os as _os
        self.result = {
            "group_name":     r["name"],
            "password":       r["pw"],
            "group_currency": r["currency"],
            "group_salt":     bytes.fromhex(r["salt"]),
        }
        self.destroy()

    def _remove_group(self):
        name = self._selected.get()
        if name and mb.askyesno("Remove",
                                f"Gruppe '{name}' aus der Liste entfernen?\n"
                                "(Daten bleiben erhalten)", parent=self):
            self.groups.pop(name, None)
            self.result = {"_removed": name}
            self.destroy()

    def _confirm(self):
        name = self._selected.get()
        if not name or name not in self.groups:
            mb.showerror("Error", "No group selected.", parent=self); return
        info = self.groups[name]
        self.result = {"group_name": name, "password": info["password"],
                       "group_currency": info.get("currency", "EUR"),
                       "group_salt": None}  # wird in _do_group_select aus Config geladen
        self.destroy()


# ---------------------------------------------------------------------------
# Attachment Viewer
# ---------------------------------------------------------------------------

class AttachmentViewer(tk.Toplevel):
    def __init__(self, parent, sha256: str, filename: str):
        from storage import attachment_path
        path = attachment_path(sha256)
        if not path:
            mb.showerror("Not found",
                         "The file is not available locally.", parent=parent)
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

    @staticmethod
    def _open_ext(path):
        import subprocess, sys
        if sys.platform == "win32": os.startfile(path)
        elif sys.platform == "darwin": subprocess.run(["open", path])
        else: subprocess.run(["xdg-open", path])


# ---------------------------------------------------------------------------
# QR-Code Dialoge: Anzeigen + Importieren
# ---------------------------------------------------------------------------

# QR payload format (JSON, base64-encoded):
# {
#   "v": 1,           # format version for future changes
#   "name": "Trip",   # group name
#   "pw": "pass123",  # password in plaintext (QR code is the key)
#   "salt": "99ca..", # salt as hex (16 bytes = 32 hex chars)
#   "currency": "EUR" # group currency
# }
# Encoded as base64(json) -> compact QR content (~120-160 bytes)

import base64 as _b64


def _encode_group_qr(name: str, password: str, salt: bytes,
                     currency: str) -> str:
    """Encodes group info as a compact base64 JSON string."""
    import json as _json
    payload = _json.dumps({
        "v":        1,
        "name":     name,
        "pw":       password,
        "salt":     salt.hex(),
        "currency": currency,
    }, separators=(",", ":"), ensure_ascii=False)
    return _b64.b64encode(payload.encode()).decode()


def _decode_group_qr(data: str) -> dict:
    """Decodes QR string. Raises ValueError for invalid data."""
    import json as _json
    try:
        # Versuche zuerst base64
        decoded = _b64.b64decode(data.strip()).decode()
    except Exception:
        # Fallback: direkt als JSON
        decoded = data.strip()
    result = _json.loads(decoded)
    if result.get("v") != 1:
        raise ValueError(f"Unbekannte QR-Version: {result.get('v')}")
    for key in ("name", "pw", "salt", "currency"):
        if key not in result:
            raise ValueError(f"Feld '{key}' fehlt im QR-Code")
    # Salt validieren
    bytes.fromhex(result["salt"])
    return result


class QRShowDialog(tk.Toplevel):
    """
    Zeigt den Gruppen-QR-Code an.

    Bevorzugt 'qrcode'-Library fuer ein echtes QR-Bild.
    Fallback: base64-String zum manuellen Kopieren.
    Zweiter Fallback: ASCII-QR im Textfeld.
    """

    def __init__(self, parent, group_name: str, password: str,
                 salt: bytes, currency: str):
        super().__init__(parent)
        self.title(f"QR-Code – {group_name}")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self._payload = _encode_group_qr(group_name, password, salt, currency)
        self._build(group_name, currency)
        self.wait_window()

    def _build(self, group_name: str, currency: str):
        pad = dict(padx=28)
        _lbl(self, "JOIN GROUP", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(20, 2), **pad)
        _lbl(self,
             f"{group_name}  ·  {currency}\n"
             "Scan this QR code to join the group.",
             fg=FG_DIM, font=FONT_SMALL, justify="left").pack(anchor="w", **pad)
        _div(self).pack(fill="x", padx=28, pady=8)

        frm = tk.Frame(self, bg=BG, padx=28)
        frm.pack()

        # Versuche QR-Bild zu rendern
        qr_shown = False

        # Versuch 1: qrcode + Pillow -> tkinter PhotoImage
        try:
            import qrcode
            from PIL import Image, ImageTk
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=6,
                border=3,
            )
            qr.add_data(self._payload)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            img = img.resize((280, 280), Image.NEAREST)
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(frm, image=photo, bg=BG, relief="flat", bd=0)
            lbl.image = photo
            lbl.pack(pady=8)
            qr_shown = True
        except ImportError:
            pass

        # Versuch 2: qrcode ASCII-Art im Textfeld
        if not qr_shown:
            try:
                import qrcode
                qr = qrcode.QRCode(
                    version=None,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=1, border=2,
                )
                qr.add_data(self._payload)
                qr.make(fit=True)
                import io
                f = io.StringIO()
                qr.print_ascii(out=f)
                ascii_qr = f.getvalue()
                txt = tk.Text(frm, bg="white", fg="black",
                              font=("Courier New", 4),
                              width=60, height=40,
                              relief="flat", bd=0,
                              state="normal")
                txt.insert("1.0", ascii_qr)
                txt.configure(state="disabled")
                txt.pack(pady=8)
                qr_shown = True
            except ImportError:
                pass

        if not qr_shown:
            # Kein qrcode installiert -> Hinweis
            _lbl(frm,
                 "pip install qrcode[pil]\nfor QR image display",
                 fg=AMBER, font=FONT_SMALL, bg=BG, justify="center").pack(pady=8)

        # Immer: kopierbarer String als Fallback
        _lbl(frm, "JOIN CODE (copy & share)", fg=FG_DIM,
             font=FONT_SMALL, bg=BG).pack(anchor="w", pady=(8, 2))
        txt_frame = tk.Frame(frm, bg=BORDER, padx=1, pady=1)
        txt_frame.pack(fill="x")
        payload_txt = tk.Text(txt_frame, bg=PANEL, fg=FG,
                              font=FONT_MONO, height=4, wrap="word",
                              relief="flat", bd=4)
        payload_txt.insert("1.0", self._payload)
        payload_txt.configure(state="disabled")
        payload_txt.pack(fill="x")

        btn_row = tk.Frame(self, bg=BG, padx=28, pady=16)
        btn_row.pack(fill="x")

        def _copy():
            self.clipboard_clear()
            self.clipboard_append(self._payload)
            _copy_btn.configure(text="Copied ✓")
            self.after(2000, lambda: _copy_btn.configure(text="Copy to clipboard"))

        _copy_btn = _ghost(btn_row, "Copy to clipboard", _copy)
        _copy_btn.pack(side="left")
        _btn(btn_row, "Close", self.destroy,
             bg=BORDER, fg=FG_MUTED).pack(side="right")


class QRImportDialog(tk.Toplevel):
    """
    QR-Code einer bestehenden Gruppe importieren.

    Drei Eingabewege:
      1. Base64-String einfuegen (immer verfuegbar)
      2. Kamerascan via OpenCV (falls cv2 installiert)
      3. Bild-Datei auswaehlen und mit cv2/zxing dekodieren
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Gruppe per QR-Code beitreten")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.result: dict = None
        self._build()
        self.wait_window()

    def _build(self):
        pad = dict(padx=28)
        _lbl(self, "SCAN QR CODE", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(20, 2), **pad)
        _lbl(self,
             "Paste the group join code, or use camera / file.",
             fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", **pad)
        _div(self).pack(fill="x", padx=28, pady=8)

        frm = tk.Frame(self, bg=BG, padx=28)
        frm.pack(fill="x")

        _lbl(frm, "PASTE JOIN CODE", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._text = tk.Text(frm, bg=PANEL, fg=FG, font=FONT_MONO,
                             height=5, wrap="word",
                             insertbackground=GREEN, relief="flat", bd=6)
        self._text.pack(fill="x", pady=(2, 8))

        # Status-Label
        self._status = _lbl(frm, "", fg=FG_DIM, font=FONT_SMALL, bg=BG)
        self._status.pack(anchor="w")

        btn_row = tk.Frame(self, bg=BG, padx=28, pady=12)
        btn_row.pack(fill="x")

        # Kamera-Scan (nur wenn cv2 verfuegbar)
        try:
            import cv2 as _cv2
            _ghost(btn_row, "📷 Scan camera",
                   self._scan_camera).pack(side="left", padx=(0, 8))
        except ImportError:
            pass

        # Bilddatei
        _ghost(btn_row, "🖼 Choose image", self._scan_file).pack(side="left", padx=(0, 8))
        _ghost(btn_row, "Cancel", self.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Importieren", self._import_text).pack(side="right")

    def _set_status(self, msg: str, color: str = FG_MUTED):
        self._status.configure(text=msg, fg=color)
        self.update_idletasks()

    def _try_decode(self, data: str) -> bool:
        """Dekodiert und validiert den QR-Payload. Gibt True bei Erfolg zurueck."""
        try:
            result = _decode_group_qr(data.strip())
            self._set_status(
                f"✓ Gruppe erkannt: {result['name']} ({result['currency']})",
                GREEN)
            self.result = result
            self.after(600, self.destroy)
            return True
        except Exception as e:
            self._set_status(f"Invalid: {e}", RED)
            return False

    def _import_text(self):
        data = self._text.get("1.0", "end").strip()
        if not data:
            self._set_status("No code entered.", RED); return
        self._try_decode(data)

    def _scan_camera(self):
        """OpenCV-Kamerascan in einem separaten Thread."""
        import threading
        self._set_status("Opening camera...", AMBER)
        threading.Thread(target=self._camera_thread, daemon=True).start()

    def _camera_thread(self):
        try:
            import cv2
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                self.after(0, lambda: self._set_status(
                    "Camera not found.", RED))
                return
            detector = cv2.QRCodeDetector()
            self.after(0, lambda: self._set_status(
                "Camera active - hold QR code in front of camera...", AMBER))
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                data, _, _ = detector.detectAndDecode(frame)
                if data:
                    cap.release()
                    self.after(0, lambda d=data: self._try_decode(d))
                    return
                cv2.imshow("QR-Code scannen (ESC = Abbrechen)", frame)
                if cv2.waitKey(1) & 0xFF == 27:  # ESC
                    break
            cap.release()
            cv2.destroyAllWindows()
            self.after(0, lambda: self._set_status("Scan cancelled.", FG_DIM))
        except Exception as e:
            self.after(0, lambda: self._set_status(f"Camera error: {e}", RED))

    def _scan_file(self):
        """QR-Code aus Bilddatei lesen."""
        path = fd.askopenfilename(
            title="QR-Code-Bild waehlen",
            filetypes=[("Bilder", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                       ("Alle Dateien", "*.*")],
            parent=self)
        if not path: return
        try:
            import cv2
            img = cv2.imread(path)
            if img is None:
                self._set_status("Could not load image.", RED); return
            detector = cv2.QRCodeDetector()
            data, _, _ = detector.detectAndDecode(img)
            if data:
                self._try_decode(data)
            else:
                self._set_status("No QR code found in image.", RED)
        except ImportError:
            self._set_status(
                "cv2 (OpenCV) required for image scanning:\npip install opencv-python",
                AMBER)
        except Exception as e:
            self._set_status(f"Scan error: {e}", RED)


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
        _lbl(self, "STORAGE LOCATION", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(24, 4), **pad)
        _lbl(self,
             "Where should the database and attachments be stored?\n"
             "This can be changed later in settings.",
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
                        filetypes=[("SQLite", "*.db"), ("All", "*.*")],
                        initialfile=os.path.basename(v.get()),
                        initialdir=os.path.dirname(os.path.abspath(v.get())))
                if p: v.set(p)
            _ghost(row, "…", pick).pack(side="left", padx=(6, 0))

        self._db_path = tk.StringVar(value=defaults.get("db_path", ""))
        self._att_dir = tk.StringVar(value=defaults.get("storage_dir", ""))
        path_row("DATABASE FILE (.db)", self._db_path)
        path_row("ATTACHMENT FOLDER", self._att_dir, is_dir=True)

        btn_row = tk.Frame(self, bg=BG, padx=28, pady=20)
        btn_row.pack(fill="x")
        _btn(btn_row, "NEXT", self._confirm).pack(side="right")

    def _confirm(self):
        db_path = self._db_path.get().strip()
        att_dir = self._att_dir.get().strip()
        if not db_path or not att_dir:
            mb.showerror("Error", "Both paths must be specified.", parent=self); return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            os.makedirs(att_dir, exist_ok=True)
        except OSError as e:
            mb.showerror("Error", f"Could not create folder:\n{e}", parent=self); return
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
        _lbl(self, "EDIT EXPENSE" if exp else "NEW EXPENSE",
             fg=GREEN, font=FONT_LARGE).pack(anchor="w", pady=(20, 2), **pad)
        _div(self).pack(fill="x", **pad)

        frm = tk.Frame(self, bg=BG, padx=24, pady=12)
        frm.pack(fill="x")

        # Beschreibung
        _lbl(frm, "DESCRIPTION", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._desc = tk.StringVar(value=exp.description if exp else "")
        tk.Entry(frm, textvariable=self._desc, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=GREEN, relief="flat", bd=6).pack(fill="x", pady=(2, 8))

        # Amount + currency
        _lbl(frm, "AMOUNT", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
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
                    text=f"⚠ rate {ic}->{self.group_currency} not available", fg=RED)

        self._amount.trace_add("write", _update_preview)
        self._input_currency.trace_add("write", _update_preview)
        _update_preview()

        # Datum
        _lbl(frm, "DATE", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        initial_ts = (exp.expense_date or exp.timestamp) if exp else int(time.time())
        self._date_picker = DatePickerFrame(frm, initial_ts=initial_ts, bg=BG)
        self._date_picker.pack(anchor="w", pady=(2, 8))

        # Kategorie
        _lbl(frm, "CATEGORY", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._category = tk.StringVar(value=getattr(exp, "category", "Allgemein") if exp else "Allgemein")
        _combobox(frm, self._category, CATEGORIES, width=24).pack(
            anchor="w", pady=(2, 8))

        # Bezahlt von
        _lbl(frm, "PAID BY", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
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
        _lbl(frm, "SPLIT", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._split_mode = tk.StringVar(value="equal")
        mode_row = tk.Frame(frm, bg=BG)
        mode_row.pack(anchor="w")
        for val, txt in [("equal", "Equal"),
                         ("custom", "Custom"),
                         ("percent", "Percent %")]:
            tk.Radiobutton(mode_row, text=txt, variable=self._split_mode, value=val,
                           bg=BG, fg=FG_MUTED, selectcolor=BG,
                           activebackground=BG, activeforeground=FG,
                           font=FONT_SMALL, command=self._update_splits).pack(
                side="left", padx=(0, 12))

        self._split_frame = tk.Frame(frm, bg=BG)
        self._split_frame.pack(fill="x", pady=4)
        self._member_vars:  dict[str, tk.BooleanVar] = {}
        self._amount_vars:  dict[str, tk.StringVar]  = {}
        self._percent_vars: dict[str, tk.StringVar]  = {}
        self._split_widgets: list = []
        for m in self.members:
            self._member_vars[m.pubkey]  = tk.BooleanVar(value=True)
            self._amount_vars[m.pubkey]  = tk.StringVar(value="")
            self._percent_vars[m.pubkey] = tk.StringVar(value="")
        self._update_splits()

        # Anhang
        _div(frm).pack(fill="x", pady=8)
        _lbl(frm, "ATTACHMENT", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        att_row = tk.Frame(frm, bg=BG)
        att_row.pack(fill="x", pady=(2, 4))
        self._att_label = _lbl(att_row,
            f"📎 {self._existing_att.filename} ({self._existing_att.size_str()})"
            if self._existing_att else "No attachment",
            fg=BLUE if self._existing_att else FG_DIM, font=FONT_SMALL, bg=BG)
        self._att_label.pack(side="left")
        _ghost(att_row, "Choose file", self._pick_file).pack(side="left", padx=8)
        if self._existing_att:
            _ghost(att_row, "Remove", self._remove_att).pack(side="left")

        btn_row = tk.Frame(self, bg=BG, padx=24, pady=16)
        btn_row.pack(fill="x")
        _ghost(btn_row, "Cancel", self.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Save", self._save).pack(side="right")

    def _update_splits(self):
        for w in self._split_widgets: w.destroy()
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
                         insertbackground=GREEN, relief="flat", bd=4, width=10).pack(
                    side="left", padx=6)
                _lbl(row, self.group_currency, fg=FG_DIM, font=FONT_SMALL, bg=BG).pack(side="left")
            elif mode == "percent":
                e = tk.Entry(row, textvariable=self._percent_vars[m.pubkey],
                             font=FONT, bg=PANEL, fg=FG,
                             insertbackground=GREEN, relief="flat", bd=4, width=6)
                e.pack(side="left", padx=6)
                _lbl(row, "%", fg=FG_DIM, font=FONT_SMALL, bg=BG).pack(side="left")
                # Live-Vorschau des absoluten Betrags
                preview = _lbl(row, "", fg=FG_DIM, font=FONT_SMALL, bg=BG)
                preview.pack(side="left", padx=(4, 0))
                def _upd_prev(_, pv=preview, pk=m.pubkey):
                    try:
                        pct = float(self._percent_vars[pk].get().replace(",", "."))
                        raw = float(self._amount.get().replace(",", ".") or "0")
                        ic  = self._input_currency.get()
                        if ic != self.group_currency:
                            from currency import convert
                            raw = convert(raw, ic, self.group_currency,
                                          self.rates) or raw
                        pv.configure(text=f"= {raw * pct / 100:.2f} {self.group_currency}")
                    except ValueError:
                        pv.configure(text="")
                self._percent_vars[m.pubkey].trace_add("write", _upd_prev)
                self._amount.trace_add("write", _upd_prev)

    def _pick_file(self):
        path = fd.askopenfilename(
            title="Choose attachment",
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
        self._att_label.configure(text="No attachment", fg=FG_DIM)

    def _save(self):
        from models import Expense, Attachment, split_equally, split_custom
        from crypto import hash_bytes, mime_type_from_path
        from storage import save_attachment
        from currency import convert

        desc = self._desc.get().strip()
        if not desc:
            mb.showerror("Error", "Description is required.", parent=self); return
        try:
            raw_amount = float(self._amount.get().replace(",", "."))
            if raw_amount <= 0: raise ValueError
        except ValueError:
            mb.showerror("Error", "Invalid amount.", parent=self); return

        input_cur = self._input_currency.get()
        original_amount = original_currency = None
        if input_cur != self.group_currency:
            converted = convert(raw_amount, input_cur, self.group_currency, self.rates)
            if converted is None:
                if not mb.askyesno("Rate missing",
                    f"No rate for {input_cur}->{self.group_currency}.\n"
                    "Use amount unchanged?", parent=self): return
                amount = raw_amount
            else:
                original_amount, original_currency = raw_amount, input_cur
                amount = converted
        else:
            amount = raw_amount

        payer = next((m for m in self.members if m.display_name == self._payer_var.get()), None)
        if not payer:
            mb.showerror("Error", "Zahler nicht gefunden.", parent=self); return

        selected = [m for m in self.members if self._member_vars[m.pubkey].get()]
        if not selected:
            mb.showerror("Error", "Select at least one member.", parent=self); return

        mode = self._split_mode.get()
        if mode == "equal":
            splits = split_equally(amount, [m.pubkey for m in selected])
        elif mode == "percent":
            try:
                pcts = {m.pubkey: float(self._percent_vars[m.pubkey].get().replace(",", "."))
                        for m in selected}
                total_pct = sum(pcts.values())
                if total_pct <= 0:
                    raise ValueError("0%")
                if abs(total_pct - 100) > 0.01:
                    if not mb.askyesno(
                        "Sum != 100%",
                        f"Percentages sum to {total_pct:.1f}%,\n"
                        "not 100%. Split proportionally?",
                        parent=self): return
            except ValueError:
                mb.showerror("Error", "Percentages are invalid.", parent=self); return
            from models import split_by_percent
            splits = split_by_percent(amount, pcts)
        else:
            try:
                custom = {m.pubkey: float(self._amount_vars[m.pubkey].get().replace(",", "."))
                          for m in selected}
            except ValueError:
                mb.showerror("Error", "Individual amounts are invalid.", parent=self); return
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
        _lbl(self, "RECORD PAYMENT", fg=PURPLE, font=FONT_LARGE).pack(
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

        _lbl(frm, "FROM (who paid)", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._from_var = tk.StringVar(value=default_from)
        _combobox(frm, self._from_var, member_names).pack(fill="x", pady=(2, 8))

        _lbl(frm, "TO (who received)", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._to_var = tk.StringVar(value=default_to)
        _combobox(frm, self._to_var, member_names).pack(fill="x", pady=(2, 8))

        # Amount + currency
        _lbl(frm, "AMOUNT", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
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
                    text=f"⚠ rate {ic}->{self.group_currency} not available", fg=RED)

        self._amount.trace_add("write", _preview)
        self._input_currency.trace_add("write", _preview)

        # Datum
        _lbl(frm, "DATE", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._date_picker = DatePickerFrame(frm, initial_ts=int(time.time()), bg=BG)
        self._date_picker.pack(anchor="w", pady=(2, 8))

        # Notiz
        _lbl(frm, "NOTE (optional)", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._note = tk.StringVar()
        tk.Entry(frm, textvariable=self._note, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=PURPLE, relief="flat", bd=6).pack(fill="x", pady=(2, 8))

        btn_row = tk.Frame(self, bg=BG, padx=24, pady=16)
        btn_row.pack(fill="x")
        _ghost(btn_row, "Cancel", self.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Save", self._save, bg=PURPLE).pack(side="right")

    def _save(self):
        from currency import convert
        frm_name = self._from_var.get()
        to_name  = self._to_var.get()
        if frm_name == to_name:
            mb.showerror("Error", "From and To must be different.", parent=self); return

        frm_m = next((m for m in self.members if m.display_name == frm_name), None)
        to_m  = next((m for m in self.members if m.display_name == to_name),  None)
        if not frm_m or not to_m:
            mb.showerror("Error", "Member not found.", parent=self); return

        try:
            raw = float(self._amount.get().replace(",", "."))
            if raw <= 0: raise ValueError
        except ValueError:
            mb.showerror("Error", "Invalid amount.", parent=self); return

        input_cur = self._input_currency.get()
        orig_amount = orig_currency = None
        if input_cur != self.group_currency:
            converted = convert(raw, input_cur, self.group_currency, self.rates)
            if converted is None:
                if not mb.askyesno("Rate missing",
                    f"Kein Kurs {input_cur}->{self.group_currency}.\n"
                    "Use amount unchanged?", parent=self): return
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
        self.title("Add Member")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        self._build()
        self.wait_window()

    def _build(self):
        pad = dict(padx=24)
        _lbl(self, "MEMBER", fg=GREEN, font=FONT_LARGE).pack(anchor="w", pady=(20, 2), **pad)
        _div(self).pack(fill="x", **pad)
        frm = tk.Frame(self, bg=BG, padx=24, pady=12)
        frm.pack(fill="x")
        _lbl(frm, "NAME", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._name_entry = tk.Entry(frm, font=FONT, bg=PANEL, fg=FG,
                                    insertbackground=GREEN, relief="flat", bd=6)
        self._name_entry.pack(fill="x", pady=4)
        _lbl(frm, "PUBLIC KEY (leave empty for temporary key)", fg=FG_DIM, font=FONT_SMALL).pack(
            anchor="w", pady=(8, 0))
        self._pk = tk.Entry(frm, font=FONT_MONO, bg=PANEL, fg=FG_MUTED,
                            insertbackground=GREEN, relief="flat", bd=6)
        self._pk.pack(fill="x", pady=4)
        btn_row = tk.Frame(self, bg=BG, padx=24, pady=16)
        btn_row.pack(fill="x")
        _ghost(btn_row, "Cancel", self.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Add", self._save).pack(side="right")

    def _save(self):
        name = self._name_entry.get().strip()
        if not name:
            mb.showerror("Error", "Name is required.", parent=self); return
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
      3. Cumulative expenses over time (line chart)

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
            _lbl(self, "matplotlib not installed.",
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

        fig = Figure(figsize=(13, 9.5), facecolor=DARK, tight_layout=True)
        fig.patch.set_facecolor(DARK)

        def style_ax(ax, title):
            ax.set_facecolor(PANEL_)
            ax.set_title(title, color=FG_, fontsize=11, pad=8)
            ax.tick_params(colors=DIM_, labelsize=9)
            for spine in ax.spines.values():
                spine.set_edgecolor("#252a36")
            ax.title.set_fontsize(10)

        # ── 1. Ausgaben nach Kategorie ───────────────────────────────
        ax1 = fig.add_subplot(3, 2, 1)
        style_ax(ax1, "Expenses by Category")
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
            ax1.text(0.5, 0.5, "No data", transform=ax1.transAxes,
                     ha="center", va="center", color=DIM_)

        # ── 2. Saldo pro Person ──────────────────────────────────────
        ax2 = fig.add_subplot(3, 2, 2)
        style_ax(ax2, "Balance per Person")
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
            ax2.text(0.5, 0.5, "No data", transform=ax2.transAxes,
                     ha="center", va="center", color=DIM_)

        # -- 3. Cumulative expenses over time ─────────────────────────
        ax3 = fig.add_subplot(3, 1, 2)
        style_ax(ax3, "Cumulative Expenses over Time")
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
            ax3.text(0.5, 0.5, "No data", transform=ax3.transAxes,
                     ha="center", va="center", color=DIM_)

        # ── 4. Saldo-Verlauf pro Person ─────────────────────────────
        ax4 = fig.add_subplot(3, 1, 3)
        style_ax(ax4, "Balance History per Person over Time")
        if expenses:
            import datetime
            from ledger import compute_balances
            # Alle Events (Expenses + Settlements) zeitlich sortieren
            all_events = []
            for e in expenses:
                all_events.append((e.display_date(), "expense", e))
            for s in settlements:
                all_events.append((s.display_date(), "settlement", s))
            all_events.sort(key=lambda x: x[0])
            # Saldo schrittweise berechnen
            running_exp, running_set = [], []
            pk_series = {m.pubkey: [] for m in members}
            ts_series = []
            for ts, etype, obj in all_events:
                if etype == "expense":
                    running_exp.append(obj)
                else:
                    running_set.append(obj)
                bals = compute_balances(running_exp, running_set)
                ts_series.append(datetime.datetime.fromtimestamp(ts))
                for m in members:
                    pk_series[m.pubkey].append(bals.get(m.pubkey, 0.0))
            if ts_series:
                for i, m in enumerate(members):
                    vals = pk_series[m.pubkey]
                    col  = COLS[i % len(COLS)]
                    ax4.plot(ts_series, vals, color=col,
                             linewidth=1.8, label=name(m.pubkey))
                    ax4.fill_between(ts_series, vals, alpha=0.08, color=col)
                ax4.axhline(0, color=DIM_, linewidth=0.8, linestyle="--")
                ax4.set_ylabel(group_currency, color=DIM_, fontsize=9)
                ax4.yaxis.label.set_color(DIM_)
                ax4.legend(facecolor=PANEL_, edgecolor=DIM_,
                           labelcolor=FG_, fontsize=8, loc="best")
                fig.autofmt_xdate(rotation=30, ha="right")
        else:
            ax4.text(0.5, 0.5, "No data", transform=ax4.transAxes,
                     ha="center", va="center", color=DIM_)

        canvas = FigureCanvasTkAgg(fig, master=self)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", pady=6)
        def save_png():
            import tkinter.filedialog as fd2
            path = fd2.asksaveasfilename(
                title="Save charts", defaultextension=".png",
                filetypes=[("PNG", "*.png"), ("All", "*.*")], parent=self)
            if path:
                fig.savefig(path, facecolor=DARK, dpi=150)
                mb.showinfo("Saved", f"Charts gespeichert:\n{path}", parent=self)
        _ghost(btn_row, "Save as PNG", save_png).pack(side="right", padx=12)


# ---------------------------------------------------------------------------
# Export Dialog
# ---------------------------------------------------------------------------

class ExportDialog(tk.Toplevel):
    """
    Exportiert Ausgaben und Zahlungen als CSV oder PDF.
    CSV: stdlib, no extra dependencies.
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

    def _member_name(self, pk):
        return self.pk_to_name.get(pk, pk[:8] + "…")

    def _build(self):
        pad = dict(padx=28)
        _lbl(self, "EXPORT", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(20, 2), **pad)
        _div(self).pack(fill="x", padx=28, pady=8)

        frm = tk.Frame(self, bg=BG, padx=28)
        frm.pack(fill="x")

        _lbl(frm, "CONTENT", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        self._incl_exp  = tk.BooleanVar(value=True)
        self._incl_set  = tk.BooleanVar(value=True)
        self._incl_debt = tk.BooleanVar(value=True)
        for var, txt in [(self._incl_exp,  "Expenses"),
                         (self._incl_set,  "Payments"),
                         (self._incl_debt, "Debt summary")]:
            tk.Checkbutton(frm, text=txt, variable=var, bg=BG, fg=FG,
                           selectcolor=BG, activebackground=BG,
                           activeforeground=FG, font=FONT).pack(anchor="w")

        _div(frm).pack(fill="x", pady=10)
        _lbl(frm, "FORMAT", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")

        btn_row = tk.Frame(frm, bg=BG)
        btn_row.pack(fill="x", pady=6)
        _btn(btn_row, "Export CSV",  self._export_csv,  width=18).pack(
            side="left", padx=(0, 8))
        _btn(btn_row, "Export PDF",  self._export_pdf,
             bg=BLUE, width=18).pack(side="left")

        _lbl(frm, "PDF requires: pip install fpdf2",
             fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", pady=(4, 0))

        tk.Frame(self, bg=BG, height=16).pack()

    def _export_csv(self):
        import csv, tkinter.filedialog as fd2
        path = fd2.asksaveasfilename(
            title="Save CSV", defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All", "*.*")], parent=self)
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if self._incl_exp.get():
                w.writerow(["Type","Date","Description","Category",
                             "Amount","Currency","Paid by","Splits",
                             "Original amount","Original currency"])
                for e in sorted(self.expenses, key=lambda x: x.display_date()):
                    splits = "; ".join(
                        f"{self._member_name(s.pubkey)}:{s.amount:.2f}"
                        for s in e.splits)
                    w.writerow([
                        "Expense",
                        time.strftime("%d.%m.%Y", time.localtime(e.display_date())),
                        e.description, e.category,
                        f"{e.amount:.2f}", e.currency,
                        self._member_name(e.payer_pubkey), splits,
                        e.original_amount or "", e.original_currency or "",
                    ])
            if self._incl_set.get():
                w.writerow([])
                w.writerow(["Type","Date","From","To","Amount","Currency","Note"])
                for s in sorted(self.settlements, key=lambda x: x.display_date()):
                    w.writerow([
                        "Payment",
                        time.strftime("%d.%m.%Y", time.localtime(s.display_date())),
                        self._member_name(s.from_pubkey), self._member_name(s.to_pubkey),
                        f"{s.amount:.2f}", s.currency, s.note or "",
                    ])
            if self._incl_debt.get():
                from ledger import get_settlements
                w.writerow([])
                w.writerow(["Debt summary","","","","","",""])
                w.writerow(["From","To","Amount","Currency","% of total"])
                _total = sum(e.amount for e in self.expenses) or 1
                for debt in get_settlements(self.expenses, self.settlements):
                    pct = debt.amount / _total * 100
                    w.writerow([self._member_name(debt.debtor), self._member_name(debt.creditor),
                                f"{debt.amount:.2f}", self.currency,
                                f"{pct:.1f}%"])
        mb.showinfo("Exported", "CSV saved: " + path, parent=self)

    def _export_pdf(self):
        import tkinter.filedialog as fd2
        try:
            from fpdf import FPDF
        except ImportError:
            mb.showerror("fpdf2 missing",
                         "Please install:\npip install fpdf2\n\n"
                         "Alternative: export CSV.", parent=self)
            return

        path = fd2.asksaveasfilename(
            title="Save PDF", defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), ("All", "*.*")], parent=self)
        if not path:
            return

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Titel
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, f"SplitP2P - {self.group_name}", ln=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 6, f"Exported {time.strftime('%Y-%m-%d %H:%M')}  "
                       f"| Currency: {self.currency}", ln=True)
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
            section("Expenses")
            row("Date", "Description", "Category", "Amount", "Paid by", "% of total", bold=True,
                color=(80,80,80))
            _exp_total = sum(e.amount for e in self.expenses) or 1
            for e in sorted(self.expenses, key=lambda x: x.display_date()):
                pct = e.amount / _exp_total * 100
                row(
                    time.strftime("%d.%m.%Y", time.localtime(e.display_date())),
                    e.description, e.category,
                    f"{e.amount:.2f} {e.currency}",
                    self._member_name(e.payer_pubkey),
                    f"{pct:.1f}%",
                )
            total = sum(e.amount for e in self.expenses)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 6, f"Total: {total:.2f} {self.currency}", ln=True)
            pdf.ln(4)

        if self._incl_set.get() and self.settlements:
            section("Recorded payments")
            row("Date", "From", "To", "Amount", "", "", bold=True, color=(80,80,80))
            for s in sorted(self.settlements, key=lambda x: x.display_date()):
                row(
                    time.strftime("%d.%m.%Y", time.localtime(s.display_date())),
                    self._member_name(s.from_pubkey), self._member_name(s.to_pubkey),
                    f"{s.amount:.2f} {s.currency}", s.note or "", "",
                )
            pdf.ln(4)

        if self._incl_debt.get():
            from ledger import get_settlements, compute_balances
            debts = get_settlements(self.expenses, self.settlements)
            balances = compute_balances(self.expenses, self.settlements)
            _exp_total = sum(e.amount for e in self.expenses) or 1

            # Balance per person with % share of total
            section("Balance per person")
            row("Person", "Net balance", "Paid", "Owes", "% of total", "",
                bold=True, color=(80,80,80))
            for m in self.members:
                paid   = sum(e.amount for e in self.expenses
                             if e.payer_pubkey == m.pubkey and not e.is_deleted)
                owes   = sum(s.amount for e in self.expenses
                             if not e.is_deleted
                             for s in e.splits if s.pubkey == m.pubkey)
                net    = balances.get(m.pubkey, 0.0)
                pct    = paid / _exp_total * 100
                sign   = "+" if net >= 0 else ""
                row(m.display_name,
                    f"{sign}{net:.2f} {self.currency}",
                    f"{paid:.2f}",
                    f"{owes:.2f}",
                    f"{pct:.1f}%", "")
            pdf.ln(4)

            # Open debts
            section("Open debts")
            if debts:
                for d in debts:
                    pct = d.amount / _exp_total * 100
                    row(self._member_name(d.debtor), "->", self._member_name(d.creditor),
                        f"{d.amount:.2f} {self.currency}",
                        f"{pct:.1f}%", "")
            else:
                pdf.set_font("Helvetica", "", 9)
                pdf.cell(0, 6, "All settled.", ln=True)

        pdf.output(path)
        mb.showinfo("Exported", "PDF saved:\n" + path, parent=self)



# ---------------------------------------------------------------------------
# Activity Log Window
# ---------------------------------------------------------------------------

class ActivityLogWindow(tk.Toplevel):
    """
    Shows all group changes in chronological order.

    Quellen:
      1. Persistente Ereignisse  – aus Expenses + Settlements rekonstruiert
         (who added/edited/deleted what and when)
      2. Laufzeit-Ereignisse     – P2P-Sync, Peer-Verbindungen, Dateiempfang
         (current session only, not persisted)

    The window can stay open; new runtime entries are
    added live via append().
    """

    # Color per level
    LEVEL_COLOR = {
        "info":    "#2ecc8f",   # green  - own actions
        "sync":    "#4d9de0",   # blue   - P2P sync
        "net":     "#a78bfa",   # purple - network events
        "warn":    "#e0a03a",   # amber  - warnings
        "recv":    "#5dcaa5",   # teal   - received changes
        "comment": "#e05c6a",   # red    - comments
        "syscmt":  "#ba7517",   # amber  - system/auto comments
    }

    def __init__(self, parent, expenses, settlements, members,
                 runtime_log, group_currency, own_pubkey,
                 db=None, group_pw="", group_salt=b""):
        super().__init__(parent)
        self.title("Activity Log")
        self.configure(bg=BG)
        self.geometry("820x600")
        self.minsize(640, 420)

        self._own_pubkey  = own_pubkey
        self._currency    = group_currency
        self._pk_to_name  = {m.pubkey: m.display_name for m in members}
        self._db          = db
        self._group_pw    = group_pw
        self._group_salt  = group_salt

        self._build_chrome()
        self._populate(expenses, settlements, runtime_log)

    def _member_name(self, pk: str) -> str:
        return self._pk_to_name.get(pk, pk[:10] + "…")

    # ── UI ──────────────────────────────────────────────────────────

    def _build_chrome(self):
        # Header
        hdr = tk.Frame(self, bg=PANEL, height=46)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        _lbl(hdr, "ACTIVITY LOG", fg=GREEN, font=FONT_BOLD, bg=PANEL).pack(
            side="left", padx=14, pady=12)

        # Level filter buttons
        filter_row = tk.Frame(hdr, bg=PANEL)
        filter_row.pack(side="right", padx=8)
        self._filter_var = tk.StringVar(value="all")
        for val, label in [("all",     "All"),
                            ("info",    "Actions"),
                            ("sync",    "Sync"),
                            ("net",     "Network"),
                            ("comment", "Comments")]:
            tk.Radiobutton(
                filter_row, text=label, variable=self._filter_var,
                value=val, command=self._apply_filter,
                bg=PANEL, fg=FG_MUTED, selectcolor=PANEL,
                activebackground=PANEL, activeforeground=FG,
                font=FONT_SMALL,
            ).pack(side="left", padx=4)

        _div(self).pack(fill="x")

        # Search bar
        search_bar = tk.Frame(self, bg=PANEL, pady=5)
        search_bar.pack(fill="x")
        _lbl(search_bar, "🔍", fg=FG_DIM, font=FONT, bg=PANEL, padx=8).pack(side="left")
        self._search_var = tk.StringVar()
        tk.Entry(search_bar, textvariable=self._search_var, font=FONT,
                 bg=BORDER, fg=FG, insertbackground=GREEN,
                 relief="flat", bd=4, width=30).pack(side="left")
        self._search_var.trace_add("write", lambda *_: self._apply_filter())
        self._count_lbl = _lbl(search_bar, "", fg=FG_DIM, font=FONT_SMALL, bg=PANEL)
        self._count_lbl.pack(side="right", padx=10)
        _ghost(search_bar, "✕", self._clear_search).pack(side="right")
        _div(self).pack(fill="x")

        # Scrollable log list
        container = tk.Frame(self, bg=BG)
        container.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(container, orient="vertical", command=self._canvas.yview,
                          bg=PANEL, troughcolor=BG)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._inner = tk.Frame(self._canvas, bg=BG)
        self._win   = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(
            self._win, width=e.width))
        self._canvas.bind_all("<MouseWheel>", lambda e: self._canvas.yview_scroll(
            int(-1*(e.delta/120)), "units"))

        # Status bar
        status = tk.Frame(self, bg=PANEL, height=32)
        status.pack(fill="x", side="bottom")
        status.pack_propagate(False)
        self._status_lbl = _lbl(status, "", fg=FG_DIM, font=FONT_SMALL, bg=PANEL)
        self._status_lbl.pack(side="left", padx=12, pady=6)
        _ghost(status, "Export TXT", self._export_txt).pack(side="right", padx=8)

    # ── Daten aufbereiten ───────────────────────────────────────────

    def _populate(self, expenses, settlements, runtime_log):
        """Combines all entries: persisted + runtime."""
        self._all_entries: list[tuple[int, str, str]] = []  # (ts, level, msg)

        # Reconstruct from expenses
        for e in expenses:
            who = self._member_name(e.payer_pubkey)
            is_own = e.payer_pubkey == self._own_pubkey
            lvl = "info" if is_own else "recv"
            self._all_entries.append((
                e.timestamp, lvl,
                f"Expense {'added' if not e.is_deleted else 'deleted'}: "
                f"'{e.description}'  {e.amount:.2f} {self._currency}  "
                f"[{e.category}]  by {who}",
            ))

        # Reconstruct from settlements
        for s in settlements:
            is_own = s.from_pubkey == self._own_pubkey
            lvl = "info" if is_own else "recv"
            self._all_entries.append((
                s.timestamp, lvl,
                f"Payment recorded: {self._member_name(s.from_pubkey)} -> "
                f"{self._member_name(s.to_pubkey)}  {s.amount:.2f} {self._currency}"
                + ('  "' + s.note + '"' if s.note else ""),
            ))

        # Comments (user + system) from DB
        if self._db is not None:
            try:
                from storage import load_comments_for_expense
                from crypto import decrypt_comment
                # Collect all expense IDs
                exp_map = {e.id: e.description for e in expenses}
                for exp_id, exp_desc in exp_map.items():
                    for _, blob in load_comments_for_expense(self._db, exp_id):
                        c = decrypt_comment(blob, self._group_pw, self._group_salt)
                        if c is None:
                            continue
                        is_own = c.author_pubkey == self._own_pubkey
                        who    = self._pk_to_name.get(
                            c.author_pubkey, c.author_pubkey[:10] + "…")
                        lvl    = "syscmt" if c.kind == "system" else \
                                 ("comment" if is_own else "recv")
                        prefix = f"[{exp_desc[:30]}] "
                        self._all_entries.append((
                            c.timestamp, lvl,
                            prefix + f"{who}: {c.text}",
                        ))
            except Exception as _ce:
                import logging as _log
                _log.getLogger(__name__).debug("Comment load error: %s", _ce)

        # Runtime entries (P2P events of this session)
        for ts, lvl, msg in runtime_log:
            self._all_entries.append((ts, lvl, msg))

        # Sort chronologically (newest first)
        self._all_entries.sort(key=lambda x: x[0], reverse=True)

        self._status_lbl.configure(
            text=f"{len(self._all_entries)} entries total")
        self._render_all()

    def _render_all(self):
        """Re-renders all entries with current filter applied."""
        for w in self._inner.winfo_children():
            w.destroy()

        query  = self._search_var.get().lower().strip()
        level  = self._filter_var.get()

        shown = 0
        for ts, lvl, msg in self._all_entries:
            if level != "all" and lvl != level:
                continue
            if query and query not in msg.lower():
                continue
            self._render_row(ts, lvl, msg)
            shown += 1

        total = len(self._all_entries)
        self._count_lbl.configure(
            text=f"{shown} of {total}" if shown < total else "")

        if shown == 0:
            _lbl(self._inner,
                 "No entries." if total else "No activity yet.",
                 fg=FG_DIM, font=FONT).pack(pady=30)

        # Scroll to top
        self._canvas.update_idletasks()
        self._canvas.yview_moveto(0)

    def _render_row(self, ts: int, level: str, msg: str):
        color  = self.LEVEL_COLOR.get(level, FG_MUTED)
        ts_str = time.strftime("%d.%m.%Y  %H:%M:%S", time.localtime(ts))
        query  = self._search_var.get().lower().strip()

        row = tk.Frame(self._inner, bg=PANEL, padx=12, pady=7)
        row.pack(fill="x", pady=1)

        # Colored level pill
        pill = tk.Frame(row, bg=color, width=4)
        pill.pack(side="left", fill="y", padx=(0, 10))

        content = tk.Frame(row, bg=PANEL)
        content.pack(side="left", fill="x", expand=True)

        # Timestamp + level badge
        meta = tk.Frame(content, bg=PANEL)
        meta.pack(fill="x")
        _lbl(meta, ts_str, fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(side="left")
        # Human-readable level label
        level_label = {
            "info":    "ACTION",
            "recv":    "RECEIVED",
            "sync":    "SYNC",
            "net":     "NETWORK",
            "warn":    "WARN",
            "comment": "COMMENT",
            "syscmt":  "SYSTEM",
        }.get(level, level.upper())
        _lbl(meta, level_label, fg=color, font=FONT_SMALL, bg=PANEL,
             padx=6).pack(side="left")

        # Message text — highlight search matches
        if query and query in msg.lower():
            # Split message around match and render with highlight
            msg_lower = msg.lower()
            idx = msg_lower.find(query)
            before = msg[:idx]
            match  = msg[idx:idx+len(query)]
            after  = msg[idx+len(query):]
            msg_frame = tk.Frame(content, bg=PANEL)
            msg_frame.pack(anchor="w", pady=(2, 0))
            if before:
                _lbl(msg_frame, before, fg=FG, font=FONT_SMALL,
                     bg=PANEL).pack(side="left")
            _lbl(msg_frame, match, fg=BG, font=FONT_BOLD,
                 bg=AMBER).pack(side="left")
            if after:
                _lbl(msg_frame, after, fg=FG, font=FONT_SMALL,
                     bg=PANEL).pack(side="left")
        else:
            _lbl(content, msg, fg=FG, font=FONT_SMALL, bg=PANEL,
                 wraplength=640, justify="left").pack(anchor="w", pady=(2, 0))

        _div(self._inner).pack(fill="x")

    # -- Live update --

    def append(self, ts: int, level: str, msg: str) -> None:
        """Adds a new entry live (thread-safe via Tk.after)."""
        self._all_entries.insert(0, (ts, level, msg))
        if len(self._all_entries) > 500:
            self._all_entries.pop()
        self._status_lbl.configure(
            text=f"{len(self._all_entries)} entries total")
        # Only re-render if no active filter would hide this entry
        query = self._search_var.get().strip()
        flvl  = self._filter_var.get()
        if not query and (flvl == "all" or flvl == level):
            self._render_row(ts, level, msg)

    # -- Filter / search --

    def _apply_filter(self):
        self._render_all()

    def _clear_search(self):
        self._search_var.set("")
        self._filter_var.set("all")

    # -- Export --

    def _export_txt(self):
        path = fd.asksaveasfilename(
            title="Export log", defaultextension=".txt",
            filetypes=[("Text file", "*.txt"), ("All", "*.*")],
            parent=self,
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write("SplitP2P - Activity Log\n")
            f.write(f"Exportiert: {time.strftime('%d.%m.%Y %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")
            for ts, lvl, msg in self._all_entries:
                ts_str = time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(ts))
                f.write(f"[{ts_str}] [{lvl.upper():4s}]  {msg}\n")
        mb.showinfo("Exported", "Log saved:\n" + path, parent=self)


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
        self._group_salt     = b""  # 16 random bytes, stored with group config
        self._group_currency = "EUR"
        self._lamport_clock  = 0    # lokale Lamport-Uhr
        # Ledger-Cache: Salden + Settlements nur neu berechnen wenn noetig
        self._ledger_cache_key = None
        self._cached_balances  = {}
        self._cached_debts     = []
        self._rates: dict    = {}
        self._network        = None
        # Activity log (in-memory, max 500 entries)
        self._log: list[tuple[int,str,str]] = []  # (ts, level, msg)
        self._log_window = None
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

        _ghost(hdr, "⚙ Settings", self._open_settings).pack(side="right", padx=8)
        _ghost(hdr, "🔑 Switch group", self._switch_group).pack(side="right", padx=4)
        _ghost(hdr, "📤 Show QR", self._show_qr).pack(side="right", padx=4)
        _ghost(hdr, "📥 Import QR", self._import_qr).pack(side="right", padx=4)
        _ghost(hdr, "🔗 Connect peer", self._manual_connect).pack(side="right", padx=4)

    def _build_sidebar(self, paned):
        sb = tk.Frame(paned, bg=PANEL, width=250)
        sb.pack_propagate(False)
        paned.add(sb, minsize=200)

        _lbl(sb, "MEMBERS", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14, pady=8).pack(fill="x")
        _div(sb).pack(fill="x")
        self._members_frame = tk.Frame(sb, bg=PANEL)
        self._members_frame.pack(fill="x", padx=12, pady=6)
        _btn(sb, "+ Member", self._add_member, width=20).pack(padx=12, pady=4)

        _div(sb).pack(fill="x", pady=8)
        _lbl(sb, "MY BALANCE", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14).pack(fill="x")
        self._balance_frame = tk.Frame(sb, bg=PANEL)
        self._balance_frame.pack(fill="x", padx=12, pady=6)

        _div(sb).pack(fill="x", pady=8)

        debt_hdr = tk.Frame(sb, bg=PANEL)
        debt_hdr.pack(fill="x")
        _lbl(debt_hdr, "OPEN DEBTS", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14).pack(side="left")
        _ghost(debt_hdr, "+ Payment", self._record_settlement).pack(side="right", padx=6)
        self._debt_frame = tk.Frame(sb, bg=PANEL)
        self._debt_frame.pack(fill="x", padx=12, pady=6)

        _div(sb).pack(fill="x", pady=8)
        _lbl(sb, "EXCHANGE RATES", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14).pack(fill="x")
        self._rates_frame = tk.Frame(sb, bg=PANEL)
        self._rates_frame.pack(fill="x", padx=12, pady=4)
        self._rates_age_label = _lbl(sb, "", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14)
        self._rates_age_label.pack(fill="x")
        _btn(sb, "↻ Refresh", self._manual_refresh_rates,
             bg=BORDER, fg=FG_MUTED, font=FONT_SMALL, width=20).pack(padx=12, pady=4)

        _div(sb).pack(fill="x", pady=8)
        _lbl(sb, "P2P SYNC", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14).pack(fill="x")
        self._sync_label = _lbl(sb, "no sync", fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=14)
        self._sync_label.pack(fill="x")
        _btn(sb, "⟳ Fetch history", self._manual_history_sync,
             bg=BORDER, fg=FG_MUTED, font=FONT_SMALL, width=20).pack(padx=12, pady=4)

    def _build_main(self, paned):
        main = tk.Frame(paned, bg=BG)
        paned.add(main, minsize=500)

        toolbar = tk.Frame(main, bg=PANEL)
        toolbar.pack(fill="x")
        _lbl(toolbar, "EXPENSES & PAYMENTS",
             fg=FG_DIM, font=FONT_SMALL, bg=PANEL, padx=16, pady=10).pack(side="left")
        _ghost(toolbar, "📋 Log",     self._open_log).pack(side="right", padx=4, pady=6)
        _ghost(toolbar, "📊 Charts",  self._open_charts).pack(side="right", padx=4, pady=6)
        _ghost(toolbar, "⬇ Export",   self._open_export).pack(side="right", padx=4, pady=6)
        _ghost(toolbar, "+ Payment",  self._record_settlement).pack(side="right", padx=4, pady=6)
        _btn(toolbar,   "+ Expense",  self._add_expense).pack(side="right", padx=8, pady=6)
        _div(main).pack(fill="x")

        # ── Suchzeile ────────────────────────────────────────────
        search_bar = tk.Frame(main, bg=PANEL, pady=5)
        search_bar.pack(fill="x")
        _lbl(search_bar, "🔍", fg=FG_DIM, font=FONT, bg=PANEL, padx=8).pack(side="left")
        tk.Entry(search_bar, textvariable=self._search_text, font=FONT,
                 bg=BORDER, fg=FG, insertbackground=GREEN, relief="flat",
                 bd=4, width=22).pack(side="left", padx=(0, 10))
        self._search_text.trace_add("write", lambda *_: self._apply_filters())

        _lbl(search_bar, "Category:", fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(side="left")
        from models import CATEGORIES
        cat_cb = _combobox(search_bar, self._filter_cat,
                           ["All"] + CATEGORIES, width=16)
        cat_cb.pack(side="left", padx=(2, 10))
        self._filter_cat.trace_add("write", lambda *_: self._apply_filters())

        _lbl(search_bar, "Member:", fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(side="left")
        self._member_filter_cb = _combobox(search_bar, self._filter_member, ["All"], width=14)
        self._member_filter_cb.pack(side="left", padx=(2, 10))
        self._filter_member.trace_add("write", lambda *_: self._apply_filters())

        _ghost(search_bar, "✕ Reset", self._reset_filters).pack(side="left")
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

    # -- Identity & group --

    def _restore_lamport_clock(self) -> None:
        """
        Loads the highest known Lamport clock from the DB and sets the
        local counter to that value. Called once after a group is opened.

        Without this, after a restart the local clock would start at 0,
        and new entries would have lamport_clock=1 - lower than many
        existing DB entries, causing them to lose every CRDT merge.
        """
        try:
            from storage import get_max_lamport_clock
            stored_max = get_max_lamport_clock()
            if stored_max > self._lamport_clock:
                self._lamport_clock = stored_max
                import logging as _log
                _log.getLogger(__name__).info(
                    "Lamport clock restored from DB: %d", stored_max)
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).warning(
                "Could not restore Lamport clock: %s", e)

    def _next_lamport(self, received: int = 0) -> int:
        """Next Lamport timestamp: local = max(local, received) + 1."""
        self._lamport_clock = max(self._lamport_clock, received) + 1
        return self._lamport_clock

    def _invalidate_cache(self) -> None:
        """Ledger-Cache loeschen. Wird bei jeder Datenaenderung aufgerufen."""
        self._ledger_cache_key = None

    def _get_cached_ledger(
            self,
            expenses: list,
            settlements: list,
    ) -> tuple:
        """
        Gibt (balances, debts) zurueck.
        Berechnet nur neu wenn sich der Cache-Key geaendert hat.
        """
        from ledger import ledger_cache_key, compute_balances, compute_settlements
        key = ledger_cache_key(expenses, settlements)
        if key != self._ledger_cache_key:
            self._cached_balances  = compute_balances(expenses, settlements)
            self._cached_debts     = compute_settlements(self._cached_balances)
            self._ledger_cache_key = key
            # Cache-Miss loggen (nur im Debug-Modus sichtbar)
            import logging as _log
            _log.getLogger(__name__).debug(
                "Ledger cache miss: %d expenses + %d settlements",
                len(expenses), len(settlements))
        return self._cached_balances, self._cached_debts

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
        # Salt: aus result (neue Gruppe) oder aus bestehender Config
        raw_salt = dlg.result.get("group_salt")
        if raw_salt is None:
            # Bestehende Gruppe: salt aus Config laden
            salt_hex = groups.get(self._group_name, {}).get("salt", "")
            raw_salt = bytes.fromhex(salt_hex) if salt_hex else b""
        self._group_salt = raw_salt
        groups[self._group_name] = {"password": self._group_pw,
                                    "currency": self._group_currency,
                                    "salt": self._group_salt.hex()}
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
        # Restore Lamport clock from DB so new entries always
        # have a higher clock than anything already stored.
        self._restore_lamport_clock()
        self._start_network()
        self._refresh()

    def _switch_group(self):
        self.withdraw()
        self._group_pw   = ""
        self._group_salt = b""
        self._rates      = {}
        if self._network:
            self._network.stop()
            self._network = None
        self._net_dot.configure(fg=FG_DIM)
        self._net_label.configure(text="offline")
        self._do_group_select()

    def _show_qr(self):
        """QR-Code der aktuellen Gruppe anzeigen."""
        if not self._group_name or not self._group_pw:
            mb.showinfo("No group",
                        "Please open a group first.", parent=self)
            return
        if not self._group_salt:
            mb.showwarning(
                "No salt",
                "This group has no salt (old group).\n"
                "Please create a new group.", parent=self)
            return
        QRShowDialog(self, self._group_name, self._group_pw,
                     self._group_salt, self._group_currency)

    def _import_qr(self):
        """QR-Code einer anderen Gruppe einlesen."""
        dlg = QRImportDialog(self)
        if not dlg.result: return
        r = dlg.result
        # Gruppe in Config speichern
        groups = self._cfg.get("groups", {})
        groups[r["name"]] = {
            "password": r["pw"],
            "currency": r["currency"],
            "salt":     r["salt"],
        }
        self._cfg.set("groups", groups)
        self._cfg.save()
        mb.showinfo(
            "Group imported",
            f"Gruppe '{r['name']}' wurde importiert.\n"
            "Wechsle zur Gruppe ueber 'Gruppe wechseln'.",
            parent=self)

    def _manual_connect(self):
        """
        Opens a dialog to manually connect to a peer by entering
        their multiaddr or just IP:port.  Useful when mDNS does not
        work (e.g. different subnets, VMs, VPN).

        The peer's listen address is shown in the log at startup:
          INFO network  P2P node started, peer ID: 12D3KooW...
        and can be read from the network status panel.
        """
        if not self._network or not self._network.is_online:
            mb.showinfo("Offline",
                        "Start the network first (needs a group open).",
                        parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.title("Connect to peer")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        pad = dict(padx=24)
        _lbl(dlg, "CONNECT TO PEER", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(20, 2), **pad)
        _lbl(dlg,
             "Enter the peer's multiaddr, IP:port or [IPv6]:port.\n"
             "Example:  /ip4/192.168.1.42/tcp/8000/p2p/12D3KooW...\n"
             "          /ip6/fe80::1/tcp/8000/p2p/12D3KooW...\n"
             "          192.168.1.42:8000  or  [fe80::1%wlan0]:8000",
             fg=FG_DIM, font=FONT_SMALL, justify="left").pack(anchor="w", **pad)
        _div(dlg).pack(fill="x", **pad, pady=6)

        frm = tk.Frame(dlg, bg=BG, padx=24)
        frm.pack(fill="x")
        _lbl(frm, "ADDRESS", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        addr_var = tk.StringVar()
        tk.Entry(frm, textvariable=addr_var, font=FONT_MONO,
                 bg=PANEL, fg=FG, insertbackground=GREEN,
                 relief="flat", bd=6, width=52).pack(fill="x", pady=(2, 4))

        # Show own peer ID + listen addresses for easy sharing
        own_id  = self._network.peer_id or "?"
        _lbl(frm, "YOUR PEER ID (share with the other side)",
             fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", pady=(10, 0))
        pid_frame = tk.Frame(frm, bg=BORDER, padx=1, pady=1)
        pid_frame.pack(fill="x", pady=(2, 4))
        pid_lbl = _lbl(pid_frame, own_id,
                       fg=FG_MUTED, font=FONT_MONO, bg=PANEL,
                       padx=6, pady=4)
        pid_lbl.pack(anchor="w")

        def copy_id():
            dlg.clipboard_clear()
            dlg.clipboard_append(own_id)
        _ghost(frm, "Copy peer ID", copy_id).pack(anchor="w", pady=(0, 8))

        status_lbl = _lbl(frm, "", fg=FG_DIM, font=FONT_SMALL, bg=BG)
        status_lbl.pack(anchor="w", pady=(4, 0))

        def do_connect():
            addr = addr_var.get().strip()
            if not addr:
                mb.showerror("Error", "Address is required.", parent=dlg)
                return
            # Accept plain IP:port, [IPv6]:port or full multiaddr
            if not addr.startswith("/"):
                import re as _re
                m6 = _re.match(r'^\[([0-9a-fA-F:]+(?:%[\w]+)?)\]:(\d+)$',
                               addr)
                m4 = _re.match(r'^([0-9.]+):(\d+)$', addr)
                if m6:
                    addr = f"/ip6/{m6.group(1)}/tcp/{m6.group(2)}"
                elif m4:
                    addr = f"/ip4/{m4.group(1)}/tcp/{m4.group(2)}"
                else:
                    mb.showerror("Error",
                                 "Formats accepted:\n"
                                 "/ip4/x.x.x.x/tcp/port/p2p/PeerID\n"
                                 "/ip6/addr/tcp/port/p2p/PeerID\n"
                                 "192.168.x.x:port  or  [fe80::1]:port",
                                 parent=dlg)
                    return
            status_lbl.configure(text="Connecting...", fg=AMBER)
            dlg.update_idletasks()
            self._network.connect_to_peer(addr)
            self._append_log("net", f"Manual connect: {addr[-50:]}")
            status_lbl.configure(
                text="Connect request sent. Check the log for result.",
                fg=GREEN)

        btn_row = tk.Frame(dlg, bg=BG, padx=24, pady=16)
        btn_row.pack(fill="x")
        _ghost(btn_row, "Close", dlg.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Connect", do_connect).pack(side="right")
        dlg.wait_window()

    def _open_settings(self, first_run=False):
        dlg = tk.Toplevel(self)
        dlg.title("Einstellungen")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        _lbl(dlg, "IDENTITY", fg=GREEN, font=FONT_LARGE).pack(
            anchor="w", pady=(20, 2), padx=24)
        _div(dlg).pack(fill="x", padx=24)
        frm = tk.Frame(dlg, bg=BG, padx=24, pady=12)
        frm.pack(fill="x")
        _lbl(frm, "DISPLAY NAME", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
        name_var = tk.StringVar(value=self._own_name)
        tk.Entry(frm, textvariable=name_var, font=FONT, bg=PANEL, fg=FG,
                 insertbackground=GREEN, relief="flat", bd=6).pack(fill="x", pady=4)
        if self._own_pubkey:
            _lbl(frm, "PUBLIC KEY", fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", pady=(8, 0))
            _lbl(frm, self._own_pubkey, fg=FG_DIM, font=FONT_MONO,
                 wraplength=340, justify="left").pack(anchor="w", pady=2)

        if not first_run:
            _div(dlg).pack(fill="x", padx=24, pady=(12, 0))
            _lbl(dlg, "STORAGE LOCATION", fg=GREEN, font=FONT_LARGE).pack(
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
                            filetypes=[("SQLite", "*.db"), ("All", "*.*")],
                            initialfile=os.path.basename(v.get()),
                            initialdir=os.path.dirname(os.path.abspath(v.get())))
                    if p: v.set(p)
                _ghost(row, "…", pick).pack(side="left", padx=(6, 0))

            db_var  = tk.StringVar(value=self._cfg.get("db_path", ""))
            att_var = tk.StringVar(value=self._cfg.get("storage_dir", ""))
            _path_row("DATABASE FILE",  db_var)
            _path_row("ATTACHMENT FOLDER",   att_var, is_dir=True)
            _lbl(sfrm, "⚠  Changes take effect on next start. Please move data files manually.",
                 fg=AMBER, font=FONT_SMALL, justify="left", wraplength=340).pack(anchor="w")

        def save():
            n = name_var.get().strip()
            if not n:
                mb.showerror("Error", "Name must not be empty.", parent=dlg); return
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
            _ghost(btn_row, "Cancel", dlg.destroy).pack(side="right", padx=(6, 0))
        _btn(btn_row, "Save", save).pack(side="right")
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
        self._rates_status.configure(text="Fetching rates...", fg=AMBER)
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
                text=f"✓ Kurse aktualisiert ({age_str})" if ok else "⚠ Online fetch failed",
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
            mb.showinfo("Key generated",
                        f"Temporary public key for '{dlg.result['name']}':\n\n{pk}",
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
                if (exp := decrypt_expense(blob, self._group_pw, self._group_salt)) is not None]

    def _load_settlements(self):
        from storage import load_all_settlement_blobs
        from crypto import decrypt_settlement
        return [s for _, blob in load_all_settlement_blobs(self._db)
                if (s := decrypt_settlement(blob, self._group_pw, self._group_salt)) is not None]

    def _save_expense(self, expense):
        from crypto import sign_expense, encrypt_expense
        from storage import save_expense_blob
        expense.lamport_clock = self._next_lamport()
        expense.signature = sign_expense(expense, self._own_key)
        blob = encrypt_expense(expense, self._group_pw, self._group_salt)
        save_expense_blob(self._db, expense.id, blob, expense.timestamp,
                          lamport_clock=expense.lamport_clock,
                          author_pubkey=expense.payer_pubkey)
        if self._network:
            self._network.publish_expense(expense.id, blob, expense.timestamp)

    def _save_settlement(self, settlement):
        from crypto import sign_settlement, encrypt_settlement
        from storage import save_settlement_blob
        settlement.lamport_clock = self._next_lamport()
        settlement.signature = sign_settlement(settlement, self._own_key)
        blob = encrypt_settlement(settlement, self._group_pw, self._group_salt)
        save_settlement_blob(self._db, settlement.id, blob, settlement.timestamp,
                             lamport_clock=settlement.lamport_clock,
                             author_pubkey=settlement.from_pubkey)
        if self._network:
            self._network.publish_settlement(settlement.id, blob, settlement.timestamp)

    def _add_expense(self):
        from storage import load_all_members
        members = load_all_members(self._db)
        if not members:
            mb.showwarning("No members",
                           "Please add members first.", parent=self); return
        dlg = ExpenseDialog(self, members, self._own_pubkey,
                            self._group_currency, self._rates)
        if not dlg.result: return
        from models import Expense
        exp = Expense.create(**dlg.result)
        self._save_expense(exp)
        self._append_log('info',
            f"Expense added: '{exp.description}' "
            f"{exp.amount:.2f} {exp.currency}")
        self._refresh()

    def _edit_expense(self, expense):
        # Nur der urspruengliche Eintraeger darf bearbeiten
        if expense.payer_pubkey != self._own_pubkey:
            mb.showerror(
                "Permission denied",
                "Only the original creator can edit this expense.",
                parent=self)
            return
        from storage import load_all_members
        dlg = ExpenseDialog(self, load_all_members(self._db),
                            self._own_pubkey, self._group_currency,
                            self._rates, expense)
        if not dlg.result: return
        from models import Expense
        # payer_pubkey bleibt unveraenderlich – er ist Teil der Signatur.
        # Wer den Public Key nicht hat, kann keinen gueltigen Edit signieren.
        result = dlg.result
        result['payer_pubkey'] = expense.payer_pubkey
        updated = Expense(id=expense.id, timestamp=int(time.time()),
                          signature="", **result)
        self._save_expense(updated)
        self._append_log('info',
            f"Expense edited: '{updated.description}' "
            f"{updated.amount:.2f} {updated.currency}")
        self._refresh()

    def _delete_expense(self, expense):
        if expense.payer_pubkey != self._own_pubkey:
            mb.showerror(
                "Permission denied",
                "Only the original creator can delete this expense.",
                parent=self)
            return
        if not mb.askyesno("Delete", f"Delete '{expense.description}'?", parent=self): return
        from crypto import sign_expense, encrypt_expense
        from storage import soft_delete_expense_blob
        expense.is_deleted = True
        expense.timestamp  = int(time.time())
        expense.signature  = sign_expense(expense, self._own_key)
        blob = encrypt_expense(expense, self._group_pw, self._group_salt)
        soft_delete_expense_blob(self._db, expense.id, blob, expense.timestamp)
        if self._network:
            self._network.publish_expense(expense.id, blob, expense.timestamp)
        self._append_log('info', f"Expense deleted: '{expense.description}'")
        self._post_system_comment(expense.id,
            f"Expense deleted by {self._own_name}")
        self._refresh()

    # ── Ausgleichszahlungen ─────────────────────────────────────────

    def _record_settlement(self, prefill: dict = None):
        from storage import load_all_members
        members = load_all_members(self._db)
        if len(members) < 2:
            mb.showwarning("Too few members",
                           "At least 2 members required.", parent=self); return
        dlg = SettlementDialog(self, members, self._own_pubkey,
                               self._group_currency, self._rates, prefill)
        if not dlg.result: return
        from models import RecordedSettlement
        rs = RecordedSettlement.create(**dlg.result)
        self._save_settlement(rs)
        from storage import load_all_members
        _m = {m.pubkey: m.display_name for m in load_all_members(self._db)}
        self._append_log('info',
            f"Payment recorded: {_m.get(rs.from_pubkey, rs.from_pubkey[:8])} "
            f"-> {_m.get(rs.to_pubkey, rs.to_pubkey[:8])} "
            f"{rs.amount:.2f} {rs.currency}")
        self._refresh()

    def _delete_settlement(self, settlement):
        if not mb.askyesno("Delete", "Delete payment?", parent=self): return
        from crypto import sign_settlement, encrypt_settlement
        from storage import soft_delete_settlement_blob
        settlement.is_deleted = True
        settlement.timestamp  = int(time.time())
        settlement.signature  = sign_settlement(settlement, self._own_key)
        blob = encrypt_settlement(settlement, self._group_pw, self._group_salt)
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
            _lbl(self._members_frame, "No members yet",
                 fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(anchor="w"); return
        for m in members:
            row = tk.Frame(self._members_frame, bg=PANEL)
            row.pack(fill="x", pady=1)
            _lbl(row, "●", fg=GREEN if m.pubkey == self._own_pubkey else FG_DIM,
                 font=("Segoe UI", 8), bg=PANEL).pack(side="left")
            _lbl(row, m.display_name, fg=FG, font=FONT_SMALL, bg=PANEL).pack(side="left", padx=4)
            if m.pubkey == self._own_pubkey:
                _lbl(row, "(you)", fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(side="left")

    def _render_balance(self, expenses, settlements, members):
        from ledger import balance_summary
        for w in self._balance_frame.winfo_children(): w.destroy()
        balances, _ = self._get_cached_ledger(expenses, settlements)
        info        = balance_summary(self._own_pubkey, balances)
        net = info["net"]

        if abs(net) < 0.01:
            _lbl(self._balance_frame, "All settled ✓",
                 fg=GREEN, font=FONT_SMALL, bg=PANEL).pack(anchor="w")
            return

        color = GREEN if net > 0 else RED
        sign  = "+" if net > 0 else ""
        _lbl(self._balance_frame, f"{sign}{net:.2f} {self._group_currency}",
             fg=color, font=FONT_BOLD, bg=PANEL).pack(anchor="w")
        _lbl(self._balance_frame,
             "you are owed" if net > 0 else "you owe",
             fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(anchor="w")

        # Breakdown per person
        pk_to_name = {m.pubkey: m.display_name for m in members}
        for pk, bal in balances.items():
            if pk == self._own_pubkey or abs(bal) < 0.01: continue
            # My net vs this person
            pass  # Detailed per-person breakdown kept in debt section

    def _render_debts(self, expenses, settlements, members):
        for w in self._debt_frame.winfo_children(): w.destroy()
        pk_to_name = {m.pubkey: m.display_name for m in members}
        def name(pk): return pk_to_name.get(pk, pk[:8] + "…")

        _, sugg = self._get_cached_ledger(expenses, settlements)
        if not sugg:
            _lbl(self._debt_frame, "All settled ✓",
                 fg=GREEN, font=FONT_SMALL, bg=PANEL).pack(anchor="w"); return

        for s in sugg:
            is_me_d = s.debtor   == self._own_pubkey
            is_me_c = s.creditor == self._own_pubkey
            color = RED if is_me_d else (GREEN if is_me_c else FG_MUTED)
            f = tk.Frame(self._debt_frame, bg=PANEL)
            f.pack(fill="x", pady=2)
            _lbl(f, f"{name(s.debtor)} -> {name(s.creditor)}",
                 fg=color, font=FONT_SMALL, bg=PANEL,
                 wraplength=180, justify="left").pack(anchor="w")
            amt_row = tk.Frame(f, bg=PANEL)
            amt_row.pack(fill="x")
            _lbl(amt_row, f"{s.amount:.2f} {self._group_currency}",
                 fg=color, font=FONT_BOLD, bg=PANEL).pack(side="left")
            if is_me_d:
                _ghost(amt_row, "✓ paid",
                       lambda s=s: self._record_settlement(
                           {"from_pubkey": s.debtor, "to_pubkey": s.creditor,
                            "amount": s.amount})).pack(side="left", padx=6)

    def _render_events(self, expenses, settlements, members):
        """Expenses und Settlements – gefiltert – zeitlich sortiert anzeigen."""
        for w in self._event_list.winfo_children(): w.destroy()
        pk_to_name = {m.pubkey: m.display_name for m in members}

        # Mitglied-Dropdown aktualisieren
        names = ["All"] + [m.display_name for m in members]
        self._member_filter_cb.configure(values=names)

        # Suchbegriff + Filter auslesen
        query   = self._search_text.get().lower().strip()
        cat_f   = self._filter_cat.get()
        mbr_f   = self._filter_member.get()
        mbr_pk  = next((m.pubkey for m in members if m.display_name == mbr_f), None)

        def matches_expense(e):
            if cat_f and cat_f != "All" and e.category != cat_f: return False
            if mbr_pk and mbr_pk != e.payer_pubkey and \
               not any(s.pubkey == mbr_pk for s in e.splits): return False
            if query and query not in e.description.lower() and \
               query not in e.category.lower() and \
               query not in (e.note or "").lower(): return False
            return True

        def matches_settlement(s):
            if cat_f and cat_f != "All": return False
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
                text=f"{len(events)} of {total_all}" if len(events) < total_all
                     else "")

        if not events:
            msg = "No results." if (query or cat_f != "All" or mbr_f != "All") \
                  else "No expenses yet."
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
            _lbl(left, f"originally: {exp.original_amount:.2f} {exp.original_currency}",
                 fg=AMBER, font=FONT_SMALL, bg=PANEL).pack(anchor="w")

        if exp.attachment:
            from storage import attachment_exists
            sha    = exp.attachment.sha256
            exists = attachment_exists(sha)
            # If file is missing and not already being downloaded: retry.
            # _pending_downloads tracks active requests to avoid
            # re-queuing on every _refresh() tick.
            if (not exists
                    and self._network
                    and getattr(self._network, "_peers", None)
                    and sha not in self._pending_downloads):
                self._pending_downloads.add(sha)
                self._network.request_file(sha)
                import logging as _lg
                _lg.getLogger(__name__).debug(
                    "Re-requesting missing attachment %s", sha[:12])
            tk.Button(left,
                text=f"📎 {exp.attachment.filename} ({exp.attachment.size_str()})"
                     + ("" if exists else "  ⚠ missing locally"),
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
        else:
            # Nur lesend: kein Edit/Delete fuer fremde Ausgaben
            _lbl(btn_r, "(read only)", fg=FG_DIM, font=FONT_SMALL, bg=PANEL).pack(side="left", padx=4)

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
            _lbl(left, f"originally: {s.original_amount:.2f} {s.original_currency}",
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
                name = data.get("display_name","?")
                self2._app.after(0, lambda: self2._app._append_log(
                    "sync", f"Mitglied empfangen: {name} ({pubkey[:12]}…)"))
            def on_peer_connected(self2, pid):
                # Clear pending downloads so missing attachments
                # are retried now that we have a new peer to ask
                self2._app._pending_downloads.clear()
                self2._app.after(0, lambda: self2._app._on_peer_change())
                self2._app.after(0, lambda: self2._app._append_log(
                    "net", f"Peer connected: {pid[:20]}..."))
            def on_peer_disconnected(self2, pid):
                self2._app.after(0, lambda: self2._app._on_peer_change())
                self2._app.after(0, lambda: self2._app._append_log(
                    "net", f"Peer getrennt: {pid[:20]}…"))
            def on_status_changed(self2, online, pid):
                self2._app.after(0, lambda: self2._app._on_net_status(online, pid))
                self2._app.after(0, lambda: self2._app._append_log(
                    "net", f"Status: {'online' if online else 'offline'}"
                           + (f"  id={pid[:16]}…" if online else "")))
            def on_file_received(self2, sha256):
                self2._app.after(0, self2._app._refresh)
                self2._app.after(0, lambda: self2._app._append_log(
                    "sync", f"Datei empfangen: {sha256[:16]}…"))
            def on_history_synced(self2, n_exp, n_set):
                if n_exp + n_set > 0:
                    self2._app.after(0, lambda: self2._app._on_history_synced(
                        n_exp, n_set))
                self2._app.after(0, lambda: self2._app._append_log(
                    "sync", f"History-Sync: +{n_exp} Ausgaben, +{n_set} Zahlungen"))

        self._network = P2PNetwork(self._group_pw, _CB(self))
        self._network.set_group_salt(self._group_salt)
        self._network.set_own_identity(
            self._own_pubkey, self._own_name, int(time.time()))
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
            text=f"online  {n} peer{'s' if n != 1 else ''}" if n else "online  no peers")

    def _on_net_expense(self, expense_id, blob):
        from storage import save_expense_blob, delete_attachment_if_unreferenced
        from crypto import decrypt_expense
        exp = decrypt_expense(blob, self._group_pw, self._group_salt)
        if exp is None: return
        self._next_lamport(exp.lamport_clock)
        if not save_expense_blob(
            self._db, exp.id, blob, exp.timestamp, exp.is_deleted,
            lamport_clock=exp.lamport_clock,
            author_pubkey=exp.payer_pubkey,
        ):
            return
        if exp.is_deleted:
            # Tombstone empfangen: Anhang loeschen falls unreferenziert.
            # Tombstone-Eintrag in DB bleibt fuer weitere Sync-Partner erhalten.
            if exp.attachment:
                deleted = delete_attachment_if_unreferenced(
                    self._db, exp.attachment.sha256)
                if deleted:
                    self._append_log(
                        'sync',
                        f"Attachment deleted via sync: {exp.attachment.filename}")
        elif exp.attachment:
            # Neue/aktualisierte Ausgabe: fehlenden Anhang vom Peer anfordern.
            from storage import attachment_exists
            if not attachment_exists(exp.attachment.sha256) and self._network:
                self._network.request_file(exp.attachment.sha256)
        self._refresh()

    def _on_net_settlement(self, settlement_id, blob):
        from storage import save_settlement_blob
        from crypto import decrypt_settlement
        s = decrypt_settlement(blob, self._group_pw, self._group_salt)
        if s is None: return
        self._next_lamport(s.lamport_clock)
        if save_settlement_blob(
            self._db, s.id, blob, s.timestamp, s.is_deleted,
            lamport_clock=s.lamport_clock,
            author_pubkey=s.from_pubkey,
        ):
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


    # -- Activity log --

    def _append_log(self, level: str, msg: str) -> None:
        """
        Appends an entry to the in-memory log.
        level: 'info' | 'sync' | 'net' | 'warn'
        Aktualisiert das Log-Fenster falls es offen ist.
        """
        import time as _t
        self._log.append((int(_t.time()), level, msg))
        if len(self._log) > 500:
            self._log.pop(0)
        if self._log_window and self._log_window.winfo_exists():
            self._log_window.append(int(_t.time()), level, msg)

    def _open_log(self) -> None:
        """Opens the log window (or brings it to front)."""
        from storage import load_all_members
        members     = load_all_members(self._db)
        expenses    = self._load_expenses()
        settlements = self._load_settlements()
        if self._log_window and self._log_window.winfo_exists():
            self._log_window.lift()
            self._log_window.focus_force()
            return
        self._log_window = ActivityLogWindow(
            self,
            expenses=expenses,
            settlements=settlements,
            members=members,
            runtime_log=list(self._log),
            group_currency=self._group_currency,
            own_pubkey=self._own_pubkey,
            db=self._db,
            group_pw=self._group_pw,
            group_salt=self._group_salt,
        )

    # ── P2P History-Sync ─────────────────────────────────────────────

    def _on_history_synced(self, n_exp: int, n_set: int) -> None:
        import time as _t
        ts  = _t.strftime("%H:%M")
        msg = f"Sync {ts}: +{n_exp} expenses, +{n_set} payments"
        self._sync_label.configure(text=msg, fg=GREEN)
        self._refresh()
        # Reset status after 8s
        self.after(8000, lambda: self._sync_label.configure(
            text="last sync: " + ts, fg=FG_DIM))

    def _manual_history_sync(self) -> None:
        if not self._network or not self._network.is_online:
            mb.showinfo("Offline", "No P2P network connected.", parent=self)
            return
        self._sync_label.configure(text="Syncing...", fg=AMBER)
        self._network.request_history_from_all()

    # ── Filter-Helfer ────────────────────────────────────────────────

    def _apply_filters(self):
        """Called on every search bar change."""
        from storage import load_all_members
        members     = load_all_members(self._db)
        expenses    = self._load_expenses()
        settlements = self._load_settlements()
        self._render_events(expenses, settlements, members)

    def _reset_filters(self):
        self._search_text.set("")
        self._filter_cat.set("All")
        self._filter_member.set("All")

    # ── Charts ───────────────────────────────────────────────────────

    def _open_charts(self):
        from storage import load_all_members
        members     = load_all_members(self._db)
        expenses    = self._load_expenses()
        settlements = self._load_settlements()
        ChartsWindow(self, expenses, settlements, members,
                     self._group_currency, self._own_pubkey)

    # -- Export --─

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
