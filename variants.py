"""Round 5b: platform files from the 1080x1920 master.
  *_4k.mp4  YouTube: upscaled to 2160x3840 (lanczos + light sharpen). YouTube then serves its better VP9 encode.
  *_ig.mp4  Instagram/Facebook: its own clean 1080x1920, 30 fps, High@4.1, ~5 Mbps, AAC 128k - the format Reels re-encode best.
Settings: YT_4K=off to skip, YT_4K_PRESET (default veryfast), IG_FILE=off to skip. Never raises; master is always kept."""
import os
import subprocess
from pathlib import Path


def _on(name, default="on"):
    return os.environ.get(name, default).strip().lower() not in ("off", "0", "no", "false")


def sibling(src, suffix):
    p = Path(src)
    return p.with_name(p.stem + suffix + ".mp4")


def _run(cmd, dst, log):
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        if Path(dst).exists() and Path(dst).stat().st_size > 20000:
            return True
    except Exception as e:
        err = getattr(e, "stderr", b"") or b""
        log(f"[variants] {Path(dst).name} failed: {str(e)[:60]} {err[-200:].decode(errors='ignore')}")
    Path(dst).unlink(missing_ok=True)
    return False


def make_variants(src, log=print):
    src, out = str(src), {}
    if _on("YT_4K", "off"):          # 4K OFF by default: the 1080p master is uploaded; YT_4K=on enables it
        dst = sibling(src, "_4k")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", "scale=2160:3840:flags=lanczos,unsharp=5:5:0.5:5:5:0",
               "-c:v", "libx264", "-preset", os.environ.get("YT_4K_PRESET", "veryfast"), "-crf", "17",
               "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "copy", "-movflags", "+faststart", str(dst)]
        if _run(cmd, dst, log):
            out["youtube"] = str(dst)
    if _on("IG_FILE"):
        dst = sibling(src, "_ig")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", "scale=1080:1920:flags=lanczos,format=yuv420p", "-r", "30",
               "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "medium", "-b:v", "5M",
               "-maxrate", "7M", "-bufsize", "10M", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
               "-movflags", "+faststart", str(dst)]
        if _run(cmd, dst, log):
            out["instagram"] = str(dst)
    log("[variants]", {k: Path(v).name for k, v in out.items()} or "none")
    return out


def pick(name, video):
    """file to upload to platform `name`; falls back to the master."""
    suf = {"youtube": "_4k" if _on("YT_4K", "off") else None, "instagram": "_ig", "facebook": "_ig"}.get(name)
    if suf:
        s = sibling(video, suf)
        if s.exists() and s.stat().st_size > 20000:
            return s
    return Path(video)
