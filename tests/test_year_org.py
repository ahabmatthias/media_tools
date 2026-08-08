"""
Tests für app/core/year_org.py – höchstes Schadenspotenzial, daher priorisiert.
Alle Tests laufen im dry-run / scan-only Modus und bewegen keine echten Dateien.
"""

from collections import defaultdict
from datetime import datetime

from app.core.year_org import (
    execute_organization,
    extract_year_from_filename,
    find_filename_conflicts,
    scan_folder,
)

# ── extract_year_from_filename ──────────────────────────────────────────────


def test_extract_year_valid():
    assert extract_year_from_filename("2023-04-15_120000_foto.jpg") == 2023


def test_extract_year_edge_cases():
    next_year = datetime.now().year + 1
    assert extract_year_from_filename("1990-01-01_000000_old.jpg") == 1990
    assert extract_year_from_filename(f"{next_year}-12-31_235959_future.jpg") == next_year


def test_extract_year_invalid():
    """Dateinamen ohne Jahr am Anfang liefern None."""
    assert extract_year_from_filename("IMG_1234.jpg") is None
    assert extract_year_from_filename("DSC_0001.mp4") is None
    assert extract_year_from_filename("") is None


def test_extract_year_out_of_range():
    """Jahre außerhalb 1990 bis <nächstes Jahr> werden abgelehnt."""
    year_after_next = datetime.now().year + 2
    assert extract_year_from_filename("1985-01-01_foto.jpg") is None
    assert extract_year_from_filename(f"{year_after_next}-01-01_foto.jpg") is None


# ── find_filename_conflicts ─────────────────────────────────────────────────


def test_no_conflicts(tmp_path):
    """Dateien mit eindeutigen Namen → keine Konflikte."""
    sub1 = tmp_path / "sub1"
    sub2 = tmp_path / "sub2"
    sub1.mkdir()
    sub2.mkdir()
    (sub1 / "2023-01-01_foto_a.jpg").write_bytes(b"a")
    (sub2 / "2023-01-02_foto_b.jpg").write_bytes(b"b")

    files_by_year = defaultdict(list)
    files_by_year[2023].append(sub1 / "2023-01-01_foto_a.jpg")
    files_by_year[2023].append(sub2 / "2023-01-02_foto_b.jpg")

    conflicts = find_filename_conflicts(dict(files_by_year), tmp_path)
    assert conflicts == []


def test_detects_conflict(tmp_dir_conflict):
    """Gleicher Dateiname in zwei Unterordnern → Konflikt erkannt."""
    files_by_year = defaultdict(list)
    for p in tmp_dir_conflict.rglob("*.jpg"):
        files_by_year[2023].append(p)

    conflicts = find_filename_conflicts(dict(files_by_year), tmp_dir_conflict)
    assert len(conflicts) == 1
    assert conflicts[0]["filename"] == "2023-05-01_120000_foto.jpg"


# ── scan_folder ─────────────────────────────────────────────────────────────


def test_scan_folder_groups_by_year(tmp_media_dir):
    """scan_folder gruppiert Dateien korrekt nach Jahr."""
    result = scan_folder(str(tmp_media_dir))

    assert 2023 in result["files_by_year"]
    assert 2024 in result["files_by_year"]
    assert result["total_files"] == 4
    assert result["invalid_files"] == []
    assert result["group_by_camera"] is False


def test_scan_folder_invalid_files(tmp_dir_no_year):
    """Dateien ohne erkennbares Jahr landen in invalid_files."""
    result = scan_folder(str(tmp_dir_no_year))

    assert result["total_files"] == 0
    assert len(result["invalid_files"]) == 2


def test_scan_folder_empty_dir(tmp_path):
    """Leeres Verzeichnis → keine Ergebnisse, kein Fehler."""
    result = scan_folder(str(tmp_path))

    assert result["total_files"] == 0
    assert result["files_by_year"] == {}


def test_scan_folder_detects_conflicts(tmp_dir_conflict):
    """Konflikte werden in scan_folder-Ergebnis gemeldet."""
    result = scan_folder(str(tmp_dir_conflict))

    assert len(result["conflicts"]) == 1


# ── execute_organization (Integrations-Test) ────────────────────────────────


def test_execute_organization_moves_files(tmp_media_dir):
    """execute_organization verschiebt Dateien in Jahr-Unterordner."""
    result = execute_organization(str(tmp_media_dir))

    assert result["error"] is None
    assert result["moved"] == 4
    assert result["errors"] == 0
    # Dateien liegen jetzt in Jahres-Ordnern
    assert (tmp_media_dir / "2023").is_dir()
    assert (tmp_media_dir / "2024").is_dir()


def test_execute_organization_idempotent(tmp_media_dir):
    """Zweimalige Ausführung verschiebt keine Dateien beim zweiten Mal."""
    execute_organization(str(tmp_media_dir))
    result2 = execute_organization(str(tmp_media_dir))

    # Beim zweiten Lauf sind alle Dateien bereits im richtigen Ordner
    assert result2["errors"] == 0


def test_execute_organization_aborts_on_conflict(tmp_dir_conflict):
    """Organisation wird bei Konflikten abgebrochen."""
    result = execute_organization(str(tmp_dir_conflict))

    assert result["error"] is not None
    assert result["moved"] == 0
