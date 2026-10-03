"""文字冒险游戏引擎：负责世界数据、游戏状态和指令解析。"""

import json
import math
import os
import re
import shutil
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from fractions import Fraction
from pathlib import Path

import dice as dice_rules
import item_table
import items
import skills
import stances
import stats
from character import Character, format_sheet
from combat import CombatMixin, distance
from enemies import Enemy, EnemyBook, format_enemy
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
# 走进去时用哪个方向当“对面”（例如从东边进屋，就站在屋里的西门口）
OPPOSITE_DIRECTIONS = {
    "north": "south", "south": "north", "east": "west",
    "west": "east", "up": "down", "down": "up",
}
# 场景格子里走一格，坐标怎么变（x 向右、y 向下）。
# 上下是楼梯，不是平面方向，所以在场景里另外处理（走到楼梯格上 / 站在楼梯旁边按上/下）。
GRID_STEPS = {
    "north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0),
}
# 一个 NPC 的台词已经全部说完时，cmd_continue 返回这一句；
# 界面（webui.py）认这个字符串，把视图栏的对话框收起来。
TALK_END = "（话说完了）"
# 门里的那一格该往哪个方向找（先试第一个，不行再试后面的）
INWARD_STEPS = {
    "north": ((0, 1), (1, 0), (-1, 0), (0, -1)),
    "south": ((0, -1), (1, 0), (-1, 0), (0, 1)),
    "west": ((1, 0), (0, 1), (0, -1), (-1, 0)),
    "east": ((-1, 0), (0, 1), (0, -1), (1, 0)),
    "up": ((0, 1), (0, -1), (1, 0), (-1, 0)),
    "down": ((0, 1), (0, -1), (1, 0), (-1, 0)),
}
WALL_TILES = ("#", "~")  # 墙和障碍物都走不过去
DOOR_TILES = ("+", "<", ">")  # 门和楼梯：走上去就换房间

# 休息时长的中文写法
REST_WORDS = {
    "半小时": 30, "一小时": 60, "1小时": 60, "两小时": 120, "2小时": 120,
    "四小时": 240, "4小时": 240, "八小时": 480, "8小时": 480,
}

# 一次休息的上下限（分钟）：网页版的时间滑条按这两个值取范围。
# 8 小时 = 480 分钟，按“每半小时恢复 10% 上限”够把任何角色的体力补满。
REST_MINUTES_MIN = 1
REST_MINUTES_MAX = 8 * 60


def format_duration(minutes):
    """把分钟数写成“45 分钟 / 2 小时 / 1 小时 30 分钟”。"""
    minutes = int(minutes)
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, rest = divmod(minutes, 60)
    return f"{hours} 小时 {rest} 分钟" if rest else f"{hours} 小时"


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

# 老版本单存档搬进 1 号槽之后留下的标记文件。有了它，清空 1 号槽之后
# 下次启动就不会被那个旧文件“复活”。
MIGRATED_MARKER = ".migrated"


def mark_migrated(save_dir):
    """记下“老存档已经处理过了”。"""
    try:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        (save_dir / MIGRATED_MARKER).write_text("1\n", encoding="utf-8")
    except OSError:
        pass


