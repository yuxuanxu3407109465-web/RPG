# -*- coding: utf-8 -*-
"""室外街区：每局随机生成一张开放地图（街道 + 特殊地点）+ 探索迷雾。

数据写在 world.json 的 "outdoor" 里：
  size        地图多少格 × 多少格（10×10）
  spacing     两处地点之间至少隔几格（切比雪夫距离），保证建筑之间夹着街道
  street      街道模板的房间 id（一格一格复制出去）
  fixed       位置固定的地点（公寓楼、便利店：每局都在同一格）
  places      随机摆的地点（count = 这一局摆几处，names = 复制出来的第二、三处叫什么）
  locked      从外面进这几处要带东西（便利店的卷帘门要撬棍）
  street_descriptions  街道的随机描述池
  street_pool 街道的随机物资池（写在 spawn_pools 里）

规则：
· 每局重新生成一次，随机种子存进存档；读档时按同一个种子重建，所以同一局地图不会变。
· 每一格要么是一处地点（一栋楼），要么是一格街道；相邻两格之间都有路，
  唯一的例外是那面墙正好是"进楼的门"（一扇门只能通向一个地方）——那种地方地图上不画连线。
· 街道的格子场景（16×10，车 / 废墟）第一次问起时才随机生成，生成结果存进存档。
· 迷雾：去过的格子 + 它周围一圈算"已知"；已知但没去过的格子在网页地图上只画一个「?」。
"""

import copy
import random

GRID_W = 16
GRID_H = 10

# 室外只走东南西北这四面；进楼的门用的是 up / down（画在方块的右上、右下角）
DELTAS = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
DOOR_TILE = {"north": (8, 0), "south": (8, 9), "east": (15, 4), "west": (0, 4)}
DOOR_INWARD = {"north": (8, 1), "south": (8, 8), "east": (14, 4), "west": (1, 4)}
WALKABLE = (".", "+")


def _key(x, y):
    return "%d,%d" % (x, y)


