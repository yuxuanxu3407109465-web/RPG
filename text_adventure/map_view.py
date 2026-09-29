"""地图显示：根据 world.json 里每个地点的 map 标注，画出文字地图。"""

import sys
import unicodedata

GAP = 4  # 同一行相邻两个地点之间的横向间距
GRAY, GREEN, RESET = "\033[90m", "\033[1;32m", "\033[0m"
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}


def text_width(s):
    """终端里的显示宽度：中文等全角字符占 2 格。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def exit_target(exit_):
    """出口可能是房间 id，也可能是带条件的对象。"""
    return exit_["to"] if isinstance(exit_, dict) else exit_


def connected(world, a, b, direction):
    """a 往 direction 走能到 b，或者 b 往反方向走能到 a。"""
    if a is None or b is None:
        return False
    a_exit = world.rooms[a]["exits"].get(direction)
    b_exit = world.rooms[b]["exits"].get(OPPOSITE[direction])
    return (a_exit is not None and exit_target(a_exit) == b) or (
        b_exit is not None and exit_target(b_exit) == a
    )


def render_map(world, current, visited, room_items):
    use_color = sys.stdout.isatty()

    def label(rid):
        room = world.rooms[rid]
        stairs = ("↑" if "up" in room["exits"] else "") + ("↓" if "down" in room["exits"] else "")
        if rid == current:
            text, color = f"[★{room['name']}]", GREEN
        elif rid in visited:
            text, color = f"[{room['name']}]", ""
        else:
            text, color = f"({room['name']})", GRAY
        return text + stairs, color

    labels = {rid: label(rid) for rid in world.rooms if "map" in world.rooms[rid]}
    cell_width = max(text_width(text) for text, _ in labels.values())

    def cell(rid, linked_east):
        """一个地点占一格（左对齐），与右边相连时用横线补满到下一格。"""
        if rid is None:
            return " " * (cell_width + GAP)
        text, color = labels[rid]
        fill = cell_width - text_width(text) + GAP
        if use_color and color:
            text = color + text + RESET
        if linked_east:
            return text + " " + "─" * (fill - 2) + " "
        return text + " " * fill

    lines = [
        "======== 地图 ========",
        "★ 你的位置   [ ] 已探索   ( ) 未探索   ↑↓ 有楼梯",
    ]
    for area in world.map_areas:
        grid = {}
        for rid, room in world.rooms.items():
            pos = room.get("map")
            if pos and pos["area"] == area:
                grid[(pos["x"], pos["y"])] = rid
        if not grid:
            continue
        max_x = max(x for x, _ in grid)
        max_y = max(y for _, y in grid)

        lines.append(f"\n【{area}】")
        for y in range(max_y + 1):
            row = "  "
            for x in range(max_x + 1):
                rid = grid.get((x, y))
                row += cell(rid, connected(world, rid, grid.get((x + 1, y)), "east"))
            lines.append(row.rstrip())

            if y < max_y:
                row = "  "
                for x in range(max_x + 1):
                    linked = connected(world, grid.get((x, y)), grid.get((x, y + 1)), "south")
                    row += "  " + ("│" if linked else " ") + " " * (cell_width + GAP - 3)
                lines.append(row.rstrip())

    # 只列出去过的地点里的物资和人物，没进去过的地方不透露
    known = []
    for rid in world.rooms:
        if rid not in visited:
            continue
        room = world.rooms[rid]
        things = [world.items[i]["name"] for i in room_items[rid]]
        things += [world.npcs[n]["name"] for n in room.get("npcs", [])]
        if things:
            known.append(f"  {room['name']}：" + "、".join(things))
    if known:
        lines.append("\n已探索地点的情况：")
        lines.extend(known)
    return "\n".join(lines)
