"""网页版入口：把游戏操作做成按钮。

用法：python webui.py            （默认 127.0.0.1:8730，自动打开浏览器）
      python webui.py --port 9000 --no-browser
      python webui.py --open     （页面已经开着时，也强制再开一次）

设计要点：
- 不动 engine.py 的规则。界面上每个按钮最终都翻译成一句玩家指令（如“走东”“拿 手电筒”），
  交给 Game.handle() 处理，规则仍然只有引擎里那一份。
- 角色创建复用 CharacterCreator + Prompter：WebPrompter 把 Prompter 的
  input()/print() 接到 HTTP 上（一问一答），所以属性、背景、同伴的校验逻辑
  一行都不用重写。
- 同一个地址只跑一个服务：再次双击启动时先探测 /api/ping，如果本游戏已经在跑，
  就不另起一个服务、也不再开新标签页（除非加 --open），这样地址永远是同一个。
- 只用标准库（http.server），不引入第三方依赖；只监听本机回环地址。
"""

import argparse
import json
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import items
import stats
from character import CharacterCreator, CharacterOptions, Prompter, check_attributes
from dice import Dice
from engine import (
    DIRECTION_NAMES, DIRECTIONS, REST_MINUTES_MAX, REST_MINUTES_MIN, SLOT_COUNT, Game, World,
)
from skills import SkillTrees, skill_details, tree_unlocked, unmet_requirements

BASE_DIR = Path(__file__).parent
WEB_DIR = BASE_DIR / "web"

# 用来认出“这个端口上跑的是我们自己”，避免重复启动
APP_ID = "fengcheng-day7"
APP_VERSION = 2

# 页面每隔 HEARTBEAT_SECONDS 秒报一次活；超过 IDLE_LIMIT 秒没动静就当成页面已经关了，
# 再次启动时才会重新打开浏览器。
HEARTBEAT_SECONDS = 20
IDLE_LIMIT = 50

# 只允许这几条路径，避免任何路径穿越问题
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/icons.svg": ("icons.svg", "image/svg+xml; charset=utf-8"),
}


# 移动按钮永远显示这六个方向，能不能走由世界数据决定
DIRECTIONS_ALL = ("north", "south", "east", "west", "up", "down")

# 休息滑条上方的快捷档位（分钟，按钮文字）；滑条本身是 1 分钟 ~ 8 小时
REST_PRESETS = [(10, "10 分钟"), (30, "半小时"), (60, "1 小时"),
                (120, "2 小时"), (240, "4 小时"), (480, "8 小时")]

MOVE_WORDS = ("走", "去", "go")

# 这些指令执行完顺手在浮层里回一句（存档、读档、清空、休息）
NOTICE_COMMANDS = ("存档", "读档", "清空", "休息", "等待", "save", "load", "clear", "rest", "wait")


def is_move(text):
    """这行指令是不是在移动？用来决定走不通时要不要弹提示。"""
    text = text.strip()
    if not text:
        return False
    if text.lower() in DIRECTIONS:  # 直接输入“东”“n”“north”这种
        return True
    return text.startswith(MOVE_WORDS) or text.split()[0:1] == ["go"]


def load_page():
    """读取首页，并把图标精灵内联进去。

    用 <use href="icons.svg#..."> 引外部精灵在部分浏览器里不生效，直接内联最稳，
    也少一次请求。图标文件缺失时页面照样能用，只是没有图标。
    """
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    sprite_path = WEB_DIR / "icons.svg"
    sprite = sprite_path.read_text(encoding="utf-8") if sprite_path.exists() else ""
    return html.replace("<!--SPRITE-->", sprite)


