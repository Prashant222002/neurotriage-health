"""Round 3 - the NeuroTriage logo, drawn the same way everywhere (reel, long video, end card, thumbnail).

Rules (so it only ever looks tasteful, never like a sticker slapped on top):
  * always a clean CIRCLE with a thin white ring and a soft shadow (the source icon is a rounded square -> we crop it)
  * small: reel 76 px on a 1080 px wide frame (7%), long 62 px on 1920 (3%), thumbnail 120 px
  * semi-transparent (<= 85%), fades in after the first 1.2 s so it never competes with the hook
  * sits in the corner that platform UIs leave empty (top-right below the status bar for reels)
  * ASSET GATE: if assets/logo.png is missing, too small (< 200 px), not roughly square or fully blank, the logo is
    skipped and one warning is printed - the build continues without it.
  * LOGO=off in build.yml removes it everywhere.
"""
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).parent / "assets"
_cache = {}


def enabled():
    return os.environ.get("LOGO", "on").strip().lower() not in ("off", "0", "no", "false")


def gate(path):
    """-> (ok, reason)."""
    p = Path(path)
    if not p.exists():
        return False, f"{p.name} not found"
    try:
        im = Image.open(p)
        w, h = im.size
    except Exception as e:
        return False, f"unreadable ({str(e)[:50]})"
    if min(w, h) < 200:
        return False, f"too small ({w}x{h}, need >= 200 px)"
    if not 0.8 <= w / h <= 1.25:
        return False, f"not square ({w}x{h})"
    rgb = np.asarray(im.convert("RGB"))
    if rgb.std() < 3:
        return False, "image is blank"
    return True, ""


def circle(path, size, ring=True, shadow=True):
    """RGBA uint8 array (size+2*pad square, transparent outside the circle). None if the gate fails."""
    ok, why = gate(path)
    if not ok:
        return None
    ss = 4                                                     # supersample for a smooth edge
    pad = int(size * 0.22) if shadow else 2
    im = Image.open(path).convert("RGBA")
    s = min(im.size)
    im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width + s) // 2, (im.height + s) // 2))
    big = size * ss
    im = im.resize((big, big), Image.LANCZOS)
    inset = int(big * 0.03)                                    # lose the icon's rounded-square corners
    m = Image.new("L", (big, big), 0)
    ImageDraw.Draw(m).ellipse((inset, inset, big - inset - 1, big - inset - 1), fill=255)
    disc = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    disc.paste(im, (0, 0), m)
    if ring:
        ImageDraw.Draw(disc).ellipse((inset, inset, big - inset - 1, big - inset - 1),
                                     outline=(255, 255, 255, 215), width=max(2, int(big * 0.035)))
    disc = disc.resize((size, size), Image.LANCZOS)
    can = Image.new("RGBA", (size + 2 * pad, size + 2 * pad), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", can.size, (0, 0, 0, 0))
        a = disc.split()[3].point(lambda v: int(v * 0.45))
        sh.paste((0, 0, 0, 255), (pad, pad + max(2, size // 18)), a)
        can = Image.alpha_composite(can, sh.filter(ImageFilter.GaussianBlur(max(2, size // 10))))
    can.alpha_composite(disc, (pad, pad))
    return np.array(can)


def load(size, assets=None, **kw):
    """Cached circle logo at `size`; None when disabled or the asset gate fails (warns once)."""
    if not enabled():
        return None
    p = Path(assets or ASSETS) / "logo.png"
    k = (str(p), size, tuple(sorted(kw.items())))
    if k not in _cache:
        arr = circle(p, size, **kw)
        if arr is None:
            ok, why = gate(p)
            print(f"[logo] skipped: {why}", flush=True)
        _cache[k] = arr
    return _cache[k]


def pad_of(size):
    return int(size * 0.22)


def fade(t, start=1.2, dur=0.6, peak=0.82):
    """opacity over time: invisible during the hook, then fades in to `peak`."""
    return max(0.0, min(1.0, (t - start) / dur)) * peak
