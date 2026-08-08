"""
Wrapper um year_folder_script.py für die UI-Integration.

Kapselt die Einzelfunktionen, unterdrückt print/tqdm-Output
und gibt strukturierte Dicts zurück.

Jahres-Erkennung: Dateiname zuerst, dann EXIF/Metadata als Fallback.
Kamera-Erkennung: EXIF model → EXIF make → Dateiname-Präfix → Sonstige.
"""

import contextlib
import io
import re
import shutil
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from app.core.constants import ALL_MEDIA_EXTS, IMAGE_EXTS
from app.core.renamer import get_metadata

_EXIF_DATETIME_TAGS = (36867, 36868, 306)  # DateTimeOriginal, DateTimeDigitized, DateTime
# Matcht XMP-Datumsattribute wie MetadataDate="2024-..." oder DateTimeOriginal>2024...
_XMP_DATE_RE = re.compile(
    r'(?:DateTimeOriginal|CreateDate|DateCreated|MetadataDate)[="\s>:]+(\d{4})'
)


_FILENAME_DATE_RE = re.compile(r"(\d{4})(\d{2})(\d{2})")

_MIN_YEAR = 1990


def _plausible_year(year: int) -> bool:
    """Plausibilitätscheck: 1990 bis nächstes Jahr (Kameras mit falscher Uhr abfangen)."""
    return _MIN_YEAR <= year <= datetime.now().year + 1


def extract_year_from_filename(filename: str) -> int | None:
    """
    Extrahiert das Jahr aus dem Dateinamen.
    1. Erste 4 Zeichen (z.B. '2025_vacation.jpg')
    2. Regex-Fallback für 8-stellige Datumssequenzen (z.B. 'DJI_20251213...')
    """
    try:
        year = int(filename[:4])
        if _plausible_year(year):
            return year
    except (ValueError, IndexError):
        pass
    m = _FILENAME_DATE_RE.search(filename)
    if m:
        year = int(m.group(1))
        if _plausible_year(year):
            return year
    return None


def find_filename_conflicts(files_by_year: dict, target_folder: Path) -> list:
    """Findet Konflikte: gleicher Dateiname aus verschiedenen Quell-Ordnern."""
    conflicts = []
    for year, files in files_by_year.items():
        filename_sources: dict = defaultdict(list)
        for file_path in files:
            filename_sources[file_path.name].append(file_path)
        for filename, file_paths in filename_sources.items():
            if len(file_paths) > 1:
                source_dirs = {fp.parent for fp in file_paths}
                if len(source_dirs) > 1:
                    conflicts.append(
                        {
                            "filename": filename,
                            "year": year,
                            "paths": file_paths,
                            "source_dirs": list(source_dirs),
                        }
                    )
    return conflicts


def _create_year_folders(files_by_year: dict, target_folder: Path) -> None:
    """Erstellt Jahr-Unterordner im Zielverzeichnis."""
    for year in sorted(files_by_year.keys()):
        (target_folder / str(year)).mkdir(exist_ok=True)


def _move_files_to_year_folders(files_by_year: dict, target_folder: Path) -> tuple[list, list]:
    """Verschiebt Dateien in die entsprechenden Jahr-Ordner."""
    moved_files = []
    errors = []
    for year in sorted(files_by_year.keys()):
        year_folder = target_folder / str(year)
        for file_path in files_by_year[year]:
            target_path = year_folder / file_path.name
            if target_path.exists() and target_path != file_path:
                errors.append(
                    {
                        "file": file_path,
                        "target": target_path,
                        "error": "Zieldatei existiert bereits",
                    }
                )
                continue
            try:
                if file_path.parent != year_folder:
                    shutil.move(str(file_path), str(target_path))
                moved_files.append({"source": file_path, "target": target_path})
            except Exception as e:
                errors.append({"file": file_path, "target": target_path, "error": str(e)})
    return moved_files, errors