class Bridge:
    """角色创建时的一问一答通道。

    创建流程跑在后台线程里，它调用 input() 时会把“已经打印的文字 + 当前问题”
    通过 out_q 交给 HTTP 线程；HTTP 线程拿到玩家的答案后塞进 in_q，让创建流程
    继续往下走。这样阻塞式的 CharacterCreator 不需要任何改造。
    """

    def __init__(self, timeout=600):
        self.lines = []
        self.in_q = queue.Queue()
        self.out_q = queue.Queue()
        self.timeout = timeout
        self.last_prompt = None  # 最近一个还没回答的问题，刷新页面后可以重新推给前端

    def write(self, text):
        self.lines.append(text)

    def ask(self, prompt, hint):
        """把问题发给前端，然后阻塞等待答案。"""
        payload = {
            "type": "prompt",
            "lines": self.lines,
            "prompt": prompt,
            "input": hint or {"kind": "text"},
        }
        self.lines = []
        self.last_prompt = payload
        self.out_q.put(payload)
        try:
            return self.in_q.get(timeout=self.timeout)
        except queue.Empty:
            raise RuntimeError("等玩家回答超时（页面可能已关闭）")

    def wait(self):
        try:
            return self.out_q.get(timeout=self.timeout)
        except queue.Empty:
            raise RuntimeError("游戏没有回应（可能已经卡住或页面被关闭）")

    def answer(self, value):
        self.in_q.put(value)
        return self.wait()

    def publish(self, payload):
        self.out_q.put(payload)


class WebPrompter(Prompter):
    """把 Prompter 的问题搬上网页。

    text/number/choice/confirm 都直接复用父类的实现（校验、报错、重问全都不变），
    只在提问前记一下“这是个什么类型的问题、有什么限制”，让前端能渲染成
    输入框 / 数字框 / 单选按钮 / 是&否按钮。
    """

    def __init__(self, bridge):
        self.bridge = bridge
        self._hint = None
        super().__init__(self._web_input, self._web_print)

    def _web_print(self, *args):
        self.bridge.write(" ".join(str(a) for a in args))

    def _web_input(self, prompt):
        return self.bridge.ask(prompt, self._hint)

    def text(self, prompt, max_length=None, default=None):
        self._hint = {"kind": "text", "max_length": max_length, "default": default}
        try:
            return super().text(prompt, max_length, default)
        finally:
            self._hint = None

    def number(self, prompt, low, high):
        hint = dict(self._hint or {})
        hint["min"] = low
        hint["max"] = high
        hint.setdefault("kind", "number")
        self._hint = hint
        try:
            return super().number(prompt, low, high)
        finally:
            self._hint = None

    def choice(self, prompt, labels):
        # 选项文字由父类负责打印，这里额外把选项本身告诉前端
        self._hint = {"kind": "choice", "options": list(labels)}
        try:
            return super().choice(prompt, labels)
        finally:
            self._hint = None

    def confirm(self, prompt):
        self._hint = {"kind": "confirm", "options": ["是", "否"]}
        try:
            return super().confirm(prompt)
        finally:
            self._hint = None

    def attributes(self, attributes, rules, attribute_defs):
        """网页版属性分配：前端用加减号按钮调，最后一次性提交整份分配。

        收到的结果仍然交给 check_attributes 校验（和控制台同一个函数），
        不合法就退回前端重来。
        """
        self._hint = {
            "kind": "attributes",
            "attributes": dict(attributes),
            "rules": dict(rules),
            "defs": [
                {"id": a["id"], "name": a["name"], "description": a["description"]}
                for a in attribute_defs
            ],
        }
        names = {a["id"]: a["name"] for a in attribute_defs}
        try:
            while True:
                raw = self._web_input("分配属性")
                try:
                    data = json.loads(raw)
                    attrs = {key: int(value) for key, value in data.items()}
                except (ValueError, TypeError, AttributeError):
                    self._web_print("  没收到能用的分配结果，请重新调好再提交。")
                    continue
                if set(attrs) != set(attributes):
                    self._web_print("  属性项对不上，请重新提交。")
                    continue
                error = check_attributes(attrs, rules)
                if error:
                    self._web_print("  " + error)
                    continue
                self._web_print("【属性】" + "  ".join(
                    "%s %d" % (attr["name"], attrs[attr["id"]]) for attr in attribute_defs
                ))
                return attrs
        finally:
            self._hint = None


