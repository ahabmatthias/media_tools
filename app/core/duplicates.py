"""
Duplikat-Finder: Scannt einen Ordner und gruppiert Dateien nach MD5-Hash.

Strategie:
  1. Alle Dateien nach Größe gruppieren  (nur stat-Aufruf, sehr schnell)
  2. Größen-Gruppen mit ≥ 2 Dateien: nur das erste MiB hashen
     (unterscheidet z.B. zwei 8-GB-Videos, ohne sie komplett zu lesen)
  3. Nur Gruppen, die auch im Kopf-Hash übereinstimmen, komplett hashen
  4. Hash-Gruppen mit ≥ 2 Dateien zurückgeben
"""

import hashlib
import os
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

_HEAD_SIZE = 1 << 20  # 1 MiB


def _md5(path: Path, chunk_size: int = 65536, limit: int | None = None) -> str:
    h = hashlib.md5()
    remaining = limit
    with open(path, "rb") as f:
        while True:
            n = chunk_size if remaining is None else min(chunk_size, remaining)
            if n <= 0:
                break
            chunk = f.read(n)
            if not chunk:
                break
            h.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return h.hexdigest()


def find_duplicates(
    folder: str,
    progress_cb: Callable[[int, int], None] | None = None,
    extensions: set[str] | None = None,
    recursive: bool = True,
) -> dict[str, list[str]]:
    """
    Scannt `folder` rekursiv und gibt {hash: [pfad1, pfad2, ...]} zurück – nur
    Gruppen mit ≥ 2 Dateien. `progress_cb` wird optional nach jedem gehashten
    File mit (scanned, total) aufgerufen. Wenn `extensions` gesetzt ist, werden
    nur Dateien mit diesen Extensions berücksichtigt.
    """
    # Schritt 1: nach Größe gruppieren
    by_size: dict[int, list[Path]] = defaultdict(list)
    walker = os.walk(folder) if recursive else [(folder, [], os.listdir(folder))]
    for root, _, files in walker:
        for name in files:
            path = Path(root) / name
            if path.is_file() and not name.startswith("."):
                if extensions is not None and path.suffix.lower() not in extensions:
                    continue
                try:
                    by_size[path.stat().st_size].append(path)
                except (OSError, PermissionError):
                    pass

    head_total = sum(len(paths) for paths in by_size.values() if len(paths) >= 2)
    scanned = 0

    # Schritt 2: Kandidaten (gleiche Größe) nur am Dateianfang hashen
    by_head: dict[tuple[int, str], list[Path]] = defaultdict(list)
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue  # einzigartige Größe → kein Duplikat möglich
        for path in paths:
            try:
                by_head[(size, _md5(path, limit=_HEAD_SIZE))].append(path)
            except (OSError, PermissionError):
                pass
            scanned += 1
            if progress_cb and head_total > 0:
                # Provisorisches Gesamt: Voll-Hash-Anteil ist noch unbekannt
                progress_cb(scanned, head_total * 2)

    # Schritt 3: nur bei übereinstimmendem Kopf-Hash komplett hashen
    full_total = sum(
        len(paths) for (size, _), paths in by_head.items() if len(paths) >= 2 and size > _HEAD_SIZE
    )
    total = head_total + full_total

    hashes: dict[str, list[str]] = defaultdict(list)
    for (size, head_hash), paths in by_head.items():
        if len(paths) < 2:
            continue
        if size <= _HEAD_SIZE:
            # Datei komplett im Kopf-Hash enthalten → ist bereits der Voll-Hash
            for path in paths:
                hashes[head_hash].append(str(path))
            continue
        for path in paths:
            try:
                hashes[_md5(path)].append(str(path))
            except (OSError, PermissionError):
                pass
            scanned += 1
            if progress_cb and total > 0:
                progress_cb(scanned, total)

    return {h: paths for h, paths in hashes.items() if len(paths) > 1}
