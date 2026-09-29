"""文字冒险游戏引擎：负责世界数据、游戏状态和指令解析。"""

import json
import shutil
from pathlib import Path

import dice as dice_rules
import items
import skills
import stances
import stats
from character import Character, format_sheet
from map_view import render_map

# 各种写法 -> 内部方向名
DIRECTIONS = {
    "北": "north", "n": "north", "north": "north",
    "南": "south", "s": "south", "south": "south",
    "东": "east", "e": "east", "east": "east",
    "西": "west", "w": "west", "west": "west",
    "上": "up", "u": "up", "up": "up",
    "下": "down", "d": "down", "down": "down",
}
DIRECTION_NAMES = {
    "north": "北", "south": "南", "east": "东",
    "west": "西", "up": "上", "down": "下",
}

# 休息时长的中文写法
REST_WORDS = {
    "半小时": 30, "一小时": 60, "1小时": 60, "两小时": 120, "2小时": 120,
    "四小时": 240, "4小时": 240, "八小时": 480, "8小时": 480,
}


def parse_minutes(text):
    """把“30”“半小时”“2小时”“90分钟”都换算成分钟数，认不出来返回 0。"""
    text = text.strip()
    if text in REST_WORDS:
        return REST_WORDS[text]
    if text.endswith("小时"):
        text = text[:-2].strip()
        unit = 60
    elif text.endswith("分钟"):
        text = text[:-2].strip()
        unit = 1
    else:
        unit = 1
    try:
        return int(float(text) * unit)
    except ValueError:
        return 0


SLOT_COUNT = 3  # 存档槽位数量


def migrate_old_save(save_dir):
    """把老版本的单存档（save.json）复制到 1 号槽。

    早期版本只有一个存档文件，改成多槽位之后旧进度会“消失”，所以启动时
    静默搬一次（保留原文件，不删）。
    """
    old = Path(save_dir) / "save.json"
    first = Path(save_dir) / "save1.json"
    if old.exists() and not first.exists():
        try:
            shutil.copyfile(old, first)
            return True
        except OSError:
            return False
    return False


