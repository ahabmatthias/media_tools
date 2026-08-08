"""
UI-Tab: Duplikat-Finder
"""

import asyncio
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from html import escape
from pathlib import Path

from nicegui import app as nicegui_app
from nicegui import ui
from send2trash import send2trash

from app.core.constants import IMAGE_EXTS, VIDEO_EXTS
from app.core.duplicates import find_duplicates
from app.ui import theme
from app.ui.utils import build_ext_filter, validate_folder_path
from app.ui.utils import short_path as _short_path

_executor = ThreadPoolExecutor(max_workers=1)

_PREVIEW_IMAGE_EXTS = IMAGE_EXTS | {".gif", ".webp"}

# Gemountete Static-Routen merken um Duplikate zu vermeiden
_mounted_routes: set[str] = set()


def _static_url(path: str) -> str | None:
    """Gibt eine servierbare URL für lokale Bilddateien zurück."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in _PREVIEW_IMAGE_EXTS:
        return None
    folder = str(p.parent)
    route = f"/preview{hashlib.md5(folder.encode()).hexdigest()[:10]}"
    if route not in _mounted_routes:
        nicegui_app.add_static_files(route, folder)
        _mounted_routes.add(route)
    return f"{route}/{p.name}"


def _file_icon(path: str) -> str:
    """Gibt ein Material-Icon für den Dateityp zurück."""
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXTS:
        return "videocam"
    if ext == ".heic":
        return "photo"
    return "insert_drive_file"


def build(shared: dict):
    """Baut den Duplikat-Finder-Tab – wird innerhalb eines tab_panel aufgerufen."""
    # ── Optionen ───────────────────────────────────────────────────
    with ui.row().classes("items-center gap-4 flex-wrap mt-2 mt-filter-cbs"):
        cb_fotos = ui.checkbox("Fotos", value=True)
        cb_videos = ui.checkbox("Videos", value=True)
        cb_audio = ui.checkbox("Audio", value=False)

    # ── Status + Spinner ───────────────────────────────────────────
    with ui.row().classes("items-center gap-3 mt-2") as status_row:
        spinner = theme.ember_spinner()
        spinner.visible = False
        status_label = ui.label("").classes("mt-hint")
    status_row.visible = False

    progress_bar = ui.linear_progress(value=0, show_value=False).classes("mt-progress")
    progress_bar.visible = False

    results_col = ui.column().classes("w-full gap-4 mt-2")
    results_col.visible = False
    checkboxes: dict = {}

    # ── Scan ───────────────────────────────────────────────────────
    async def do_scan():
        folder = shared["folder"].strip() if shared else ""
        if not folder or not os.path.isdir(folder):
            ui.notify("Bitte einen gültigen Ordner eingeben.", type="negative")
            return
        if not validate_folder_path(folder):
            ui.notify("Ordner liegt außerhalb des Home-Verzeichnisses.", type="negative")
            return

        exts = build_ext_filter(cb_fotos.value, cb_videos.value, cb_audio.value)
        if not exts:
            status_label.set_text("Bitte mindestens einen Dateityp wählen.")
            return

        status_row.visible = True
        spinner.visible = True
        status_label.set_text("Scanne …")
        results_col.clear()
        results_col.visible = False
        checkboxes.clear()
        progress_bar.set_value(0)
        progress_bar.visible = True
        await asyncio.sleep(0)  # flush: Browser erhält spinner + progress sofort

        loop = asyncio.get_running_loop()
        _last_update = [0.0]  # Zeitstempel für Throttle

        async def _update_progress(value: float):
            progress_bar.set_value(value)
            status_label.set_text(f"Scanne … {int(value * 100)} %")

        def progress_cb(done, total):
            import time

            if total > 0:
                now = time.monotonic()
                if now - _last_update[0] < 0.1 and done < total:
                    return  # max. 10 Updates/s, letztes Update immer durchlassen
                _last_update[0] = now
                asyncio.run_coroutine_threadsafe(_update_progress(done / total), loop)

        recursive = shared.get("recursive", True)
        dupes = await loop.run_in_executor(
            _executor,
            lambda: find_duplicates(folder, progress_cb, extensions=exts, recursive=recursive),
        )

        spinner.visible = False
        progress_bar.visible = False

        if not dupes:
            status_label.set_text("Keine Duplikate gefunden.")

            return

        total_files = sum(len(v) for v in dupes.values())
        status_label.set_text(f"{len(dupes)} Duplikat-Gruppe(n) · {total_files} Dateien")

        results_col.visible = True
        with results_col:
            for _group_hash, paths in dupes.items():
                with ui.element("div").classes("mt-dupe-group"):
                    hash_short = _group_hash[:12]
                    ui.html(
                        f'<div class="mt-dupe-header">'
                        f"{len(paths)} Dateien · Hash {hash_short}…"
                        f"</div>"
                    )
                    for path in paths:
                        try:
                            size_kb = Path(path).stat().st_size // 1024
                        except OSError:
                            size_kb = 0
                        url = _static_url(path)
                        with ui.element("div").classes("mt-dupe-row"):
                            with ui.row().classes("items-center gap-3 w-full"):
                                # Vorschau
                                if url:
                                    ui.image(url).classes("w-16 h-16 object-cover rounded").style(
                                        f"border: 1px solid {theme.COLORS['border']};"
                                    )
                                else:
                                    with (
                                        ui.element("div")
                                        .classes(
                                            "w-16 h-16 flex items-center justify-center rounded"
                                        )
                                        .style(
                                            f"background: {theme.COLORS['surface2']};"
                                            f" border: 1px solid {theme.COLORS['border']};"
                                        )
                                    ):
                                        ui.icon(_file_icon(path), size="1.5rem").classes(
                                            f"text-[{theme.COLORS['muted']}]"
                                        )

                                # Info + Checkbox
                                with ui.column().classes("flex-1 gap-0"):
                                    cb = ui.checkbox(Path(path).name)
                                    short = _short_path(path, folder)
                                    ui.html(f'<div class="mt-dupe-path">{escape(short)}</div>')
                                    ui.html(f'<div class="mt-dupe-path">{size_kb} KB</div>')
                                checkboxes[cb] = path

    ui.button("Scannen", on_click=do_scan, icon="search").classes("mt-btn-primary mt-2").props(
        "no-caps"
    )

    ui.separator().classes("mt-4")

    # ── Löschen (in den Papierkorb) ────────────────────────────────
    async def _execute_delete(to_delete: list[str]):
        deleted, errors = 0, []
        for path in to_delete:
            try:
                if os.path.islink(path):
                    errors.append(f"{path}: Symlinks werden nicht gelöscht")
                    continue
                send2trash(path)
                deleted += 1
            except OSError as e:
                errors.append(f"{path}: {e}")

        msg = f"{deleted} Datei(en) in den Papierkorb gelegt."
        if errors:
            msg += f"  {len(errors)} Fehler."
        ui.notify(msg, type="positive" if not errors else "warning")
        await do_scan()

    async def do_delete():
        to_delete = [path for cb, path in checkboxes.items() if cb.value]
        if not to_delete:
            ui.notify("Keine Dateien ausgewählt.", type="warning")
            return

        async def _confirm_and_delete():
            dialog.close()
            await _execute_delete(to_delete)

        with ui.dialog() as dialog, ui.card().classes("mt-card"):
            ui.label(f"{len(to_delete)} Datei(en) in den Papierkorb legen?").classes(
                f"font-semibold text-[{theme.COLORS['text']}]"
            )
            ui.label("Die Dateien können im Papierkorb wiederhergestellt werden.").classes(
                "mt-hint"
            )
            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button("Abbrechen", on_click=dialog.close).classes("mt-btn-ghost").props(
                    "flat no-caps"
                )
                ui.button("In den Papierkorb", on_click=_confirm_and_delete).classes(
                    "mt-btn-danger"
                ).props("flat no-caps")
        dialog.open()

    ui.button(
        "Ausgewählte in den Papierkorb",
        on_click=do_delete,
        icon="delete",
    ).classes("mt-btn-danger mt-2").props("flat no-caps")
    ui.label("Dateien landen im Papierkorb und können wiederhergestellt werden.").classes(
        "mt-hint mt-1"
    )