def write_json_file(path, payload):
    """先写临时文件再替换，中途出错也不会把原来那份存档写坏。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # 同盘替换是原子操作，Windows 上也一样


def migrate_old_save(save_dir):
    """把老版本的单存档（save.json）复制到 1 号槽，只做一次。

    早期版本只有一个存档文件，改成多槽位之后旧进度会“消失”，所以启动时
    静默搬一次（保留原文件，不删）。搬完写一个标记：否则玩家清空 1 号槽后，
    下次启动又会从旧文件里把进度搬回来。
    """
    save_dir = Path(save_dir)
    old = save_dir / "save.json"
    first = save_dir / "save1.json"
    if (save_dir / MIGRATED_MARKER).exists():
        return False
    if not old.exists():
        return False
    moved = False
    if not first.exists():
        try:
            shutil.copyfile(old, first)
            moved = True
        except OSError:
            return False
    mark_migrated(save_dir)
    return moved


class World:
    """只读的世界数据（地图、物品、NPC），从 JSON 文件加载。"""

    def __init__(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.data_dir = Path(path).parent  # 其他数据文件（如 enemies.json）和它放在一起
        self.title = data["title"]
        self.intro = data["intro"]
        self.start_room = data["start_room"]
        self.rooms = data["rooms"]
        self.items = dict(data.get("items", {}))
        # 物品主要写在 data/items.csv（表格，不用改代码就能加 / 改物品，见 item_table.py 和 物品表说明.md）
        table = self.data_dir / "items.csv"
        if table.exists():
            for item_id, item in item_table.load(table, data).items():
                if item_id in self.items:
                    raise ValueError(f"物品 {item_id} 在 world.json 和 items.csv 里都有，只能留一份")
                self.items[item_id] = item
        self.npcs = data["npcs"]
        self.map_areas = data.get("map_areas", [])
        # 随机物资池：好几处地方可以共用一份「第一次进来扔什么」的清单（见 world.json 的 spawn_pools）
        self.spawn_pools = data.get("spawn_pools", {})
        self.weapon_types = data.get("weapon_types", {})  # 武器类型 id -> 显示名
        self.armor_slots = data.get("armor_slots", {})  # 护甲部位 id -> 显示名
        # 其他装备位 id -> {name, kind}；同一 kind 可以有多个位置（饰品有两个）
        self.gear_slots = data.get("gear_slots", {})
        self.wear_slot_names = dict(self.armor_slots)  # 所有穿戴位（护甲 + 其他）的显示名
        self.wear_slot_names.update({slot: info["name"] for slot, info in self.gear_slots.items()})
        gear_kinds = {info["kind"] for info in self.gear_slots.values()}
        for room_id, room in self.rooms.items():
            # random_items / random_pool：第一次进入这个地点时随机生成的地面物资（min ~ max 个）
            specs = list(room.get("random_items", []))
            where = f"world.json 里的地点 {room_id}"
            for spec in room.get("random_pool", []):
                pool = self.spawn_pools.get(spec.get("name"))
                if pool is None:
                    raise ValueError(f"{where}：random_pool 里的“{spec.get('name')}”不在 spawn_pools 里")
                for one in pool:  # 池子按同一份 min / max 掷一次
                    specs.append(dict(one, min=spec.get("min", 1), max=spec.get("max", 1)))
            for spec in specs:
                if spec.get("id") not in self.items:
                    raise ValueError(f"{where}：随机物资里的物品 id {spec.get('id')} 不在物品表里")
                low, high = spec.get("min", 1), spec.get("max", 1)
                if not 1 <= low <= high:
                    raise ValueError(f"{where}：随机物资的个数要写 1 ≤ min ≤ max")
        for room_id, room in self.rooms.items():
            for item_id in room.get("items", []):
                if item_id not in self.items:
                    raise ValueError(f"world.json 里的地点 {room_id} 放了物品 {item_id}，但物品表里没有这个 ID")
        for item_id, item in self.items.items():
            weapon = item.get("weapon")
            if weapon and weapon.get("improvised") and weapon.get("damage") not in stats.DAMAGE_TIERS:
                raise ValueError(f"物品表里的代用武器 {item_id}：伤害要是 {'、'.join(stats.DAMAGE_TIERS)} 中的一档"
                                 "（会自动降一档）")
            if weapon and not dice_rules.DICE_PATTERN.match(weapon.get("damage", "")):
                raise ValueError(f"物品表里的武器 {item_id}：伤害骰要写成 1d8、2d6 这样的格式")
            if weapon and not dice_rules.CRIT_RANGE_PATTERN.match(weapon.get("crit_range", "20")):
                raise ValueError(f"物品表里的武器 {item_id}：暴击范围要写成 19-20 或 20 这样的格式")
            armor = item.get("armor")
            if armor:
                where = f"物品表里的护甲 {item_id}"
                if armor.get("slot") not in self.armor_slots:
                    raise ValueError(f"{where}：部位要是 {'、'.join(self.armor_slots)} 之一")
                if armor.get("class") not in stats.ARMOR_CLASSES:
                    raise ValueError(f"{where}：类别要是 {'、'.join(stats.ARMOR_CLASSES)} 之一")
                name, low, high = stats.ARMOR_CLASSES[armor["class"]]
                if not low <= armor.get("value", 0) <= high:
                    raise ValueError(f"{where}：{name}的基础护甲值要在 {low}~{high} 之间")
            for tag in (weapon or {}).get("tags", []):
                if tag not in stats.WEAPON_TAGS:
                    raise ValueError(f"物品表里的武器 {item_id}：标签要是 {'、'.join(stats.WEAPON_TAGS)} 之一")
            if item.get("hold") and item["hold"] not in stats.HOLD_TYPES:
                raise ValueError(f"物品表里的物品 {item_id}：手持类别要是 {'、'.join(stats.HOLD_TYPES)} 之一")
            if item.get("quality", "normal") not in stats.QUALITIES:
                raise ValueError(f"物品表里的物品 {item_id}：等阶要是 {'、'.join(stats.QUALITIES)} 之一")
            gear = item.get("gear")
            if gear:
                where = f"物品表里的装备 {item_id}"
                if gear.get("slot") not in gear_kinds:
                    raise ValueError(f"{where}：装备位要是 {'、'.join(sorted(gear_kinds))} 之一")
                if not 0 <= gear.get("weight_reduction", 0) <= 100:
                    raise ValueError(f"{where}：减重率要在 0~100 之间")

    def wear_candidates(self, item_id):
        """这件物品可以穿戴在哪些位置（按顺序），不能穿戴就是空列表。"""
        item = self.items[item_id]
        if item.get("armor"):
            return [item["armor"]["slot"]]
        if item.get("gear"):
            kind = item["gear"]["slot"]
            return [slot for slot, info in self.gear_slots.items() if info["kind"] == kind]
        return []


class Game(CombatMixin):
    """一局游戏的可变状态，以及所有玩家指令。"""

    def __init__(self, world, options, skill_trees, dice, save_path):
        self.world = world
        self.options = options
        self.skill_trees = skill_trees
        self.dice = dice
        self.enemies = EnemyBook(world.data_dir / "enemies.json", [a["id"] for a in options.attributes], world.items)
        for room_id, room in world.rooms.items():
            for spec in room.get("enemies", []) + room.get("random_enemies", []):
                if spec.get("id") not in self.enemies.templates:
                    raise ValueError(f"world.json 里的地点 {room_id}：敌人 {spec.get('id')} 不在 enemies.json 里")
        # 存档分成几个槽：save1.json / save2.json / save3.json
        self.save_dir = Path(save_path).parent
        self.slot = 1
        self.save_path = self.slot_path(self.slot)
        migrate_old_save(self.save_dir)
        self.character = None
        self.running = True
        self.settings = self._load_settings()  # 个人偏好（不跟存档走），见 cmd_settings
        self.reset()
        # (别名列表, 处理函数)，别名越长越优先匹配
        self.commands = [
            (["看", "观察", "look", "l"], self.cmd_look),
            (["查看", "检查", "examine", "x"], self.cmd_examine),
            (["走", "去", "go"], self.cmd_go),
            (["拿", "捡", "拾取", "take", "get"], self.cmd_take),
            (["放下", "丢掉", "drop"], self.cmd_drop),
            (["拆分", "分开", "split"], self.cmd_split),
            (["堆叠", "合并", "stack"], self.cmd_stack),
            (["背包", "物品", "inventory", "i"], self.cmd_inventory),
            (["地图", "map", "m"], self.cmd_map),
            (["角色", "状态", "status", "c"], self.cmd_status),
            (["技能", "skills", "k"], self.cmd_skills),
            (["用", "use skill"], self.cmd_use_skill),
            (["学习", "learn"], self.cmd_learn),
            (["装备", "equip"], self.cmd_equip),
            (["卸下", "unequip"], self.cmd_unequip),
            (["姿态", "stance"], self.cmd_stance),
            (["掷骰", "roll"], self.cmd_roll),
            (["检定", "check"], self.cmd_check),
            (["试攻击", "attack test"], self.cmd_attack_test),
            (["敌人", "enemy"], self.cmd_enemy),
            (["试受击", "defend test"], self.cmd_defend_test),
            (["试盾击", "bash test"], self.cmd_bash_test),
            (["试眩晕", "stun test"], self.cmd_stun_test),
            (["试先攻", "initiative test"], self.cmd_initiative_test),
            (["试刷怪", "spawn test"], self.cmd_spawn_test),
            (["攻击", "打", "attack"], self.cmd_attack),
            (["使用", "吃", "喝", "use"], self.cmd_use),
            (["休息", "睡", "rest"], self.cmd_rest),
            (["等待", "结束回合", "wait"], self.cmd_wait),
            (["说话", "交谈", "对话", "talk"], self.cmd_talk),
            (["继续", "下一句", "下一段", "continue"], self.cmd_continue),
            (["存档", "save"], self.cmd_save),
            (["读档", "load"], self.cmd_load),
            (["清空存档", "清空", "删除存档", "clear"], self.cmd_clear),
            (["设置", "settings"], self.cmd_settings),
            (["帮助", "help", "h", "?"], self.cmd_help),
            (["退出", "quit", "q"], self.cmd_quit),
        ]
        # 摊平并排序一次即可：指令表是静态的，没必要每输入一行都重建一遍
        self.aliases = [(a, fn) for names, fn in self.commands for a in names]
        self.aliases.sort(key=lambda pair: len(pair[0]), reverse=True)

    def reset(self):
        self.current_room = self.world.start_room
        # 背包里每一项都是一“堆”，见下面「背包：一格一堆」那一段
        self.inventory = []
        self.next_stack_id = 1  # 每堆东西的编号，界面靠它指定具体哪一堆
        self.equipment = {"main_hand": None, "off_hand": None}  # 双手武器会同时占两个位置
        self.worn = {slot: None for slot in self.world.wear_slot_names}  # 护甲、饰品、披风、背包
        self.stance = None  # 当前姿态 id
        self.turns = 0
        self._reset_combat()  # 地图上的敌人、先攻、持续伤害（combat.py）
        self.moved_this_turn = False  # 这一回合走过路没有（全垒打：没移动过伤害 +60%）
        self.step_credit = Fraction(0)  # 灵动步伐多付的半格行动点（回合结束清零）
        self.ap = 0  # 当前行动点（不分战斗内外，每回合 = 1 分钟开始时获得，见 spend_ap / _pass_turn）
        self.indoor_steps = 0  # 室内已经走了几步（凑满 10 步扣一次体力）
        self.need_minutes = {"food": 0, "water": 0}  # 距离下一次食物 / 水源 −1 已经过了多少分钟
        self.stamina_carry = Fraction(0)  # 体力消耗乘上饥饿 / 口渴倍率后的小数部分，攒满 1 才扣
        self.pending_notes = []  # 这一步里自动发生的事（例如开始饿了），附在指令输出后面
        self.death_cause = None  # 死了就记下死因（stats.DEATH_CAUSES 的 id），读档后清掉
        self.starving_drain = 0  # 这一步里饿 / 渴掉了多少血（攒起来一次提示）
        self.day = stats.START_DAY  # 计时器：第几天
        self.minutes = stats.START_MINUTES  # 计时器：当天已经过去的分钟数
        self._load_notice = ""  # 读档时若按新版本适配过，这里放一句提示
        # 去过的地点（地图上的显示方式不同，内容也只对去过的地点公开）
        self.visited = {self.current_room}
        # 每个房间里现有的物品（会随玩家拿取/丢弃而变化）。同一种东西地上可以摆好几件，
        # 所以这是一串物品 id，可能重复；每件东西的格子记在 ground_positions 里（一一对应）。
        self.room_items = {rid: list(r.get("items", [])) for rid, r in self.world.rooms.items()}
        # 场景格子：玩家现在站在哪一格 [x, y]，以及每个房间里每件地面物品的格子
        # ground_positions[房间] = [[x, y], ...]，长度和 room_items[房间] 一样，按顺序对应
        self.pos = None
        self.ground_positions = {}
        # 每个 NPC 已经说到第几句
        self.dialogue_index = {nid: 0 for nid in self.world.npcs}
        # 正在和谁说话（对话框里显示的是哪个 NPC 的台词）；不在对话里就是 None
        self.talk_npc = None

    def start_new(self, character):
        """用新创建的角色开始一局游戏，背景自带的物品放进背包。"""
        self.reset()
        self.character = character
        background = self.options.background(character.background)
        for item_id in background.get("starting_items", []):
            self.add_item(item_id)
        character.hp = self.options.max_hp(character)
        character.stamina = stats.stamina_max(character.attributes)
        self.ap = self.ap_gain()  # 第一回合的行动点
        self.blocks_left = self.blocks_per_turn()

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

    def _background_name(self, background_id):
        """存档里的背景 id 在当前版本里可能已经没了，查不到就留空。"""
        if not background_id:
            return ""
        try:
            return self.options.background(background_id)["name"]
        except (StopIteration, KeyError, TypeError):
            return ""

    def _saved_at(self, path):
        """存档文件的最后修改时间，界面用来显示“什么时候存的”。"""
        try:
            return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            return ""

    def slot_info(self, slot):
        """读一个槽的概要，给界面显示用。空槽返回 None，文件坏了返回 broken。"""
        path = self.slot_path(slot)
        if not path.exists():
            return None
        saved_at = self._saved_at(path)
        base = {"slot": slot, "exists": True, "current": slot == self.slot, "saved_at": saved_at}
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("存档内容不是一个对象")
        except (ValueError, OSError, UnicodeDecodeError):
            return dict(base, broken=True, name="存档损坏", level="-", background="",
                        room="-", day=0, minutes=0, time="-")
        character = state.get("character")
        if not isinstance(character, dict):
            character = {}
        room = self.world.rooms.get(state.get("current_room")) or {}
        day = state.get("day", stats.START_DAY)
        minutes = state.get("minutes", stats.START_MINUTES)
        try:  # 存档里的数字理论上没问题，坏了也不该让整个界面报错
            day = int(day)
            minutes = int(minutes)
        except (TypeError, ValueError):
            day, minutes = stats.START_DAY, stats.START_MINUTES
        return dict(base,
                    broken=False,
                    name=character.get("name") or "无名幸存者",
                    level=character.get("level", 1),
                    background=self._background_name(character.get("background")),
                    room=room.get("name") or state.get("current_room") or "未知地点",
                    day=day,
                    minutes=minutes,
                    time="第 %d 天 %02d:%02d" % (day, minutes // 60, minutes % 60))


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
        fn, arg = self._resolve(text)
        if fn is None:
            return "我不明白你的意思。输入“帮助”查看可用指令。"
        # 死了只能读档、看帮助或退出（方向指令也拦下）
        if self.death_cause and fn not in (self.cmd_load, self.cmd_help, self.cmd_quit):
            return self.death_text() + "\n（只能读档、查看帮助或退出）"
        return self._with_notes(fn(arg))

    def _resolve(self, text):
        """把一行输入解析成 (指令函数, 参数)；认不出来返回 (None, None)。"""
        if text in DIRECTIONS:
            return self.cmd_go, text
        for alias, fn in self.aliases:
            if alias.isascii():
                # 英文指令需要用空格和参数隔开，避免 "i" 误匹配 "inn"
                if text == alias or text.startswith(alias + " "):
                    return fn, text[len(alias):].strip()
            elif text.startswith(alias):
                # 中文指令允许不加空格，例如 "拿火把"
                return fn, text[len(alias):].strip()
        return None, None

    def _with_notes(self, output):
        """把这一步里自动发生的事（饿了、渴了、掉血、死亡）接在指令输出后面。"""
        if self.character:
            self._flush_starving_note()
        if self.death_cause and not any("你死了" in n for n in self.pending_notes) and "你死了" not in (output or ""):
            self.pending_notes.append("\n" + self.death_text())
        if not self.pending_notes:
            return output
        notes, self.pending_notes = self.pending_notes, []
        return (output + "\n" if output else "") + "\n".join(notes)

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

    # ---------- 场景格子 ----------
    #
    # world.json 里每个房间可以写一段 grid（见数据文件里的注释）：
    #   tiles   10 行 × 16 列的字符串，'#' 墙、'.' 地板、'~' 障碍物、'+' 门、'<' 上楼、'>' 下楼
    #   doors   {出口方向: [x, y]}，和房间的 exits 一一对应
    #   objects {物品 / NPC id: [x, y]}，只写初始位置的物品
    # 没写 grid 的房间自动退回老做法（走一步 = 直接换房间），所以旧数据也能跑。

    def room_grid(self, room_id=None):
        """这个房间的格子场景；没写就返回 None。"""
        room = self.world.rooms[room_id or self.current_room]
        grid = room.get("grid")
        if not grid or not grid.get("tiles"):
            return None
        return grid

    def grid_size(self, grid):
        """(宽, 高)：宽取第一行的长度，高取行数。"""
        return len(grid["tiles"][0]), len(grid["tiles"])

    def tile_at(self, grid, x, y):
        """这一格是什么；越界一律当墙。"""
        tiles = grid["tiles"]
        if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
            return tiles[y][x]
        return "#"

    def tile_walkable(self, grid, x, y):
        return self.tile_at(grid, x, y) not in WALL_TILES

    def tile_is_door(self, grid, x, y):
        return self.tile_at(grid, x, y) in DOOR_TILES

    def door_direction(self, grid, pos):
        """这一格是哪扇门 / 楼梯（出口方向）；不是门就返回 None。"""
        for direction, coord in (grid.get("doors") or {}).items():
            if list(coord)[:2] == [pos[0], pos[1]]:
                return direction
        return None

    def door_tile(self, grid, direction):
        """某个出口的门 / 楼梯在哪一格。"""
        coord = (grid.get("doors") or {}).get(direction)
        return (coord[0], coord[1]) if coord else None

    def _npc_tiles(self, room_id, grid):
        """房间里 NPC 占的格子（NPC 位置写在世界数据里，不会变）。"""
        taken = set()
        objects = grid.get("objects") or {}
        for npc_id in self.world.rooms[room_id].get("npcs", []):
            coord = objects.get(npc_id)
            if coord:
                taken.add((coord[0], coord[1]))
        return taken

    def ground_positions_in(self, room_id=None):
        """房间里每件地面物品的格子坐标：[[x, y], ...]，和 room_items 一一对应。

        世界数据里写了初始位置的就用写的（同种东西只有第一件用那个位置，其余另找地方）；
        后来丢下的、或者数据里没写位置的，自动找最近的空格子，结果记进 self.ground_positions
        （存进存档，一件东西一个格子）。列表短了补 None，长了截掉。
        """
        room_id = room_id or self.current_room
        grid = self.room_grid(room_id)
        if not grid:
            return []
        items = self.room_items[room_id]
        table = self.ground_positions.setdefault(room_id, [])
        del table[len(items):]  # 东西被拿走了，多出来的坐标一并丢掉
        while len(table) < len(items):
            table.append(None)
        occupied = {tuple(c) for c in table if c} | self._npc_tiles(room_id, grid)
        occupied.add(self.player_pos(grid))
        authored = grid.get("objects") or {}
        for index, item_id in enumerate(items):
            if table[index]:
                continue
            coord = authored.get(item_id)
            if coord and self.tile_walkable(grid, coord[0], coord[1]) and tuple(coord) not in occupied:
                table[index] = [coord[0], coord[1]]
            else:
                free = self._nearest_free_tile(grid, self.player_pos(grid), occupied)
                if free:
                    table[index] = [free[0], free[1]]
            if table[index]:
                occupied.add(tuple(table[index]))
        return table

    def ground_names(self, room_id=None):
        """地上东西的名字，同种几件合并写成「名字 ×N」。"""
        room_id = room_id or self.current_room
        order, counts = [], {}
        for item_id in self.room_items[room_id]:
            if item_id not in counts:
                order.append(item_id)
                counts[item_id] = 0
            counts[item_id] += 1
        return [self.world.items[i]["name"] + (f" ×{counts[i]}" if counts[i] > 1 else "")
                for i in order]

    def ground_names_at(self, pos, room_id=None):
        """某一格上摆着哪些东西（名字列表）。"""
        room_id = room_id or self.current_room
        names = []
        for item_id, coord in zip(self.room_items[room_id], self.ground_positions_in(room_id)):
            if coord and coord[0] == pos[0] and coord[1] == pos[1]:
                names.append(self.world.items[item_id]["name"])
        return names

    def _nearest_free_tile(self, grid, start, occupied):
        """从 start 一圈圈往外找最近的空格子（不压墙、不压门、不压别的东西）。"""
        width, height = self.grid_size(grid)
        sx, sy = start
        for radius in range(0, max(width, height) + 1):
            found = []
            for y in range(max(0, sy - radius), min(height, sy + radius + 1)):
                for x in range(max(0, sx - radius), min(width, sx + radius + 1)):
                    if max(abs(x - sx), abs(y - sy)) != radius:
                        continue
                    if not self.tile_walkable(grid, x, y) or self.tile_is_door(grid, x, y):
                        continue
                    if (x, y) in occupied:
                        continue
                    found.append((x, y))
            if found:
                found.sort(key=lambda p: (p[1], p[0]))
                return found[0]
        return None

    def player_pos(self, grid=None):
        """玩家现在站在哪一格；没有就按房间中心找一格空的定下来。

        注意：这里不能再回头调 ground_positions_in（那个函数会来问玩家在哪一格），
        所以占用情况直接读已经记下的坐标。
        """
        grid = grid if grid is not None else self.room_grid()
        if not grid:
            return (0, 0)
        width, height = self.grid_size(grid)
        if self.pos and self.tile_walkable(grid, self.pos[0], self.pos[1]):
            return (self.pos[0], self.pos[1])
        occupied = self._npc_tiles(self.current_room, grid) | {
            tuple(c) for c in self.ground_positions.get(self.current_room, []) if c}
        free = self._nearest_free_tile(grid, (width // 2, height // 2), occupied)
        self.set_pos(free or (width // 2, height // 2))
        return (self.pos[0], self.pos[1])

    def set_pos(self, pos):
        """记住玩家站在哪一格（存进存档）。"""
        if pos:
            self.pos = [int(pos[0]), int(pos[1])]

    def near(self, pos, target):
        """两格是不是挨着（同一格算，斜角也算）：拾取 / 说话要走到跟前。"""
        if not pos or not target:
            return True
        return max(abs(pos[0] - target[0]), abs(pos[1] - target[1])) <= 1

    def entry_tile(self, room_id, from_direction):
        """从 from_direction 走进这个房间时，人物落在哪一格（门里面那一格）。"""
        grid = self.room_grid(room_id)
        if not grid:
            return None
        tile = self.door_tile(grid, OPPOSITE_DIRECTIONS.get(from_direction))
        if not tile:
            return None
        occupied = self._npc_tiles(room_id, grid) | {
            tuple(c) for c in self.ground_positions_in(room_id) if c}
        for dx, dy in INWARD_STEPS.get(from_direction, ((0, 1),)):
            x, y = tile[0] + dx, tile[1] + dy
            if (self.tile_walkable(grid, x, y) and not self.tile_is_door(grid, x, y)
                    and (x, y) not in occupied):
                return (x, y)
        return self._nearest_free_tile(grid, tile, occupied)

    def scene_state(self):
        """打包给网页版渲染场景：格子、门、人物、物品、玩家坐标。"""
        grid = self.room_grid()
        if not grid:
            return None
        width, height = self.grid_size(grid)
        coords = self.ground_positions_in()
        things = [
            {"id": f"g{index}", "name": self.world.items[item_id]["name"],
             "kind": "item", "x": coord[0], "y": coord[1]}
            for index, (item_id, coord)
            in enumerate(zip(self.room_items[self.current_room], coords))
            if coord
        ]
        objects = grid.get("objects") or {}
        for npc_id in self.world.rooms[self.current_room].get("npcs", []):
            coord = objects.get(npc_id)
            if coord:
                things.append({"id": npc_id, "name": self.world.npcs[npc_id]["name"],
                               "kind": "npc", "x": coord[0], "y": coord[1]})
        for e in self.visible_enemies():
            things.append({"id": f"e{e.uid}", "name": e.label, "kind": "enemy", "x": e.pos[0], "y": e.pos[1],
                           "hp": e.hp, "max_hp": e.max_hp, "aware": e.aware})
        x, y = self.player_pos(grid)
        return {
            "width": width,
            "height": height,
            "tiles": list(grid["tiles"]),
            "doors": {d: list(c) for d, c in (grid.get("doors") or {}).items()},
            "things": things,
            "player": [x, y],
        }

    def _drop_tile(self, grid):
        """丢在脚下：优先玩家自己这一格，被占了就找最近的空格子。"""
        pos = self.player_pos(grid)
        occupied = self._npc_tiles(self.current_room, grid) | {
            tuple(c) for c in self.ground_positions_in() if c}
        if self.tile_walkable(grid, pos[0], pos[1]) and not self.tile_is_door(grid, pos[0], pos[1]) \
                and pos not in occupied:
            return pos
        return self._nearest_free_tile(grid, pos, occupied)

    def describe_room(self):
        room = self._room()
        lines = [f"【{room['name']}】", room["description"]]
        items = self.ground_names()
        if items:
            lines.append("你看到：" + "、".join(items))
        npcs = room.get("npcs", [])
        if npcs:
            lines.append("这里有：" + "、".join(self.world.npcs[n]["name"] for n in npcs))
        enemies = self.visible_enemies() if self.character else []
        if enemies:
            here = self.player_pos()
            lines.append("敌人：" + "、".join(f"{e.label}（{distance(e.pos, here)} 格外，生命 {e.hp}/{e.max_hp}）"
                                             for e in enemies))
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
        enemy = self.find_enemy(arg)
        if enemy:
            here = self.player_pos()
            status = []
            if not enemy.aware:
                status.append("还没发现你")
            if enemy.knocked_down:
                status.append("倒地")
            if enemy.stun:
                status.append(stats.STUN_CONDITIONS[enemy.stun])
            for kind, (name, _) in stats.DOT_KINDS.items():
                n = sum(1 for d in enemy.dots if d["kind"] == kind)
                if n:
                    status.append(f"{name} {n} 层")
            return (f"{enemy.label}：第 {enemy.pos[0] + 1} 列，第 {enemy.pos[1] + 1} 行，离你 {distance(enemy.pos, here)} 格"
                    + (f"（{'、'.join(status)}）" if status else "") + "\n"
                    + format_enemy(enemy, self.options, self.world.weapon_types, self.world.items, self.enemies))
        visible_items = self.inventory_ids() + self.room_items[self.current_room]
        item_id = self._match(arg, visible_items, self.world.items)
        if item_id:
            return self.world.items[item_id]["description"]
        npc_id = self._match(arg, self._room().get("npcs", []), self.world.npcs)
        if npc_id:
            return self.world.npcs[npc_id]["description"]
        return "这里没有这样东西。"

    def cmd_go(self, arg):
        """走：房间里就挪一格，走到门/楼梯格上就换房间；没写场景的房间直接换房间。"""
        direction = DIRECTIONS.get(arg)
        if not direction:
            return "你想往哪个方向走？（东/南/西/北/上/下）"
        grid = self.room_grid()
        if grid:
            return self._step(direction, grid)
        return self._travel(direction, self._room())

    def _step(self, direction, grid):
        """在场景里走一格。"""
        room = self._room()
        pos = self.player_pos(grid)
        if direction in ("up", "down"):
            return self._take_stairs(direction, grid, pos)
        dx, dy = GRID_STEPS[direction]
        target = (pos[0] + dx, pos[1] + dy)
        if not self.tile_walkable(grid, target[0], target[1]):
            return self._no_path(room, direction)
        # 踩到门 / 楼梯格上就换房间，走过去的那一格由目标房间的“门里那格”决定
        blocker = self.enemy_at(target)
        if blocker:
            return f"{blocker.label}挡在那一格，过不去。"
        door_dir = self.door_direction(grid, target)
        if door_dir:
            return self._travel(door_dir, room)

        error, overweight, cost = self._prepare_move()
        if error:
            return error
        self.set_pos(target)
        cost_note, notes = self._pay_move(overweight, cost)
        self.check_enemies()
        text = f"移动至（第 {target[0] + 1} 列，第 {target[1] + 1} 行）"
        text += ("，" + cost_note if cost_note else "") + "。"
        if notes:
            text += "\n" + notes
        here = self.ground_names_at(target)
        if here:
            text += "\n脚下有：" + "、".join(here) + "。"
        shock = self._check_shock()
        if shock:
            text += "\n\n" + shock
        return text

    def _take_stairs(self, direction, grid, pos):
        """上下楼：站在楼梯格上（或紧挨着）才走得动。"""
        room = self._room()
        if direction not in room["exits"]:
            return f"这里没有往{DIRECTION_NAMES[direction]}的楼梯。"
        tile = self.door_tile(grid, direction)
        if not tile:
            return self._travel(direction, room)
        near = max(abs(tile[0] - pos[0]), abs(tile[1] - pos[1])) <= 1
        if not near:
            name = "上" if direction == "up" else "下"
            return f"楼梯不在这儿——你得先走到楼梯那格上（{name}楼口在第 {tile[0] + 1} 列，第 {tile[1] + 1} 行）。"
        return self._travel(direction, room)

    def _prepare_move(self):
        """走一步之前的检查，返回 (错误文字, 是否超重, 这一步的体力消耗)。

        室内外一样：每走 INDOOR_STEPS_PER_COST 步扣一次体力，没凑满的那几步消耗是 0。
        口渴时这一步的消耗翻倍（见 stats.move_cost）。
        """
        if self.load_level() == "immobile":
            capacity = stats.carry_capacity(self.character.attributes)
            return (f"你背的东西太重了（负重 {self._carried_weight():g}/{capacity} kg，"
                    f"超过上限的 {stats.IMMOBILE_WEIGHT_MULTIPLIER} 倍），一步也挪不动。先放下些东西吧。",
                    False, 0)
        overweight = self.load_level() == "overweight"
        cost = 0
        if self.character:
            cost = self.next_move_cost(overweight)
            if self.character.stamina < cost:
                return (f"体力不够：走这一步要 {cost} 点，你只剩 {self.character.stamina} 点。\n"
                        f"先休息一下吧（例如：休息 60）。", overweight, cost)
        return (None, overweight, cost)

    def _pay_move(self, overweight, cost):
        """真正扣体力、推时间、数步数。

        返回 (要显示的那句说明, 额外提示)：说明不带括号和句号，额外提示是新触发的
        口渴之类，调用方另起一行接在正文后面。
        """
        base = self._move_base_cost(overweight)  # 要在步数加一之前算
        self.moved_this_turn = True
        self.indoor_steps = (self.indoor_steps + 1) % stats.INDOOR_STEPS_PER_COST
        if not self.character:
            return "", ""
        # 饥饿 / 口渴的体力倍率按分数累加，攒满 1 点才真正扣（所有计算向下取整）
        self.stamina_carry += base * self.need_stamina_multiplier()
        cost = math.floor(self.stamina_carry)
        self.stamina_carry -= cost
        note = self.spend_stamina(cost)
        # 时间不再按步算：走一格花行动点（超重 2 点），回合结束才过 1 分钟。
        # 这一步花了多少体力、多少行动点直接写进正文。控制台版和网页版共用这段。
        ap_cost = self._step_ap_cost(overweight)
        ap_text = self.spend_ap(ap_cost)
        extra = "，超重翻倍" if overweight else ""
        return f"体力消耗 {cost}，行动点 −{ap_cost}{extra}{ap_text}", note

    def _travel(self, direction, room):
        """换到相邻的地点（可能是走过门，也可能是没有场景数据时的直接走）。"""
        exit_ = room["exits"].get(direction)
        if exit_ is None:
            return self._no_path(room, direction)
        # 出口可以是房间 id，也可以是带条件的对象
        if isinstance(exit_, dict):
            required = exit_.get("requires")
            # 拿在手上 / 挂在身上也算带着（手电筒装备着照样能下地下室）
            if required and self.count_item(required) <= 0 and required not in self.equipped_ids():
                return exit_.get("blocked_message", "你过不去。")
            exit_ = exit_["to"]

        error, overweight, cost = self._prepare_move()
        if error:
            return error

        first_visit = exit_ not in self.visited
        self.current_room = exit_
        self.visited.add(exit_)
        # 第一次进某个地点才掷一次随机物资（见 roll_room_spawns），之后再来不会再生成
        if first_visit and self.character:
            self.roll_room_spawns(exit_)
            self.spawn_room_enemies(exit_)
        entry = self.entry_tile(exit_, direction)
        if entry:
            self.set_pos(entry)
        self.seen_enemy_ids = []  # 换了场景：新场景里的敌人都算“刚出现”
        cost_note, notes = self._pay_move(overweight, cost)
        self.check_enemies()
        text = self.describe_room()
        if cost_note:
            text += "\n" + cost_note + "。"
        if notes:
            text += "\n" + notes
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
        """推进时间，跨过午夜就进入下一天；食物和水源随时间下降。"""
        self._drain_needs(minutes)
        self.minutes += minutes
        while self.minutes >= stats.MINUTES_PER_DAY:
            self.minutes -= stats.MINUTES_PER_DAY
            self.day += 1

    def clock_total(self):
        """从第 START_DAY 天 0 点算起的绝对分钟数：算时限（饱腹、进食窗口）用它。"""
        return (self.day - stats.START_DAY) * stats.MINUTES_PER_DAY + self.minutes

    def roll_room_spawns(self, room_id):
        """第一次走进某个地点时，按世界数据里的随机物资掷一次。

        清单有两处来源（两份都会掷）：
          · 这个地点自己的 random_items
          · random_pool 指向的公共物资池（spawn_pools），min / max 写在这边，好几处地方能共用一份
        只在第一次进入时生成：之后再来（或者从存档读回来）都不会重新生成，
        免得反复进出刷物资。
        """
        room = self.world.rooms[room_id]
        specs = list(room.get("random_items") or [])
        for spec in room.get("random_pool") or []:
            for one in self.world.spawn_pools.get(spec.get("name"), []):
                specs.append(dict(one, min=spec.get("min", 1), max=spec.get("max", 1)))
        for spec in specs:
            count = self.dice.rng.randint(int(spec.get("min", 1)), int(spec.get("max", 1)))
            self.room_items[room_id] += [spec["id"]] * count

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
            for _ in range(stats.REST_MINUTES_PER_TICK):
                self._pass_turn()
            minutes += stats.REST_MINUTES_PER_TICK
        return (f"你眼前一黑，直接瘫倒在地上——体力彻底耗尽了。\n"
                f"（休克：强制休息 {minutes // 60} 小时 {minutes % 60} 分钟，"
                f"醒来时是 {self.clock_text()}，体力 {c.stamina}/{cap}）")

    def cmd_rest(self, arg):
        """休息：只推进时间、恢复体力，绝不提前结束。

        以前的写法是“体力一满就停下”，结果玩家想靠休息把时间推到晚上会被卡住。
        现在不管体力满没满，请求多久就过多久，只是体力最多补到上限。
        """
        c = self.character
        if not c:
            return "还没有创建角色。"
        cap = stats.stamina_max(c.attributes)
        if not arg:
            return ("你想休息多久？可以写 %d~%d 分钟，例如：休息 30、休息 2小时、休息 8小时。\n"
                    "（体力满了也能接着休息，只是时间照样过去）"
                    % (REST_MINUTES_MIN, REST_MINUTES_MAX))
        minutes = parse_minutes(arg)
        if minutes <= 0:
            return "没听明白要休息多久。可以写分钟数（休息 90），或者半小时 / 1小时 / 2小时 / 8小时。"
        clamped = ""
        if minutes < REST_MINUTES_MIN:
            minutes = REST_MINUTES_MIN
        elif minutes > REST_MINUTES_MAX:
            minutes = REST_MINUTES_MAX
            clamped = f"（一次最多休息 {format_duration(REST_MINUTES_MAX)}）\n"

        visible = self.visible_enemies()
        if visible:
            return f"附近有敌人（{'、'.join(e.label for e in visible)}），这时候可没法休息。"
        before = c.stamina
        rested = 0
        for _ in range(minutes):  # 1 回合 = 1 分钟：逐回合推进（快进，不花行动点）
            self._pass_turn()
            rested += 1
            if self.death_cause or self.interrupted:
                break
        c.stamina = min(cap, before + stats.rest_recovery(c.attributes, rested))
        if self.death_cause and rested < minutes:
            return f"你休息了 {format_duration(rested)}，再也没能醒来。"
        if rested < minutes:
            return (f"你才休息了 {format_duration(rested)} 就被打断了，现在是 {self.clock_text()}。"
                    f"体力 {before} → {c.stamina}/{cap}。")

        lines = [
            clamped + f"你休息了 {format_duration(minutes)}，现在是 {self.clock_text()}。",
            f"体力 {before} → {c.stamina}/{cap}。",
        ]
        if before >= cap:
            lines.append("（体力本来就是满的——休息不拦着你，时间就这么过去了。）")
        elif c.stamina >= cap:
            lines.append("（体力已经补满，多躺的那段时间也没白过。）")
        return "\n".join(lines)

    def conditions(self):
        """身上的异常状态。

        体力不足造成的力竭、超重这些是实时算出来的，不写进存档；口渴、饱腹记在角色身上，
        其中带时限（until）的过期后自动消失。
        """
        c = self.character
        if not c:
            return []
        self._purge_conditions()
        active = [dict(x) for x in c.conditions]
        for entry in active:  # 有时限的状态把“还剩多久”算出来给界面看
            if entry.get("until"):
                entry["note"] = f"还剩 {format_duration(self.condition_minutes_left(entry['until']))}"
        if stats.is_exhausted(c) and not any(x.get("id") == "exhausted" for x in active):
            active.insert(0, {
                "id": "exhausted",
                "name": "力竭",
                "source": "stamina",
                "effect": f"攻击力 {stats.EXHAUSTED_DAMAGE_PENALTY}%",
                "note": "体力低于上限的 10%，恢复体力即可解除",
            })
        level = self.load_level()
        if level != "normal":
            active.append(self._load_condition(level))
        for need in ("food", "water"):
            cond = self._need_condition(need)
            if cond:
                active.append(cond)
        active += self.dot_conditions()  # 流血、灼烧、强酸腐蚀（combat.py）
        return active

    def _purge_conditions(self):
        """把到期的临时状态（例如饱腹）从角色身上摘掉。"""
        c = self.character
        if not c:
            return
        now = self.clock_total()
        c.conditions = [x for x in c.conditions if not x.get("until") or x["until"] > now]

    def condition_minutes_left(self, until):
        """某个时限状态还剩多少分钟。"""
        return max(0, int(until - self.clock_total()))

    def has_condition(self, condition_id):
        """身上有没有这个异常状态（含力竭、超重这些实时算出来的）。"""
        return any(x.get("id") == condition_id for x in self.conditions())


    # ---------- 死亡 ----------

    def damage_player(self, amount, cause):
        """扣玩家生命；扣到 0 就死了，记下死因（stats.DEATH_CAUSES 的 id）。"""
        c = self.character
        if not c or self.death_cause or amount <= 0:
            return
        c.hp = max(0, c.hp - amount)
        if c.hp == 0:
            self.death_cause = cause

    def death_text(self):
        """“你死了”的文字（控制台和网页都用）。"""
        return f"======== 你死了 ========\n死因：{stats.DEATH_CAUSES.get(self.death_cause, self.death_cause)}"

    def spend_stamina(self, amount):
        """扣体力。返回要补在正文里的提示（现在没有，留着接口）。
        以前这里按累计消耗触发口渴；口渴现在由水源条决定（need_stage）。"""
        c = self.character
        if c and amount > 0:
            c.stamina = max(0, c.stamina - amount)
        return ""

    # ---------- 食物与水源 ----------

    def need_stage(self, need):
        """食物 / 水源当前的等级（0~3，见 stats.need_stage）。"""
        return stats.need_stage(getattr(self.character, need))

    def need_stamina_multiplier(self):
        """饥饿和口渴各自的体力倍率相乘（不同来源相乘）。"""
        if not self.character:
            return Fraction(1)
        return (stats.need_stamina_multiplier(self.need_stage("food"))
                * stats.need_stamina_multiplier(self.need_stage("water")))

    def _need_condition(self, need):
        stage = self.need_stage(need)
        if not stage:
            return None
        name = stats.NEED_STAGE_NAMES[need][stage - 1]
        effect = f"体力消耗 +{stats.NEED_STAGE_STAMINA_PERCENT[stage - 1]}%"
        if stage == 3:
            effect += f"，每回合生命 −{stats.NEED_STARVING_HP_PER_TURN}"
        fix = "吃点东西" if need == "food" else "喝点水"
        label = "食物" if need == "food" else "水源"
        return {"id": "hunger" if need == "food" else "thirst", "name": name, "source": need,
                "effect": effect, "note": f"{label} {getattr(self.character, need)}/{stats.NEED_MAX}，{fix}可以缓解"}

    def _drain_needs(self, minutes):
        """时间流逝：食物每 30 分钟 −1、水源每 15 分钟 −1；跨过等级时记一句提示。"""
        c = self.character
        if not c:
            return
        for need, per_point in (("food", stats.FOOD_MINUTES_PER_POINT), ("water", stats.WATER_MINUTES_PER_POINT)):
            before = self.need_stage(need)
            self.need_minutes[need] += minutes
            drop, self.need_minutes[need] = divmod(self.need_minutes[need], per_point)
            setattr(c, need, max(0, getattr(c, need) - drop))
            after = self.need_stage(need)
            if after > before:
                cond = self._need_condition(need)
                self.pending_notes.append(f"（你{cond['name'].rstrip('！')}了：{cond['effect']}）")

    def load_level(self):
        """当前负重状态（normal / overweight / immobile），见 stats.load_level。"""
        if not self.character:
            return "normal"
        return stats.load_level(self._carried_weight(), stats.carry_capacity(self.character.attributes))

    def _load_condition(self, level):
        capacity = stats.carry_capacity(self.character.attributes)
        weight = f"负重 {self._carried_weight():g}/{capacity} kg"
        if level == "immobile":
            return {"id": "immobile", "name": "严重超重", "source": "weight",
                    "effect": "完全无法移动",
                    "note": f"{weight}，超过上限的 {stats.IMMOBILE_WEIGHT_MULTIPLIER} 倍，放下些东西才能走"}
        return {"id": "overweight", "name": "超重", "source": "weight",
                "effect": f"移动能力减半（每格 {stats.OVERWEIGHT_MOVE_AP_COST} 行动点）",
                "note": f"{weight}，放下些东西即可解除"}

    def _load_change_note(self, before):
        """负重状态变了就补一句提示（拿东西、换背包之后用）。"""
        after = self.load_level()
        if after == before:
            return ""
        if after == "normal":
            return "\n负重恢复正常。"
        condition = self._load_condition(after)
        return f"\n你现在{condition['name']}了：{condition['effect']}。（{condition['note']}）"

    def clear_condition(self, condition_id):
        """清除异常状态（例如喝水解除口渴；留给以后的解毒剂之类道具调用）。

        体力不足造成的力竭不能直接清掉，必须先把体力补回来；其它来源的力竭可以清。
        """
        c = self.character
        if not c:
            return "还没有创建角色。"
        if condition_id == "exhausted" and stats.is_exhausted(c):
            return "这种力竭是体力耗尽引起的，清除异常状态的道具不管用，得先恢复体力。"
        cleared = self.clear_dot(condition_id)  # 持续伤害（例如绷带止血）
        if cleared:
            return cleared
        self._purge_conditions()
        found = next((x for x in c.conditions if x.get("id") == condition_id), None)
        if not found:
            return "身上没有这个异常状态。"
        c.conditions = [x for x in c.conditions if x.get("id") != condition_id]
        return f"{found.get('name', '异常状态')}解除了。"

    def _move_base_cost(self, overweight=False):
        """这一步的基础体力消耗（还没乘饥饿 / 口渴倍率）：只有凑满 10 步的那一步才扣，其余是 0；超重翻倍。"""
        if self.indoor_steps + 1 >= stats.INDOOR_STEPS_PER_COST:
            return stats.move_cost(overweight)
        return 0

    def next_move_cost(self, overweight=False):
        """下一步实际会扣多少体力：基础消耗 × 饥饿 / 口渴倍率，加上之前攒下的小数部分，向下取整。"""
        exact = self.stamina_carry + self._move_base_cost(overweight) * self.need_stamina_multiplier()
        return math.floor(exact)

    def cmd_wait(self, arg):
        """等待 = 结束当前回合：过 1 分钟，没用完的行动点保留（不超过上限 = 每回合获得量 × 2）。"""
        c = self.character
        if not c:
            return "还没有创建角色。"
        hp_before = c.hp
        kept = self.ap
        self._pass_turn()
        text = (f"你结束了这一回合（剩下的 {kept} 点行动点留到下回合），现在是 {self.clock_text()}。"
                f"行动点 {self.ap}/{self.ap_cap()}。")
        if c.hp > hp_before:
            text += f"\n生命恢复 {hp_before} → {c.hp}/{self.options.max_hp(c)}。"
        return text

    # ---------- 回合与行动点 ----------
    # 不分战斗内外：1 回合 = 1 分钟。每回合开始获得 敏捷×2（减重甲惩罚）点行动点，没用完的留到
    # 下回合（上限 = 每回合获得量 × 2）。移动、拾取、使用物品、换装备、技能都花行动点。
    # 回合结束的三种情况：玩家“等待”；行动点花到 0；指令要的行动点不够——先用剩下的行动点
    # 做掉一部分（例如走路先走几格；一个动作就算“做了一半”），结束回合，下回合补上剩下的。

    def nimble(self):
        """灵动步伐（被动）生效没有：学会了、并且两只手空着（武术技能的通用条件）。"""
        return (self.character and "martial_nimble_steps" in self.character.learned_skills and self.hands_empty())

    def _step_ap_cost(self, overweight):
        """这一格要扣几点行动点。灵动步伐：每格消耗减半——先付整数，多付的半格存着下一格用，回合结束清零。"""
        base = stats.OVERWEIGHT_MOVE_AP_COST if overweight else stats.MOVE_AP_COST
        if not self.nimble():
            return base
        need = Fraction(base, stats.NIMBLE_STEPS_PER_AP)
        if self.step_credit >= need:
            self.step_credit -= need
            return 0
        cost = math.ceil(need - self.step_credit)
        self.step_credit += cost - need
        return cost

    def ap_gain(self):
        return stats.ap_per_turn(self.character.attributes, self.armor_ap_penalty())

    def ap_cap(self):
        return stats.ap_cap(self.character.attributes, self.armor_ap_penalty())

    def _pass_turn(self):
        """你的回合结束：先攻比你低的敌人行动 → 过 1 分钟（饿 / 渴、回血、掉血）→ 新一轮：
        大家补行动点 → 先攻比你高的敌人行动 → 你身上的持续伤害结算 → 轮到你。
        被震慑的话，新的这一回合照样获得行动点，但不能行动，直接跳过（再过 1 分钟）。"""
        self._enemy_phase(before_player=False)
        self.turns += 1
        self.moved_this_turn = False
        self.step_credit = Fraction(0)
        self.advance_time(1)
        self._regenerate()
        if not self.character or self.death_cause:
            return
        self.ap = min(self.ap_cap(), self.ap + self.ap_gain())
        self._new_round()
        skipped = self._tick_stun()
        self._enemy_phase(before_player=True)
        self._tick_player_dots()
        self.check_enemies()
        if skipped and not self.death_cause:
            self.pending_notes.append("（你被震慑了，跳过了这一回合，行动点照样攒下）")
            self._pass_turn()

    # ---------- 眩晕 / 震慑（玩家）----------
    # 眩晕：下回合最后一个行动（等战斗流程接上）；同一回合第二次被眩晕 → 震慑：跳过下一个回合。

    def stun_player(self):
        """玩家被眩晕一次，返回现在的状态 id（stunned / dazed）。"""
        c = self.character
        cur = next((x for x in c.conditions if x.get("id") in stats.STUN_CONDITIONS), None)
        count = cur.get("count", 1) + 1 if cur and cur.get("turn") == self.turns else 1
        level = "dazed" if cur and cur["id"] == "dazed" else stats.stun_level(count)
        c.conditions = [x for x in c.conditions if x is not cur]
        c.conditions.append({"id": level, "name": stats.STUN_CONDITIONS[level],
                             "effect": stats.STUN_EFFECTS[level], "turn": self.turns, "count": count})
        return level

    def _tick_stun(self):
        """新回合开始时结算眩晕类状态：震慑 → 这一回合跳过（返回 True）并解除；
        眩晕 → 撑过被眩晕后的那一整个回合才解除。"""
        c = self.character
        for x in list(c.conditions):
            if x.get("id") == "dazed" and self.turns > x["turn"]:
                c.conditions.remove(x)
                return True
            if x.get("id") == "stunned" and self.turns > x["turn"] + 1:
                c.conditions.remove(x)
        return False

    def cmd_stun_test(self, arg):
        """试眩晕 [次数]：这一回合里让自己被眩晕几次（演示眩晕 → 震慑），不花行动点。"""
        if not self.character:
            return "还没有创建角色。"
        times = max(1, min(5, int(arg))) if arg.isdigit() else 1
        lines = []
        for n in range(times):
            level = self.stun_player()
            lines.append(f"第 {n + 1} 次：你【{stats.STUN_CONDITIONS[level]}】——{stats.STUN_EFFECTS[level]}")
        lines.append("（测试：结束回合后就能看到效果；震慑会让下一回合直接跳过，但行动点照拿）")
        return "\n".join(lines)

    def spend_ap(self, cost):
        """花行动点。不够就先把剩下的花掉、结束回合、下回合接着付；花到 0 也结束回合。
        返回附在正文后面的说明（过了几个回合），没跨回合就是空字符串。"""
        if not self.character:
            return ""
        passed = 0
        while cost > self.ap and not self.death_cause:
            cost -= self.ap
            self.ap = 0
            self._pass_turn()
            passed += 1
        if self.death_cause:
            return ""
        self.ap -= cost
        if self.ap == 0:
            self._pass_turn()
            passed += 1
        if not passed:
            return f"（行动点剩 {self.ap}）"
        # 跨了回合：单独一行写在指令输出最后（由 _with_notes 接上）
        self.pending_notes.append("—— 回合结束" + (f"（过了 {passed} 回合）" if passed > 1 else "")
                                  + f"，现在是 {self.clock_text()}，行动点 {self.ap}/{self.ap_cap()} ——")
        return ""

    def _regenerate(self):
        """每个回合结束时调用：每隔一定回合按体质恢复生命；饿死了 / 渴死了每回合掉血。"""
        c = self.character
        if not c:
            return
        if self.turns % stats.REGEN_INTERVAL == 0:
            c.hp = min(self.options.max_hp(c), c.hp + stats.hp_regen(c.attributes))
        for need, cause in (("food", "hunger"), ("water", "thirst")):
            if self.need_stage(need) == 3 and not self.death_cause:
                self.damage_player(stats.NEED_STARVING_HP_PER_TURN, cause)
                self.starving_drain += stats.NEED_STARVING_HP_PER_TURN

    def _flush_starving_note(self):
        """把这段时间里饿 / 渴掉的血汇成一句提示（休息几百分钟也只说一次）。"""
        if self.starving_drain:
            self.pending_notes.append(f"（饥饿 / 脱水让你越来越虚弱：生命 −{self.starving_drain}，"
                                      f"剩 {self.character.hp}）")
            self.starving_drain = 0

    # ---------- 背包：一格一堆 ----------
    #
    # self.inventory 里每一项都是一“堆”东西：
    #     {"sid": 1, "id": "water", "count": 3, "auto": True}
    # sid 是这一堆的编号（界面拖动 / 拆分时靠它指定具体哪一堆），
    # auto=True 表示“以后捡到同种东西可以自动摞进来”。手动拆分出来的那一堆
    # auto=False，所以不会被自动摞回去，但可以手动拖到同种物品上合并。
    # 只有物品数据里带 stack 词条的才摞得起来，别的物品一格一件、也不能拆分。

    def stack_limit(self, item_id):
        """这一堆最多几个。"""
        return stats.stack_max(self.world.items[item_id])

    def _new_stack(self, item_id, count=1, auto=True):
        stack = {"sid": self.next_stack_id, "id": item_id, "count": int(count), "auto": bool(auto)}
        self.next_stack_id += 1
        return stack

    def add_item(self, item_id, count=1, auto=True):
        """把东西放进背包：带 stack 词条又允许自动堆叠的，先往已有的堆里摞（摞满为止）。"""
        left = int(count)
        limit = self.stack_limit(item_id) if auto else 1
        if limit > 1:
            for stack in self.inventory:
                if left <= 0:
                    break
                if stack["id"] != item_id or not stack["auto"]:
                    continue
                room = limit - stack["count"]
                if room <= 0:
                    continue
                take = min(room, left)
                stack["count"] += take
                left -= take
        while left > 0:
            take = min(limit, left)
            self.inventory.append(self._new_stack(item_id, take, auto))
            left -= take

    def take_item(self, item_id, count=1):
        """从背包里拿走几个（按顺序拿，拿光了就把那一堆删掉），返回真正拿走的数量。"""
        left = int(count)
        taken = 0
        for stack in list(self.inventory):
            if left <= 0:
                break
            if stack["id"] != item_id:
                continue
            take = min(stack["count"], left)
            stack["count"] -= take
            left -= take
            taken += take
            if stack["count"] <= 0:
                self.inventory.remove(stack)
        return taken

    def count_item(self, item_id):
        """背包里这种东西一共有几个。"""
        return sum(stack["count"] for stack in self.inventory if stack["id"] == item_id)

    def inventory_ids(self):
        """背包里所有物品 id（有几个就重复几次），指令解析用它来找东西。"""
        ids = []
        for stack in self.inventory:
            ids += [stack["id"]] * stack["count"]
        return ids

    def find_stack(self, sid):
        """按编号找一堆东西。"""
        return next((stack for stack in self.inventory if stack["sid"] == sid), None)

    def merge_stacks(self, source, target):
        """把 source 这堆摞到 target 上（摞满为止，剩下的留在原来那堆）。"""
        limit = self.stack_limit(target["id"])
        room = limit - target["count"]
        if room <= 0:
            return 0
        moved = min(room, source["count"])
        target["count"] += moved
        source["count"] -= moved
        if source["count"] <= 0:
            self.inventory.remove(source)
        return moved

    def _stack_arg(self, arg):
        """解析“<物品名 或 堆号> [数量]”，返回 (指定的堆, 物品 id, 数量)。

        第一段写成数字（例如界面拖动时发的“3”）就是指定第 3 堆，
        否则按名字 / 别名找背包里的东西。认不出来时对应项是 None。
        """
        parts = (arg or "").split()
        count = None
        if len(parts) > 1 and parts[-1].isdigit():
            count = int(parts[-1])
            parts = parts[:-1]
        head = " ".join(parts).strip()
        if not head:
            return None, None, count
        stack = self.find_stack(int(head)) if head.isdigit() else None
        if stack:
            return stack, stack["id"], count
        item_id = self._match(head, self.inventory_ids(), self.world.items)
        return None, item_id, count

    def cmd_split(self, arg):
        """拆分：从一堆里分出几个，分出来的那堆不会被自动堆叠。"""
        if not arg:
            return "你想拆开什么？例如：拆分 矿泉水 2"
        stack, item_id, count = self._stack_arg(arg)
        if not item_id:
            return f"你身上没有{arg}。"
        name = self.world.items[item_id]["name"]
        if self.stack_limit(item_id) <= 1:
            return f"{name}没有堆叠词条，一格就是一件，拆不开。"
        if stack is None:
            stack = next((s for s in self.inventory if s["id"] == item_id and s["count"] > 1), None)
        if stack is None:
            return f"背包里的{name}只有一件，没什么好拆的。"
        if stack["count"] < 2:
            return f"这堆{name}只有 {stack['count']} 个，没什么好拆的。"
        if count is None:
            count = stack["count"] // 2
        count = max(1, min(count, stack["count"] - 1))
        split = self._new_stack(item_id, count, auto=False)
        stack["count"] -= count
        self.inventory.insert(self.inventory.index(stack) + 1, split)
        return (f"你把{name}拆成 {stack['count']} 个和 {count} 个。"
                f"分开的那 {count} 个不会自动摞回原堆，但可以再拖回去合并。")

    def cmd_stack(self, arg):
        """合并：把一堆摞到另一堆上。界面拖动时发“堆叠 <来源堆号> <目标堆号>”。"""
        if not arg:
            return "你想把什么摞起来？例如：堆叠 矿泉水"
        parts = arg.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            source, target = self.find_stack(int(parts[0])), self.find_stack(int(parts[1]))
            if not source or not target:
                return "这两堆东西已经不在背包里了。"
            if source is target:
                return "它们本来就是同一堆。"
            if source["id"] != target["id"]:
                return "只有同一种东西才摞得起来。"
            name = self.world.items[target["id"]]["name"]
            moved = self.merge_stacks(source, target)
            if not moved:
                return f"这堆{name}已经摞满了（{target['count']}/{self.stack_limit(target['id'])}）。"
            text = f"你把 {moved} 个{name}摞到了一起，现在这堆有 {target['count']} 个。"
            if source["count"] > 0:
                text += f"（还剩下 {source['count']} 个，这堆满了）"
            return text
        item_id = self._match(arg, self.inventory_ids(), self.world.items)
        if not item_id:
            return f"你身上没有{arg}。"
        name = self.world.items[item_id]["name"]
        if self.stack_limit(item_id) <= 1:
            return f"{name}没有堆叠词条，一格就是一件，摞不起来。"
        stacks = [s for s in self.inventory if s["id"] == item_id]
        if len(stacks) < 2:
            return f"背包里的{name}只有一堆，不用合并。"
        target = stacks[0]
        moved = 0
        for source in stacks[1:]:
            if source not in self.inventory:
                continue
            moved += self.merge_stacks(source, target)
        if not moved:
            return f"{name}这几堆都已经摞满了（每堆 {self.stack_limit(item_id)} 个）。"
        left = sum(s["count"] for s in self.inventory if s["id"] == item_id)
        return f"你把{name}摞到一起，现在一共 {left} 个。"

    def equipped_ids(self):
        """手上和身上穿着的物品（双手武器两个槽是同一件，去重）。"""
        return {i for i in self.equipment.values() if i} | {i for i in self.worn.values() if i}

    def all_carried(self):
        """背包 + 手上 + 身上：负重按这些算（装备了也一样压在身上）。"""
        ids = self.inventory_ids()
        ids += sorted(self.equipped_ids())
        return ids

    def _carried_weight(self, extra=0):
        """身上所有东西的重量（extra 是准备拿起来的东西），按背着的背包的减重率打折。"""
        raw = sum(self.world.items[i].get("weight", 1) for i in self.all_carried()) + extra
        # 重量保留 1 位小数，向下取整（用 Decimal 避免 0.1 这类小数的浮点误差）
        total = max(Decimal(0), Decimal(str(round(raw, 6))) * (100 - self.backpack_reduction()) / 100)
        return float(total.quantize(Decimal("0.1"), rounding=ROUND_FLOOR))

    def can_stow(self, item_id):
        """背包还塞得下这件东西吗？按负重上限算（塞进去会超重就是塞不下）。"""
        if not self.character:
            return True
        capacity = stats.carry_capacity(self.character.attributes)
        weight = self.world.items[item_id].get("weight", 1)
        return self._carried_weight(weight) <= capacity

    def _to_ground(self, item_id):
        """把东西丢在当前房间的地上，并给它找个格子。"""
        room_id = self.current_room
        grid = self.room_grid()
        # 先把坐标表补齐成和 room_items 一样长（_drop_tile 里也会补一遍），之后两边一起加，
        # 顺序就一直对得上。没有场景数据的房间只留 None。
        table = (self.ground_positions_in(room_id) if grid
                 else self.ground_positions.setdefault(room_id, []))
        while len(table) < len(self.room_items[room_id]):
            table.append(None)
        tile = self._drop_tile(grid) if grid else None
        self.room_items[room_id].append(item_id)
        table.append([tile[0], tile[1]] if tile else None)
        return tile

    def stow(self, item_id):
        """把一件装备/武器放回背包；塞不下就丢在脚下。返回要补的那句话（放得下就是空）。"""
        name = self.world.items[item_id]["name"]
        if self.can_stow(item_id):
            self.add_item(item_id)
            return ""
        self._to_ground(item_id)
        return f"\n背包已经塞不下了，{name}被你丢在脚下。"

    def stow_all(self, item_ids):
        """把一堆东西放回背包，返回要补的说明（可能有好几句）。"""
        return "".join(self.stow(i) for i in sorted(item_ids))

    def backpack_reduction(self):
        """减重率（%）= 背着的背包 + perk（井井有条 +20%），加算，最高 100。"""
        perk = self.options.perk_effect(self.character.perks, "weight_reduction") if self.character else 0
        backpack = 0
        for item_id in self.worn.values():
            gear = self.world.items[item_id].get("gear") if item_id else None
            if gear and gear.get("weight_reduction"):
                backpack = gear["weight_reduction"]
                break
        return backpack + perk  # 理论上没有上限（超过 100% 时重量按 0 算）

    def cmd_take(self, arg):
        if not arg:
            return "你想拿什么？"
        items = self.room_items[self.current_room]
        item_id = self._match(arg, items, self.world.items)
        if not item_id:
            return "这里没有这样东西。"
        name = self.world.items[item_id]["name"]
        # 拾取要走到跟前（同一格或相邻一格，斜角也算），不能远程拿；查看不受限
        index = items.index(item_id)
        grid = self.room_grid()
        if grid:
            pos = self.player_pos(grid)
            coords = self.ground_positions_in()

            def distance(at):
                coord = coords[at] if at < len(coords) else None
                if not coord:
                    return 99
                return max(abs(coord[0] - pos[0]), abs(coord[1] - pos[1]))

            # 同一种东西地上可能摆着好几件：拿离自己最近的那一件
            index = min((at for at, i in enumerate(items) if i == item_id), key=distance)
            coord = coords[index] if index < len(coords) else None
            if coord and not self.near(pos, coord):
                return (f"{name}在（第 {coord[0] + 1} 列，第 {coord[1] + 1} 行），"
                        f"你得先走到那一格旁边再拿。")
        # 超重也能拿，只是会影响移动（见 stats.load_level）
        before = self.load_level()
        items.pop(index)
        table = self.ground_positions.get(self.current_room) or []
        if index < len(table):
            table.pop(index)  # 坐标和物品一一对应，删东西要连它的那一格一起删
        self.add_item(item_id)  # 进背包就自动摞进同种的那一堆
        return (f"你拿起了{name}。" + self._load_change_note(before)
                + self.spend_ap(stats.PICKUP_AP_COST))

    def cmd_drop(self, arg):
        """放下 / 丢掉。后面可以写数量（例如：放下 矿泉水 3），不写就是一件。"""
        if not arg:
            return "你想放下什么？"
        parts = arg.split()
        count = 1
        if len(parts) > 1 and parts[-1].isdigit():
            count = max(1, int(parts[-1]))
            arg = " ".join(parts[:-1])
        # 手上拿着的、身上穿着的也算“你身上的东西”
        item_id = self._match(arg, self.inventory_ids() + sorted(self.equipped_ids()), self.world.items)
        if not item_id:
            return "你身上没有这样东西。"
        name = self.world.items[item_id]["name"]
        before = self.load_level()
        in_bag = self.count_item(item_id)
        if not in_bag:  # 装备着的：先脱下来（和“卸下”一样花行动点），再丢在地上
            worn = item_id in self.worn.values()
            cost = (stats.ARMOR_AP_COST if worn and self._armor(item_id)
                    else stats.GEAR_AP_COST if worn else stats.HOLD_AP_COST)
            self._unequip(item_id)
            self._to_ground(item_id)
            return (f"你放下了{name}。" + self._check_stance() + self._load_change_note(before)
                    + self.spend_ap(cost))
        count = min(count, in_bag)
        self.take_item(item_id, count)
        for _ in range(count):
            self._to_ground(item_id)
        text = f"你放下了{name} ×{count}。" if count > 1 else f"你放下了{name}。"
        return text + self._check_stance() + self._load_change_note(before) + self.spend_ap(stats.BAG_AP_COST)

    def cmd_use(self, arg):
        """使用物品。效果写在物品数据的 use 字段里，见 items.py。"""
        if not self.character:
            return "还没有创建角色。"
        if not arg:
            return "你想用什么？例如：使用 能量棒"
        item_id = self._match(arg, self.inventory_ids(), self.world.items)
        if not item_id:
            return f"你身上没有{arg}。"
        error = items.use_error(self, self.character, item_id)
        if error:
            return error
        return items.use(self, self.character, item_id) + self.spend_ap(stats.USE_ITEM_AP_COST)

    def cmd_inventory(self, arg):
        """背包和装备分开列：装备着的东西不在背包里；同种东西摞成一堆显示。"""
        lines = []
        if self.inventory:
            parts = []
            for stack in self.inventory:
                name = self.world.items[stack["id"]]["name"]
                parts.append(name if stack["count"] <= 1 else f"{name} ×{stack['count']}")
            lines.append("背包里：" + "、".join(parts))
        else:
            lines.append("你的背包是空的。")
        equipped = [(self.item_location(i), self.world.items[i]["name"])
                    for i in sorted(self.equipped_ids())]
        if equipped:
            lines.append("装备着：" + "、".join(f"{where}{name}" for where, name in equipped))
        if self.character:
            capacity = stats.carry_capacity(self.character.attributes)
            lines.append(f"负重：{self._carried_weight():g}/{capacity} kg")
        return "\n".join(lines)

    def cmd_map(self, arg):
        return render_map(self.world, self.current_room, self.visited, self.room_items)

    def cmd_status(self, arg):
        if not self.character:
            return "还没有创建角色。"
        tree_names = {t["id"]: t["name"] for t in self.skill_trees.trees}
        bonuses = stances.stance_bonuses(self.character, self._current_stance(), self.skill_trees)
        sheet = format_sheet(
            self.character, self.options, self.world.items, self._carried_weight(), tree_names, bonuses,
            self.armor_ap_penalty(), overweight=self.load_level() == "overweight",
        )
        worn = [(self.world.wear_slot_names[s], i) for s, i in self.worn.items() if i and self._armor(i)]
        armor_line = f"  护甲 {self.armor_total()}" + (
            "：" + "、".join(f"{slot} {self.item_display_name(i)} +{stats.armor_value(self.world.items[i])}"
                            for slot, i in worn)
            if worn else "：什么也没穿")
        gear_line = "  " + "    ".join(
            f"{info['name']} " + (self.world.items[self.worn[slot]]["name"] if self.worn[slot] else "空")
            for slot, info in self.world.gear_slots.items()
        )
        if self.backpack_reduction():
            gear_line += f"（减重 {self.backpack_reduction()}%）"
        active = self.passive_effects("crit_range_multiplier") + self.passive_effects("armor_ignore")
        passives = ("（生效中：" + "、".join(sorted({name for name, _ in active})) + "）") if active else ""
        if self.armor_ignore():
            passives += f"，攻击无视 {self.armor_ignore()} 点护甲"

        def damage_text(w):
            if not w["damage"]:
                return "伤害未定"
            multiplier = stats.damage_multiplier(w["damage_modifiers"])
            return (f"伤害 {w['damage']}" + (f" ×{float(multiplier):g}" if multiplier != 1 else "")
                    + f"，暴击 {w['crit_range']}" + (f"，射程 {w['range']}" if w.get("range") else "")
                    + (f"，无视护甲 {w['armor_ignore']}" if w.get("armor_ignore") else "")
                    + (f"，标签：{'、'.join(w['tag_names'])}" if w.get("tag_names") else ""))

        weapons = "\n".join(
            f"  {w['hand']} {w['name']}（{w['type']}）：精准 {w['accuracy']:g}（{w['attribute']}"
            + (f"，含姿态 {w['stance_bonus']:+g}" if w["stance_bonus"] else "")
            + (f"，含等阶 {w['quality_bonus']:+d}" if w["quality_bonus"] else "")
            + (f"，含绝境 {w['last_stand_bonus']:+d}" if w.get("last_stand_bonus") else "") + f"），{damage_text(w)}"
            for w in self.weapon_summary()
        )
        stance = self._current_stance()
        conditions = self.conditions()
        active = "、".join(f"{x['name']}（{x['effect']}）" for x in conditions) if conditions else "无"
        return (sheet
                + f"\n\n【装备与姿态】\n  持握：{self.grip_name()}{passives}\n{weapons}\n{armor_line}\n{gear_line}"
                + (f"\n  格挡：每回合 {self.blocks_per_turn()} 次，格挡修正 {stats.block_modifier(self.character.attributes)}"
                   f"（体质×1.5 + 力量）" if self.blocks_per_turn() else "")
                + f"\n  姿态：{stance['name'] if stance else '无'}"
                + f"\n  视野 {self.sight_range()} 格" + (f"（护甲 −{self.armor_sight_penalty()}）" if self.armor_sight_penalty() else "")
                + f"\n  行动点消耗：普通攻击 {stats.ATTACK_AP_COST}{self._offhand_cost_text()}、"
                  f"移动 1 格 {self._move_cost_text()}、使用物品 {stats.USE_ITEM_AP_COST}、拾取 {stats.PICKUP_AP_COST}、"
                  f"拿起 / 收起 / 换手 {stats.HOLD_AP_COST}、穿脱护甲 {stats.ARMOR_AP_COST}"
                + f"\n  当前行动点 {self.ap}/{self.ap_cap()}（每回合 +{self.ap_gain()}，1 回合 = 1 分钟）"
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

    def use_skill_check(self, skill):
        """能不能现在用这个主动技能：返回一句说明，能用就返回 None。

        战斗回合流程还没接上，所以这里只把"数据上说得通"的部分先校验掉：
        学过、是主动技能、手上的武器 / 持握方式对得上。冷却等接上流程再算。
        """
        if not self.character:
            return "还没有创建角色。"
        name = skill["name"]
        if skill["id"] not in self.character.learned_skills:
            return f"你还没学会「{name}」，先去技能树里学（学习 {name}）。"
        if skill.get("type") != "active":
            return f"「{name}」是被动技能，不用主动释放。"
        weapon_type = skill.get("weapon_type")
        if weapon_type and weapon_type not in self._wielded_types():
            return (f"「{name}」需要手持{self.world.weapon_types.get(weapon_type, weapon_type)}武器，"
                    f"先装备一把。")
        if self.skill_trees.tree(skill["tree"]).get("unarmed_only") and not self.hands_empty():
            return f"「{name}」是武术，两只手都不能拿东西（先把手上的东西收起来）。"
        grip = skill.get("grip")
        if grip and self.grip_style() != grip:
            return f"「{name}」要在{stats.GRIPS[grip]}状态下用（现在是{self.grip_name()}）。"
        cost = skills.ap_cost(skill)
        if self.ap < cost:
            return (f"「{name}」要 {cost} 点行动点，你现在只有 {self.ap} 点。\n"
                    f"先结束回合（或者等）攒回来。")
        return None

    def cmd_use_skill(self, arg):
        """用 <技能>：快捷释放一个主动技能（技能栏里的格子点一下就是发这句）。

        「用」也能顺手用物品（「用 肉罐头」走 cmd_use）：先当技能找，找不到技能才当物品，
        这样两种写法都不用记前缀。
        """
        if not self.character:
            return "还没有创建角色。"
        if not arg:
            return "你想用哪个技能？例如：用 盾击"
        skill = self.skill_trees.find_skill(arg)
        if not skill:
            return self.cmd_use(arg)
        error = self.use_skill_check(skill)
        if error:
            return error
        cost = skills.ap_cost(skill)
        note = self.spend_ap(cost)
        text = (f"你用出了「{skill['name']}」（花 {cost} 点行动点）。\n"
                f"（战斗回合流程还没接上，这一下暂时只有动作，没有实际效果。）")
        return text + ("\n" + note if note else "")

    # ---------- 装备与姿态 ----------

    def _weapon(self, item_id):
        return self.world.items[item_id].get("weapon") if item_id else None

    # 删掉的旧技能（占位技能）当初花了几点：读档时退回去
    REMOVED_SKILL_COSTS = {"blunt_1": 1, "blunt_2": 2, "martial_1": 1, "martial_2": 2}

    def _load_skills(self):
        """存档里学过、但现在技能树里已经没有的技能：去掉，并退还技能点。"""
        c = self.character
        gone = [s for s in c.learned_skills if not self.skill_trees.find_skill(s)]
        if not gone:
            return []
        refund = sum(self.REMOVED_SKILL_COSTS.get(s, 1) for s in gone)
        c.learned_skills = [s for s in c.learned_skills if s not in gone]
        c.skill_points += refund
        return [f"{len(gone)} 个已删除的旧技能退还了 {refund} 点技能点"]

    def hands_empty(self):
        """两只手都没拿任何东西（武器、盾牌都不行）：武术技能、武道姿态的使用条件。"""
        return not any(self.equipment.values())

    def stance_usable(self, stance):
        """姿态的武器要求满足没有：徒手姿态要两手空空，其余要手里有对应类型的武器。"""
        if stance["weapon_type"] == stats.UNARMED:
            return self.hands_empty()
        return stance["weapon_type"] in self._wielded_types()

    def _stance_requirement(self, stance):
        if stance["weapon_type"] == stats.UNARMED:
            return "两只手都空着"
        return f"手持{self.world.weapon_types[stance['weapon_type']]}武器"

    def _wielded_types(self):
        types = set()
        for i in self.equipment.values():
            if self._weapon(i):
                types |= self.weapon_counts_as(self._weapon(i)["type"])
        return types

    def weapon_counts_as(self, weapon_type):
        """这类武器在应用技能 / 姿态时算哪些类型。刀锋舞者（perk）：重刃、轻刃互相视为对方。"""
        if (weapon_type in stats.BLADE_TYPES and self.character
                and self.options.perk_effect(self.character.perks, "blades_as_both")):
            return set(stats.BLADE_TYPES)
        return {weapon_type}

    def _shield(self, item_id):
        """是不是盾牌（物品带 shield 字段就算，内容可以是空的）。"""
        return bool(item_id) and "shield" in self.world.items[item_id]

    def _current_stance(self):
        return self.skill_trees.stance(self.stance) if self.stance else None

    def _unequip(self, item_id):
        for slot, held in self.equipment.items():
            if held == item_id:
                self.equipment[slot] = None
        for slot, held in self.worn.items():
            if held == item_id:
                self.worn[slot] = None

    def item_location(self, item_id):
        """物品现在拿在哪只手 / 穿在哪个部位，没装备就是空字符串。"""
        slot_names = {"main_hand": "主手", "off_hand": "副手"}
        hands = [slot_names[s] for s, held in self.equipment.items() if held == item_id]
        if hands:
            return "双手" if len(hands) == 2 else hands[0]
        worn = [self.world.wear_slot_names[s] for s, held in self.worn.items() if held == item_id]
        return worn[0] if worn else ""

    def _armor(self, item_id):
        return self.world.items[item_id].get("armor") if item_id else None

    def armor_total(self):
        """身上所有部位的护甲值之和。"""
        return sum(stats.armor_value(self.world.items[i]) for i in self.worn.values() if self._armor(i))

    def armor_sight_penalty(self):
        """身上护甲带来的视野减少量（每件的 sight_penalty 相加）。"""
        return sum(self._armor(i).get("sight_penalty", 0) for i in self.worn.values() if self._armor(i))

    def sight_range(self):
        """视野范围 = 4 + 感知 − 护甲的视野惩罚。"""
        bonus = self.options.perk_effect(self.character.perks, "sight_bonus")  # 警觉 +2
        return stats.sight_range_with(self.character.attributes, self.armor_sight_penalty()) + bonus

    def item_display_name(self, item_id):
        """装备名字前加上等阶（普通的不加），例如“精良 防暴护甲”。"""
        item = self.world.items[item_id]
        quality = item.get("quality", "normal")
        return item["name"] if quality == "normal" else f"{stats.quality_name(item)} {item['name']}"

    def armor_ap_penalty(self):
        """身上重甲的 ap_penalty 相加（每点 = 每回合行动点 −5%，见 stats.ap_per_turn）。"""
        return sum(self._armor(i).get("ap_penalty", 0) for i in self.worn.values() if self._armor(i))

    def _take_from_inventory(self, item_id):
        """从背包里拿出这件东西（装备时会用到）；不在背包里就什么也不做。"""
        self.take_item(item_id, 1)

    def _wear(self, item_id):
        """穿戴到对应的位置：有空位就放空位（饰品有两个），都满了就换下第一个。"""
        name = self.world.items[item_id]["name"]
        if item_id in self.worn.values():
            return f"你已经装备着{name}了。"
        candidates = self.world.wear_candidates(item_id)
        slot = next((s for s in candidates if not self.worn[s]), candidates[0])
        old = self.worn[slot]
        self._take_from_inventory(item_id)
        self.worn[slot] = item_id
        slot_name = self.world.wear_slot_names[slot]
        armor = self._armor(item_id)
        if armor:
            class_name = stats.ARMOR_CLASSES[armor["class"]][0]
            text = (f"你穿上了{self.item_display_name(item_id)}（{slot_name}，{class_name}，"
                    f"护甲 +{stats.armor_value(self.world.items[item_id])}")
            if armor.get("ap_penalty"):
                text += f"，每回合行动点 −{stats.armor_ap_percent(armor['ap_penalty'])}%"
            if armor.get("sight_penalty"):
                text += f"，视野 −{armor['sight_penalty']}"
            text += f"）。现在总护甲 {self.armor_total()}。"
        else:
            reduction = self.world.items[item_id]["gear"].get("weight_reduction")
            text = f"你装备了{name}（{slot_name}" + (f"，减重 {reduction}%" if reduction else "") + "）。"
        note = ""
        if old:
            text = f"你换下了{self.world.items[old]['name']}，" + text
            note = self.stow(old)  # 换下来的那件回背包（塞不下就丢在脚下）
        return text + note

    def _check_stance(self):
        """换下武器后，如果不再满足当前姿态的武器要求，就自动解除姿态。"""
        stance = self._current_stance()
        if stance and not self.stance_usable(stance):
            self.stance = None
            return f"\n不再满足{stance['name']}姿态的条件（{self._stance_requirement(stance)}），姿态解除。"
        return ""

    def _hold_type(self, item_id):
        return stats.hold_type(self.world.items[item_id]) if item_id else None

    def _holding_two_handed(self):
        main = self.equipment["main_hand"]
        return bool(main) and main == self.equipment["off_hand"]

    def _switch_hand(self, item_id, want):
        """把已经拿在手上的单手物换到另一只手：另一只手空着就挪过去，拿着单手物就互换。

        返回一句结果文字；不适用的情况（不是单手物）返回 None，调用方会退回“你已经拿着 X 了”。
        """
        source = next((s for s, held in self.equipment.items() if held == item_id), None)
        if not source or source == want or self._hold_type(item_id) != "one_hand":
            return None
        where = "主手" if want == "main_hand" else "副手"
        from_where = "主手" if source == "main_hand" else "副手"
        name = self.world.items[item_id]["name"]
        other = self.equipment[want]
        if other and self._hold_type(other) != "one_hand":
            return (f"{name}现在拿在{from_where}；{where}那边的{self.world.items[other]['name']}"
                    f"只能拿在{stats.HOLD_TYPES[self._hold_type(other)]}，换不过去——先把它收起来。")
        self.equipment[source], self.equipment[want] = other, item_id
        if other:
            return f"你把{name}换到{where}，{self.world.items[other]['name']}换到{from_where}。"
        return f"你把{name}从{from_where}换到{where}。"

    def _hold(self, item_id, want=None):
        """把手持物（武器、盾牌……）拿到手上，按类别决定放哪只手：
        单手：指定了就放指定的手；没指定先放主手，主手有东西放副手，都满了替换主手。
        双手：只能放主手，同时占掉副手（两只手原来的东西都收起来）。
        主手 / 副手：只能放在那一只手。
        手上原本是双手物的话，换任何东西都要先把它整个放下。"""
        name = self.world.items[item_id]["name"]
        kind = self._hold_type(item_id)
        allowed = stats.hold_slots(self.world.items[item_id])
        if want and want not in allowed:
            return f"{name}是{stats.HOLD_TYPES[kind]}物品，只能拿在{'、'.join('主手' if s == 'main_hand' else '副手' for s in allowed)}。"
        put_away = set()
        if kind == "two_hand" or self._holding_two_handed():
            put_away = {i for i in self.equipment.values() if i} if kind == "two_hand" else {self.equipment["main_hand"]}
            if kind != "two_hand":
                self.equipment = {"main_hand": None, "off_hand": None}
        if kind == "two_hand":
            self.equipment = {"main_hand": item_id, "off_hand": item_id}
            where = "双手"
        else:
            if want:
                slot = want
            elif len(allowed) == 1:
                slot = allowed[0]
            elif not self.equipment["main_hand"]:
                slot = "main_hand"
            elif not self.equipment["off_hand"]:
                slot = "off_hand"
            else:
                slot = "main_hand"
            if self.equipment[slot]:
                put_away.add(self.equipment[slot])
            self.equipment[slot] = item_id
            where = "主手" if slot == "main_hand" else "副手"
        self._take_from_inventory(item_id)
        text = f"你把{name}拿在{where}。"
        put_away.discard(None)
        if put_away:
            text = "你收起了" + "、".join(self.world.items[i]["name"] for i in put_away) + "，" + text
        return text + self.stow_all(put_away) + self._check_stance()

    def cmd_equip(self, arg):
        return self._with_gear_cost(self._cmd_equip, arg)

    def _with_gear_cost(self, fn, arg):
        """装备 / 卸下 / 换手：执行成功（手上或身上的东西变了）才花行动点。
        动到护甲就是穿脱护甲（6 点），否则是手持物 / 背包饰品（1 点）。"""
        before = (dict(self.equipment), dict(self.worn))
        text = fn(arg)
        after = (self.equipment, self.worn)
        changed = {i for b, a in zip(before, after) for s in set(b) | set(a) if b.get(s) != a.get(s)
                   for i in (b.get(s), a.get(s)) if i}
        if not changed or not self.character:
            return text
        if any(self._armor(i) for i in changed if i in before[1].values() or i in self.worn.values()):
            cost = stats.ARMOR_AP_COST
        elif any(i in before[1].values() or i in self.worn.values() for i in changed):
            cost = stats.GEAR_AP_COST
        else:
            cost = stats.HOLD_AP_COST
        return text + self.spend_ap(cost)

    def _cmd_equip(self, arg):
        if not arg:
            return "你想装备什么？"
        # 末尾可以写“主手 / 副手”，指定拿到哪只手上（网页版拖动时会带上）
        want = None
        parts = (arg or "").split()
        if len(parts) > 1 and parts[-1] in ("主手", "副手"):
            want = "main_hand" if parts[-1] == "主手" else "off_hand"
            arg = " ".join(parts[:-1])
        item_id = self._match(arg, self.inventory_ids(), self.world.items)
        if not item_id:
            held = self._match(arg, sorted(self.equipped_ids()), self.world.items)
            if held and want:
                # 已经拿在手上的东西：拖到另一只手的方框上就直接换手
                switched = self._switch_hand(held, want)
                if switched:
                    return switched
            if held:
                return f"你已经拿着{self.world.items[held]['name']}了。"
            return "你身上没有这样东西。"
        name = self.world.items[item_id]["name"]
        if self.world.wear_candidates(item_id):
            before = self.load_level()  # 换背包会改变减重率
            return self._wear(item_id) + self._load_change_note(before)
        if not self._hold_type(item_id):
            return f"{name}没法装备。"
        if self._weapon(item_id) and self.character and self.options.perk_effect(self.character.perks, "no_weapons"):
            return f"你是踢腿的武道家，不用武器——{name}拿在手上反而碍事。"
        if (self._weapon(item_id) and self._weapon(item_id)["type"] == "firearm" and self.character
                and self.options.perk_effect(self.character.perks, "no_firearms")):
            return f"你是刀锋舞者，不碰枪——{name}还是留给别人吧。"
        return self._hold(item_id, want)

    def cmd_unequip(self, arg):
        return self._with_gear_cost(self._cmd_unequip, arg)

    def _cmd_unequip(self, arg):
        if not arg:
            return "你想收起什么？"
        held = [i for i in set(self.equipment.values()) if i]
        worn = [i for i in self.worn.values() if i]
        item_id = self._match(arg, held + worn, self.world.items)
        if not item_id:
            return "你身上没装备这样东西。"
        before = self.load_level()
        self._unequip(item_id)
        note = self.stow(item_id)  # 脱下就回背包；塞不下就丢在脚下
        if item_id in worn and not self._armor(item_id):
            return f"你取下了{self.world.items[item_id]['name']}。" + note + self._load_change_note(before)
        if item_id in worn and self._armor(item_id):
            return (f"你脱下了{self.world.items[item_id]['name']}。现在总护甲 {self.armor_total()}。"
                    + note + self._load_change_note(before))
        return f"你收起了{self.world.items[item_id]['name']}。" + note + self._check_stance()

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
        if not self.stance_usable(stance):
            return f"需要{self._stance_requirement(stance)}才能使用{stance['name']}姿态。"
        self.stance = stance["id"]
        bonuses = stances.stance_bonuses(self.character, stance, self.skill_trees)
        return f"你切换到{stance['name']}姿态：{stances.format_bonuses(bonuses)}。"

    # ---------- 抛骰 ----------

    def accuracy(self, weapon_type, poor=False):
        """用某类武器攻击时的精准 =（武器对应属性 × 1.5，劣质武器 × 1）+（姿态加成，只加在姿态要求的武器上）。"""
        base = stats.accuracy(self.character.attributes, weapon_type, poor)
        stance = self._current_stance()
        if stance and stance["weapon_type"] in self.weapon_counts_as(weapon_type):
            base += stances.stance_bonuses(self.character, stance, self.skill_trees).get("accuracy", 0)
        return base + (stats.LAST_STAND_BONUS if self.last_stand() else 0)

    def last_stand(self):
        """绝境（perk）：生命低于上限的 30% 时生效。"""
        c = self.character
        if not c or not self.options.perk_effect(c.perks, "last_stand"):
            return False
        return c.hp * 100 <= self.options.max_hp(c) * stats.LAST_STAND_HP_PERCENT

    def bleed_damage(self):
        """自己造成的流血每层每回合伤害（残忍：4 → 6）。"""
        return self.options.perk_effect(self.character.perks, "bleed_damage") or stats.BLEED_DAMAGE

    def stance_armor_ignore(self, weapon_type):
        """姿态给这类攻击的无视护甲（猛虎下山：徒手攻击无视 4 + 力量 ÷ 4）。"""
        stance = self._current_stance()
        if not stance or stance["weapon_type"] != weapon_type:
            return 0
        return stances.stance_bonuses(self.character, stance, self.skill_trees).get("armor_ignore", 0)

    def dodge(self):
        """闪避（含姿态加成）。"""
        bonuses = stances.stance_bonuses(self.character, self._current_stance(), self.skill_trees)
        parry = sum(stats.PARRY_DODGE for i in set(self.equipment.values())
                    if self._weapon(i) and "parry" in self._weapon(i).get("tags", []))
        last_stand = stats.LAST_STAND_BONUS if self.last_stand() else 0
        return stats.dodge(self.character.attributes) + bonuses.get("dodge", 0) + parry + last_stand

    def grip_style(self):
        """武器持握方式（stats.GRIPS 的 id）：徒手、单手（另一只手空着）、双持、双手、持盾（任一只手拿着盾牌）。"""
        main, off = self.equipment["main_hand"], self.equipment["off_hand"]
        if self._shield(main) or self._shield(off):
            return "shield"
        if not main and not off:
            return "unarmed"
        if main and main == off:
            return "two_hand"
        if main and off:
            return "dual_wield"
        return "one_hand"

    def grip_name(self):
        return stats.GRIPS[self.grip_style()]

    def passive_effects(self, effect_type):
        """已学会、并且当前满足条件（持握方式）的被动效果：[(技能名, 数值), ...]。"""
        if not self.character:
            return []
        grip = self.grip_style()
        found = []
        for skill_id in self.character.learned_skills:
            skill = self.skill_trees.find_skill(skill_id)
            for effect in (skill or {}).get("effects", []):
                if effect["type"] == effect_type and effect.get("grip", grip) == grip:
                    found.append((skill["name"], effect["value"]))
        return found

    def offhand_attack_cost(self):
        """双持时主手攻击之后，副手追击一次的行动点；没有相关被动就是 None。"""
        effects = self.passive_effects("offhand_attack_ap_percent")
        if not effects:
            return None
        percent = min(value for _, value in effects)
        return stats.ATTACK_AP_COST * percent // 100

    def _offhand_cost_text(self):
        cost = self.offhand_attack_cost()
        if cost is None:
            return ""
        names = "、".join(name for name, _ in self.passive_effects("offhand_attack_ap_percent"))
        return f"（主手攻击后副手追击 {cost}，{names}）"

    def blocks_per_turn(self):
        """持盾时每回合能格挡几次（被动技能可以增加）；没拿盾是 0。"""
        if self.grip_style() != "shield":
            return 0
        return stats.BLOCKS_PER_TURN + sum(value for _, value in self.passive_effects("extra_blocks"))

    def armor_ignore(self):
        """攻击时无视的护甲值（被动技能相加）。"""
        return sum(value for _, value in self.passive_effects("armor_ignore"))

    def _move_cost_text(self):
        """战斗中移动一格的行动点，超重翻倍，严重超重无法移动。"""
        capacity = stats.carry_capacity(self.character.attributes)
        cost = stats.move_ap_cost(self._carried_weight(), capacity)
        if cost is None:
            return "无法移动（严重超重）"
        return f"{cost}（超重）" if cost != stats.MOVE_AP_COST else f"{cost}"

    def weapon_summary(self):
        """手上每件武器（没拿就是徒手）的精准，角色卡和网页版共用。"""
        main, off = self.equipment["main_hand"], self.equipment["off_hand"]
        if main and main == off:
            held = [("双手", main)]
        else:
            held = [(hand, i) for hand, i in (("主手", main), ("副手", off)) if self._weapon(i)]
        if not held:
            held = [("徒手", None)]
        summary = []
        for hand, item_id in held:
            weapon_type = self._weapon(item_id)["type"] if item_id else stats.UNARMED
            poor = bool(item_id and self._weapon(item_id).get("poor"))
            quality = stats.quality_bonus(self.world.items[item_id]) if item_id else 0
            tags = self._weapon(item_id).get("tags", []) if item_id else []
            base = stats.accuracy(self.character.attributes, weapon_type, poor)
            heavy = stats.HEAVY_ACCURACY if "heavy" in tags else 0
            total = self.accuracy(weapon_type, poor) + quality + heavy
            summary.append({
                "hand": hand,
                "name": self.item_display_name(item_id) if item_id else self._unarmed_attack()["name"],
                "type": self.world.weapon_types[weapon_type],
                "weapon_type": weapon_type,
                "attribute": self.options.attribute_name(stats.WEAPON_ATTRIBUTES[weapon_type]),
                "accuracy": total,
                "last_stand_bonus": stats.LAST_STAND_BONUS if self.last_stand() else 0,
                "stance_bonus": total - base - quality - heavy - (stats.LAST_STAND_BONUS if self.last_stand() else 0),
                "tags": tags,
                "tag_names": [stats.WEAPON_TAGS[x][0] for x in tags],
                "armor_ignore": (stats.TAG_ARMOR_IGNORE if "armor_piercing" in tags else 0) + self.stance_armor_ignore(weapon_type),
                "crit_bonus": stats.crit_damage_bonus(tags),
                "quality_bonus": quality,
                "damage": stats.weapon_damage(self.world.items[item_id]) if item_id else self._unarmed_attack()["damage"],
                "range": ((stats.REACH_RANGE if "reach" in tags else stats.MELEE_RANGE)
                          if weapon_type in stats.MELEE_WEAPON_TYPES else None) if item_id
                else self._unarmed_attack().get("range", stats.MELEE_RANGE),
                "crit_range": self._crit_range(weapon_type, item_id),
                "damage_modifiers": self.damage_modifiers(weapon_type) + stats.tag_damage_modifiers(tags),
            })
            summary[-1]["damage_multiplier"] = float(stats.damage_multiplier(summary[-1]["damage_modifiers"]))
        return summary

    def _unarmed_attack(self):
        """空手时的攻击：默认拳脚 1d4；踢腿的武道家改成踢击（1d8，射程 2）。"""
        kick = self.options.perk_effect(self.character.perks, "unarmed_attack") if self.character else None
        return kick or {"name": "拳脚", "damage": stats.UNARMED_DAMAGE}

    def _crit_range(self, weapon_type, item_id):
        """武器的暴击范围，再按被动技能扩大（例如精通重击：单手持用时翻倍）。"""
        crit = stats.crit_range(weapon_type, self._weapon(item_id))
        multiplier = 1
        for _, value in self.passive_effects("crit_range_multiplier"):
            multiplier *= value
        return stats.widen_crit_range(crit, multiplier) if multiplier != 1 else crit

    def damage_modifiers(self, weapon_type):
        """用某类武器攻击时的伤害修正，每项 (来源, %, 加算 / 乘算)，见 stats.damage_multiplier。"""
        c = self.character
        mods = []
        if weapon_type in stats.MELEE_WEAPON_TYPES:
            per_point = max([stats.STRENGTH_DAMAGE_PERCENT]
                            + [v for _, v in self.passive_effects("strength_damage_percent")])
            penalty = min([stats.STRENGTH_DAMAGE_PERCENT]
                          + [v for _, v in self.passive_effects("strength_penalty_percent")])
            mods.append(("力量", stats.melee_damage_bonus(c.attributes, per_point, penalty), stats.ADD))
        stance = self._current_stance()
        if stance and stance["weapon_type"] in self.weapon_counts_as(weapon_type):
            bonus = stances.stance_bonuses(c, stance, self.skill_trees).get("melee_damage_bonus", 0)
            mods.append((f"{stance['name']}姿态", bonus, stats.ADD))  # 技能：加算
        mods.append(("力竭", stats.attack_penalty(c), stats.MUL))  # 状态：乘算
        if self.last_stand():
            mods.append(("绝境", stats.LAST_STAND_DAMAGE_PERCENT, stats.MUL))  # perk：乘算
        return [m for m in mods if m[1]]

    def _parse_enemy(self, arg):
        """“僵尸 精英”这种写法 -> 生成的敌人；不是敌人名就返回 None。"""
        parts = arg.split()
        if not parts:
            return None
        template_id = self.enemies.find(parts[0])
        if not template_id:
            return None
        tier = "normal"
        forced = None
        level = None
        for part in parts[1:]:
            found_tier = next((t for t, info in stats.ENEMY_TIERS.items() if part in (t, info[0])), None)
            mutation = self.enemies.find_mutation(part)
            level_match = re.match(r"^(\d+)级?$", part)
            if level_match:
                level = int(level_match.group(1))  # “5级”或“5”：指定等级（低于最低等级会被抬上来）
            elif found_tier:
                tier = found_tier
            elif mutation:
                forced = (forced or []) + [mutation]  # 写了变异名就强制带上（测试用）
            else:
                return None
        return self.enemies.create(template_id, tier, self.dice.rng, forced, level)

    def cmd_enemy(self, arg):
        """敌人 <名字> <等阶>：查看敌人资料（测试用）。"""
        tiers = "、".join(info[0] for info in stats.ENEMY_TIERS.values())
        names = "、".join(t["name"] for t in self.enemies.templates.values())
        if not arg:
            mutations = "、".join(m["name"] for m in self.enemies.mutations.values())
            return (f"已有的敌人：{names}。用法：敌人 名字 等级 等阶（{tiers}）变异，例如：敌人 僵尸 5级 精英 表皮硬化"
                    f"（变异：{mutations}；不写变异就按概率随机）")
        enemy = self._parse_enemy(arg)
        if not enemy:
            return f"没找到这个敌人。已有的敌人：{names}；等阶：{tiers}。"
        return format_enemy(enemy, self.options, self.world.weapon_types, self.world.items, self.enemies)

    def cmd_attack_test(self, arg):
        """试攻击：用手上第一件武器（没拿就徒手）试一次攻击，目标可以是数值，也可以是敌人。"""
        if not self.character:
            return "还没有创建角色。"
        usage = ("用法：试攻击 目标闪避 目标护甲（例如：试攻击 15 3），或者 试攻击 敌人 等阶"
                 "（例如：试攻击 僵尸 精英）；不写就用你自己的闪避、护甲 0")
        advantage = "优势" in arg.split()  # 模拟洞察：自己的攻击 2d20 取高
        sneak = "偷袭" in arg.split()  # 模拟偷袭（目标没发现你）：暗袭技能、背刺标签各自加成
        arg = " ".join(p for p in arg.split() if p not in ("优势", "偷袭"))
        has_sneak_skill = "sneak_attack" in self.character.learned_skills
        enemy = self._parse_enemy(arg) if arg and not arg.split()[0].replace(".", "").isdigit() else None
        if enemy:
            target, armor = enemy.dodge(), enemy.armor
        else:
            parts = arg.split()
            try:
                target = float(parts[0]) if parts else self.dodge()
                armor = int(parts[1]) if len(parts) > 1 else 0
            except ValueError:
                return usage
            if len(parts) > 2:
                return usage
        weapon = self.weapon_summary()[0]
        if sneak:
            weapon = dict(weapon)
            if has_sneak_skill:  # 暗袭：命中 +（敏捷 + 感知）÷ 2，伤害 +100%
                weapon["accuracy"] += stats.sneak_attack_accuracy_bonus(self.character.attributes)
                weapon["damage_modifiers"] = weapon["damage_modifiers"] + [("暗袭", stats.SNEAK_ATTACK_DAMAGE_PERCENT, stats.ADD)]
            if "backstab" in weapon["tags"]:  # 背刺标签：偷袭伤害 +200%
                weapon["damage_modifiers"] = weapon["damage_modifiers"] + stats.tag_damage_modifiers(["backstab"], sneak=True)
        result = self.dice.attack(weapon["accuracy"], target, weapon["crit_range"], advantage=advantage)
        who = enemy.name if enemy else "目标"
        lines = [
            f"用{weapon['name']}{'偷袭' if sneak else '试攻击'}{who}（{weapon['type']}，精准看{weapon['attribute']}"
            + (f"，含暗袭 +{stats.sneak_attack_accuracy_bonus(self.character.attributes)}" if sneak and has_sneak_skill else "")
            + f"），闪避 {dice_rules.format_number(target)}、护甲 {armor}：",
            result.text,
        ]
        if result.hit:
            damage_text, damage = self._roll_damage(weapon, armor, result.crit,
                                                    self.armor_ignore() + weapon["armor_ignore"])
            lines.append(damage_text)
            if enemy and weapon["damage"]:
                enemy.hp = max(0, enemy.hp - damage)
                lines.append(f"{enemy.name} 生命 {enemy.max_hp} → {enemy.hp}/{enemy.max_hp}"
                             + ("，倒下了！" if enemy.hp == 0 else ""))
        lines.append(f"（一次普通攻击消耗 {stats.ATTACK_AP_COST} 行动点）")
        return "\n".join(lines)

    def _roll_damage(self, weapon, armor, crit=False, armor_ignore=0):
        """掷伤害并写出计算过程：骰子 → 修正（加算的相加、乘算的相乘）→ 暴击 → 向下取整 → 护甲。"""
        if not weapon["damage"]:
            return f"{weapon['name']}的伤害还没有定。", 0
        roll = self.dice.roll(weapon["damage"])
        modifiers = weapon["damage_modifiers"]
        steps = [roll.describe()]
        if modifiers:
            steps.append("修正 " + stats.modifier_text(modifiers))
        crit_bonus = weapon.get("crit_bonus", stats.CRIT_DAMAGE_BONUS)
        if crit:
            steps.append(f"暴击 +{crit_bonus}%")
        exact = roll.total * stats.damage_multiplier(modifiers, crit, crit_bonus)
        if exact != roll.total:
            steps[-1] += f" = {float(exact):g}，向下取整 {math.floor(exact)}"
        effective_armor = max(0, armor - armor_ignore)
        if armor and armor_ignore:
            steps.append(f"护甲 {armor} 无视 {armor_ignore} → −{effective_armor}")
        elif armor:
            steps.append(f"护甲 −{armor}")
        damage = stats.final_damage(roll.total, modifiers, effective_armor, crit, crit_bonus=crit_bonus)
        return "，".join(steps) + f" → 造成 {damage} 点伤害", damage

    def cmd_defend_test(self, arg):
        """试受击：让一个敌人打你一次，看闪避、格挡、护甲的效果（不会真的扣你的生命）。
        最后加“劣势”可以模拟预判：敌人的命中判定 2d20 取低。"""
        if not self.character:
            return "还没有创建角色。"
        disadvantage = "劣势" in arg.split()
        arg = " ".join(p for p in arg.split() if p != "劣势")
        enemy = self._parse_enemy(arg) if arg else None
        if not enemy:
            names = "、".join(t["name"] for t in self.enemies.templates.values())
            return f"用法：试受击 敌人 等阶，例如：试受击 壮尸 精英（已有的敌人：{names}）"
        c = self.character
        result = self.dice.attack(enemy.accuracy(), self.dodge(), enemy.crit_range(), disadvantage)
        lines = [f"{enemy.name}用{enemy.attack['name']}攻击你（你的闪避 {self.dodge():g}、护甲 {self.armor_total()}"
                 + ("，它处于劣势" if disadvantage else "") + "）：", result.text]
        if result.hit and self.blocks_per_turn():
            block = self.dice.block(stats.block_modifier(c.attributes), result.total)
            lines.append(block.text + f"（每回合可格挡 {self.blocks_per_turn()} 次）")
            if block.success:
                return "\n".join(lines + ["（测试，不会真的扣你的生命）"])
        if result.hit:
            tags = enemy.attack.get("tags", [])
            weapon = {"name": enemy.attack["name"], "damage": enemy.attack["damage"],
                      "damage_modifiers": enemy.damage_modifiers(), "crit_bonus": stats.crit_damage_bonus(tags)}
            text, damage = self._roll_damage(weapon, self.armor_total(), result.crit,
                                             stats.TAG_ARMOR_IGNORE if "armor_piercing" in tags else 0)
            hp_max = self.options.max_hp(c)
            lines += [text, f"你的生命 {c.hp} → {max(0, c.hp - damage)}/{hp_max}"]
        lines.append("（测试，不会真的扣你的生命）")
        return "\n".join(lines)

    def cmd_bash_test(self, arg):
        """试盾击：对敌人用一次盾击（伤害 + 目标体质检定），会扣它的生命，不花行动点。"""
        if not self.character:
            return "还没有创建角色。"
        if self.grip_style() != "shield":
            return "得先拿着盾牌（装备 盾牌）。"
        enemy = self._parse_enemy(arg) if arg else None
        if not enemy:
            return "用法：试盾击 敌人 等阶，例如：试盾击 壮尸 精英"
        # 末尾写个数字 = 同一回合里连着盾击几次（演示眩晕升级为震慑），例如：试盾击 壮尸 2
        times = 1
        parts = arg.split()
        if parts and parts[-1].isdigit():
            times = max(1, min(5, int(parts[-1])))
        a = self.character.attributes
        shield = self.world.items[next(i for i in self.equipment.values() if self._shield(i))]
        accuracy = stats.shield_bash_accuracy(a, shield)
        weapon = {"name": "盾击", "damage": stats.shield_bash_damage(shield),
                  "damage_modifiers": self.damage_modifiers(stats.UNARMED)}  # 近战：力量、力竭
        difficulty = stats.shield_bash_difficulty(a)
        quality = stats.quality_bonus(shield)
        lines = [f"你用{shield['name']}猛击{enemy.name}（闪避 {enemy.dodge()}、护甲 {enemy.armor}），"
                 f"精准 {accuracy}（体质 × 1.5" + (f"，含盾牌等阶 {quality:+d}" if quality else "") + "）："]
        for n in range(times):
            if times > 1:
                lines.append(f"—— 第 {n + 1} 次 ——")
            result = self.dice.attack(accuracy, enemy.dodge(), "20")
            lines.append(result.text)
            if not result.hit:
                continue
            text, damage = self._roll_damage(weapon, enemy.armor, result.crit)
            enemy.hp = max(0, enemy.hp - damage)
            lines += [text, f"{enemy.name} 生命 → {enemy.hp}/{enemy.max_hp}"]
            modifier = stats.check_modifier(enemy.attributes, "constitution")
            check = self.dice.check(modifier, difficulty, "体质修正")
            lines.append(f"体质检定（难度 {difficulty} =（你的力量 {a['strength']} + 体质 {a['constitution']}）× 1.5）：")
            if check.success:
                lines.append(check.text + f" → {enemy.name}撑住了")
                continue
            state = enemy.apply_stun(self.turns)
            upgraded = state == "dazed" and enemy.stun_count >= 2
            lines.append(check.text + f" → {enemy.name}" + (
                "这一回合第二次被撞晕，眩晕升级为【震慑】：跳过下一个回合" if upgraded
                else f"【{stats.STUN_CONDITIONS[state]}】：{stats.STUN_EFFECTS[state]}"))
        lines.append("（测试：不花行动点；真正使用时消耗 6 行动点，冷却到本回合结束）")
        return "\n".join(lines)

    def cmd_initiative_test(self, arg):
        """试先攻：你和一个敌人各掷一次先攻检定，看谁先动。"""
        if not self.character:
            return "还没有创建角色。"
        enemy = self._parse_enemy(arg) if arg else None
        if not enemy:
            return "用法：试先攻 敌人 等阶，例如：试先攻 疾尸 精英"
        advantage = self.options.perk_effect(self.character.perks, "initiative_advantage")
        lines = []
        while True:  # 平手就重掷（警觉的优势照样生效），直到分出先后
            mine, my_text = self.dice.initiative(stats.initiative(self.character.attributes), advantage)
            theirs, their_text = self.dice.initiative(enemy.initiative())
            lines += [f"你：{my_text}" + ("（警觉：优势）" if advantage else ""), f"{enemy.name}：{their_text}"]
            if mine != theirs:
                break
            lines.append("平手，重新掷一次：")
        lines.append("→ 你先行动" if mine > theirs else f"→ {enemy.name}先行动")
        return "\n".join(lines)

    def cmd_roll(self, arg):
        roll = self.dice.roll(arg or "1d20")
        if not roll:
            return "格式不对。例如：掷骰 1d20、掷骰 2d6+1、掷骰 d100"
        return roll.describe()

    def attribute_check(self, attribute_id, difficulty):
        """属性检定：d20 + 属性 × 1.5 ≥ 难度。以后开锁、说服这类检定都调用这个。"""
        modifier = stats.check_modifier(self.character.attributes, attribute_id)
        name = self.options.attribute_name(attribute_id)
        return self.dice.check(modifier, difficulty, f"{name}修正")

    def cmd_check(self, arg):
        """检定 属性 难度：手动做一次属性检定（测试用）。"""
        usage = "用法：检定 属性 难度，例如：检定 敏捷 15"
        if not self.character:
            return "还没有创建角色。"
        match = re.match(r"^(\D+?)\s*(\d+)$", arg)
        if not match:
            return usage
        name, difficulty = match.group(1).strip(), int(match.group(2))
        attribute = next((a for a in self.options.attributes if name in (a["name"], a["id"])), None)
        if not attribute:
            return "没有这个属性。可以检定：" + "、".join(a["name"] for a in self.options.attributes)
        a = self.character.attributes
        result = self.attribute_check(attribute["id"], difficulty)
        return (f"{attribute['name']}检定（修正 {stats.check_modifier(a, attribute['id']):g} = "
                f"{attribute['name']} {a[attribute['id']]} × {stats.CHECK_MODIFIER_MULTIPLIER:g}），"
                f"难度 {difficulty}：\n{result.text}")

    def cmd_talk(self, arg):
        npcs = self._room().get("npcs", [])
        if not npcs:
            return "这里没有人可以说话。"
        # 只有一个人时可以省略对象
        npc_id = self._match(arg, npcs, self.world.npcs) if arg else (npcs[0] if len(npcs) == 1 else None)
        if not npc_id:
            return "你想和谁说话？"
        npc = self.world.npcs[npc_id]
        # 说话也要走到跟前（同一格或相邻一格，斜角也算），不能隔着半张地图聊
        grid = self.room_grid()
        coord = (grid.get("objects") or {}).get(npc_id) if grid else None
        if coord and not self.near(self.player_pos(grid), coord):
            return (f"{npc['name']}在（第 {coord[0] + 1} 列，第 {coord[1] + 1} 行），"
                    f"你得先走到跟前再说话。")
        lines = npc["dialogue"]
        index = self.dialogue_index.get(npc_id, 0)
        # 对话说完了再点一次「说话」：从最后一句重新听，不至于卡在那里没有反应
        if index >= len(lines):
            index = 0
        self.dialogue_index[npc_id] = index + 1
        self.talk_npc = npc_id  # 界面据此把这一句放进视图栏的对话框
        return f"{npc['name']}：{lines[index]}"

    def cmd_continue(self, arg):
        """对话框里的「继续」：接着上一个 NPC 往下说一句（界面点视图栏就是发这句）。"""
        npc_id = self.talk_npc
        if not npc_id:
            return "现在没有说话的对象。先用「说话 <人>」跟人说上一句。"
        if npc_id not in (self._room().get("npcs") or []):
            self.talk_npc = None
            return "这里没有人可以说话了。"
        npc = self.world.npcs[npc_id]
        lines = npc["dialogue"]
        index = self.dialogue_index.get(npc_id, 0)
        if index >= len(lines):
            self.talk_npc = None
            return TALK_END  # 说完了：界面收到这句就把对话框收起来
        self.dialogue_index[npc_id] = index + 1
        return f"{npc['name']}：{lines[index]}"

    def cmd_save(self, arg):
        if not self.character:
            return "还没有创建角色，先开一局新游戏再存档。"
        if self.death_cause:
            return "你已经死了，不能存档。"
        slot, error = self._parse_slot(arg)
        if error:
            return error
        state = {
            "character": self.character.to_dict(),
            "current_room": self.current_room,
            "inventory": self.inventory,   # 一格一堆：[{"sid":1,"id":"water","count":3,"auto":true}]
            "next_stack_id": self.next_stack_id,
            "turns": self.turns,
            "room_enemies": {r: [e.to_dict() for e in es] for r, es in self.room_enemies.items() if es},
            "next_enemy_uid": self.next_enemy_uid,
            "player_dots": self.player_dots,
            "player_init": self.player_init,
            "seen_enemy_ids": self.seen_enemy_ids,
            "blocks_left": self.blocks_left,
            "ap": self.ap,
            "indoor_steps": self.indoor_steps,
            "need_minutes": self.need_minutes,  # 食物 / 水源下一次 −1 前已过的分钟
            "stamina_carry": [self.stamina_carry.numerator, self.stamina_carry.denominator],
            "day": self.day,
            "minutes": self.minutes,
            "visited": sorted(self.visited),
            "equipment": self.equipment,
            "worn": self.worn,
            "stance": self.stance,
            "room_items": self.room_items,
            "dialogue_index": self.dialogue_index,
            "pos": self.pos,
            "ground_positions": self.ground_positions,  # 每件地面物品一个格子，和 room_items 一一对应
        }
        # 写盘成功之后才切换当前槽：写失败时至少不会连"当前用的是哪个槽"都改掉
        try:
            write_json_file(self.slot_path(slot), state)
        except OSError as exc:
            return f"存档失败：{exc}\n（{slot} 号槽里原来的内容没有被改动，可以再试一次）"
        self.use_slot(slot)
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
        try:
            state = json.loads(self.slot_path(slot).read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("存档内容不是一个对象")
        except (ValueError, OSError, UnicodeDecodeError):
            return (f"{slot} 号存档读不出来（文件损坏或者不是存档）。\n"
                    f"可以用「清空 {slot}」删掉它，再重新存一次。")
        if "current_room" not in state:
            return f"{slot} 号存档缺少地点信息，读不了。"
        self.use_slot(slot)
        if state.get("character"):
            self.character = Character.from_dict(state["character"])
            # 旧存档没有属性，按默认值补上
            if not self.character.attributes:
                self.character.attributes = self.options.default_attributes()
            # 原始属性不能超过 10（加成只能来自 buff）
            self.character.attributes = {
                k: max(stats.ATTRIBUTE_MIN, min(stats.ATTRIBUTE_MAX, v)) for k, v in self.character.attributes.items()
            }
            if not self.character.hp:
                self.character.hp = self.options.max_hp(self.character)
            # 旧存档没有体力，按满值补上
            if not self.character.stamina:
                self.character.stamina = stats.stamina_max(self.character.attributes)
            # 公式改过之后，旧存档里的生命 / 体力可能超过新上限，压回上限
            c = self.character
            c.hp = min(c.hp, self.options.max_hp(c))
            c.stamina = min(c.stamina, stats.stamina_max(c.attributes))
        self.current_room = state["current_room"]
        self.turns = state["turns"]
        self._reset_combat()
        self.room_enemies = {r: [Enemy.from_dict(d) for d in es]
                             for r, es in (state.get("room_enemies") or {}).items()}
        self.next_enemy_uid = state.get("next_enemy_uid", 1)
        self.player_dots = state.get("player_dots", [])
        self.player_init = state.get("player_init")
        self.seen_enemy_ids = state.get("seen_enemy_ids", [])
        self.blocks_left = state.get("blocks_left", 0)
        # 老存档没有行动点：给满一回合的量
        self.ap = min(state.get("ap", self.ap_gain()), self.ap_cap()) if self.character else 0
        self.indoor_steps = state.get("indoor_steps", 0)
        self.need_minutes = dict({"food": 0, "water": 0}, **(state.get("need_minutes") or {}))
        carry = state.get("stamina_carry") or [0, 1]
        self.stamina_carry = Fraction(carry[0], carry[1])
        if self.character:  # 旧的“口渴”（按体力消耗挂上的）和“饱腹”状态都已经不用了，摘掉
            self.character.conditions = [x for x in self.character.conditions if x.get("id") not in ("thirst", "full")]
        self.death_cause = None  # 读档就是活过来了
        self.starving_drain = 0
        self.day = state.get("day", stats.START_DAY)
        self.minutes = state.get("minutes", stats.START_MINUTES)
        self.visited = set(state.get("visited", [self.current_room]))
        self.stance = state.get("stance")
        # 场景格子：玩家站在哪一格，以及地面物品的坐标
        self.pos = state.get("pos")
        if not isinstance(self.pos, (list, tuple)) or len(self.pos) != 2:
            self.pos = None
        # 三张表都要按当前世界数据重建，顺序不能换：装备栏依赖清理后的背包
        notes = self._load_room_items(state.get("room_items", {}),
                                      state.get("ground_positions"),
                                      state.get("item_positions"))
        notes += self._load_inventory(state.get("inventory", []))
        # 存档里记的堆号计数器接着用，别和后加的东西撞号
        saved_sid = state.get("next_stack_id")
        if isinstance(saved_sid, int) and saved_sid > self.next_stack_id:
            self.next_stack_id = saved_sid
        notes += self._load_equipment(state.get("equipment"))
        notes += self._load_worn(state.get("worn"))
        notes += self._load_skills()
        self.dialogue_index = state.get("dialogue_index", {})
        self.talk_npc = None   # 读档不接上一次的说话对象
        self._load_notice = ("（存档已按当前版本适配：" + "、".join(notes) + "）\n") if notes else ""
        return self._load_notice + f"读档成功（{slot} 号槽）。\n\n" + self.describe_room()

    def cmd_clear(self, arg):
        """清空一个存档槽：删掉那个文件，不影响正在进行的这一局。"""
        arg = (arg or "").strip()
        if arg.startswith("存档"):  # 兼容“清空存档 2”这种写法
            arg = arg[len("存档"):].strip()
        if not arg:
            return f"要清空哪个存档？例如：清空 2（槽位 1~{SLOT_COUNT}）"
        slot, error = self._parse_slot(arg)
        if error:
            return error
        path = self.slot_path(slot)
        if not path.exists():
            return f"{slot} 号存档本来就是空的。"
        try:
            path.unlink()
        except OSError as exc:
            return f"清空失败：{exc}"
        # 老版本的 save.json 还在的话，别让 1 号槽下次启动时被它顶回来
        mark_migrated(self.save_dir)
        return f"{slot} 号存档已清空。"


    def _load_room_items(self, saved, saved_positions=None, legacy_positions=None):
        """按当前世界数据重建房间物品表和地面坐标，返回适配提示。

        存档里记的是当时每个房间的地面物品。世界数据之后可能加房间、
        加物品或删物品，所以不能直接赋值：以当前世界为基准，逐房间比对，
        存档里没有的新房间补上默认值，存档里有但世界已不存在的条目丢掉。

        地面坐标和物品是一一对应的两串（见 ground_positions_in），所以删掉不存在的
        物品时，它的那一格也要跟着删。老存档里坐标是按物品 id 记的字典
        （item_positions），顺手搬成新写法。
        """
        items = self.world.items
        saved = saved if isinstance(saved, dict) else {}
        saved_positions = saved_positions if isinstance(saved_positions, dict) else {}
        legacy_positions = legacy_positions if isinstance(legacy_positions, dict) else {}
        rebuilt = {}
        positions = {}
        added_rooms = 0
        removed_items = 0
        for room_id, room in self.world.rooms.items():
            if room_id not in saved:
                # 新房间：世界数据里还没有存档记录，用世界默认值填上
                rebuilt[room_id] = list(room.get("items", []))
                added_rooms += 1
                continue
            entries = saved[room_id] if isinstance(saved[room_id], list) else []
            old_table = saved_positions.get(room_id)
            old_dict = legacy_positions.get(room_id)
            keep, coords = [], []
            for index, item_id in enumerate(entries):
                if item_id not in items:
                    removed_items += 1
                    continue
                coord = None
                if isinstance(old_table, list) and index < len(old_table):
                    coord = old_table[index]
                elif isinstance(old_dict, dict):
                    # 老存档：一个物品 id 一个坐标，用掉就删，同种多出来的那几件另找地方
                    coord = old_dict.pop(item_id, None)
                keep.append(item_id)
                coords.append([int(coord[0]), int(coord[1])]
                              if isinstance(coord, (list, tuple)) and len(coord) == 2 else None)
            rebuilt[room_id] = keep
            if any(c for c in coords):
                positions[room_id] = coords
        self.room_items = rebuilt
        self.ground_positions = positions

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
        老存档里背包是一串物品 id（一格一件），这里顺手搬成堆的格式。
        """
        items = self.world.items
        self.inventory = []
        removed = 0
        for entry in saved if isinstance(saved, list) else []:
            if isinstance(entry, dict):
                item_id, count, auto = entry.get("id"), entry.get("count", 1), entry.get("auto", True)
            else:  # 老存档：直接就是物品 id（同种的会在这里重新摞起来）
                item_id, count, auto = entry, 1, True
            if item_id not in items:
                removed += 1
                continue
            try:
                count = max(1, int(count))
            except (TypeError, ValueError):
                count = 1
            self.add_item(item_id, count, auto=bool(auto))
        # 堆号重新排一遍：存档里的编号可能和清理后的背包对不上
        for index, stack in enumerate(self.inventory, start=1):
            stack["sid"] = index
        self.next_stack_id = len(self.inventory) + 1
        return [f"背包里有 {removed} 件物品已不存在"] if removed else []

    def _load_equipment(self, saved):
        """按清理后的背包重建装备栏，返回适配提示。

        装备栏里存的是物品 id。新版本的背包和装备是分开的：装备着的东西
        不在背包里；旧存档里它同时还在背包里，所以这里顺手把它从背包拿走。
        """
        if not isinstance(saved, dict):
            saved = {}
        equipment = {"main_hand": None, "off_hand": None}
        for slot in equipment:
            held = saved.get(slot)
            if held and held in self.world.items:
                equipment[slot] = held
                if self.count_item(held):  # 旧存档：装备也留在背包里，这里搬出来
                    self.take_item(held, 1)
        # 双手武器两个槽存同一个 id，按件数去重后再报数字
        dropped = {h for h in (saved.get(slot) for slot in equipment)
                   if h and h not in self.world.items}
        self.equipment = equipment
        return [f"已卸下 {len(dropped)} 件失效装备"] if dropped else []

    def _load_worn(self, saved):
        """按清理后的背包重建身上的护甲、饰品、披风、背包（位置按当前世界数据），返回适配提示。"""
        if not isinstance(saved, dict):
            saved = {}
        self.worn = {slot: None for slot in self.world.wear_slot_names}
        restored = 0
        dropped = 0
        for slot, item_id in saved.items():
            if not item_id:
                continue
            valid = (item_id in self.world.items and slot in self.worn
                     and slot in self.world.wear_candidates(item_id))
            if valid:
                self.worn[slot] = item_id
                if self.count_item(item_id):  # 旧存档：穿着的东西也在背包里
                    self.take_item(item_id, 1)
            elif item_id in self.world.items and not self.count_item(item_id):
                # 这个装备位在现在的世界数据里没有了（例如照明位被删掉）：
                # 东西不能凭空消失，塞回背包
                self.add_item(item_id)
                restored += 1
            else:
                dropped += 1
        notes = []
        if restored:
            notes.append(f"{restored} 件东西原来的装备位没有了，已经放回背包")
        if dropped:
            notes.append(f"已取下 {dropped} 件失效的穿戴装备")
        return notes

    # ---------- 设置（个人偏好，存在 saves/settings.json，不跟存档走）----------

    SETTINGS = {
        "interrupt_every_enemy": ("遇敌中断", {False: "首个敌人", True: "每个敌人"},
                                  "首个敌人：只在视野里出现第一个敌人（进入战斗）时打断行动；"
                                  "每个敌人：每有敌人新进入视野都打断"),
    }

    def _load_settings(self):
        settings = {key: False for key in self.SETTINGS}
        try:
            saved = json.loads((self.save_dir / "settings.json").read_text(encoding="utf-8"))
            settings.update({k: bool(v) for k, v in saved.items() if k in settings})
        except (OSError, ValueError):
            pass
        return settings

    def cmd_settings(self, arg):
        """设置：不写参数列出当前设置；“设置 遇敌中断 每个敌人”改一项（只写名字就来回切换）。"""
        parts = (arg or "").split()
        if not parts:
            lines = ["当前设置："]
            for key, (name, values, note) in self.SETTINGS.items():
                lines.append(f"  {name}：{values[self.settings[key]]}（{note}）")
            lines.append("改设置：设置 遇敌中断 每个敌人 / 首个敌人（只写“设置 遇敌中断”就来回切换）")
            return "\n".join(lines)
        key = next((k for k, (name, _, _) in self.SETTINGS.items() if parts[0] in (k, name)), None)
        if not key:
            return f"没有“{parts[0]}”这个设置。输入“设置”看看有哪些。"
        name, values, _ = self.SETTINGS[key]
        if len(parts) > 1:
            choice = next((v for v, label in values.items() if parts[1] in (label, label[:2])), None)
            if choice is None:
                return f"{name}可以设成：{'、'.join(values.values())}。"
        else:
            choice = not self.settings[key]
        self.settings[key] = choice
        try:
            write_json_file(self.save_dir / "settings.json", self.settings)
        except OSError:
            return f"{name}：{values[choice]}（这次有效，但设置文件没能保存）"
        return f"{name}：{values[choice]}。"

    def cmd_help(self, arg):
        return (
            "可用指令：\n"
            "  看 / look              查看周围\n"
            "  北、南、东、西 / n s e w  移动（也可以写“走 北”）：在场景里走一格；\n"
            "                          走到门 / 楼梯那一格就换地点，楼梯要先走到它旁边\n"
            "  查看 <东西>              仔细查看物品或人物（隔着多远都能看）\n"
            "  拿 <东西> / 放下 <东西> [数量]  拾取或丢弃物品（放下 矿泉水 3 = 丢 3 瓶）\n"
            "                          拿东西要先走到跟前（同一格或相邻一格，斜角也算）\n"
            "  使用 <东西>             使用物品（例如：使用 肉罐头、使用 矿泉水）\n"
            "                          肉罐头：体力 +20、生命 +1；矿泉水：体力 +10，还能解除口渴\n"
            "                          累计消耗 60 点体力会口渴（体力消耗翻倍，喝水解除）；\n"
            "                          半小时内吃三份带食物的东西会饱腹，之后一小时内吃不下食物\n"
            "  拆分 <东西> [数量]        把一堆可堆叠的东西拆成两堆，拆出来的那堆不会被自动堆叠\n"
            "  堆叠 <东西> / 堆叠 <堆号> <堆号>  把同种物品摞成一堆（拖到另一堆上也是这个意思）\n"
            "  背包 / i               查看携带的物品（同种东西显示成 矿泉水 ×3）\n"
            "  地图 / m               查看地图\n"
            "  角色 / c               查看角色卡（属性、衍生数值）\n"
            "  技能 / 技能 <树名>        查看技能树，例如：技能 锐器\n"
            "  用 <技能>               快捷释放一个主动技能，例如：用 盾击（技能栏里点格子就是这句）\n"
            "  学习 <技能>              花技能点解锁技能\n"
            "  装备 <物品> / 卸下 <物品>  拿起或收起武器，穿戴或取下护甲、饰品、披风、背包\n"
            "                          武器可以指定手：装备 撬棍 副手（网页版拖到哪个方框就是哪只手）\n"
            "                          已经拿在手上的武器拖到另一只手就是换手，不用先卸下\n"
            "  姿态 / 姿态 <名字>        查看或切换姿态，“姿态 取消”解除\n"
            "  掷骰 <骰子>              掷骰，例如：掷骰 2d6+1\n"
            "  检定 <属性> <难度>        做一次属性检定（d20 + 属性×1.5 ≥ 难度），例如：检定 敏捷 15\n"
            "  试攻击 <闪避> <护甲>       用手上的武器试一次攻击（命中 + 伤害），例如：试攻击 15 3\n"
            "  试攻击 <敌人> <等阶>       对敌人试一次攻击，例如：试攻击 僵尸 精英（末尾加“优势”“偷袭”模拟）\n"
            "  敌人 <名字> <等阶>         随机生成一个敌人看看资料，例如：敌人 疾尸 精英\n"
            "  试受击 <敌人> <等阶>       让敌人打你一次，看闪避 / 格挡 / 护甲（不扣血），例如：试受击 壮尸\n"
            "                          末尾加“劣势”模拟敌人处于劣势，例如：试受击 疾尸 精英 劣势\n"
            "  试盾击 <敌人> <等阶> [次数] 持盾时对敌人试盾击，例如：试盾击 壮尸 精英；末尾写 2 演示同回合眩晕升级为震慑\n"
            "  试先攻 <敌人> <等阶>       和敌人各掷一次先攻检定，例如：试先攻 疾尸\n"
            "  攻击 <敌人> [副手]         打一个够得着的敌人（6 行动点），例如：攻击 行尸A；不写目标就打最近的\n"
            "  试刷怪 <敌人> [等级] [等阶] 在当前场景随机放一只敌人（测试用），例如：试刷怪 行尸 2\n"
            "  设置 [名字] [值]          查看 / 修改设置，例如：设置 遇敌中断 每个敌人\n"
            "  等待 / wait             原地等一回合（战斗外 1 分钟，也算生命恢复的回合）\n"
            "  休息 <时长>             恢复体力并推进时间，例如：休息 30、休息 2小时（1~480 分钟）\n"
            "                          体力满了也能休息，只是时间照样过去\n"
            "  说话 <人>               和 NPC 交谈（同样要先走到跟前）；说完点视图栏横幅看下一句\n"
            "  存档 [槽位] / 读档 [槽位]  保存或读取进度（槽位 1~3，不写就用当前槽）\n"
            "  清空 <槽位>             删掉某个槽位的存档，例如：清空 2\n"
            "  退出 / quit            离开游戏"
        )

    def cmd_quit(self, arg):
        self.running = False
        return "再见，幸存者。"