class World:
    """只读的世界数据（地图、物品、NPC），从 JSON 文件加载。"""

    def __init__(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.title = data["title"]
        self.intro = data["intro"]
        self.start_room = data["start_room"]
        self.rooms = data["rooms"]
        self.items = data["items"]
        self.npcs = data["npcs"]
        self.map_areas = data.get("map_areas", [])
        self.weapon_types = data.get("weapon_types", {})  # 武器类型 id -> 显示名


class Game:
    """一局游戏的可变状态，以及所有玩家指令。"""

    def __init__(self, world, options, skill_trees, dice, save_path):
        self.world = world
        self.options = options
        self.skill_trees = skill_trees
        self.dice = dice
        # 存档分成几个槽：save1.json / save2.json / save3.json
        self.save_dir = Path(save_path).parent
        self.slot = 1
        self.save_path = self.slot_path(self.slot)
        migrate_old_save(self.save_dir)
        self.character = None
        self.running = True
        self.reset()
        # (别名列表, 处理函数)，别名越长越优先匹配
        self.commands = [
            (["看", "观察", "look", "l"], self.cmd_look),
            (["查看", "检查", "examine", "x"], self.cmd_examine),
            (["走", "去", "go"], self.cmd_go),
            (["拿", "捡", "拾取", "take", "get"], self.cmd_take),
            (["放下", "丢掉", "drop"], self.cmd_drop),
            (["背包", "物品", "inventory", "i"], self.cmd_inventory),
            (["地图", "map", "m"], self.cmd_map),
            (["角色", "状态", "status", "c"], self.cmd_status),
            (["技能", "skills", "k"], self.cmd_skills),
            (["学习", "learn"], self.cmd_learn),
            (["装备", "equip"], self.cmd_equip),
            (["卸下", "unequip"], self.cmd_unequip),
            (["姿态", "stance"], self.cmd_stance),
            (["掷骰", "roll"], self.cmd_roll),
            (["检定", "check"], self.cmd_check),
            (["骰子系统", "dice"], self.cmd_dice_system),
            (["使用", "吃", "喝", "use"], self.cmd_use),
            (["休息", "睡", "rest"], self.cmd_rest),
            (["说话", "交谈", "对话", "talk"], self.cmd_talk),
            (["存档", "save"], self.cmd_save),
            (["读档", "load"], self.cmd_load),
            (["帮助", "help", "h", "?"], self.cmd_help),
            (["退出", "quit", "q"], self.cmd_quit),
        ]
        # 摊平并排序一次即可：指令表是静态的，没必要每输入一行都重建一遍
        self.aliases = [(a, fn) for names, fn in self.commands for a in names]
        self.aliases.sort(key=lambda pair: len(pair[0]), reverse=True)

    def reset(self):
        self.current_room = self.world.start_room
        self.inventory = []
        self.equipment = {"main_hand": None, "off_hand": None}  # 双手武器会同时占两个位置
        self.stance = None  # 当前姿态 id
        self.turns = 0
        self.day = stats.START_DAY  # 计时器：第几天
        self.minutes = stats.START_MINUTES  # 计时器：当天已经过去的分钟数
        self._load_notice = ""  # 读档时若按新版本适配过，这里放一句提示
        # 去过的地点（地图上的显示方式不同，内容也只对去过的地点公开）
        self.visited = {self.current_room}
        # 每个房间里现有的物品（会随玩家拿取/丢弃而变化）
        self.room_items = {rid: list(r.get("items", [])) for rid, r in self.world.rooms.items()}
        # 每个 NPC 已经说到第几句
        self.dialogue_index = {nid: 0 for nid in self.world.npcs}

    def start_new(self, character):
        """用新创建的角色开始一局游戏，背景自带的物品放进背包。"""
        self.reset()
        self.character = character
        background = self.options.background(character.background)
        self.inventory = list(background.get("starting_items", []))
        character.hp = stats.max_hp(character.attributes, character.level)
        character.stamina = stats.stamina_max(character.attributes)

    # ---------- 存档槽位 ----------

    def slot_path(self, slot):
        """第 n 号存档的文件路径（从 1 开始）。"""
        return self.save_dir / f"save{slot}.json"

    def use_slot(self, slot):
        """切换当前使用的存档槽。"""
        self.slot = slot
        self.save_path = self.slot_path(slot)

    def has_save(self):
        """任意一个槽里有存档。"""
        return any(self.slot_path(n).exists() for n in range(1, SLOT_COUNT + 1))

    def newest_slot(self):
        """最近改过的那个槽；都没有就返回 1。"""
        existing = [n for n in range(1, SLOT_COUNT + 1) if self.slot_path(n).exists()]
        if not existing:
            return 1
        return max(existing, key=lambda n: self.slot_path(n).stat().st_mtime)

    def slot_info(self, slot):
        """读一个槽的概要，给界面显示用。空槽返回 None，文件坏了返回 broken。"""
        path = self.slot_path(slot)
        if not path.exists():
            return None
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {"slot": slot, "exists": True, "broken": True, "name": "存档损坏",
                    "level": "-", "room": "-", "time": "-"}
        character = state.get("character") or {}
        room = self.world.rooms.get(state.get("current_room"), {})
        day = state.get("day", stats.START_DAY)
        minutes = state.get("minutes", stats.START_MINUTES)
        background = self.options.background(character["background"])["name"] \
            if character.get("background") else ""
        return {
            "slot": slot,
            "exists": True,
            "broken": False,
            "name": character.get("name") or "无名幸存者",
            "level": character.get("level", 1),
            "background": background,
            "room": room.get("name", state.get("current_room") or "未知地点"),
            "day": day,
            "minutes": minutes,
            "time": "第 %d 天 %02d:%02d" % (day, minutes // 60, minutes % 60),
        }

    def _parse_slot(self, arg):
        """从“存档 2”这类参数里取槽位号，返回 (槽位, 错误文字)。"""
        arg = (arg or "").strip()
        if not arg:
            return self.slot, None
        if arg.isdigit() and 1 <= int(arg) <= SLOT_COUNT:
            return int(arg), None
        return None, "存档槽位要写 1~%d，例如：存档 2" % SLOT_COUNT

    # ---------- 指令解析 ----------

    def handle(self, text):
        """处理一行玩家输入，返回要显示的文字。"""
        text = text.strip().lower()
        if not text:
            return ""
        if text in DIRECTIONS:
            return self.cmd_go(text)

        for alias, fn in self.aliases:
            if alias.isascii():
                # 英文指令需要用空格和参数隔开，避免 "i" 误匹配 "inn"
                if text == alias or text.startswith(alias + " "):
                    return fn(text[len(alias):].strip())
            elif text.startswith(alias):
                # 中文指令允许不加空格，例如 "拿火把"
                return fn(text[len(alias):].strip())
        return "我不明白你的意思。输入“帮助”查看可用指令。"

    # ---------- 查找工具 ----------

    def _match(self, arg, ids, table):
        """在给定的物品/NPC id 列表中，按名字或别名找到与 arg 匹配的那一个。"""
        for obj_id in ids:
            obj = table[obj_id]
            names = [obj["name"].lower()] + [a.lower() for a in obj.get("aliases", [])]
            if arg in names or any(arg in n for n in names):
                return obj_id
        return None

    def _room(self):
        return self.world.rooms[self.current_room]

    def describe_room(self):
        room = self._room()
        lines = [f"【{room['name']}】", room["description"]]
        items = self.room_items[self.current_room]
        if items:
            lines.append("你看到：" + "、".join(self.world.items[i]["name"] for i in items))
        npcs = room.get("npcs", [])
        if npcs:
            lines.append("这里有：" + "、".join(self.world.npcs[n]["name"] for n in npcs))
        if self.character and self.character.companions:
            names = "、".join(c.name for c in self.character.companions)
            lines.append(f"{names}跟在你身边。")
        exits = "、".join(DIRECTION_NAMES.get(d, d) for d in room["exits"])
        lines.append(f"出口：{exits}")
        return "\n".join(lines)

    # ---------- 指令实现 ----------

    def cmd_look(self, arg):
        if arg:
            return self.cmd_examine(arg)
        return self.describe_room()

    def cmd_examine(self, arg):
        if not arg:
            return "你想查看什么？"
        visible_items = self.inventory + self.room_items[self.current_room]
        item_id = self._match(arg, visible_items, self.world.items)
        if item_id:
            return self.world.items[item_id]["description"]
        npc_id = self._match(arg, self._room().get("npcs", []), self.world.npcs)
        if npc_id:
            return self.world.npcs[npc_id]["description"]
        return "这里没有这样东西。"

    def cmd_go(self, arg):
        direction = DIRECTIONS.get(arg)
        if not direction:
            return "你想往哪个方向走？（东/南/西/北/上/下）"
        room = self._room()
        exit_ = room["exits"].get(direction)
        if exit_ is None:
            return self._no_path(room, direction)
        # 出口可以是房间 id，也可以是带条件的对象
        if isinstance(exit_, dict):
            required = exit_.get("requires")
            if required and required not in self.inventory:
                return exit_.get("blocked_message", "你过不去。")
            exit_ = exit_["to"]

        outdoor = bool(room.get("outdoor"))
        cost = 0
        if self.character:
            cost = stats.move_cost(self.character.attributes, outdoor)
            if self.character.stamina < cost:
                return (f"体力不够：走这一步要 {cost} 点，你只剩 {self.character.stamina} 点。\n"
                        f"先休息一下吧（例如：休息 60）。")

        first_visit = exit_ not in self.visited
        self.current_room = exit_
        self.visited.add(exit_)
        self.turns += 1
        if self.character:
            self.character.stamina = max(0, self.character.stamina - cost)
            self.advance_time(stats.move_minutes(outdoor))
        self._regenerate()
        text = self.describe_room()
        if first_visit and self.character:
            text += "\n\n探索了新地点。" + stats.gain_xp(
                self.character, self.options.progression["explore_xp"], self.options
            )
        shock = self._check_shock()
        if shock:
            text += "\n\n" + shock
        return text

    # ---------- 时间与体力 ----------

    def clock_text(self):
        """计时器文字：第几天 + 当天时间。"""
        return f"第 {self.day} 天 {self.minutes // 60:02d}:{self.minutes % 60:02d}"

    def advance_time(self, minutes):
        """推进时间，跨过午夜就进入下一天。"""
        self.minutes += minutes
        while self.minutes >= stats.MINUTES_PER_DAY:
            self.minutes -= stats.MINUTES_PER_DAY
            self.day += 1

    def _no_path(self, room, direction):
        """那个方向走不通：普通房间说墙壁，走廊和室外说有障碍物。"""
        name = DIRECTION_NAMES.get(direction, direction)
        if room.get("blocked") == "障碍物":
            return f"{name}边有障碍物，过不去。"
        return f"{name}边是墙壁，没有路。"

    def _check_shock(self):
        """体力归零会当场休克：失去行动能力，强制休息到缓过来。"""
        c = self.character
        if not c or c.stamina > 0:
            return ""
        cap = stats.stamina_max(c.attributes)
        target = int(cap * stats.SHOCK_WAKE_RATIO)
        minutes = 0
        while c.stamina < target:
            c.stamina = min(
                cap, c.stamina + stats.rest_recovery(c.attributes, stats.REST_MINUTES_PER_TICK)
            )
            self.advance_time(stats.REST_MINUTES_PER_TICK)
            minutes += stats.REST_MINUTES_PER_TICK
        return (f"你眼前一黑，直接瘫倒在地上——体力彻底耗尽了。\n"
                f"（休克：强制休息 {minutes // 60} 小时 {minutes % 60} 分钟，"
                f"醒来时是 {self.clock_text()}，体力 {c.stamina}/{cap}）")

    def cmd_rest(self, arg):
        c = self.character
        if not c:
            return "还没有创建角色。"
        if not arg:
            return "你想休息多久？例如：休息 30、休息 2小时（每半小时恢复 10% 体力上限）"
        minutes = parse_minutes(arg)
        if minutes <= 0:
            return "没听明白要休息多久。可以写分钟数（休息 90），或者半小时 / 1小时 / 2小时。"
        cap = stats.stamina_max(c.attributes)
        before = c.stamina
        spent = 0
        while spent < minutes and c.stamina < cap:
            c.stamina = min(
                cap, c.stamina + stats.rest_recovery(c.attributes, stats.REST_MINUTES_PER_TICK)
            )
            self.advance_time(stats.REST_MINUTES_PER_TICK)
            spent += stats.REST_MINUTES_PER_TICK
        lines = [f"你休息了 {spent} 分钟，现在是 {self.clock_text()}。",
                 f"体力 {before} → {c.stamina}/{cap}。"]
        if spent < minutes:
            lines.append("（体力已经恢复满，没必要再躺着了）")
        return "\n".join(lines)

    def conditions(self):
        """身上的异常状态。体力不足造成的力竭是实时算出来的，不写进存档。"""
        c = self.character
        if not c:
            return []
        active = [dict(x) for x in c.conditions]
        if stats.is_exhausted(c) and not any(x.get("id") == "exhausted" for x in active):
            active.insert(0, {
                "id": "exhausted",
                "name": "力竭",
                "source": "stamina",
                "effect": f"攻击力 {stats.EXHAUSTED_DAMAGE_PENALTY}%",
                "note": "体力低于上限的 10%，恢复体力即可解除",
            })
        return active

    def clear_condition(self, condition_id):
        """清除异常状态（留给以后的解毒剂之类道具调用）。

        体力不足造成的力竭不能直接清掉，必须先把体力补回来；其它来源的力竭可以清。
        """
        c = self.character
        if not c:
            return "还没有创建角色。"
        if condition_id == "exhausted" and stats.is_exhausted(c):
            return "这种力竭是体力耗尽引起的，清除异常状态的道具不管用，得先恢复体力。"
        before = len(c.conditions)
        c.conditions = [x for x in c.conditions if x.get("id") != condition_id]
        if len(c.conditions) == before:
            return "身上没有这个异常状态。"
        return "异常状态已解除。"

    def _regenerate(self):
        """每隔一定回合按体质恢复生命。"""
        c = self.character
        if c and self.turns % stats.REGEN_INTERVAL == 0:
            c.hp = min(stats.max_hp(c.attributes, c.level), c.hp + stats.hp_regen(c.attributes))

    def _carried_weight(self):
        return round(sum(self.world.items[i].get("weight", 1) for i in self.inventory), 1)

    def cmd_take(self, arg):
        if not arg:
            return "你想拿什么？"
        items = self.room_items[self.current_room]
        item_id = self._match(arg, items, self.world.items)
        if not item_id:
            return "这里没有这样东西。"
        if self.character:
            capacity = stats.carry_capacity(self.character.attributes)
            weight = self.world.items[item_id].get("weight", 1)
            if self._carried_weight() + weight > capacity:
                return f"太重了，背不动。（负重 {self._carried_weight():g}/{capacity} kg）"
        items.remove(item_id)
        self.inventory.append(item_id)
        return f"你拿起了{self.world.items[item_id]['name']}。"

    def cmd_drop(self, arg):
        if not arg:
            return "你想放下什么？"
        item_id = self._match(arg, self.inventory, self.world.items)
        if not item_id:
            return "你身上没有这样东西。"
        self._unequip(item_id)
        self.inventory.remove(item_id)
        self.room_items[self.current_room].append(item_id)
        return f"你放下了{self.world.items[item_id]['name']}。" + self._check_stance()

    def cmd_use(self, arg):
        """使用物品。效果写在物品数据的 use 字段里，见 items.py。"""
        if not self.character:
            return "还没有创建角色。"
        if not arg:
            return "你想用什么？例如：使用 能量棒"
        item_id = self._match(arg, self.inventory, self.world.items)
        if not item_id:
            return f"你身上没有{arg}。"
        return items.use(self, self.character, item_id)

    def cmd_inventory(self, arg):
        if not self.inventory:
            return "你的背包是空的。"
        slot_names = {"main_hand": "主手", "off_hand": "副手"}
        names = []
        for i in self.inventory:
            slots = [slot_names[s] for s, held in self.equipment.items() if held == i]
            where = "双手" if len(slots) == 2 else "".join(slots)
            names.append(self.world.items[i]["name"] + (f"（{where}）" if where else ""))
        text = "你带着：" + "、".join(names)
        if self.character:
            capacity = stats.carry_capacity(self.character.attributes)
            text += f"\n负重：{self._carried_weight():g}/{capacity} kg"
        return text

    def cmd_map(self, arg):
        return render_map(self.world, self.current_room, self.visited, self.room_items)

    def cmd_status(self, arg):
        if not self.character:
            return "还没有创建角色。"
        tree_names = {t["id"]: t["name"] for t in self.skill_trees.trees}
        bonuses = stances.stance_bonuses(self.character, self._current_stance(), self.skill_trees)
        sheet = format_sheet(
            self.character, self.options, self.world.items, self._carried_weight(), tree_names, bonuses
        )
        main, off = self.equipment["main_hand"], self.equipment["off_hand"]
        if main and main == off:
            hands = f"双手 {self.world.items[main]['name']}"
        else:
            name = lambda i: self.world.items[i]["name"] if i else "空"
            hands = f"主手 {name(main)}    副手 {name(off)}"
        stance = self._current_stance()
        conditions = self.conditions()
        active = "、".join(f"{x['name']}（{x['effect']}）" for x in conditions) if conditions else "无"
        return (sheet
                + f"\n\n【装备与姿态】\n  {hands}\n  姿态：{stance['name'] if stance else '无'}"
                + f"\n\n【时间】{self.clock_text()}\n【异常状态】{active}")

    def cmd_skills(self, arg):
        if not self.character:
            return "还没有创建角色。"
        if not arg:
            return skills.format_overview(self.character, self.skill_trees, self.options)
        tree = self.skill_trees.find_tree(arg)
        if not tree:
            return f"没有叫“{arg}”的技能树。输入“技能”查看全部技能树。"
        return skills.format_tree(self.character, tree, self.skill_trees, self.options, self.world.weapon_types)

    def cmd_learn(self, arg):
        if not self.character:
            return "还没有创建角色。"
        if not arg:
            return "你想学习哪个技能？例如：学习 锐器入门"
        skill = self.skill_trees.find_skill(arg)
        if not skill:
            return f"没有叫“{arg}”的技能。输入“技能 树名”查看某棵技能树里的技能。"
        return skills.learn(self.character, skill, self.skill_trees, self.options)

    # ---------- 装备与姿态 ----------

    def _weapon(self, item_id):
        return self.world.items[item_id].get("weapon") if item_id else None

    def _wielded_types(self):
        return {self._weapon(i)["type"] for i in self.equipment.values() if i}

    def _current_stance(self):
        return self.skill_trees.stance(self.stance) if self.stance else None

    def _unequip(self, item_id):
        for slot, held in self.equipment.items():
            if held == item_id:
                self.equipment[slot] = None

    def _check_stance(self):
        """换下武器后，如果不再满足当前姿态的武器要求，就自动解除姿态。"""
        stance = self._current_stance()
        if stance and stance["weapon_type"] not in self._wielded_types():
            self.stance = None
            weapon = self.world.weapon_types[stance["weapon_type"]]
            return f"\n你手里没有{weapon}武器了，{stance['name']}姿态解除。"
        return ""

    def cmd_equip(self, arg):
        if not arg:
            return "你想装备什么？"
        item_id = self._match(arg, self.inventory, self.world.items)
        if not item_id:
            return "你身上没有这样东西。"
        name = self.world.items[item_id]["name"]
        weapon = self._weapon(item_id)
        if not weapon:
            return f"{name}没法当武器拿在手上。"
        if item_id in self.equipment.values():
            return f"你已经拿着{name}了。"

        two_handed = weapon.get("hands", 1) == 2
        main = self.equipment["main_hand"]
        put_away = set()
        # 换上双手武器，或者原来拿的是双手武器，都要先把手空出来
        if two_handed or (main and self._weapon(main).get("hands", 1) == 2):
            put_away = {i for i in self.equipment.values() if i}
            self.equipment = {"main_hand": None, "off_hand": None}
        if two_handed:
            self.equipment = {"main_hand": item_id, "off_hand": item_id}
            where = "双手"
        elif not self.equipment["main_hand"]:
            self.equipment["main_hand"], where = item_id, "主手"
        elif not self.equipment["off_hand"]:
            self.equipment["off_hand"], where = item_id, "副手"
        else:
            put_away.add(self.equipment["main_hand"])
            self.equipment["main_hand"], where = item_id, "主手"

        text = f"你把{name}拿在{where}。"
        if put_away:
            text = "你收起了" + "、".join(self.world.items[i]["name"] for i in put_away) + "，" + text
        return text + self._check_stance()

    def cmd_unequip(self, arg):
        if not arg:
            return "你想收起什么？"
        held = [i for i in set(self.equipment.values()) if i]
        item_id = self._match(arg, held, self.world.items)
        if not item_id:
            return "你手里没拿着这样东西。"
        self._unequip(item_id)
        return f"你收起了{self.world.items[item_id]['name']}。" + self._check_stance()

    def cmd_stance(self, arg):
        if not self.character:
            return "还没有创建角色。"
        available = stances.available_stances(self.character, self.skill_trees)
        if not available:
            return "你还没有学会任何姿态。"
        if not arg:
            current = self._current_stance()
            lines = [f"当前姿态：{current['name'] if current else '无'}"]
            for s in available:
                bonuses = stances.stance_bonuses(self.character, s, self.skill_trees)
                weapon = self.world.weapon_types[s["weapon_type"]]
                lines.append(f"  {s['name']}：{stances.format_bonuses(bonuses)}（需要手持{weapon}武器）")
                lines.append(f"    {s['description']}")
            lines.append("输入“姿态 名字”切换（例如：姿态 进攻），“姿态 取消”解除")
            return "\n".join(lines)
        if arg in ("取消", "解除", "无", "none"):
            if not self.stance:
                return "你现在没有开启姿态。"
            name = self._current_stance()["name"]
            self.stance = None
            return f"你解除了{name}姿态。"
        stance = stances.find_stance(arg, self.character, self.skill_trees)
        if not stance:
            return f"你不会“{arg}”这个姿态。输入“姿态”查看可用的姿态。"
        if stance["weapon_type"] not in self._wielded_types():
            weapon = self.world.weapon_types[stance["weapon_type"]]
            return f"需要手持{weapon}武器才能使用{stance['name']}姿态。"
        self.stance = stance["id"]
        bonuses = stances.stance_bonuses(self.character, stance, self.skill_trees)
        return f"你切换到{stance['name']}姿态：{stances.format_bonuses(bonuses)}。"

    # ---------- 抛骰 ----------

    def _check_stats(self):
        """可以拿来做检定的数值（已含姿态加成）：名字 -> 成功率。"""
        a = self.character.attributes
        bonuses = stances.stance_bonuses(self.character, self._current_stance(), self.skill_trees)
        return {
            "近战精准": stats.melee_accuracy(a) + bonuses.get("melee_accuracy", 0),
            "远程精准": stats.ranged_accuracy(a),
            "闪避": stats.dodge(a) + bonuses.get("dodge", 0),
        }

    def cmd_roll(self, arg):
        roll = self.dice.roll(arg or "1d20")
        if not roll:
            return "格式不对。例如：掷骰 1d20、掷骰 2d6+1、掷骰 d100"
        return roll.describe()

    def cmd_check(self, arg):
        if not arg:
            return "用法：检定 成功率（例如：检定 70），或者 检定 数值名（例如：检定 近战精准）"
        if arg.isdigit():
            name, chance = "", int(arg)
        else:
            if not self.character:
                return "还没有创建角色。"
            checkable = self._check_stats()
            if arg not in checkable:
                return "可以检定的数值：" + "、".join(checkable) + "，或者直接输入成功率。"
            name, chance = arg, checkable[arg]
        result = self.dice.check(chance)
        title = f"{name}检定（成功率 {chance}%）" if name else f"检定（成功率 {chance}%）"
        if self.dice.system == "d20":
            title += f"，D20 调整值 {dice_rules.d20_modifier(chance):+d}"
        return f"{title}\n{result.text}"

    def cmd_dice_system(self, arg):
        if not arg:
            return (f"当前骰子系统：{self.dice.system.upper()}。"
                    "输入“骰子系统 d20”或“骰子系统 d100”切换（只在本次游戏中生效，默认值在 data/rules.json）")
        if arg not in ("d20", "d100"):
            return "只能切换成 d20 或 d100。"
        self.dice.system = arg
        return f"已切换为 {arg.upper()} 检定。"

    def cmd_talk(self, arg):
        npcs = self._room().get("npcs", [])
        if not npcs:
            return "这里没有人可以说话。"
        # 只有一个人时可以省略对象
        npc_id = self._match(arg, npcs, self.world.npcs) if arg else (npcs[0] if len(npcs) == 1 else None)
        if not npc_id:
            return "你想和谁说话？"
        npc = self.world.npcs[npc_id]
        lines = npc["dialogue"]
        index = self.dialogue_index[npc_id]
        self.dialogue_index[npc_id] = min(index + 1, len(lines) - 1)
        return f"{npc['name']}：{lines[index]}"

    def cmd_save(self, arg):
        slot, error = self._parse_slot(arg)
        if error:
            return error
        self.use_slot(slot)
        state = {
            "character": self.character.to_dict() if self.character else None,
            "current_room": self.current_room,
            "inventory": self.inventory,
            "turns": self.turns,
            "day": self.day,
            "minutes": self.minutes,
            "visited": sorted(self.visited),
            "equipment": self.equipment,
            "stance": self.stance,
            "room_items": self.room_items,
            "dialogue_index": self.dialogue_index,
        }
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        self.save_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return f"游戏已保存到 {slot} 号槽。"

    def cmd_load(self, arg):
        if (arg or "").strip():
            slot, error = self._parse_slot(arg)
            if error:
                return error
        else:
            # 不写槽位：优先当前槽，没有就找最近改过的那个
            slot = self.slot if self.slot_path(self.slot).exists() else self.newest_slot()
        if not self.slot_path(slot).exists():
            return f"{slot} 号存档是空的。"
        self.use_slot(slot)
        state = json.loads(self.save_path.read_text(encoding="utf-8"))
        if state.get("character"):
            self.character = Character.from_dict(state["character"])
            # 旧存档没有属性，按默认值补上
            if not self.character.attributes:
                self.character.attributes = self.options.default_attributes()
            if not self.character.hp:
                self.character.hp = stats.max_hp(self.character.attributes, self.character.level)
            # 旧存档没有体力，按满值补上
            if not self.character.stamina:
                self.character.stamina = stats.stamina_max(self.character.attributes)
        self.current_room = state["current_room"]
        self.turns = state["turns"]
        self.day = state.get("day", stats.START_DAY)
        self.minutes = state.get("minutes", stats.START_MINUTES)
        self.visited = set(state.get("visited", [self.current_room]))
        self.stance = state.get("stance")
        # 三张表都要按当前世界数据重建，顺序不能换：装备栏依赖清理后的背包
        notes = self._load_room_items(state.get("room_items", {}))
        notes += self._load_inventory(state.get("inventory", []))
        notes += self._load_equipment(state.get("equipment"))
        self.dialogue_index = state.get("dialogue_index", {})
        self._load_notice = ("（存档已按当前版本适配：" + "、".join(notes) + "）\n") if notes else ""
        return self._load_notice + f"读档成功（{slot} 号槽）。\n\n" + self.describe_room()

    def _load_room_items(self, saved):
        """按当前世界数据重建房间物品表，返回适配提示。

        存档里记的是当时每个房间的地面物品。世界数据之后可能加房间、
        加物品或删物品，所以不能直接赋值：以当前世界为基准，逐房间比对，
        存档里没有的新房间补上默认值，存档里有但世界已不存在的条目丢掉。
        """
        items = self.world.items
        rebuilt = {}
        added_rooms = 0
        removed_items = 0
        for room_id, room in self.world.rooms.items():
            if room_id in saved:
                keep = [i for i in saved[room_id] if i in items]
                removed_items += len(saved[room_id]) - len(keep)
                rebuilt[room_id] = keep
            else:
                # 新房间：世界数据里还没有存档记录，用世界默认值填上
                rebuilt[room_id] = list(room.get("items", []))
                added_rooms += 1
        self.room_items = rebuilt

        notes = []
        if added_rooms:
            notes.append(f"{added_rooms} 个新地点")
        if removed_items:
            notes.append(f"{removed_items} 件已不存在的物品")
        return notes

    def _load_inventory(self, saved):
        """按当前世界数据清理背包，返回适配提示。

        与地面物品同理：存档里的物品 id 可能在世界数据里已被删除或改名，
        直接赋值会让之后的拿取、查看、放下在查物品表时崩溃。
        """
        items = self.world.items
        kept = [i for i in saved if i in items]
        removed = len(saved) - len(kept)
        self.inventory = kept
        return [f"背包里有 {removed} 件物品已不存在"] if removed else []

    def _load_equipment(self, saved):
        """按清理后的背包重建装备栏，返回适配提示。

        装备栏里存的是物品 id：物品若已失效或已不在背包里，就不能继续挂在
        手上，否则状态面板和武器类型判断会查到不存在的物品。
        """
        if not isinstance(saved, dict):
            saved = {}
        equipment = {"main_hand": None, "off_hand": None}
        for slot in equipment:
            held = saved.get(slot)
            if held and held in self.inventory:
                equipment[slot] = held
        # 双手武器两个槽存同一个 id，按件数去重后再报数字
        dropped = {h for h in (saved.get(slot) for slot in equipment) if h and h not in self.inventory}
        self.equipment = equipment
        return [f"已卸下 {len(dropped)} 件失效装备"] if dropped else []

    def cmd_help(self, arg):
        return (
            "可用指令：\n"
            "  看 / look              查看周围\n"
            "  北、南、东、西 / n s e w  移动（也可以写“走 北”）\n"
            "  查看 <东西>              仔细查看物品或人物\n"
            "  拿 <东西> / 放下 <东西>   拾取或丢弃物品\n"
            "  使用 <东西>             使用物品（例如：使用 能量棒）\n"
            "  背包 / i               查看携带的物品\n"
            "  地图 / m               查看地图\n"
            "  角色 / c               查看角色卡（属性、衍生数值）\n"
            "  技能 / 技能 <树名>        查看技能树，例如：技能 锐器\n"
            "  学习 <技能>              花技能点解锁技能\n"
            "  装备 <武器> / 卸下 <武器>  拿起或收起武器\n"
            "  姿态 / 姿态 <名字>        查看或切换姿态，“姿态 取消”解除\n"
            "  掷骰 <骰子>              掷骰，例如：掷骰 2d6+1\n"
            "  检定 <成功率/数值名>       做一次检定，例如：检定 70、检定 近战精准\n"
            "  骰子系统 <d20/d100>       查看或切换检定用的骰子\n"
            "  休息 <时长>             恢复体力，例如：休息 30、休息 2小时\n"
            "  说话 <人>               和 NPC 交谈\n"
            "  存档 [槽位] / 读档 [槽位]  保存或读取进度（槽位 1~3，不写就用当前槽）\n"
            "  退出 / quit            离开游戏"
        )

    def cmd_quit(self, arg):
        self.running = False
        return "再见，幸存者。"
