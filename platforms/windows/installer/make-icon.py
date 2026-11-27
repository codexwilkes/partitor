# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Make partitor.ico (16 to 256 px) from neume.png, the neume of the author's logo (black on
white, cropped). Needs Pillow and numpy; it is a maintainer tool, run by hand, not by the build:
    python make-icon.py
The rectangle and the stroke under it are drawn on whole pixels with one right edge, so the stroke
is never past the rectangle. The stroke has a fixed pixel width per size. At small sizes the three
neumes are a little smaller, so the gaps stay open."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
m = Image.open(HERE / "neume.png").convert("L")
W, H = m.size
SIZES = [16, 24, 32, 48, 64, 128, 256]
BG, INK = (255, 255, 255, 255), (17, 17, 17, 255)

arr = np.array(m) > 127
# measured in neume.png (white = ink): the rectangle and the stroke both end before column RECT_RIGHT
RECT_RIGHT, RECT_BOTTOM = 833, 417
STEM_PX = {16: 1, 24: 1, 32: 1, 48: 1, 64: 2, 128: 3, 256: 5}                    # stroke width in icon pixels
NEUMES = [(995, 133, 1482, 621), (1282, 421, 1770, 908), (1566, 708, 2053, 1196)]  # boxes in neume.png
SHRINK = {16: 0.72, 24: 0.82, 32: 0.88, 48: 0.92, 64: 0.94, 128: 0.96, 256: 1.0}


def render(px):
    ss = 8
    big = px * ss
    scale = (1 - 2 * 0.14) * px / max(W, H)             # source px -> icon px
    gw, gh = round(W * scale), round(H * scale)
    ox, oy = (px - gw) // 2, (px - gh) // 2
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=round(big * 0.18), fill=BG)
    for x0, y0, x1, y1 in NEUMES:                       # each neume is scaled about its own centre
        nw, nh = (round(v * scale * ss * SHRINK[px]) for v in (x1 - x0, y1 - y0))
        mk = Image.fromarray((arr[y0:y1, x0:x1] * 255).astype("uint8")).resize((nw, nh), Image.LANCZOS)
        at = (round((ox + (x0 + x1) / 2 * scale) * ss - nw / 2), round((oy + (y0 + y1) / 2 * scale) * ss - nh / 2))
        canvas.paste(Image.new("RGBA", mk.size, INK), at, mk)
    right = ox + round(RECT_RIGHT * scale)
    rect_bottom = oy + max(2, round(RECT_BOTTOM * scale))
    d.rectangle([ox * ss, oy * ss, right * ss - 1, rect_bottom * ss - 1], fill=INK)
    d.rectangle([(right - STEM_PX[px]) * ss, rect_bottom * ss, right * ss - 1, (oy + gh) * ss - 1], fill=INK)
    return canvas.resize((px, px), Image.BOX)           # BOX: no ringing past a pixel edge


imgs = [render(s) for s in SIZES]
imgs[-1].save(HERE / "partitor.ico", sizes=[(s, s) for s in SIZES], append_images=imgs[:-1])
print(f"wrote {HERE / 'partitor.ico'}")