def _find_empty_folders(folder_path: str) -> list:
    """Findet leere Ordner (rekursiv), Jahr-Ordner werden nie als leer betrachtet."""
    folder = Path(folder_path)
    empty_folders = []

    def _is_empty(path: Path) -> bool:
        if not path.is_dir():
            return False
        if path.name.isdigit() and path.parent == folder:
            return False
        try:
            for item in path.iterdir():
                if item.is_file():
                    if not (item.name.startswith("._") or item.name == ".DS_Store"):
                        return False
                elif item.is_dir() and not _is_empty(item):
                    return False
            return True
        except PermissionError:
            return False

    all_dirs = sorted(folder.rglob("*"), key=lambda x: len(x.parts), reverse=True)
    for d in all_dirs:
        if d.is_dir() and d != folder and _is_empty(d):
            empty_folders.append(d)
    return empty_folders


_heif_registered = False


def _read_exif_year(file_path: Path) -> int | None:
    """
    Liest das Aufnahmejahr aus Bilddateien.
    Stufen: EXIF IFD0 → EXIF Sub-IFD (34665) → XMP-Metadaten.
    """
    from PIL import Image  # noqa: PLC0415

    global _heif_registered  # noqa: PLW0603
    if not _heif_registered:
        try:
            import pillow_heif  # noqa: PLC0415

            pillow_heif.register_heif_opener()
        except ImportError:
            pass  # HEIC-Support optional
        _heif_registered = True

    try:
        with Image.open(file_path) as img:
            exif = img.getexif()
            # IFD0 + EXIF-Sub-IFD durchsuchen
            for source in (exif, exif.get_ifd(34665)):
                for tag in _EXIF_DATETIME_TAGS:
                    val = source.get(tag)
                    if val:
                        year = int(str(val)[:4])
                        if _plausible_year(year):
                            return year
            # XMP-Fallback (z.B. Photoshop-bearbeitete Sony-Dateien ohne DateTimeOriginal)
            xmp_raw = img.info.get("xmp")
            if xmp_raw:
                xmp = (
                    xmp_raw.decode("utf-8", errors="ignore")
                    if isinstance(xmp_raw, bytes)
                    else xmp_raw
                )
                m = _XMP_DATE_RE.search(xmp)
                if m:
                    year = int(m.group(1))
                    if _plausible_year(year):
                        return year
    except Exception:
        pass
    return None


def _remove_empty_folders(empty_folders: list) -> list:
    """Löscht leere Ordner – entfernt vorher macOS-Systemdateien (.DS_Store, ._*)."""
    removed = []
    for folder in empty_folders:
        for f in folder.iterdir():
            if f.name == ".DS_Store" or f.name.startswith("._"):
                f.unlink()
        try:
            folder.rmdir()
            removed.append(folder)
        except OSError:
            pass  # Ordner doch nicht leer (z.B. Race condition)
    return removed


