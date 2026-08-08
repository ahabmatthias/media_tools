"""
Video-Komprimierung: Batch-HEVC-Encoding mit ffmpeg.

Stellt zwei öffentliche Funktionen bereit:
  preview_compression() – Dry-run, gibt strukturierte Liste zurück
  compress_files()      – Führt Komprimierung aus, unterstützt progress_cb
"""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTS = {".mp4", ".mov", ".m4v"}

_LOW_BITRATE_THRESHOLD_MBPS = 5.0


# ── Datenklassen ──────────────────────────────────────────────


@dataclass
class ProbeInfo:
    width: int | None
    height: int | None
    bitrate_bps: int | None


@dataclass
class Config:
    source: Path
    target: Path
    recursive: bool
    min_size_mb: float
    low_bitrate_threshold_mbps: float
    bitrate_4k: str
    bitrate_1440p: str
    bitrate_1080p: str
    bitrate_720p: str
    fallback_bitrate: str
    codec: str  # "auto", "hevc_videotoolbox", "libx265"
    copy_original_on_skip: bool
    overwrite: bool
    dry_run: bool
    audio_bitrate: str
    copy_audio: bool


# ── Hilfsfunktionen ───────────────────────────────────────────


def human_mb(bytes_size: float) -> float:
    return bytes_size / (1024 * 1024)


def detect_videotoolbox() -> bool:
    """Prüft per Mini-Encode, ob hevc_videotoolbox zur Laufzeit funktioniert.

    Ein Listing-Check (`-h encoder=...`) reicht nicht: Der Encoder kann
    einkompiliert sein, aber zur Laufzeit fehlen – z.B. verweigert macOS 26
    x86_64-Binaries unter Rosetta das Hardware-Encoding.
    """
    try:
        res = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x240:r=10:d=0.1",
                "-frames:v",
                "1",
                "-c:v",
                "hevc_videotoolbox",
                "-b:v",
                "1M",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return res.returncode == 0
    except Exception:
        return False


def collect_files(source: Path, recursive: bool) -> list[Path]:
    if recursive:
        files = [p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]
    else:
        files = [p for p in source.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]
    files.sort()
    return files


