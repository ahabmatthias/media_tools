"""
UI-Tab: Video Komprimierung
"""

import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from html import escape

from nicegui import ui

from app.ui import theme
from app.ui.utils import pick_folder, validate_folder_path

_executor = ThreadPoolExecutor(max_workers=1)

_ACTION_TAG = {
    "compress": ("mt-tag mt-tag-compress", "Komprimieren"),
    "skip": ("mt-tag mt-tag-skip", "Überspringen"),
    "skip_exists": ("mt-tag mt-tag-skip", "Ziel existiert"),
    "skip_and_copy": ("mt-tag mt-tag-copy", "Kopieren"),
}


def build(shared: dict):
    """Baut den Video-Komprimierungs-Tab – wird innerhalb eines tab_panel aufgerufen."""
    # ── Optionen ──────────────────────────────────────────────────
    with ui.element("div").classes("mt-card w-full mt-2"):
        ui.html('<div class="mt-card-header">Optionen</div>')
        with ui.column().classes("w-full gap-2 p-3"):
            with ui.row().classes("w-full items-center gap-2"):
                target_input = (
                    ui.input(
                        label="Zielordner",
                        placeholder="/Users/du/Videos_compressed",
                    )
                    .classes("flex-1")
                    .props('outlined dense input-style="direction:rtl;text-align:left"')
                )

                async def on_pick_target():
                    result = await pick_folder()
                    if result:
                        target_input.set_value(result)

                ui.button("Ordner wählen", on_click=on_pick_target, icon="folder_open").classes(
                    "mt-btn-primary"
                ).props("no-caps")

            # Reaktives Auto-Fill: Zielordner wird gesetzt sobald Quellordner gewählt wird
            def _auto_fill_target(folder: str):
                if folder and not target_input.value.strip():
                    target_input.set_value(folder + "_compressed")

            shared.setdefault("_on_folder_change", []).append(_auto_fill_target)

            with ui.row().classes("items-center gap-4"):
                if sys.platform == "darwin":
                    _codec_options = {
                        "hevc_videotoolbox": "Hardware (Default)",
                        "libx265": "Software (gründlicher)",
                    }
                    _codec_default = "hevc_videotoolbox"
                    _codec_tooltip = (
                        "Hardware nutzt den Apple-Chip direkt – schnell und stromsparend. "
                        "Software encodiert in reinem Code – langsamer, minimal präziser."
                    )
                else:
                    _codec_options = {
                        "libx265": "Software (Default)",
                    }
                    _codec_default = "libx265"
                    _codec_tooltip = "Software-Encoder – funktioniert auf allen Systemen."

                codec_select = (
                    ui.select(
                        label="Codec",
                        options=_codec_options,
                        value=_codec_default,
                    )
                    .classes("w-52")
                    .props("outlined dense")
                )
                ui.icon("info_outline").classes(
                    f"text-[{theme.COLORS['accent']}] text-sm cursor-default"
                ).tooltip(_codec_tooltip)

                min_size_input = (
                    ui.number(label="Min-Größe (MB)", value=30.0, min=0, step=5)
                    .classes("w-32")
                    .props("outlined dense")
                )

    # ── Status + Spinner ──────────────────────────────────────────
    with ui.row().classes("items-center gap-3 mt-2") as status_row:
        spinner = theme.ember_spinner()
        spinner.visible = False
        status_label = ui.label("").classes("mt-hint")
    status_row.visible = False

    # ── Pills-Zeile ───────────────────────────────────────────────
    pills_row = ui.row().classes("items-center gap-2 mt-1")
    pills_row.visible = False

    preview_col = ui.column().classes("w-full gap-0 mt-2")
    preview_col.visible = False
    _state: dict = {"preview": None, "source": None, "target": None, "config": None}

    def _show_preview_pills(n_compress: int, n_skip: int, n_copy: int, n_exists: int = 0):
        pills_row.clear()
        pills_row.visible = True
        with pills_row:
            if n_compress:
                theme.pill(f"{n_compress} komprimieren", "neutral")
            if n_copy:
                theme.pill(f"{n_copy} kopieren", "neutral")
            if n_skip:
                theme.pill(f"{n_skip} überspringen", "")
            if n_exists:
                theme.pill(f"{n_exists} Ziel existiert", "")

    # ── Vorschau ──────────────────────────────────────────────────
    async def do_preview():
        source = shared["folder"].strip() if shared else ""
        target = target_input.value.strip()

        if not source:
            ui.notify("Bitte einen Quellordner eingeben.", type="negative")
            return
        if not os.path.isdir(source):
            ui.notify("Quellordner nicht gefunden.", type="negative")
            return
        if not validate_folder_path(source):
            ui.notify("Quellordner liegt außerhalb des Home-Verzeichnisses.", type="negative")
            return
        if not target:
            ui.notify("Bitte einen Zielordner eingeben.", type="negative")
            return
        if not validate_folder_path(target):
            ui.notify("Zielordner liegt außerhalb des Home-Verzeichnisses.", type="negative")
            return
        if os.path.abspath(source) == os.path.abspath(target):
            ui.notify("Quell- und Zielordner dürfen nicht identisch sein.", type="negative")
            return

        status_row.visible = True
        spinner.visible = True
        status_label.set_text("Scanne …")
        preview_col.clear()
        preview_col.visible = False
        pills_row.visible = False
        _state["preview"] = None
        btn_execute.disable()
        await asyncio.sleep(0)

        from app.core.video_compress import preview_compression  # noqa: PLC0415

        config = {
            "recursive": shared.get("recursive", True),
            "min_size_mb": float(min_size_input.value or 30.0),
            "codec": codec_select.value,
        }

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _executor, lambda: preview_compression(source, target, **config)
        )

        spinner.visible = False

        if not result:
            status_label.set_text("Keine Video-Dateien im Quellordner gefunden.")

            return

        _state["preview"] = result
        _state["source"] = source
        _state["target"] = target
        _state["config"] = config

        n_compress = sum(1 for f in result if f["action"] == "compress")
        n_skip = sum(1 for f in result if f["action"] == "skip")
        n_exists = sum(1 for f in result if f["action"] == "skip_exists")
        n_copy = sum(1 for f in result if f["action"] == "skip_and_copy")

        status_label.set_text(f"{len(result)} Dateien gefunden")
        _show_preview_pills(n_compress, n_skip, n_copy, n_exists)

        # ── HTML-Tabelle ──────────────────────────────────────
        MAX_SHOWN = 50
        shown = result[:MAX_SHOWN]

        header = (
            "<tr>"
            '<th style="text-align:left;">Dateiname</th>'
            '<th style="text-align:right;">Größe</th>'
            "<th>Auflösung</th>"
            "<th>Bitrate</th>"
            "<th>Aktion</th>"
            "</tr>"
        )

        rows_html = []
        for e in shown:
            tag_cls, tag_label = _ACTION_TAG.get(e["action"], ("mt-tag", "?"))
            bitrate = (
                f"{e['current_bitrate_mbps']} Mbps"
                if e["current_bitrate_mbps"] is not None
                else "–"
            )
            rows_html.append(
                f"<tr>"
                f'<td style="text-align:left;">{escape(e["name"])}</td>'
                f'<td style="text-align:right;">{e["size_mb"]} MB</td>'
                f"<td>{escape(e['resolution'])}</td>"
                f"<td>{bitrate}</td>"
                f'<td><span class="{tag_cls}">{tag_label}</span></td>'
                f"</tr>"
            )

        table_html = (
            '<div class="mt-table">'
            '<table class="q-table" style="width:100%;border-collapse:collapse;">'
            f"<thead>{header}</thead>"
            f"<tbody>{''.join(rows_html)}</tbody>"
            "</table>"
            "</div>"
        )

        preview_col.visible = True
        with preview_col:
            with ui.element("div").classes("mt-card"):
                ui.html('<div class="mt-card-header">Vorschau</div>')
                ui.html(table_html)
                if len(result) > MAX_SHOWN:
                    ui.html(
                        f'<div class="mt-hint" style="padding:8px 16px;">'
                        f"… und {len(result) - MAX_SHOWN} weitere</div>"
                    )

        btn_execute.enable()

    ui.button("Vorschau", on_click=do_preview, icon="preview").classes("mt-btn-primary mt-2").props(
        "no-caps"
    )

    ui.separator().classes("mt-4")

    # ── Ausführen ─────────────────────────────────────────────────
    async def do_execute():
        if not _state.get("preview") or not _state.get("source"):
            return

        source = _state["source"]
        target = _state["target"]
        config = _state["config"]

        status_row.visible = True
        spinner.visible = True
        btn_execute.disable()
        preview_col.clear()
        preview_col.visible = False
        pills_row.visible = False
        await asyncio.sleep(0)

        from app.core.video_compress import ProbeInfo, compress_files  # noqa: PLC0415

        # Build cached probes from preview to avoid re-running ffprobe
        cached_probes: dict[str, ProbeInfo] = {}
        for entry in _state.get("preview") or []:
            if entry.get("path") and entry.get("probe_width") is not None:
                cached_probes[entry["path"]] = ProbeInfo(
                    width=entry["probe_width"],
                    height=entry["probe_height"],
                    bitrate_bps=entry["probe_bitrate_bps"],
                )

        loop = asyncio.get_running_loop()

        async def _set_status(text: str):
            status_label.set_text(text)

        def progress_cb(current, total, filename):
            asyncio.run_coroutine_threadsafe(_set_status(f"[{current}/{total}] {filename}"), loop)

        result = await loop.run_in_executor(
            _executor,
            lambda: compress_files(
                source, target, **config, progress_cb=progress_cb, cached_probes=cached_probes
            ),
        )

        spinner.visible = False
        _state["preview"] = None

        status_label.set_text("Komprimierung abgeschlossen")
        pills_row.clear()
        pills_row.visible = True
        with pills_row:
            if result["compressed"]:
                theme.pill(f"{result['compressed']} komprimiert", "good")
            if result.get("hw_unavailable"):
                theme.pill("Hardware nicht verfügbar – Software genutzt", "neutral")
            if result.get("hw_fallbacks"):
                theme.pill(f"{result['hw_fallbacks']}× Software-Fallback", "neutral")
            if result["skipped"]:
                theme.pill(f"{result['skipped']} übersprungen", "")
            if result["failed"]:
                theme.pill(f"{result['failed']} Fehler", "danger")

        if result.get("error_details"):
            preview_col.visible = True
            with preview_col:
                with ui.element("div").classes("mt-card w-full"):
                    ui.html('<div class="mt-card-header">Fehler</div>')
                    for err in result["error_details"][:20]:
                        ui.html(
                            f'<div class="mt-rename-row">'
                            f'<span class="mt-rename-old">{escape(err["file"])}</span>'
                            f'<span class="mt-rename-arrow">✕</span>'
                            f'<span style="color:{theme.COLORS["danger"]}">{escape(err["error"])}</span>'
                            f"</div>"
                        )

    btn_execute = (
        ui.button("Komprimieren", on_click=do_execute, icon="movie")
        .classes("mt-btn-success mt-2")
        .props("color=positive no-caps")
    )
    btn_execute.disable()
