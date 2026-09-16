"""ffmpeg wrappers: frame extraction, sampling, normalising, concatenation."""
from __future__ import annotations

import subprocess
from pathlib import Path

OUTPUT_SIZE = (1080, 1920)
FPS = 30


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
    for old in list(out_dir.glob("f_*.png")) + list(out_dir.glob("raw_*.png")):
        old.unlink()
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", f"select='not(mod(n\\,{every}))'",
         "-fps_mode", "vfr", "-start_number", "0", str(out_dir / "raw_%04d.png")])
    renamed = []
    for i, f in enumerate(sorted(out_dir.glob("raw_*.png"))):
        dst = out_dir / f"f_{i * every + 1:04d}.png"
        f.rename(dst)
        renamed.append(dst)
    return renamed


def has_audio(src: Path) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                          "-of", "csv=p=0", str(src)], capture_output=True, text=True).stdout
    return bool(out.strip())


def normalise(src: Path, dst: Path, start: float, duration: float, keep_audio: bool = False,
              overlay: Path | None = None, size=OUTPUT_SIZE, fps: int = FPS) -> Path:
    """One encode per part: cover-crop to 9:16 (rotation metadata is applied by ffmpeg's autorotate),
    constant fps, optional caption overlay, trimmed; audio kept or replaced by stereo silence of the
    same length, so every part shares codec parameters and concat can stream-copy."""
    w, h = size
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},setsar=1"
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src),
           "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    graph = [f"[0:v]{vf}[base]"]
    if overlay:
        cmd += ["-i", str(overlay)]
        graph.append(f"[base][2:v]overlay=0:0,format=yuv420p[v]")
    else:
        graph.append("[base]format=yuv420p[v]")
    if keep_audio:
        graph.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo[src];"
                     f"[src][1:a]amix=inputs=2:duration=longest:normalize=0,atrim=0:{duration:.3f}[a]")
        amap = "[a]"
    else:
        amap = "1:a:0"
    cmd += ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", amap,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-r", str(fps),
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-t", f"{duration:.3f}", str(dst)]
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(cmd)
    return dst


def _concat_escape(p: Path) -> str:
    s = str(p.resolve())
    if "\n" in s or "\r" in s:
        raise ValueError(f"path contains a newline: {s!r}")
    return "'" + s.replace("'", "'\\''") + "'"


def concat(parts: list[Path], dst: Path) -> Path:
    """Stream-copy when parts match (they do when all came from normalise); re-encode as a fallback."""
    listing = dst.with_suffix(".txt")
    listing.write_text("".join(f"file {_concat_escape(p)}\n" for p in parts))
    base = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing)]
    try:
        run(base + ["-c", "copy", "-movflags", "+faststart", str(dst)])
    except RuntimeError:
        run(base + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac",
                    "-movflags", "+faststart", str(dst)])
    listing.unlink()
    return dst


def loudnorm(src: Path, dst: Path, target: float, audio: Path | None = None) -> Path:
    """Two-pass EBU R128 normalisation to `target` LUFS; with `audio`, replace the soundtrack first.

    Single-pass loudnorm runs in dynamic mode and undershoots on short clips (measured -17.3
    for a -14 target on a 20 s cut), so the first pass measures and the second applies linear gain.
    """
    import json

    base = src
    if audio:
        base = dst.with_name(dst.stem + "-swapped.mp4")
        run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-i", str(audio), "-map", "0:v", "-map", "1:a",
             "-shortest", "-c:v", "copy", "-c:a", "aac", "-ar", "48000", str(base)])
    spec = f"loudnorm=I={target}:TP=-1.5:LRA=11"
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(base), "-map", "0:a:0",
                          "-af", f"{spec}:print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
    try:
        m = json.loads(err[err.rindex("{"):err.rindex("}") + 1])
    except ValueError:
        raise RuntimeError(f"loudnorm measurement failed: {err.strip()[-300:]}")
    af = (f"{spec}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
          f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(base), "-c:v", "copy", "-af", af, "-c:a", "aac", "-ar", "48000",
         "-movflags", "+faststart", str(dst)])
    if audio:
        base.unlink(missing_ok=True)
    return dst
