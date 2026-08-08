#!/usr/bin/env python3
"""
FileFiend – Einstiegspunkt
Starten mit: python -m app.main
"""

import multiprocessing
from pathlib import Path

multiprocessing.freeze_support()

from nicegui import app as nicegui_app  # noqa: E402
from nicegui import ui  # noqa: E402

# ── Static asset mount (absolute path for PyInstaller compatibility) ──
from app.core.runtime import (  # noqa: E402
    is_frozen,
    setup_path,
)
from app.ui import (  # noqa: E402
    duplicates_tab,
    renamer_tab,
    theme,
    video_compress_tab,
    year_org_tab,
)
from app.ui.utils import pick_folder  # noqa: E402

if is_frozen():
    import sys

    _ASSETS_DIR = Path(sys._MEIPASS) / "assets" / "alternate"  # type: ignore[attr-defined]
else:
    _ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "alternate"
if _ASSETS_DIR.is_dir():
    nicegui_app.add_static_files("/assets", str(_ASSETS_DIR))


@ui.page("/")
def index():
    theme.apply()

    # ── Splash Overlay ──────────────────────────────────────────────────
    splash = ui.element("div").classes("mt-splash")
    with splash:
        ui.image("/assets/sleek_fiend.png").classes("mt-splash-logo")
        ui.html(
            '<span class="mt-splash-wordmark">'
            "File"
            f'<span style="color:{theme.COLORS["accent"]};position:relative;top:0.5px;">'
            "Fiend</span></span>"
        )

    # ── Main UI (hidden behind splash) ──────────────────────────────────
    shared: dict = {"folder": "", "recursive": True, "_on_folder_change": []}

    def _notify_folder_change(folder: str):
        for cb in shared.get("_on_folder_change", []):
            cb(folder)

    with ui.header().classes("mt-header"):
        with ui.row().classes("items-center gap-3 w-full"):
            ui.html(
                f'<span style="display:inline-flex;align-items:baseline;'
                f"font-size:15px;letter-spacing:-0.01em;"
                f'white-space:nowrap;user-select:none;">'
                f'<span style="font-weight:700;">File</span>'
                f'<span style="font-weight:700;color:{theme.COLORS["accent"]};position:relative;top:0.5px;">'
                f"Fiend</span></span>"
            )
            shared_input = (
                ui.input(
                    placeholder="/Users/du/Bilder",
                )
                .classes("flex-1")
                .props('outlined dense input-style="direction:rtl;text-align:left"')
            )

            shared_input.on(
                "change",
                lambda e: (
                    shared.update({"folder": e.value}),
                    _notify_folder_change(e.value),
                ),
            )

            async def on_pick_shared():
                result = await pick_folder()
                if result:
                    shared["folder"] = result
                    shared_input.set_value(result)
                    _notify_folder_change(result)

            ui.button("Ordner wählen", on_click=on_pick_shared).classes("mt-btn-primary").props(
                "no-caps"
            )

        with ui.row().classes("mt-header-sub items-center gap-2 w-full"):
            ui.checkbox(
                "Mit Unterordnern",
                value=True,
                on_change=lambda e: shared.update({"recursive": e.value}),
            )

    with ui.tabs().classes("w-full") as tabs:
        tab_dupes = ui.tab("Duplikate", icon="content_copy")
        tab_rename = ui.tab("Umbenennen", icon="drive_file_rename_outline")
        tab_year = ui.tab("Ordnen", icon="layers")
        tab_video = ui.tab("Komprimieren", icon="movie")

    with ui.tab_panels(tabs, value=tab_dupes).classes("w-full"):
        with ui.tab_panel(tab_dupes):
            duplicates_tab.build(shared)
        with ui.tab_panel(tab_rename):
            renamer_tab.build(shared)
        with ui.tab_panel(tab_year):
            year_org_tab.build(shared)
        with ui.tab_panel(tab_video):
            video_compress_tab.build(shared)

    # ── Dismiss splash after 2s ─────────────────────────────────────────
    ui.timer(3.0, lambda: splash.set_visibility(False), once=True)


def main():
    setup_path()

    from nicegui.native import find_open_port  # noqa: PLC0415

    ui.run(
        title="FileFiend",
        native=True,
        window_size=(1000, 680),
        port=find_open_port(),
        reload=False,
        favicon="/assets/sleek_fiend.png",
    )


if __name__ == "__main__":
    main()
