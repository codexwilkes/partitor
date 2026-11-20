# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Make partitor.ico (16 to 256 px) from neume.png, the neume of the author's logo (black on
white, cropped). Needs Pillow and numpy; it is a maintainer tool, run by hand, not by the build:
    python make-icon.py
The stem is drawn at a fixed pixel width per size, so the thin line stays visible at 16 px."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
m = Image.open(HERE / "neume.png").convert("L")
W, H = m.size
SIZES = [16, 24, 32, 48, 64, 128, 256]
BG, INK = (255, 255, 255, 255), (17, 17, 17, 255)

arr = np.array(m) > 127
rows = arr.shape[0]
stem_cols = np.where(arr[int(rows * 0.85):].any(axis=0))[0]
STEM_C = (stem_cols.min() + stem_cols.max()) / 2
block_bottom = int(np.where(arr[:, :int(STEM_C) - 40].any(axis=1))[0].max())   # bottom of the wide block
STEM_PX = {16: 2, 24: 2, 32: 3, 48: 3, 64: 3, 128: 4, 256: 6}                    # stem width in icon pixels

def render(px):
    ss = 8 if px < 64 else 2
    big = px * ss
    pad = 0.14 * big
    scale = (big - 2 * pad) / max(W, H)
    a2 = arr.copy()
    half = (STEM_PX[px] * ss / scale) / 2                # widen the stem to a fixed pixel width
    lo, hi = int(STEM_C - half), int(STEM_C + half) + 1
    a2[block_bottom:, max(lo, 0):hi] = True
    mk0 = Image.fromarray((a2 * 255).astype("uint8"))
    nw, nh = round(W * scale), round(H * scale)
    mk = mk0.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=round(big * 0.18), fill=BG)
    ink = Image.new("RGBA", (nw, nh), INK)
    canvas.paste(ink, (round((big - nw) / 2), round((big - nh) / 2)), mk)
    return canvas.resize((px, px), Image.LANCZOS)

imgs = [render(s) for s in SIZES]
imgs[-1].save(HERE / "partitor.ico", sizes=[(s, s) for s in SIZES], append_images=imgs[:-1])
print(f"wrote {HERE / 'partitor.ico'}")