class OutdoorMixin:
    """混进 engine.Game：室外街区的生成、迷雾、随机街道地形。"""

    # ---------- 生成 ----------

    def build_outdoor(self, seed=None):
        """生成这一局的室外街区：新游戏传 None（随机种子），读档传存档里的种子。"""
        cfg = getattr(self.world, "outdoor", None)
        if not cfg:
            return
        if seed is None:
            seed = self.dice.rng.randrange(1, 10 ** 9)
        self.outdoor_seed = int(seed)
        rng = random.Random(self.outdoor_seed)
        width, height = cfg["size"]
        area = cfg["area"]

        # 上一局生成出来的房间先清掉（街道格 + 复制出来的那几处地点）
        for room_id in sorted(getattr(self, "outdoor_generated", ())):
            self.world.rooms.pop(room_id, None)
        self.outdoor_generated = set()
        self.gen_grids = {}
        self.outdoor_seen = set()

        layout = {}        # (x, y) -> 房间 id
        placed = []        # [(房间 id, (x, y))]，用来算间距
        for fixed in cfg.get("fixed", []):
            x, y = fixed["at"]
            layout[(x, y)] = fixed["room"]
            placed.append((fixed["room"], (x, y)))

        # 随机摆各处地点：互相（以及和固定地点）至少隔 spacing 格
        for spec in cfg.get("places", []):
            names = list(spec.get("names") or [])
            for index in range(int(spec.get("count", 1))):
                room_id = spec["room"] if index == 0 else "%s_%d" % (spec["room"], index + 1)
                if index:
                    clone = copy.deepcopy(self.world.rooms[spec["room"]])
                    if index < len(names):
                        clone["name"] = names[index]
                    self.world.rooms[room_id] = clone
                    self.outdoor_generated.add(room_id)
                spot = self._pick_place(rng, layout, placed, width, height, int(cfg.get("spacing", 2)))
                if not spot:
                    continue
                layout[spot] = room_id
                placed.append((room_id, spot))

        # 剩下的格子全是街道。公寓楼门口那一格算"家门口的街"，模板里写死的东西（那把弯刀）留给它
        template = self.world.rooms[cfg["street"]]
        front_pos = self._front_street_pos(layout, width, height)
        for y in range(height):
            for x in range(width):
                if (x, y) in layout:
                    continue
                room_id = "street_%d_%d" % (x, y)
                clone = copy.deepcopy(template)
                clone["exits"] = {}
                clone["map"] = {"area": area, "x": x, "y": y}
                clone["random_grid"] = "street"
                clone["description"] = rng.choice(cfg.get("street_descriptions") or [template.get("description", "")])
                clone.pop("grid", None)      # 街道地形第一次进去时才生成
                if (x, y) != front_pos:
                    clone["items"] = []
                self.world.rooms[room_id] = clone
                self.outdoor_generated.add(room_id)
                layout[(x, y)] = room_id

        outdoor_ids = set(layout.values())
        # 每处地点哪一面墙是"进楼的门"：那一面不能再连街道。
        # 旧一局的出口（通到上一张地图的街道）在这里一并清掉，只留真正通楼里的那几面。
        inner_door = {}
        inner_exits = {}
        for room_id in outdoor_ids:
            keep = {}
            for direction, exit_ in (self.world.rooms[room_id].get("exits") or {}).items():
                target = exit_.get("to") if isinstance(exit_, dict) else exit_
                if target in self.world.rooms and target not in outdoor_ids:
                    keep[direction] = exit_
                    inner_door[room_id] = direction
            inner_exits[room_id] = keep
        # 连线：相邻两格之间都通
        for (x, y), room_id in layout.items():
            room = self.world.rooms[room_id]
            exits = dict(inner_exits[room_id])         # 进楼的门留着
            for direction, (dx, dy) in DELTAS.items():
                if direction in exits:
                    continue
                neighbour = layout.get((x + dx, y + dy))
                if not neighbour or inner_door.get(neighbour) == OPPOSITE[direction]:
                    continue
                exits[direction] = neighbour
            room["exits"] = exits
            room["map"] = {"area": area, "x": x, "y": y}

        # 锁着的地方（便利店）：从外面走的每一扇门都要带撬棍
        for locked_id, lock in (cfg.get("locked") or {}).items():
            for room_id in outdoor_ids - {locked_id}:
                room = self.world.rooms[room_id]
                for direction, exit_ in list(room["exits"].items()):
                    target = exit_.get("to") if isinstance(exit_, dict) else exit_
                    if target == locked_id:
                        room["exits"][direction] = dict(lock, to=locked_id)

        self.outdoor_cells = layout
        # 房间表换了：物品表 / 地面坐标表跟着补齐（读档时还会按存档重建一遍）
        if hasattr(self, "room_items"):
            for room_id, room in self.world.rooms.items():
                self.room_items.setdefault(room_id, list(room.get("items") or []))
                self.ground_positions.setdefault(room_id, [])
        self.reveal_outdoor("apartment_gate")  # 自家楼下那格一开始就"已知"
        self.reveal_outdoor()                  # 玩家现在这间（如果在室外）

    def _pick_place(self, rng, layout, placed, width, height, spacing):
        """挑一格摆地点：离已经摆好的地点至少 spacing 格；实在挑不出来就把要求放松一格。"""
        for gap in range(max(1, spacing), 0, -1):
            free = [(x, y) for y in range(height) for x in range(width)
                    if (x, y) not in layout
                    and all(max(abs(x - px), abs(y - py)) >= gap for _, (px, py) in placed)]
            if free:
                return rng.choice(free)
        return None

    def _front_street_pos(self, layout, width, height):
        """公寓楼门口那条街在哪一格（还没铺街道时按位置算）。"""
        home = next((pos for pos, rid in layout.items() if rid == "apartment_gate"), None)
        if not home:
            return None
        for direction in ("south", "east", "west", "north"):
            dx, dy = DELTAS[direction]
            spot = (home[0] + dx, home[1] + dy)
            if 0 <= spot[0] < width and 0 <= spot[1] < height and spot not in layout:
                return spot
        return None

    def _front_street(self, layout, cfg):
        """公寓楼门口那条街的房间 id（铺完街道以后才算得出来）。"""
        home = next((pos for pos, rid in layout.items() if rid == "apartment_gate"), None)
        if not home:
            return None
        x, y = home
        for direction in ("south", "east", "west", "north"):
            dx, dy = DELTAS[direction]
            room_id = layout.get((x + dx, y + dy))
            if room_id and room_id.startswith("street_"):
                return room_id
        return None

    # ---------- 迷雾 ----------

    def is_outdoor(self, room_id=None):
        room = self.world.rooms.get(room_id or self.current_room) or {}
        return bool(room.get("outdoor")) and isinstance(room.get("map"), dict)

    def reveal_outdoor(self, room_id=None):
        """把某个地点（默认玩家现在这间）和它周围一圈标成"已知"。"""
        room_id = room_id or self.current_room
        room = self.world.rooms.get(room_id) or {}
        pos = room.get("map")
        if not room.get("outdoor") or not pos:
            return
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                self.outdoor_seen.add(_key(pos["x"] + dx, pos["y"] + dy))

    def outdoor_known(self, x, y):
        return _key(x, y) in getattr(self, "outdoor_seen", ())

    def explored_outdoor(self):
        """去过（真进过门）的室外格子。"""
        return [rid for rid in self.visited if self.is_outdoor(rid)]

    # ---------- 随机街道地形 ----------

    def street_grid(self, room_id):
        """随机生一条街道：四面墙上按出口开门，中间撒上车和废墟，保证门与门之间走得通。"""
        room = self.world.rooms[room_id]
        rng = random.Random("%d|%s" % (getattr(self, "outdoor_seed", 0), room_id))
        directions = [d for d in ("north", "south", "east", "west") if d in (room.get("exits") or {})]
        for attempt in range(60):
            density = 0.22 if attempt < 36 else 0.10
            tiles = [["#"] * GRID_W for _ in range(GRID_H)]
            for y in range(1, GRID_H - 1):
                for x in range(1, GRID_W - 1):
                    tiles[y][x] = "~" if rng.random() < density else "."
            doors = {}
            for direction in directions:
                dx, dy = DOOR_TILE[direction]
                tiles[dy][dx] = "+"
                ix, iy = DOOR_INWARD[direction]
                tiles[iy][ix] = "."
                doors[direction] = [dx, dy]
            if self._street_linked(tiles, doors):
                return {"tiles": ["".join(row) for row in tiles], "doors": doors, "objects": {}}
        # 兜底：实在连通不了就来一块空地（四面的门照旧）
        tiles = [["#"] * GRID_W for _ in range(GRID_H)]
        for y in range(1, GRID_H - 1):
            for x in range(1, GRID_W - 1):
                tiles[y][x] = "."
        doors = {}
        for direction in directions:
            dx, dy = DOOR_TILE[direction]
            tiles[dy][dx] = "+"
            doors[direction] = [dx, dy]
        return {"tiles": ["".join(row) for row in tiles], "doors": doors, "objects": {}}

    def _street_linked(self, tiles, doors):
        """这一条街上，每一扇门里面那格都能从别的门走到。"""
        starts = [DOOR_INWARD[d] for d in doors]
        if len(starts) < 2:
            return True
        seen = {starts[0]}
        queue = [starts[0]]
        while queue:
            x, y = queue.pop()
            for dx, dy in DELTAS.values():
                nx, ny = x + dx, y + dy
                if not (0 <= nx < GRID_W and 0 <= ny < GRID_H):
                    continue
                spot = (nx, ny)
                if spot in seen:
                    continue
                if tiles[ny][nx] in WALKABLE:
                    seen.add(spot)
                    queue.append(spot)
        return all(start in seen for start in starts)
