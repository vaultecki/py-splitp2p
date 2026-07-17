"""Full live-app smoke test: constructs the real gui.App (not a bare/mocked
instance) and drives it through identity+group bootstrap, add expense, add
settlement, export, and charts -- exactly the path that several crash bugs
(configure_paths/set_paths, Pubsub._manager, _u() vs sqlite3.Row,
SettlementDialog default collision) were only ever caught on, since none of
those bugs are reachable through App.__new__(App)-bypassed unit tests.

Starts a real P2PNetwork (real mDNS + bootstrap dialing, hits the internet)
and a real currency-rate fetch, so this is excluded from the default `pytest`
run (see addopts in pyproject.toml) and from the pre-push hook. Run it
explicitly before relying on a release:

    pytest -m smoke -s tests/test_smoke_app.py

Uses pytest's tmp_path as a throwaway HOME (via a Path.home patch) so it
never touches the real ~/.config/SplitP2P.
"""

import json
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest

# Import trio *before* Path.home gets patched below: trio's _path.py builds
# its wrapped Path class at import time via `wrapped.__qualname__` on
# pathlib.Path.home. If that import is deferred (as it is in network.py's
# P2P thread) until after Path.home is a mock, it explodes with
# AttributeError: __qualname__. Not a real app bug, just an import-order
# requirement of this test's Path.home patch.
import trio  # noqa: F401

pytestmark = pytest.mark.smoke


def _find_toplevel(root, title_substr):
    for w in root.winfo_children():
        if isinstance(w, tk.Toplevel) and title_substr.lower() in w.title().lower():
            return w
    return None


def test_live_app_end_to_end(tmp_path):
    errors = []

    def record_error(where, exc):
        errors.append(f"{where}: {exc!r}")

    home = tmp_path
    cfg_dir = home / ".config" / "SplitP2P"
    cfg_dir.mkdir(parents=True)
    db_path = home / "data" / "splitp2p.db"
    storage_dir = home / "data" / "attachments"
    db_path.parent.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(
        json.dumps(
            {
                "display_name": "SmokeTestUser",
                "db_path": str(db_path),
                "storage_dir": str(storage_dir),
            }
        )
    )

    class FakeGroupSelectDialog:
        """Bootstrap group selection is unit-tested elsewhere; here we just
        want App() to land in the main window with a fresh group."""

        def __init__(self, parent, groups, last_group):
            import uuid

            self.result = {
                "group_name": "Smoke Test Trip",
                "group_key": b"0" * 32,
                "group_topic": str(uuid.uuid4()),
                "group_currency": "EUR",
            }

    with (
        patch.object(Path, "home", return_value=home),
        patch("gui.GroupSelectDialog", FakeGroupSelectDialog),
    ):
        import gui
        import storage

        app = gui.App()

        def step_add_expense():
            # ExpenseDialog blocks inside wait_window(), so the follow-up
            # step must be scheduled *before* calling it.
            app.after(800, step_fill_expense)
            try:
                app._add_expense()
            except Exception as e:
                record_error("add_expense", e)

        def step_fill_expense():
            try:
                dlg = _find_toplevel(app, "ausgabe")  # ExpenseDialog title is German
                if not dlg:
                    record_error("fill_expense", RuntimeError("ExpenseDialog not found"))
                    app.after(100, step_check_events)
                    return
                dlg._desc.set("Smoke test dinner")
                dlg._amount.set("42.50")
                dlg._save()  # destroy() -> _add_expense() returns -> next after() fires
            except Exception as e:
                record_error("fill_expense", e)
            app.after(300, step_check_events)

        def step_check_events():
            try:
                if not app._event_list.winfo_children():
                    record_error("check_events", RuntimeError("event list is empty"))
                if "1 expenses" not in app._total_label.cget("text"):
                    record_error(
                        "check_events",
                        RuntimeError(f"unexpected total: {app._total_label.cget('text')!r}"),
                    )
            except Exception as e:
                record_error("check_events", e)
            step_add_settlement()

        def step_add_settlement():
            try:
                storage.save_user(
                    app._db,
                    group_id=app._group_id,
                    public_key="b" * 64,
                    name="Bob",
                    timestamp=0,
                    lamport_clock=0,
                    signature="",
                )
            except Exception as e:
                record_error("save_bob", e)
                app.after(100, step_export)
                return
            app.after(300, step_fill_settlement)
            try:
                app._record_settlement()
            except Exception as e:
                record_error("add_settlement", e)

        def step_fill_settlement():
            try:
                dlg = _find_toplevel(app, "zahlung")  # SettlementDialog title is German
                if not dlg:
                    record_error("fill_settlement", RuntimeError("SettlementDialog not found"))
                    app.after(100, step_check_settlement)
                    return
                # Regression: default from/to used to collide whenever the
                # own account's name sorted alphabetically last among
                # members, silently blocking the save.
                if dlg._from_var.get() == dlg._to_var.get():
                    record_error(
                        "fill_settlement",
                        RuntimeError(f"default from == to: {dlg._from_var.get()!r}"),
                    )
                dlg._amount.set("10.00")
                dlg._save()
            except Exception as e:
                record_error("fill_settlement", e)
            app.after(300, step_check_settlement)

        def step_check_settlement():
            try:
                settlements = storage.get_settlements(app._db, app._group_id)
                if len(settlements) != 1:
                    record_error(
                        "check_settlement",
                        RuntimeError(f"expected 1 settlement, got {len(settlements)}"),
                    )
            except Exception as e:
                record_error("check_settlement", e)
            step_export()

        def step_export():
            app.after(300, step_close_export)
            try:
                app._open_export()  # blocks until step_close_export destroys it
            except Exception as e:
                record_error("export", e)

        def step_close_export():
            try:
                dlg = _find_toplevel(app, "export")
                if dlg:
                    dlg.destroy()
                else:
                    record_error("close_export", RuntimeError("Export dialog not found"))
            except Exception as e:
                record_error("close_export", e)
            app.after(200, step_charts)

        def step_charts():
            try:
                app._open_charts()  # not modal, returns immediately
                app.after(500, step_close_charts)
            except Exception as e:
                record_error("charts", e)
                app.after(100, finish)

        def step_close_charts():
            try:
                dlg = _find_toplevel(app, "charts")
                if dlg:
                    dlg.destroy()
                else:
                    record_error("close_charts", RuntimeError("Charts window not found"))
            except Exception as e:
                record_error("close_charts", e)
            app.after(200, finish)

        def finish():
            app.quit()

        app.after(300, step_add_expense)
        app.after(30000, app.quit)  # safety net
        app.mainloop()
        app.destroy()

    assert not errors, "\n".join(errors)