def ffprobe_json(path: Path) -> ProbeInfo:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,bit_rate",
        "-of",
        "json",
        str(path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            return ProbeInfo(None, None, None)
        data = json.loads(res.stdout or "{}")
        streams = data.get("streams", [])
        if not streams:
            return ProbeInfo(None, None, None)
        s = streams[0]
        width = int(s.get("width")) if s.get("width") is not None else None
        height = int(s.get("height")) if s.get("height") is not None else None
        br = s.get("bit_rate")
        bitrate_bps = int(br) if br is not None else None
        return ProbeInfo(width, height, bitrate_bps)
    except Exception:
        return ProbeInfo(None, None, None)


def pick_target_bitrate(width: int | None, cfg: Config) -> str:
    if width is None:
        return cfg.fallback_bitrate
    if width >= 3840:
        return cfg.bitrate_4k
    if width >= 2560:
        return cfg.bitrate_1440p
    if width >= 1920:
        return cfg.bitrate_1080p
    return cfg.bitrate_720p


def should_skip_copy(
    file_path: Path,
    probe: ProbeInfo,
    min_size_mb: float,
    low_bitrate_threshold_mbps: float,
    target_bitrate_mbps: float,
) -> tuple[bool, str]:
    try:
        size_mb = human_mb(file_path.stat().st_size)
    except FileNotFoundError:
        return False, ""

    if size_mb < min_size_mb:
        return True, f"Überspringe kleine Datei ({size_mb:.1f} MB)"

    if probe.bitrate_bps and probe.width:
        current_mbps = probe.bitrate_bps / 1_000_000.0
        if current_mbps < low_bitrate_threshold_mbps and probe.width < 1920:
            return True, f"Bereits gut komprimiert ({current_mbps:.1f} Mbps)"
        if current_mbps <= target_bitrate_mbps * 1.2:
            return True, f"Bereits optimal komprimiert ({current_mbps:.1f} Mbps)"

    return False, ""


def categorize_error(stderr: str) -> str:
    """Translate raw ffmpeg stderr into a human-readable message."""
    s = stderr.lower()
    if "no such file or directory" in s:
        return "Datei nicht gefunden"
    if "permission denied" in s:
        return "Keine Schreibrechte im Zielordner"
    if "encoder" in s and ("not found" in s or "unknown" in s or "not available" in s):
        return "Hardware-Encoder nicht verfügbar – Software-Codec nutzen"
    if "videotoolbox" in s and ("error" in s or "failed" in s or "init" in s):
        return "Hardware-Encoder nicht verfügbar – Software-Codec nutzen"
    if "invalid data" in s or "corrupt" in s or "error while decoding" in s:
        return "Datei konnte nicht gelesen werden (möglicherweise beschädigt)"
    if "no video stream" in s or "does not contain any stream" in s:
        return "Kein Video-Stream in der Datei gefunden"
    if "already exists" in s:
        return "Zieldatei existiert bereits"
    if "no space left" in s:
        return "Kein Speicherplatz auf dem Zielgerät"
    if "moov atom not found" in s:
        return "Datei ist unvollständig oder abgebrochen"
    # Fallback: last meaningful line
    lines = stderr.strip().splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("frame="):
            return stripped[:120]
    return stderr.strip()[:120] if stderr.strip() else "Unbekannter Fehler"


def build_ffmpeg_cmd(
    src: Path,
    dst: Path,
    video_codec: str,
    target_bitrate: str,
    audio_bitrate: str,
    copy_audio: bool,
) -> list[str]:
    cmd = [
        "ffmpeg",
        "-i",
        str(src),
        "-c:v",
        video_codec,
        "-b:v",
        target_bitrate,
        "-tag:v",
        "hvc1",
    ]
    if copy_audio:
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", audio_bitrate]
    cmd += ["-movflags", "+faststart", "-y", str(dst)]
    return cmd


# ── Konfiguration ─────────────────────────────────────────────


def _make_config(
    source: Path,
    target: Path,
    recursive: bool,
    min_size_mb: float,
    codec: str,
    *,
    dry_run: bool,
) -> Config:
    return Config(
        source=source,
        target=target,
        recursive=recursive,
        min_size_mb=min_size_mb,
        low_bitrate_threshold_mbps=_LOW_BITRATE_THRESHOLD_MBPS,
        bitrate_4k="25M",
        bitrate_1440p="18M",
        bitrate_1080p="12M",
        bitrate_720p="8M",
        fallback_bitrate="15M",
        codec=codec,
        copy_original_on_skip=True,
        overwrite=False,
        dry_run=dry_run,
        audio_bitrate="128k",
        copy_audio=False,
    )


# ── Öffentliche API ───────────────────────────────────────────


def preview_compression(
    source: str,
    target: str,
    *,
    recursive: bool = False,
    min_size_mb: float = 30.0,
    codec: str = "auto",
) -> list[dict]:
    """
    Dry-run: gibt je Datei ein Dict zurück – ohne tatsächlich zu encodieren.

    Jeder Eintrag:
        {name, size_mb, resolution, current_bitrate_mbps, target_bitrate, action}
    action: "compress" | "skip" | "skip_and_copy"
    """
    source_path = Path(source)
    target_path = Path(target)
    cfg = _make_config(source_path, target_path, recursive, min_size_mb, codec, dry_run=True)
    files = collect_files(source_path, recursive)
    result = []

    for src in files:
        # Relative Struktur im Ziel spiegeln – verhindert Namenskollisionen
        # bei rekursivem Scan (gleicher Dateiname in verschiedenen Unterordnern)
        rel = src.relative_to(source_path)
        dst_encoded = (target_path / rel).with_suffix(".mp4")
        dst_copy = target_path / rel

        try:
            size_mb = round(human_mb(src.stat().st_size), 1)
        except Exception:
            size_mb = 0.0

        # Bereits existierende Zieldatei → überspringen
        if not cfg.overwrite and (dst_encoded.exists() or dst_copy.exists()):
            result.append(
                {
                    "name": str(rel),
                    "path": str(src),
                    "size_mb": size_mb,
                    "resolution": "–",
                    "current_bitrate_mbps": None,
                    "target_bitrate": "–",
                    "action": "skip_exists",
                }
            )
            continue

        probe = ffprobe_json(src)
        target_bitrate = pick_target_bitrate(probe.width, cfg)
        target_bitrate_mbps = float(target_bitrate.rstrip("M"))

        do_skip, _ = should_skip_copy(
            src, probe, min_size_mb, _LOW_BITRATE_THRESHOLD_MBPS, target_bitrate_mbps
        )

        resolution = f"{probe.width}×{probe.height}" if probe.width and probe.height else "–"
        current_bitrate_mbps = (
            round(probe.bitrate_bps / 1_000_000, 1) if probe.bitrate_bps else None
        )

        action = (
            ("skip_and_copy" if cfg.copy_original_on_skip else "skip") if do_skip else "compress"
        )

        result.append(
            {
                "name": str(rel),
                "path": str(src),
                "size_mb": size_mb,
                "resolution": resolution,
                "current_bitrate_mbps": current_bitrate_mbps,
                "target_bitrate": target_bitrate,
                "action": action,
                "probe_width": probe.width,
                "probe_height": probe.height,
                "probe_bitrate_bps": probe.bitrate_bps,
            }
        )

    return result


def compress_files(
    source: str,
    target: str,
    *,
    recursive: bool = False,
    min_size_mb: float = 30.0,
    codec: str = "auto",
    progress_cb=None,
    cached_probes: dict[str, ProbeInfo] | None = None,
) -> dict:
    """
    Führt Komprimierung aus.

    progress_cb(current, total, filename) wird vor jeder Datei aufgerufen.
    cached_probes: {voller Quellpfad: ProbeInfo} aus Preview – vermeidet erneutes ffprobe.
    Gibt zurück: {compressed, skipped, failed, hw_fallbacks, hw_unavailable, error_details}
    """
    source_path = Path(source)
    target_path = Path(target)

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return {
            "compressed": 0,
            "skipped": 0,
            "failed": 0,
            "errors": ["ffmpeg/ffprobe nicht gefunden. Bitte im PATH verfügbar machen."],
        }

    target_path.mkdir(parents=True, exist_ok=True)

    want_vt = codec in ("auto", "hevc_videotoolbox")
    use_vt = want_vt and detect_videotoolbox()
    hw_unavailable = want_vt and not use_vt
    video_codec = "hevc_videotoolbox" if use_vt else "libx265"

    cfg = _make_config(source_path, target_path, recursive, min_size_mb, codec, dry_run=False)
    files = collect_files(source_path, recursive)
    total = len(files)
    compressed = skipped = failed = 0
    hw_fallbacks = 0
    error_details: list[dict] = []

    for idx, src in enumerate(files, 1):
        if progress_cb:
            try:
                progress_cb(idx, total, src.name)
            except Exception:
                pass

        rel = src.relative_to(source_path)
        dst_encoded = (target_path / rel).with_suffix(".mp4")
        dst_copy = target_path / rel

        if not cfg.overwrite and (dst_encoded.exists() or dst_copy.exists()):
            skipped += 1
            continue

        if cached_probes and str(src) in cached_probes:
            probe = cached_probes[str(src)]
        else:
            probe = ffprobe_json(src)
        target_bitrate = pick_target_bitrate(probe.width, cfg)
        target_bitrate_mbps = float(target_bitrate.rstrip("M"))

        do_skip, _ = should_skip_copy(
            src, probe, min_size_mb, _LOW_BITRATE_THRESHOLD_MBPS, target_bitrate_mbps
        )

        if do_skip:
            if cfg.copy_original_on_skip:
                out = dst_copy
                if not cfg.overwrite and out.exists():
                    skipped += 1
                    continue
                try:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, out)
                    skipped += 1
                except Exception as e:
                    failed += 1
                    msg = categorize_error(str(e))
                    error_details.append({"file": src.name, "error": msg})
            else:
                skipped += 1
            continue

        cmd = build_ffmpeg_cmd(
            src, dst_encoded, video_codec, target_bitrate, cfg.audio_bitrate, cfg.copy_audio
        )
        try:
            dst_encoded.parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0 and dst_encoded.exists():
                compressed += 1
            else:
                # Auto-fallback: retry with software codec if hardware failed
                hw_failed = video_codec == "hevc_videotoolbox"
                if hw_failed:
                    try:
                        if dst_encoded.exists():
                            dst_encoded.unlink()
                    except Exception:
                        pass
                    cmd_sw = build_ffmpeg_cmd(
                        src,
                        dst_encoded,
                        "libx265",
                        target_bitrate,
                        cfg.audio_bitrate,
                        cfg.copy_audio,
                    )
                    proc_sw = subprocess.run(cmd_sw, capture_output=True, text=True)
                    if proc_sw.returncode == 0 and dst_encoded.exists():
                        compressed += 1
                        hw_fallbacks += 1
                        continue
                    # Both failed – report the software error (more informative)
                    proc = proc_sw

                failed += 1
                msg = categorize_error(proc.stderr or "")
                error_details.append({"file": src.name, "error": msg})
                try:
                    if dst_encoded.exists():
                        dst_encoded.unlink()
                except Exception:
                    pass
        except Exception as e:
            failed += 1
            msg = categorize_error(str(e))
            error_details.append({"file": src.name, "error": msg})

    return {
        "compressed": compressed,
        "skipped": skipped,
        "failed": failed,
        "hw_fallbacks": hw_fallbacks,
        "hw_unavailable": hw_unavailable,
        "error_details": error_details,
    }
