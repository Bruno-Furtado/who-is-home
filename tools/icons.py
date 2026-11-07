#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera os ícones do app (static/icon.svg e os PNGs) sem dependências: a casinha violeta sobre o grafite
(o mesmo fundo do ícone do down-again), rasterizada por distância até os traços (bordas suavizadas).

    python3 tools/icons.py
"""
import math
import os
import struct
import zlib

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
STATIC = os.path.join(ROOT, "static")
C1, C2 = (0x3b, 0x34, 0x70), (0x17, 0x18, 0x1d)     # brilho violeta no canto → grafite (igual ao logo do painel)
INK = (0xa7, 0x8b, 0xfa)                             # casinha

# casinha numa grade 24x24 (igual ao SVG do logo)
ROOF = [(3, 11.5), (12, 4), (21, 11.5)]
WALLS = [(5.5, 9.5), (5.5, 20), (18.5, 20), (18.5, 9.5)]
DOOR = [(8.5, 20), (8.5, 15.5)] + [(12 - 3.5 * math.cos(a), 15.5 - 3.5 * math.sin(a))
                                   for a in [i * math.pi / 12 for i in range(1, 12)]] + [(15.5, 15.5), (15.5, 20)]
STROKE = 2.2
SVG_PATH = "M3 11.5L12 4l9 7.5M8.5 20v-4.5a3.5 3.5 0 0 1 7 0V20M5.5 9.5V20h13V9.5"


def segments(scale, offset):
    out = []
    for line in (ROOF, WALLS, DOOR):
        pts = [(offset + x * scale, offset + y * scale) for x, y in line]
        out += list(zip(pts, pts[1:]))
    return out


def dist(px, py, a, b):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def render(size):
    radius = size * 0.225
    scale = size * 0.62 / 24          # desenho ocupa ~62% do ícone
    offset = (size - 24 * scale) / 2
    segs = segments(scale, offset)
    half = STROKE * scale / 2
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            # canto arredondado (cobertura suavizada)
            cx = min(max(px, radius), size - radius)
            cy = min(max(py, radius), size - radius)
            edge = max(0.0, min(1.0, radius - math.hypot(px - cx, py - cy) + 0.5))
            k = min(1.0, math.hypot(px, py) / (0.95 * size))         # degradê radial a partir do canto de cima
            bg = [C1[i] + (C2[i] - C1[i]) * k for i in range(3)]
            d = min(dist(px, py, a, b) for a, b in segs)
            ink = max(0.0, min(1.0, half - d + 0.5))
            rgb = [int(round(c + (INK[i] - c) * ink)) for i, c in enumerate(bg)]
            row += bytes(rgb + [int(round(255 * edge))])
        rows.append(bytes(row))
    return rows


def png(rows, size):
    raw = b"".join(b"\x00" + r for r in rows)
    chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    s = 64 * 0.62 / 24
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><defs>'
           '<radialGradient id="g" cx="0" cy="0" r="1.2"><stop offset="0" stop-color="#3b3470"/>'
           '<stop offset=".7" stop-color="#17181d"/></radialGradient></defs><rect width="64" height="64" rx="14.4" fill="url(#g)"/>'
           '<path transform="translate(%.2f %.2f) scale(%.4f)" d="%s" fill="none" stroke="#a78bfa" stroke-width="%.1f" '
           'stroke-linecap="round" stroke-linejoin="round"/></svg>\n') % ((64 - 24 * s) / 2, (64 - 24 * s) / 2, s, SVG_PATH, STROKE)
    with open(os.path.join(STATIC, "icon.svg"), "w") as f:
        f.write(svg)
    for size in (180, 192, 512):
        with open(os.path.join(STATIC, "icon-%d.png" % size), "wb") as f:
            f.write(png(render(size), size))
        print("static/icon-%d.png" % size)


if __name__ == "__main__":
    main()
