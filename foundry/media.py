"""ffmpeg wrappers: frame extraction, sampling, normalising, concatenation."""
from __future__ import annotations

import subprocess
from pathlib import Path


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({' '.join(cmd[:6])} ...): {r.stderr.strip()[-600:]}")


def frame_at(video: Path, t: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(out)])
    return out


def sample_frames(video: Path, out_dir: Path, every: int = 10) -> list[Path]:
    """Frame 1 plus every Nth frame, as f_0001.png, f_0011.png, ..."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f_*.png"):
        old.unlink()
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", f"select='not(mod(n\\,{every}))'",
         "-vsync", "vfr", "-start_number", "0", str(out_dir / "raw_%04d.png")])
    frames = sorted(out_dir.glob("raw_*.png"))
    renamed = []
    for i, f in enumerate(frames):
        dst = out_dir / f"f_{i * every + 1:04d}.png"
        f.rename(dst)
        renamed.append(dst)
    return renamed


def normalise(src: Path, dst: Path, start: float, duration: float, size=(1080, 1920), fps: int = 30,
              keep_audio: bool = False) -> Path:
    """Cover-crop to 9:16, fixed fps, trimmed; audio either kept (resampled) or replaced by silence."""
    w, h = size
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},setsar=1,format=yuv420p"
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src)]
    if keep_audio:
        cmd += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                "-filter_complex", f"[0:v]{vf}[v];[0:a][1:a]amix=inputs=2:duration=longest:normalize=0,atrim=0:{duration:.3f}[a]",
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                "-vf", vf, "-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-ar", "48000", "-ac", "2",
            "-shortest", str(dst)]
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(cmd)
    return dst


def has_audio(src: Path) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                          "-of", "csv=p=0", str(src)], capture_output=True, text=True).stdout
    return bool(out.strip())


def burn_overlay(src: Path, png: Path, dst: Path) -> Path:
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-i", str(png), "-filter_complex", "[0:v][1:v]overlay=0:0",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "copy", str(dst)])
    return dst


def concat(parts: list[Path], dst: Path) -> Path:
    listing = dst.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-movflags", "+faststart", str(dst)])
    listing.unlink()
    return dst
