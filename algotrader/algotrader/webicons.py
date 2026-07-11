"""App icons rendered as PNG with the stdlib (no image libraries).

Dark surface with the equity-line motif in the panel's series blue —
served for the PWA manifest and iOS home-screen icon.
"""
from __future__ import annotations

import struct
import zlib
from functools import lru_cache

_BG = (26, 26, 25)      # dark chart surface
_LINE = (57, 135, 229)  # series blue (dark-mode step)

_POINTS = [(0.12, 0.72), (0.30, 0.56), (0.44, 0.63), (0.60, 0.38),
           (0.74, 0.46), (0.88, 0.24)]


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


@lru_cache(maxsize=8)
def make_icon_png(size: int) -> bytes:
    canvas = [[_BG] * size for _ in range(size)]
    thick = max(2, size // 22)
    pts = [(int(x * size), int(y * size)) for x, y in _POINTS]

    def blot(cx: int, cy: int) -> None:
        for dy in range(-thick, thick + 1):
            for dx in range(-thick, thick + 1):
                if dx * dx + dy * dy <= thick * thick:
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        canvas[y][x] = _LINE

    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(steps + 1):
            blot(x0 + (x1 - x0) * i // steps, y0 + (y1 - y0) * i // steps)

    raw = b"".join(
        b"\x00" + b"".join(bytes(px) for px in row) for row in canvas
    )
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))