class Session:
    """一个本地单人游戏会话：加载数据、维护 Game、把状态打包给前端。"""

    def __init__(self):
        self.lock = threading.RLock()
        self.mode = "menu"  # menu / create / play / quit
        self.started = False
        self.bridge = None
        self.last_seen = 0.0  # 页面最后一次心跳的时间，用来决定要不要重开浏览器
        self.world = World(BASE_DIR / "data" / "world.json")
        self.options = CharacterOptions(BASE_DIR / "data" / "character_options.json")
        self.skill_trees = SkillTrees(BASE_DIR / "data" / "skill_trees.json")
        self.dice = Dice()
        self.game = Game(
            self.world, self.options, self.skill_trees, self.dice,
            BASE_DIR / "saves" / "save.json",
        )

    # ---------- 页面存活探测 ----------

    def heartbeat(self):
        """页面每隔一会儿叫一声，用来判断“还有人在看这个页面”。"""
        with self.lock:
            self.last_seen = time.time()
        return {"type": "pong", "app": APP_ID, "version": APP_VERSION}

    def idle_seconds(self):
        """距上一次页面心跳过去了几秒；从来没有过就返回 None。"""
        with self.lock:
            if not self.last_seen:
                return None
            return time.time() - self.last_seen

    def ping(self):
        """给新启动的进程认人用：这个端口上跑的是不是这个游戏。"""
        return {
            "app": APP_ID,
            "version": APP_VERSION,
            "mode": self.mode,
            "started": self.started,
            "idle_seconds": self.idle_seconds(),
        }

    # ---------- 状态打包 ----------

    def exits_for(self, room):
        """六个方向全部返回，颜色交给界面决定。

        open    = 现在就能走（绿色）
        danger  = 出口数据里写了 danger，那边有危险（红色）
        blocked = 走不通、或者暂时过不去（保持原色，点了才会知道原因）
        """
        game = self.game
        result = []
        overweight = game.load_level() == "overweight"
        for direction in DIRECTIONS_ALL:
            exit_ = room["exits"].get(direction)
            outdoor = bool(room.get("outdoor"))
            info = {
                "id": direction,
                "name": DIRECTION_NAMES.get(direction, direction),
                "state": "blocked",
                "target": None,
                "danger": None,
                "cost": game.next_move_cost(outdoor, overweight) if game.character else 0,
                "minutes": stats.move_minutes(outdoor, overweight),
            }
            if exit_ is not None:
                danger = None
                required = None
                if isinstance(exit_, dict):
                    danger = exit_.get("danger")
                    required = exit_.get("requires")
                    target = exit_.get("to")
                else:
                    target = exit_
                passable = not required or required in game.inventory
                if danger:
                    info["state"] = "danger"
                    info["danger"] = danger
                elif passable:
                    info["state"] = "open"
                if target in game.visited:
                    info["target"] = self.world.rooms[target]["name"]
            result.append(info)
        return result

    def quick_action(self, item_id):
        """快捷栏里点这件物品时默认执行什么：返回 {cmd, label}。"""
        data = self.world.items[item_id]
        name = data["name"]
        if items.is_usable(data):
            return {"cmd": "使用 " + name, "label": "使用"}
        if data.get("weapon") or "shield" in data or self.world.wear_candidates(item_id):
            return {"cmd": "装备 " + name, "label": "装备"}
        return {"cmd": "查看 " + name, "label": "查看"}

    def skills_state(self):
        """技能树打包给前端：按分支分组，能学的给按钮，学过的和不合条件的不可点。"""
        c = self.game.character
        trees = self.skill_trees
        data = {"points": c.skill_points, "trees": []}
        for tree in trees.trees:
            unlocked = tree_unlocked(c, tree)
            skills = []
            for skill in trees.skills_in(tree["id"]):
                learned = skill["id"] in c.learned_skills
                unmet = []
                if not learned and unlocked:
                    unmet = unmet_requirements(c, skill, trees, self.options)
                weapon = skill.get("weapon_type")
                skills.append({
                    "id": skill["id"],
                    "name": skill["name"],
                    "branch": skill.get("branch", ""),
                    "cost": skill.get("cost", 1),
                    "description": skill["description"],
                    "active": skill.get("type") == "active",
                    "cooldown": skill.get("cooldown", 0),
                    "ap_cost": skill.get("ap_cost", 0),
                    "weapon": self.world.weapon_types.get(weapon, weapon) if weapon else "",
                    "details": skill_details(c, skill, trees, self.options),
                    "learned": learned,
                    "unmet": unmet,
                })
            data["trees"].append({
                "id": tree["id"],
                "name": tree["name"],
                "attribute": self.options.attribute_name(tree["attribute"])
                if tree.get("attribute") else "",
                "special": bool(tree.get("special")),
                "description": tree.get("description", ""),
                "unlocked": unlocked,
                "locked_message": tree.get("locked_message", "尚未解锁"),
                "branches": [{"id": b["id"], "name": b["name"]}
                             for b in tree.get("branches", [])],
                "skills": skills,
            })
        return data

    def slot_state(self):
        """三个存档槽的概要，界面拿去渲染成可点选的形式。"""
        game = self.game
        slots = []
        for n in range(1, SLOT_COUNT + 1):
            info = game.slot_info(n)
            slots.append(info if info else {"slot": n, "exists": False})
        return slots

    def state(self):
        game = self.game
        snap = {
            "mode": self.mode,
            "started": self.started,
            "has_save": game.has_save(),
            "current_slot": game.slot,
            "slots": self.slot_state(),
        }
        if not self.started or not game.character:
            return snap

        world = self.world
        room = world.rooms[game.current_room]
        inventory = []
        for item_id in game.inventory:
            data = world.items[item_id]
            inventory.append({
                "id": item_id,
                "name": data["name"],
                "where": game.item_location(item_id),
                "usable": items.is_usable(data),
                "use_hint": (data.get("use") or {}).get("hint", ""),
                "desc": data.get("description", ""),
                "weight": data.get("weight", 1),
                "weapon": bool(data.get("weapon")),
                # 快捷栏点一下默认做什么：能吃能喝就使用，武器就装备，其它就查看
                "quick": self.quick_action(item_id),
            })

        c = game.character
        stance = game._current_stance()
        snap.update({
            "turns": game.turns,
            "time": {"day": game.day, "minutes": game.minutes, "text": game.clock_text()},
            "room": {"id": game.current_room, "name": room["name"]},
            "exits": self.exits_for(room),
            "rest": {
                "min": REST_MINUTES_MIN,
                "max": REST_MINUTES_MAX,
                "presets": [{"minutes": m, "label": label} for m, label in REST_PRESETS],
                "hint": "滑条可以从 1 分钟拖到 8 小时；每 %d 分钟恢复 %d%% 体力上限，8 小时足够补满。"
                        % (stats.REST_MINUTES_PER_TICK, int(stats.REST_RECOVER_RATIO * 100)),
            },
            "skills": self.skills_state(),
            "room_items": [
                {"id": i, "name": world.items[i]["name"]}
                for i in game.room_items[game.current_room]
            ],
            "npcs": [{"id": n, "name": world.npcs[n]["name"]} for n in room.get("npcs", [])],
            "inventory": inventory,
            "character": {
                "name": c.name,
                "gender": c.gender,
                "age": c.age,
                "height": c.height,
                "background": self.options.background(c.background)["name"],
                "level": c.level,
                "xp": c.xp,
                "hp": c.hp,
                "hp_max": stats.max_hp(c.attributes, c.level),
                "skill_points": c.skill_points,
                "attributes": [
                    {"id": a["id"], "name": a["name"], "value": c.attributes.get(a["id"], 0)}
                    for a in self.options.attributes
                ],
                "companions": [
                    {"name": p.name, "relationship": p.relationship, "age": p.age}
                    for p in c.companions
                ],
            },
            "carry": {
                "weight": game._carried_weight(),
                "capacity": stats.carry_capacity(c.attributes),
            },
            "stamina": {
                "value": c.stamina,
                "max": stats.stamina_max(c.attributes),
                "cost_multiplier": round(stats.stamina_cost_multiplier(c.attributes), 2),
                "exhausted": stats.is_exhausted(c),
            },
            "conditions": game.conditions(),
            "attack_penalty": stats.attack_penalty(c),
            "combat": {
                "ap_per_turn": stats.ap_per_turn(c.attributes, game.armor_ap_penalty()),
                "ap_cap": stats.ap_cap(c.attributes, game.armor_ap_penalty()),
                "armor_ap_penalty": game.armor_ap_penalty(),
                "armor": game.armor_total(),
                "worn": [
                    {"slot": world.armor_slots[s], "name": world.items[i]["name"],
                     "value": world.items[i]["armor"]["value"]}
                    for s, i in game.worn.items() if i and world.items[i].get("armor")
                ],
                "attack_cost": stats.ATTACK_AP_COST,
                "move_cost": (lambda cost: "无法移动" if cost is None else
                              f"{cost}/格" + ("（超重）" if cost != stats.MOVE_AP_COST else ""))(
                    stats.move_ap_cost(game._carried_weight(), stats.carry_capacity(c.attributes))),
                "item_cost": stats.USE_ITEM_AP_COST,
                "dodge": game.dodge(),
                "initiative": stats.initiative(c.attributes),
                "weapons": game.weapon_summary(),
            },
            "equipment": {
                slot: (world.items[i]["name"] if i else None)
                for slot, i in game.equipment.items()
            },
            "stance": stance["name"] if stance else None,
            "grip": game.grip_name(),
            "gear": [
                {"slot": info["name"], "name": world.items[game.worn[slot]]["name"] if game.worn[slot] else None}
                for slot, info in world.gear_slots.items()
            ],
            "backpack_reduction": game.backpack_reduction(),
            "running": game.running,
        })
        return snap

    # ---------- 流程 ----------

    def start_creation(self):
        """开一局新游戏：后台线程跑角色创建，前端一问一答。"""
        with self.lock:
            if self.mode == "create" and self.bridge and self.bridge.last_prompt:
                # 创建还没走完（比如刷新了页面）：把当前这个问题再推一遍，别让玩家卡死
                return self.bridge.last_prompt
            self.mode = "create"
            self.started = False
            bridge = Bridge()
            self.bridge = bridge
            ask = WebPrompter(bridge)
            tree_names = {t["id"]: t["name"] for t in self.skill_trees.trees}

        def work():
            try:
                character = CharacterCreator(
                    self.options, self.world.items, tree_names, ask
                ).run()
                with self.lock:
                    self.game.start_new(character)
                    self.started = True
                    self.mode = "play"
                    self.bridge = None
                    intro = [
                        "你是%s，%s。" % (
                            character.name,
                            self.options.background(character.background)["name"],
                        ),
                        self.world.intro,
                        "下面是你的第一个落脚点，用按钮行动吧。",
                        self.game.describe_room(),
                    ]
                bridge.publish({"type": "play", "lines": intro, "state": self.state()})
            except Exception as exc:  # 让前端看到错误，而不是页面一直转圈
                with self.lock:
                    self.mode = "menu"
                    self.bridge = None
                bridge.publish({"type": "error", "lines": ["创建角色失败：%s" % exc],
                                "state": self.state()})

        threading.Thread(target=work, daemon=True).start()
        return bridge.wait()

    def answer(self, value):
        with self.lock:
            bridge = self.bridge
        if bridge is None:
            return {"type": "error", "lines": ["现在没有等待回答的问题。"], "state": self.state()}
        return bridge.answer(value)

    def continue_game(self):
        """继续上次的进度：读最近改过的那个存档槽。"""
        with self.lock:
            self.game.running = True
            text = self.game.cmd_load("")
            self.started = self.game.character is not None
            self.mode = "play" if self.started else "menu"
            return {"type": "play", "lines": [text], "state": self.state(),
                    "notice": text.splitlines()[0] if text else ""}

    def _reply(self, text, notice=None, kind=None):
        """存档类操作的统一回包。

        已经开局就回到游戏界面；还没开局（比如在主菜单里清空存档）就留在主菜单，
        别因为一次清空把玩家踢进游戏界面。notice 是浮层提示的文字，成功失败都说一声。
        """
        if kind is None:
            kind = "play" if self.started else "menu"
        return {
            "type": kind,
            "lines": [text],
            "state": self.state(),
            "notice": text.splitlines()[0] if (notice is None and text) else notice,
        }

    def save_to(self, slot):
        """存到指定槽位（槽位里已有存档时就是覆盖）。"""
        with self.lock:
            if not self.started or not self.game.character:
                return {"type": "error", "lines": ["还没有角色，先开一局新游戏。"],
                        "state": self.state()}
            text = self.game.cmd_save(str(slot))
            failed = text.startswith("存档失败")
            return self._reply(text, notice=text.splitlines()[0], kind="error" if failed else "play")

    def load_slot(self, slot):
        """从指定槽位读档。"""
        with self.lock:
            was_playing = self.started
            self.game.running = True
            text = self.game.cmd_load(str(slot))
            ok = "读档成功" in text
            self.started = self.game.character is not None
            # 读失败时别把正在玩的人踢回主菜单
            self.mode = "play" if (ok or was_playing) else "menu"
            return self._reply(text, kind="play" if (ok or was_playing) else "menu")

    def clear_slot(self, slot):
        """清空一个存档槽（不需要先开局，在主菜单里也能清）。"""
        with self.lock:
            text = self.game.cmd_clear(str(slot))
            return self._reply(text)

    def quit_game(self):
        """退出游戏：结束这一局，并且让本地服务停下来。

        网页不是脚本打开的，浏览器一般不让页面自己关标签页，所以这里至少把
        游戏和服务真正结束掉，前端再给一句“可以关掉这个页面了”。
        """
        with self.lock:
            self.game.running = False
            self.started = False
            self.mode = "quit"
            return {
                "type": "quit",
                "lines": ["你退出了游戏，本地服务正在关闭。"],
                "state": self.state(),
            }


    def command(self, text):
        """玩家在界面上按了一个按钮（或输入了一行指令）。"""
        with self.lock:
            if not self.started:
                return {"type": "error", "lines": ["还没有角色，先新游戏或读档。"],
                        "state": self.state()}
            text = (text or "").strip()
            if not text:
                return {"type": "play", "lines": [], "state": self.state()}
            lines = ["> " + text]
            output = self.game.handle(text)
            if output:
                lines.append(output)
            # 走不通、体力不够这类提示额外带一份，界面会用浮层弹出来
            notice = None
            if is_move(text) and not (output or "").startswith("【"):
                notice = output or "那边走不过去。"
            elif output and text.split()[0] in NOTICE_COMMANDS:
                # 存档 / 读档 / 清空 / 休息 这类操作，浮层里也回一句，省得去日志里翻
                notice = next((line for line in output.splitlines() if line.strip()), None)
            return {
                "type": "play",
                "lines": lines,
                "state": self.state(),
                "quit": not self.game.running,
                "notice": notice,
            }