def _run_silent(fn, *args, **kwargs):
    """Führt fn(*args, **kwargs) aus und unterdrückt jede Ausgabe."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        return fn(*args, **kwargs)


def _sanitize_folder_name(name: str) -> str:
    """Bereinigt einen EXIF-Wert für die sichere Verwendung als Ordnername.
    Ersetzt alle Zeichen außer Buchstaben, Ziffern, Leerzeichen, Bindestrich und
    Klammern durch '_'. Verhindert Path-Traversal durch '..' oder '/' in EXIF-Feldern.
    """
    import re  # noqa: PLC0415

    safe = re.sub(r"[^\w\s\-()\.]", "_", name)
    # Entferne führende/folgende Punkte um '..' und versteckte Ordner zu verhindern
    return safe.strip(".") or "Sonstige"


def _detect_camera(file_path: Path) -> str:
    """
    Erkennt die Kamera aus EXIF-Daten oder Dateinamen.
    Reihenfolge: EXIF model → EXIF make → Dateiname-Präfix → 'Sonstige'.
    """
    file_type = "image" if file_path.suffix.lower() in IMAGE_EXTS else "video"
    try:
        meta = _run_silent(get_metadata, str(file_path), file_type)
    except Exception:
        meta = {}

    # 1. EXIF model direkt verwenden
    model = str(meta.get("model", "")).strip()
    if model:
        return _sanitize_folder_name(model)

    # 2. EXIF make als Fallback
    make = str(meta.get("make", "")).strip()
    if make:
        return _sanitize_folder_name(make)

    # 3. Dateiname-Präfix
    if file_path.name.upper().startswith("DJI_"):
        return "DJI"

    return "Sonstige"


def _extract_year(file_path: Path) -> int | None:
    """
    Jahres-Erkennung:
    1. Metadaten (EXIF / pymediainfo) – zuverlässigste Quelle
    2. Dateiname als Fallback
    """
    if file_path.suffix.lower() in IMAGE_EXTS:
        year = _read_exif_year(file_path)
        if year:
            return year
    else:
        try:
            meta = _run_silent(get_metadata, str(file_path), "video")
            dt = meta.get("datetime")
            if dt and _plausible_year(dt.year):
                return int(dt.year)
        except Exception:
            pass

    return extract_year_from_filename(file_path.name)


def _collect_files_with_years(
    folder_path: str,
    group_by_camera: bool = False,
    extensions: set[str] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    recursive: bool = True,
) -> tuple[dict, list[dict]]:
    """
    Sammelt Mediendateien und gruppiert sie nach Jahr (und optional Kamera).

    Rückgabe wenn group_by_camera=False: ({year: [Path, ...]}, invalid_files)
    Rückgabe wenn group_by_camera=True:  ({year: {camera: [Path, ...]}}, invalid_files)
    progress_cb(done, total) wird optional nach jeder verarbeiteten Datei aufgerufen.
    """
    folder = Path(folder_path)
    if group_by_camera:
        files_by_year: dict = defaultdict(lambda: defaultdict(list))
    else:
        files_by_year = defaultdict(list)
    invalid_files = []

    # Pre-collect für Fortschrittsanzeige
    active_exts = extensions if extensions is not None else ALL_MEDIA_EXTS
    glob_iter = folder.rglob("*") if recursive else folder.glob("*")
    all_files = [
        f
        for f in glob_iter
        if (
            not f.name.startswith("._")
            and f.name != ".DS_Store"
            and not f.name.startswith("rename_log_")
            and not f.name.startswith("camera_rename_log_")
            and f.parent.name != "duplicates"
            and f.suffix.lower() in active_exts
            and f.is_file()
        )
    ]
    total = len(all_files)

    for i, file_path in enumerate(all_files, 1):
        year = _extract_year(file_path)
        if year is None:
            invalid_files.append(
                {
                    "path": file_path,
                    "reason": "Jahr nicht erkennbar (Dateiname + Metadata geprüft)",
                }
            )
        elif group_by_camera:
            camera = _detect_camera(file_path)
            files_by_year[year][camera].append(file_path)
        else:
            files_by_year[year].append(file_path)

        if progress_cb and total > 0:
            progress_cb(i, total)

    return files_by_year, invalid_files


def scan_folder(
    folder_path: str,
    group_by_camera: bool = False,
    extensions: set[str] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    recursive: bool = True,
) -> dict:
    """
    Scannt den Ordner und gibt eine Vorschau zurück – ohne Dateien zu bewegen
    und ohne Log-File zu schreiben.

    Rückgabe (group_by_camera=False):
        {
            "files_by_year":   {int: [Path, ...]},
            "invalid_files":   [...],
            "conflicts":       [...],
            "total_files":     int,
            "group_by_camera": False,
        }

    Rückgabe (group_by_camera=True):
        {
            "files_by_year":   {int: {str: [Path, ...]}},
            "invalid_files":   [...],
            "conflicts":       [...],
            "total_files":     int,
            "group_by_camera": True,
        }
    """
    folder = Path(folder_path)

    files_by_year, invalid_files = _collect_files_with_years(
        folder_path,
        group_by_camera,
        extensions=extensions,
        progress_cb=progress_cb,
        recursive=recursive,
    )

    # Konflikt-Prüfung braucht flache {year: [Path, ...]} Struktur
    conflicts: list = []
    if files_by_year:
        if group_by_camera:
            flat = {
                year: [f for paths in cam_dict.values() for f in paths]
                for year, cam_dict in files_by_year.items()
            }
        else:
            flat = files_by_year
        conflicts = find_filename_conflicts(flat, folder)

    if group_by_camera:
        total = sum(
            len(paths) for cam_dict in files_by_year.values() for paths in cam_dict.values()
        )
    else:
        total = sum(len(f) for f in files_by_year.values())

    return {
        "files_by_year": {k: dict(v) if group_by_camera else v for k, v in files_by_year.items()},
        "invalid_files": invalid_files,
        "conflicts": conflicts,
        "total_files": total,
        "group_by_camera": group_by_camera,
    }


def _move_with_camera_groups(files_by_year: dict, folder: Path):
    """
    Verschiebt Dateien in <folder>/<year>/<camera>/ Unterordner.
    Gibt (moved_files, errors) zurück.
    """
    moved_files = []
    errors = []

    for year in sorted(files_by_year.keys()):
        cam_dict = files_by_year[year]
        for camera, paths in cam_dict.items():
            target_dir = folder / str(year) / camera
            target_dir.mkdir(parents=True, exist_ok=True)
            for file_path in paths:
                target_path = target_dir / file_path.name
                if target_path.exists() and target_path != file_path:
                    errors.append(
                        {
                            "file": file_path,
                            "target": target_path,
                            "error": "Zieldatei existiert bereits",
                        }
                    )
                    continue
                try:
                    if file_path.parent != target_dir:
                        shutil.move(str(file_path), str(target_path))
                    moved_files.append({"source": file_path, "target": target_path})
                except Exception as e:
                    errors.append({"file": file_path, "target": target_path, "error": str(e)})

    return moved_files, errors


def execute_organization(
    folder_path: str,
    group_by_camera: bool = False,
    extensions: set[str] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    recursive: bool = True,
) -> dict:
    """
    Führt die Jahr-Organisation durch (verschiebt Dateien, löscht leere Ordner).

    Wenn group_by_camera=True: Zielstruktur ist <year>/<camera>/<datei>.

    Rückgabe:
        {
            "moved":           int,
            "errors":          int,
            "removed_folders": int,
            "error_details":   list,
            "error":           str | None,
        }
    """
    folder = Path(folder_path)

    files_by_year, invalid_files = _collect_files_with_years(
        folder_path,
        group_by_camera,
        extensions=extensions,
        progress_cb=progress_cb,
        recursive=recursive,
    )

    if not files_by_year:
        return {
            "error": "Keine Dateien mit erkennbarem Jahr gefunden.",
            "moved": 0,
            "errors": 0,
            "removed_folders": 0,
            "error_details": [],
        }

    # Konflikt-Prüfung mit flacher Struktur
    if group_by_camera:
        flat = {
            year: [f for paths in cam_dict.values() for f in paths]
            for year, cam_dict in files_by_year.items()
        }
    else:
        flat = files_by_year

    conflicts = find_filename_conflicts(flat, folder)
    if conflicts:
        return {
            "error": f"{len(conflicts)} Dateiname-Konflikte – Organisation abgebrochen.",
            "conflicts": conflicts,
            "moved": 0,
            "errors": 0,
            "removed_folders": 0,
            "error_details": [],
        }

    if group_by_camera:
        moved_files, move_errors = _move_with_camera_groups(files_by_year, folder)
    else:
        _create_year_folders(files_by_year, folder)
        moved_files, move_errors = _move_files_to_year_folders(files_by_year, folder)

    empty_folders = _find_empty_folders(folder_path)
    removed = _remove_empty_folders(empty_folders)

    return {
        "moved": len(moved_files),
        "errors": len(move_errors),
        "removed_folders": len(removed),
        "error_details": move_errors,
        "error": None,
    }
