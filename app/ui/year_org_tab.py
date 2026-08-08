"""
UI-Tab: Jahr-Organisation
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from html import escape

from nicegui import ui

from app.ui import theme
from app.ui.utils import build_ext_filter, validate_folder_path

_executor = ThreadPoolExecutor(max_workers=1)


def build(shared: dict):
    """Baut den Jahr-Organisations-Tab – wird innerhalb eines tab_panel aufgerufen."""
    # ── Optionen ────────────────────────────────────────────────────
    with ui.row().classes("items-center gap-4 flex-wrap mt-2 mt-filter-cbs"):
        cb_fotos = ui.checkbox("Fotos", value=True)
        cb_videos = ui.checkbox("Videos", value=True)
    with ui.row().classes("items-center gap-2 mt-1"):
        camera_checkbox = ui.checkbox("Zusätzlich nach Kamera ordnen")
        ui.icon("info_outline").classes(
            f"text-[{theme.COLORS['accent']}] text-sm cursor-default"
        ).tooltip(
            "Kamera-Erkennung liest EXIF Make/Model aus den Dateien. "
            "Dateien ohne EXIF landen im Ordner 'Sonstige'."
        )

    # ── Status + Spinner ───────────────────────────────────────────
    with ui.row().classes("items-center gap-3 mt-2") as status_row:
        spinner = theme.ember_spinner()
        spinner.visible = False
        status_label = ui.label("").classes("mt-hint")
    status_row.visible = False

    progress_bar = ui.linear_progress(value=0, show_value=False).classes("mt-progress")
    progress_bar.visible = False

    # ── Pills-Zeile ───────────────────────────────────────────────
    pills_row = ui.row().classes("items-center gap-2 mt-1")
    pills_row.visible = False

    preview_col = ui.column().classes("w-full gap-0 mt-2")
    preview_col.visible = False
    _state: dict = {"scan": None, "folder": None, "extensions": None}

    def _show_pills(years: int, invalid: int, conflicts: int):
        pills_row.clear()
        pills_row.visible = True
        with pills_row:
            if years:
                theme.pill(f"{years} Jahre", "info")
            if invalid:
                theme.pill(f"{invalid} ungültig", "neutral")
            if conflicts:
                theme.pill(f"{conflicts} Konflikte", "danger")

    # ── Vorschau ───────────────────────────────────────────────────
    async def do_preview():
        folder = shared["folder"].strip() if shared else ""
        if not folder:
            ui.notify("Bitte einen Ordner eingeben.", type="negative")
            return
        if not os.path.isdir(folder):
            ui.notify("Ordner nicht gefunden.", type="negative")
            return
        if not validate_folder_path(folder):
            ui.notify("Ordner liegt außerhalb des Home-Verzeichnisses.", type="negative")
            return

        exts = build_ext_filter(cb_fotos.value, cb_videos.value)
        if not exts:
            status_label.set_text("Bitte mindestens einen Dateityp wählen.")
            return

        group_by_camera = camera_checkbox.value

        status_row.visible = True
        spinner.visible = True
        status_label.set_text("Scanne …")
        preview_col.clear()
        preview_col.visible = False
        pills_row.visible = False
        _state["scan"] = None
        _state["folder"] = None
        _state["extensions"] = None
        btn_execute.disable()
        progress_bar.set_value(0)
        progress_bar.visible = True
        await asyncio.sleep(0)

        from app.core.year_org import scan_folder  # noqa: PLC0415

        loop = asyncio.get_running_loop()
        _last_scan = [0.0]

        async def _update_scan_progress(value: float):
            progress_bar.set_value(value)
            status_label.set_text(f"Scanne … {int(value * 100)} %")

        def scan_progress_cb(done, total):
            import time

            if total > 0:
                now = time.monotonic()
                if now - _last_scan[0] < 0.1 and done < total:
                    return
                _last_scan[0] = now
                asyncio.run_coroutine_threadsafe(_update_scan_progress(done / total), loop)

        recursive = shared.get("recursive", True)
        result = await loop.run_in_executor(
            _executor,
            lambda: scan_folder(
                folder,
                group_by_camera,
                extensions=exts,
                progress_cb=scan_progress_cb,
                recursive=recursive,
            ),
        )

        spinner.visible = False
        progress_bar.visible = False

        if not result["files_by_year"]:
            status_label.set_text("Keine Dateien mit erkennbarem Jahr gefunden.")

            return

        _state["scan"] = result
        _state["folder"] = folder
        _state["extensions"] = exts

        status_label.set_text(f"{result['total_files']} Dateien gefunden")
        _show_pills(
            len(result["files_by_year"]),
            len(result["invalid_files"]),
            len(result["conflicts"]),
        )

        preview_col.visible = True
        with preview_col:
            with ui.element("div").classes("mt-card"):
                if group_by_camera:
                    ui.html('<div class="mt-card-header">Vorschau – Jahr / Kamera</div>')
                    for year in sorted(result["files_by_year"].keys()):
                        cam_dict = result["files_by_year"][year]
                        total_in_year = sum(len(v) for v in cam_dict.values())
                        ui.html(
                            f'<div style="padding:8px 16px;color:{theme.COLORS["text"]};'
                            f"font-family:Menlo,monospace;font-size:12px;"
                            f'font-weight:600;">'
                            f'{year}/ <span style="color:{theme.COLORS["muted"]};font-weight:400;">'
                            f"({total_in_year})</span></div>"
                        )
                        for camera in sorted(cam_dict.keys()):
                            count = len(cam_dict[camera])
                            ui.html(
                                f'<div style="padding:4px 16px 4px 32px;'
                                f"font-family:Menlo,monospace;font-size:11px;"
                                f'color:{theme.COLORS["muted"]};">└─ {escape(camera)}'
                                f'<span style="color:{theme.COLORS["accent"]};margin-left:8px;">'
                                f"{count}</span></div>"
                            )
                else:
                    ui.html('<div class="mt-card-header">Vorschau – Jahr</div>')
                    for year in sorted(result["files_by_year"].keys()):
                        files = result["files_by_year"][year]
                        ui.html(
                            f'<div style="padding:8px 16px;'
                            f"font-family:Menlo,monospace;font-size:12px;"
                            f'color:{theme.COLORS["text"]};border-bottom:1px solid {theme.COLORS["surface"]};">'
                            f'{year}/ <span style="color:{theme.COLORS["accent"]};">→</span> '
                            f'<span style="color:{theme.COLORS["success"]};">{len(files)} Datei(en)'
                            f"</span></div>"
                        )

                if result["invalid_files"]:
                    ui.html(
                        f'<div class="mt-card-header" style="margin-top:4px;">'
                        f"Ungültig ({len(result['invalid_files'])})</div>"
                    )
                    for inv in result["invalid_files"][:10]:
                        ui.html(
                            f'<div style="padding:4px 16px;'
                            f"font-family:Menlo,monospace;font-size:11px;"
                            f'color:{theme.COLORS["muted"]};">{escape(inv["path"].name)}</div>'
                        )
                    if len(result["invalid_files"]) > 10:
                        ui.html(
                            f'<div class="mt-hint" style="padding:4px 16px;">'
                            f"… und {len(result['invalid_files']) - 10} weitere</div>"
                        )

                if result["conflicts"]:
                    ui.html(
                        f'<div class="mt-card-header" style="margin-top:4px;'
                        f'color:{theme.COLORS["danger"]} !important;">'
                        f"{len(result['conflicts'])} Konflikte – Ausführen blockiert</div>"
                    )
                    for c in result["conflicts"][:5]:
                        ui.html(
                            f'<div style="padding:4px 16px;'
                            f"font-family:Menlo,monospace;font-size:11px;"
                            f'color:{theme.COLORS["danger"]};">{c["filename"]} (Jahr {c["year"]})</div>'
                        )

        if not result["conflicts"]:
            btn_execute.enable()

    ui.button("Vorschau", on_click=do_preview, icon="preview").classes("mt-btn-primary mt-2").props(
        "no-caps"
    )

    ui.separator().classes("mt-4")

    # ── Ausführen ──────────────────────────────────────────────────
    async def do_execute():
        folder = _state.get("folder")
        if not _state.get("scan") or not folder:
            return

        status_row.visible = True
        spinner.visible = True
        status_label.set_text("Organisiere …")
        btn_execute.disable()
        preview_col.clear()
        preview_col.visible = False
        pills_row.visible = False
        progress_bar.set_value(0)
        progress_bar.visible = True
        await asyncio.sleep(0)

        from app.core.year_org import execute_organization  # noqa: PLC0415

        group_by_camera = _state["scan"].get("group_by_camera", False)
        exts = _state["extensions"]
        recursive = shared.get("recursive", True)
        loop = asyncio.get_running_loop()
        _last_exec = [0.0]

        async def _update_exec_progress(value: float):
            progress_bar.set_value(value)
            status_label.set_text(f"Organisiere … {int(value * 100)} %")

        def exec_progress_cb(done, total):
            import time

            if total > 0:
                now = time.monotonic()
                if now - _last_exec[0] < 0.1 and done < total:
                    return
                _last_exec[0] = now
                asyncio.run_coroutine_threadsafe(_update_exec_progress(done / total), loop)

        result = await loop.run_in_executor(
            _executor,
            lambda: execute_organization(
                folder,
                group_by_camera,
                extensions=exts,
                progress_cb=exec_progress_cb,
                recursive=recursive,
            ),
        )

        spinner.visible = False
        progress_bar.visible = False

        if result.get("error"):
            ui.notify(result["error"], type="negative")
            status_label.set_text(result["error"])
            _state["scan"] = None
            return

        status_label.set_text(f"{result['moved']} Datei(en) verschoben")
        pills_row.clear()
        pills_row.visible = True
        with pills_row:
            theme.pill(f"{result['moved']} verschoben", "good")
            if result["errors"]:
                theme.pill(f"{result['errors']} Fehler", "danger")
            if result["removed_folders"]:
                theme.pill(f"{result['removed_folders']} leere Ordner entfernt", "neutral")

        _state["scan"] = None

    btn_execute = (
        ui.button("Ausführen", on_click=do_execute, icon="folder_special")
        .classes("mt-btn-success mt-2")
        .props("color=positive no-caps")
    )
    btn_execute.disable()

    ui.label("Tipp: Vorher Backup erstellen!").classes("mt-hint mt-1")