class LazySession:
    """第一次真的收到请求时才建 Session。

    端口空着（最常见的情况）就直接把服务起起来，不需要任何探测；发现本游戏
    已经在跑时也直接退出，没必要先把世界数据读一遍。这样启动只剩解释器启动
    和 import 的时间。
    """

    def __init__(self):
        self._session = None
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            if self._session is None:
                self._session = Session()
            return self._session

    def __getattr__(self, name):
        return getattr(self.get(), name)


class Handler(BaseHTTPRequestHandler):
    server_version = "FengchengWeb/1.0"
    session = None

    # 默认会把每个请求打到 stderr，本地玩的时候太吵，静音
    def log_message(self, fmt, *args):
        pass

    # ---------- 工具 ----------

    def _send(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # 开发期避免浏览器缓存旧的 js/css
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(body, "application/json; charset=utf-8", status)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    # ---------- 路由 ----------

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/state":
            self._json({"type": "state", "state": self.session.state()})
            return
        if path == "/api/ping":
            # 只给“新启动的进程”探测用，不算页面活动
            self._json(self.session.ping())
            return
        entry = STATIC_FILES.get(path)
        if not entry:
            self._json({"error": "没有这个地址"}, 404)
            return
        name, content_type = entry
        file_path = WEB_DIR / name
        if not file_path.exists():
            self._json({"error": "缺少文件 %s" % name}, 500)
            return
        if name == "index.html":
            self._send(load_page().encode("utf-8"), content_type)
            return
        self._send(file_path.read_bytes(), content_type)

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            payload = self._body()
        except ValueError as exc:
            self._json({"type": "error", "lines": ["请求格式不对：%s" % exc]}, 400)
            return
        try:
            if path == "/api/new":
                self._json(self.session.start_creation())
            elif path == "/api/answer":
                self._json(self.session.answer(str(payload.get("value", ""))))
            elif path == "/api/continue":
                self._json(self.session.continue_game())
            elif path == "/api/save":
                self._json(self.session.save_to(int(payload.get("slot") or 1)))
            elif path == "/api/load":
                self._json(self.session.load_slot(int(payload.get("slot") or 1)))
            elif path == "/api/clear":
                self._json(self.session.clear_slot(int(payload.get("slot") or 1)))
            elif path == "/api/heartbeat":
                self._json(self.session.heartbeat())
            elif path == "/api/command":
                self._json(self.session.command(str(payload.get("text", ""))))
            elif path == "/api/quit":
                self._json(self.session.quit_game())
                # 先把回包发出去，再让服务停下来（不然浏览器什么都收不到）
                stop = getattr(type(self), "stop_server", None)
                if stop:
                    threading.Timer(0.6, stop).start()
            else:
                self._json({"error": "没有这个地址"}, 404)
        except Exception as exc:
            self._json({"type": "error", "lines": ["服务器出错：%s" % exc],
                        "state": self.session.state()}, 500)


def make_handler(session):
    return type("BoundHandler", (Handler,), {"session": session})

def port_is_free(host, port):
    """这个端口现在是不是空的。

    不能直接拿 HTTPServer 去试：它开了 SO_REUSEADDR，而 Windows 上带这个选项的
    bind 在别人已经监听时也会成功。所以用一个不带任何选项的裸 socket 来判断。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def probe_app(host, port, timeout=0.3):
    """看看这个端口上是不是本游戏已经在跑。

    返回 (状态, 信息)：
      "ours"    本游戏的服务
      "foreign" 别的程序在监听
      "closed"  没人监听（连接被拒绝）
      "unknown" 说不清（超时、被防火墙挡了、端口被系统保留）
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 别走系统代理
    request = urllib.request.Request("http://%s:%d/api/ping" % (host, port))
    try:
        with opener.open(request, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return "foreign", None
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), ConnectionRefusedError):
            return "closed", None
        return "unknown", None
    except Exception:
        return "unknown", None
    if isinstance(data, dict) and data.get("app") == APP_ID:
        return "ours", data
    return "foreign", None


