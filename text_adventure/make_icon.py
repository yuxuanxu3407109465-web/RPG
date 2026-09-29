# -*- coding: utf-8 -*-
"""生成游戏图标：icon.ico（多尺寸）和 icon_preview.png（预览）。

没有用任何第三方库，也没有图片素材：
- PNG 编码是自己按格式写的（zlib + struct）
- ICO 就是把几个尺寸的 PNG 按 Windows 的目录结构打包
- 图形用有向距离场（SDF）算覆盖度，边缘自带抗锯齿，16px 下也认得出

想改样子就改下面的配色和形状参数，然后重新运行：

    python make_icon.py

设计：深色圆角方块（能在浅色和深色桌面上都看清）+ 琥珀色圆环 + 血红的“7”
（对应“封城第七天”）。
"""

import struct
import zlib
from pathlib import Path

BASE_DIR = Path(__file__).parent

# ---------- 外观参数 ----------
BG_TOP = (30, 36, 45)          # 背景渐变：上
BG_BOTTOM = (11, 14, 18)       # 背景渐变：下
RING_COLOR = (224, 163, 60)    # 琥珀色圆环
SEVEN_COLOR = (211, 88, 64)    # 血红数字
CORNER = 0.18                  # 圆角半径（相对边长）
RING_RADIUS = 0.335            # 圆环半径
RING_WIDTH = 0.028             # 圆环半宽

# “7”的轮廓，相对坐标（顺时针）
SEVEN_SOURCE = [
    (0.290, 0.270), (0.710, 0.270), (0.710, 0.380),
    (0.520, 0.750), (0.395, 0.750), (0.575, 0.380),
    (0.290, 0.380),
]
SEVEN_SCALE = 0.86  # 往中心收一点，别贴到圆环上


def _scaled(poly, scale):
    return [(0.5 + (x - 0.5) * scale, 0.5 + (y - 0.5) * scale) for x, y in poly]


SEVEN = _scaled(SEVEN_SOURCE, SEVEN_SCALE)
SEVEN_BOX = (
    min(p[0] for p in SEVEN), min(p[1] for p in SEVEN),
    max(p[0] for p in SEVEN), max(p[1] for p in SEVEN),
)

SIZES = [256, 128, 64, 48, 32, 16]
SUBSAMPLES = 3  # 数字部分的超采样密度（抗锯齿）


def _clamp(value, low=0.0, high=1.0):
    return low if value < low else (high if value > high else value)


def _mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _rounded_box_sdf(px, py, half, radius):
    """圆角矩形的有向距离：内部为负。"""
    dx = abs(px) - (half - radius)
    dy = abs(py) - (half - radius)
    ax, ay = max(dx, 0.0), max(dy, 0.0)
    return (ax * ax + ay * ay) ** 0.5 + min(max(dx, dy), 0.0) - radius


def _in_polygon(px, py, poly):
    """射线法：点是否在多边形内。"""
    inside = False
    count = len(poly)
    for i in range(count):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % count]
        if (y1 > py) != (y2 > py):
            if px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def _seven_coverage(x, y, size):
    """数字“7”在这个像素上占多少（超采样）。坐标用 0~1 的归一化系。"""
    inv = 1.0 / size
    hits = 0
    for sy in range(SUBSAMPLES):
        qy = (y + (sy + 0.5) / SUBSAMPLES) * inv
        for sx in range(SUBSAMPLES):
            qx = (x + (sx + 0.5) / SUBSAMPLES) * inv
            if _in_polygon(qx, qy, SEVEN):
                hits += 1
    return hits / float(SUBSAMPLES * SUBSAMPLES)


def render(size):
    """画一张 size×size 的 RGBA 图，返回按行排列的像素。"""
    rows = []
    inv = 1.0 / size
    for y in range(size):
        row = []
        for x in range(size):
            px = (x + 0.5) * inv - 0.5
            py = (y + 0.5) * inv - 0.5

            # 背景：圆角方块（外面透明，桌面上不会有难看的方角）
            coverage = _clamp(0.5 - _rounded_box_sdf(px, py, 0.5, CORNER) * size)
            if coverage <= 0:
                row.append((0, 0, 0, 0))
                continue
            color = _mix(BG_TOP, BG_BOTTOM, _clamp(y * inv))

            # 圆环
            radius = (px * px + py * py) ** 0.5
            ring = _clamp(0.5 - (abs(radius - RING_RADIUS) - RING_WIDTH) * size)
            if ring > 0:
                color = _mix(color, RING_COLOR, ring)

            # 数字：先判断这个像素是否落在“7”的外框里，再算覆盖度
            nx = px + 0.5
            ny = py + 0.5
            if (SEVEN_BOX[0] - inv <= nx <= SEVEN_BOX[2] + inv
                    and SEVEN_BOX[1] - inv <= ny <= SEVEN_BOX[3] + inv):
                seven = _seven_coverage(x, y, size)
                if seven > 0:
                    color = _mix(color, SEVEN_COLOR, seven)

            row.append((color[0], color[1], color[2], int(round(coverage * 255))))
        rows.append(row)
    return rows


def png_bytes(rows, size):
    """手写 PNG：8 位 RGBA、不隔行、每行 filter=0。"""
    raw = bytearray()
    for row in rows:
        raw.append(0)
        for pixel in row:
            raw += bytes(pixel)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def ico_bytes(images):
    """把 [(尺寸, png数据)] 打包成 ICO（Windows Vista 以后支持内嵌 PNG）。"""
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    entries = b""
    payload = b""
    offset = 6 + 16 * count
    for size, blob in images:
        dim = 0 if size >= 256 else size  # 256 在 ICO 里写 0
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        payload += blob
    return header + entries + payload


def main():
    images = []
    for size in SIZES:
        images.append((size, png_bytes(render(size), size)))
    ico_path = BASE_DIR / "icon.ico"
    ico_path.write_bytes(ico_bytes(images))
    preview = BASE_DIR / "icon_preview.png"
    preview.write_bytes(dict(images)[256])
    print("已生成 %s（%d 个尺寸：%s）" % (
        ico_path.name, len(SIZES), "、".join(str(s) for s in SIZES)))
    print("预览图：%s" % preview.name)


if __name__ == "__main__":
    main()