def announce_existing(host, port, info, args):
    """已经有一个在跑：不再起第二个服务，地址也永远是那一个，页面就不会越开越多。"""
    url = "http://%s:%d/" % (host, port)
    idle = (info or {}).get("idle_seconds")
    print("=== 封城第七天 · 网页版 ===")
    print("游戏已经在运行了，地址还是：%s" % url)
    if args.no_browser:
        print("（--no-browser：自己打开上面的地址就行）")
    elif args.open or idle is None or idle > IDLE_LIMIT:
        print("这个地址上好像没有开着的页面，帮你打开。")
        webbrowser.open(url)
    else:
        print("页面应该还开着（%.0f 秒前还有活动），这次就不另开标签页了。" % idle)
        print("想强制再开一个页面就加 --open。")
    return 0


def main():
    parser = argparse.ArgumentParser(description="《封城第七天》网页版入口")
    parser.add_argument("--port", type=int, default=8730, help="起始端口，被占用就往后找")
    parser.add_argument("--host", default="127.0.0.1", help="默认只监听本机")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--open", action="store_true",
                        help="页面还开着的时候也强制再打开一次（默认不重复开标签页）")
    parser.add_argument("--force", action="store_true",
                        help="就算已经有在跑的服务，也另起一个（端口会往后找）")
    args = parser.parse_args()

    ports = list(range(args.port, args.port + 10))
    handler = make_handler(LazySession())

    # 先看端口空不空：空就直接用，连探测都不做（启动最快）。
    # 只有端口被占时才去问一句“是不是我们自己”，问的代价只有 0.3 秒。
    server = None
    for port in ports:
        if not port_is_free(args.host, port):
            if args.force:
                continue  # 指定要另起一个，那占用中的端口一律跳过
            status, info = probe_app(args.host, port)
            if status == "ours":
                return announce_existing(args.host, port, info, args)
            if status != "closed":
                continue  # 别的程序占着（或者问不出来），换下一个端口
            # "closed"：探测说没人监听，多半只是 TIME_WAIT，照常自己起
        try:
            server = ThreadingHTTPServer((args.host, port), handler)
            break
        except OSError:
            continue
    if server is None:
        print("端口 %d~%d 都被占用了，请用 --port 换一个。" % (args.port, args.port + 9))
        return 1

    server.daemon_threads = True
    url = "http://%s:%d/" % (args.host, server.server_address[1])
    print("=== 封城第七天 · 网页版 ===")
    print("地址：%s" % url)
    print("在这个窗口按 Ctrl+C 结束服务；游戏里的“退出游戏”按钮也会结束它。")
    if not args.no_browser:
        # 服务已经绑好端口了，这里只留一丁点时间让 print 刷出来就开浏览器
        threading.Timer(0.15, webbrowser.open, args=(url,)).start()

    # 游戏里点“退出游戏”时用这个把服务停掉
    handler.stop_server = server.shutdown
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
