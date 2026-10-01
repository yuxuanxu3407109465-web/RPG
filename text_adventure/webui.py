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
- 关掉网页就等于关掉游戏：页面临走前用 sendBeacon 报一声 /api/bye，服务确认一个页面都
  不剩了，就结束这一局并自己退出（刷新页面有十几秒宽限期，不会连服务一起关掉）。
  页面被强杀、电脑休眠这种来不及打招呼的情况，靠心跳超时兜底（先只当“没人看”，
  半小时还没有页面回来才真的结束）。存档一个字节都不动。
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
    DIRECTION_NAMES, DIRECTIONS, GRID_STEPS, REST_MINUTES_MAX, REST_MINUTES_MIN, SLOT_COUNT,
    Game, World,
)
import skills as skill_rules
from skills import SkillTrees, skill_details, tree_unlocked, unmet_requirements

BASE_DIR = Path(__file__).parent
WEB_DIR = BASE_DIR / "web"

# 用来认出“这个端口上跑的是我们自己”，避免重复启动
APP_ID = "fengcheng-day7"
APP_VERSION = 3

# 页面每隔 HEARTBEAT_SECONDS 秒报一次活；超过 IDLE_LIMIT 秒没动静就当成页面已经关了，
# 再次启动时才会重新打开浏览器。
HEARTBEAT_SECONDS = 20
IDLE_LIMIT = 50

# 页面说“我要关了”之后，服务再等这么久才真的退出：刷新页面会在这段时间里回来。
CLOSE_GRACE_SECONDS = 12
# 页面超过这么久没有心跳，就不算“还有人在看”了（ping.pages 会减掉它，重新双击会帮着开浏览器）。
# 浏览器会把后台标签页的定时器降频到一分钟左右一次，所以这里留得比心跳间隔宽不少。
PAGE_TIMEOUT = 150
# 一个页面都没有的状态持续这么久，才真的结束这一局、退出服务。
# 浏览器被强杀、电脑休眠这种来不及报备的情况会让心跳突然断掉，但人可能还会回来：
# 先按“没人看”处理（重新双击开浏览器、接着玩内存里这一局），这么久还没人回来才结束。
GAME_IDLE_TIMEOUT = 1800
# 每隔这么久检查一次“还有没有页面在看”
SWEEP_SECONDS = 10

# 没带页面 id 的请求（老页面、curl 之类）统一算作这一个页面
DEFAULT_PAGE_ID = "default"

# main() 的退出码：启动器（启动网页版.bat）靠它决定那个黑窗口要不要自己关
EXIT_OK = 0
EXIT_PAGE_CLOSED = 2      # 页面关了 / 点过“退出游戏”：游戏和服务都结束了
EXIT_ALREADY_RUNNING = 3  # 已经有一个在跑，这次什么都没做

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

# 这些指令执行完顺手在浮层里回一句（存档、读档、清空、休息、拆分、堆叠）
NOTICE_COMMANDS = ("存档", "读档", "清空", "休息", "等待", "拆分", "堆叠",
                   "save", "load", "clear", "rest", "wait", "split", "stack")


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
        self.last_seen = 0.0  # 页面最后一次活动的时间，用来决定要不要重开浏览器
        self.on_close = None  # 页面全关了以后用它停掉服务（main 里接到 server.shutdown）
        self.pages = {}       # 页面 id -> 最后一次活动时间；关一个页面不影响另一个页面
        self.ever_had_page = False
        self.last_page_seen = 0.0   # 最后一次“有页面在”的时间（页面都走了以后用来等一会儿）
        self.close_deadline = None  # 到这个时刻还没有页面回来，就结束游戏、退出服务
        self.closed = False
        self._watchdog = None
        self.world = World(BASE_DIR / "data" / "world.json")
        self.options = CharacterOptions(BASE_DIR / "data" / "character_options.json")
        self.skill_trees = SkillTrees(BASE_DIR / "data" / "skill_trees.json")
        self.dice = Dice()
        self.game = Game(
            self.world, self.options, self.skill_trees, self.dice,
            BASE_DIR / "saves" / "save.json",
        )

    # ---------- 页面存活探测 ----------

    def page_seen(self, page_id):
        """有页面在活动：记一笔，顺便撤销“准备关掉”的倒计时。

        page_id 由页面自己生成，每打开一次页面就换一个：同一个浏览器开了两个页面也能
        分得清，关掉其中一个不会把另一个也结束掉。
        """
        page_id = page_id or DEFAULT_PAGE_ID
        now = time.time()
        with self.lock:
            self.pages[page_id] = now
            self.last_seen = now
            self.last_page_seen = now
            self.ever_had_page = True
            self.close_deadline = None
            self._start_watchdog()
        return page_id

    def heartbeat(self, page_id=None):
        """页面每隔一会儿叫一声，用来判断“还有人在看这个页面”。"""
        self.page_seen(page_id)
        return {"type": "pong", "app": APP_ID, "version": APP_VERSION}

    def page_closed(self, page_id):
        """页面说“我要关了”（关标签页 / 刷新之前用 sendBeacon 报一声）。

        这里只点上一个倒计时，不是立刻退服务：刷新页面会在宽限期里重新报到，
        只有真的没有页面回来了，才结束这一局并把服务停掉。
        """
        page_id = page_id or DEFAULT_PAGE_ID
        with self.lock:
            self.pages.pop(page_id, None)
            self.ever_had_page = True
            self.last_page_seen = time.time()
            if not self.pages:
                self.close_deadline = time.time() + CLOSE_GRACE_SECONDS
            self._start_watchdog()
        return {"type": "bye", "app": APP_ID, "grace": CLOSE_GRACE_SECONDS}

    def _start_watchdog(self):
        """起一个后台线程盯着“还有没有页面在看”（只在拿着锁的时候调用）。"""
        if self._watchdog is None:
            self._watchdog = threading.Thread(target=self._watch_loop, daemon=True)
            self._watchdog.start()

    def _watch_loop(self):
        while True:
            time.sleep(SWEEP_SECONDS)
            self._sweep()

    def _sweep(self):
        """心跳断了的页面剔掉；确定没人看了，才结束游戏、停掉服务。"""
        now = time.time()
        with self.lock:
            for page_id in [p for p, seen in self.pages.items() if now - seen > PAGE_TIMEOUT]:
                del self.pages[page_id]
            if self.pages:
                self.close_deadline = None   # 还有页面在看：撤销倒计时
                return
            if not self.ever_had_page or self.closed:
                return  # 从来没有页面连上来过：别把刚起来的服务自己关掉
            if self.close_deadline is None:
                # 页面没打招呼就没了（被强杀、电脑休眠……）：先只当“没人看”，游戏再留一会儿，
                # 人要是回来了（重新双击，或者标签页从冻结里醒过来）还能接着玩这一局。
                if now - self.last_page_seen < GAME_IDLE_TIMEOUT:
                    return
                self.close_deadline = now
            if now < self.close_deadline:
                return
        self.shutdown_because_page_closed()

    def shutdown_because_page_closed(self):
        """页面全关了：结束这一局，然后把本地服务也停掉。

        存档一个字节都不动 —— 进度以玩家自己按下的那一下“保存”为准。
        """
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.game.running = False
            self.started = False
            self.mode = "menu"
            self.pages = {}
            callback = self.on_close
        print("页面已关闭，游戏结束，服务停止。", flush=True)
        if callback:
            callback()

    def idle_seconds(self):
        """距上一次页面心跳过去了几秒；从来没有过就返回 None。"""
        with self.lock:
            if not self.last_seen:
                return None
            return time.time() - self.last_seen

    def ping(self):
        """给新启动的进程认人用：这个端口上跑的是不是这个游戏。"""
        with self.lock:
            pages = len(self.pages)
        return {
            "app": APP_ID,
            "version": APP_VERSION,
            "mode": self.mode,
            "started": self.started,
            "idle_seconds": self.idle_seconds(),
            "pages": pages,   # 现在还有几个页面在看（0 就是没人看）
        }

    # ---------- 状态打包 ----------

    def exits_for(self, room):
        """六个方向全部返回，颜色交给界面决定。

        有场景格子的房间：一个方向 = 走一格。旁边的格子能走就是 open，
        是墙/障碍物就是 blocked；那一格正好是门 / 楼梯时，照旧带上出口信息。
        没有场景数据的房间退回老做法（一个方向 = 直接换房间）。
        """
        game = self.game
        result = []
        overweight = game.load_level() == "overweight"
        grid = game.room_grid()
        pos = game.player_pos(grid) if grid else None
        for direction in DIRECTIONS_ALL:
            exit_ = room["exits"].get(direction)
            info = {
                "id": direction,
                "name": DIRECTION_NAMES.get(direction, direction),
                "state": "blocked",
                "tile": None,
                "target": None,
                "danger": None,
                "cost": game.next_move_cost(overweight) if game.character else 0,
                "minutes": stats.move_minutes(overweight),
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
                # 要带某件东西才过得去（例如下地下室要手电筒）：背着或者装备着都算
                passable = (not required or game.count_item(required) > 0
                            or required in game.equipped_ids())
                if not passable:
                    # 缺东西就过不去：按钮画成走不通，提示里写清楚为什么过不去
                    info["state"] = "blocked"
                    blocked_message = exit_.get("blocked_message") if isinstance(exit_, dict) else None
                    info["danger"] = blocked_message or danger
                elif danger:
                    info["state"] = "danger"
                    info["danger"] = danger
                else:
                    info["state"] = "open"
                if target in game.visited:
                    info["target"] = self.world.rooms[target]["name"]
            if grid:
                self._grid_direction_info(game, grid, pos, direction, exit_, info)
            result.append(info)
        return result

    def _grid_direction_info(self, game, grid, pos, direction, exit_, info):
        """按场景格子修正这一个方向的状态（见 exits_for 的注释）。"""
        if direction in ("up", "down"):
            tile = game.door_tile(grid, direction)
            if tile and exit_ is not None:
                near = max(abs(tile[0] - pos[0]), abs(tile[1] - pos[1])) <= 1
                info["tile"] = "stairs"
                # 楼上楼下的出口信息照旧，只有站到楼梯边上才点得动
                info["state"] = info["state"] if near else "blocked"
                if not near:
                    info["danger"] = info["danger"] or "楼梯不在这儿，先走过去"
            else:
                info["state"] = "blocked"
            return
        dx, dy = GRID_STEPS[direction]
        target = (pos[0] + dx, pos[1] + dy)
        walkable = game.tile_walkable(grid, target[0], target[1])
        door_dir = game.door_direction(grid, target) if walkable else None
        if not walkable:
            info["tile"] = "wall"
            info["state"] = "blocked"
            info["target"] = None
            info["danger"] = None
        elif door_dir and exit_ is not None:
            info["tile"] = "door"
        else:
            info["tile"] = "floor"
            info["state"] = "open"
            info["target"] = None
            info["danger"] = None

    def equip_slots(self):
        """装备栏：每个位置一个方框，给网页版拖动装备用。"""
        game = self.game
        slots = []
        for slot, label in (("main_hand", "主手"), ("off_hand", "副手")):
            slots.append(self._slot_payload(slot, label, "hand", game.equipment.get(slot)))
        for slot, label in self.world.armor_slots.items():
            slots.append(self._slot_payload(slot, label, "armor", game.worn.get(slot)))
        for slot, info in self.world.gear_slots.items():
            slots.append(self._slot_payload(slot, info["name"], info["kind"], game.worn.get(slot)))
        return slots

    def _slot_payload(self, slot, label, kind, item_id):
        payload = {"slot": slot, "label": label, "kind": kind, "item": None}
        if not item_id:
            return payload
        data = self.world.items[item_id]
        payload["item"] = {
            "id": item_id,
            "name": self.game.item_display_name(item_id),
            "weight": data.get("weight", 1),
            "detail": self.item_detail(item_id),
            "slots": self.item_slots(item_id),  # 拖到另一只手上换手时要用
            "weapon": bool(data.get("weapon")),
            "count": 1,
        }
        return payload

    def item_payload(self, item_id, stack=None):
        """一件物品打包给前端；给了 stack 就连这一堆（sid / 数量 / 能不能堆叠）一起带上。"""
        data = self.world.items[item_id]
        limit = stats.stack_max(data)
        payload = {
            "id": item_id,
            "name": data["name"],
            "usable": items.is_usable(data),
            "use_hint": (data.get("use") or {}).get("hint", ""),
            "desc": data.get("description", ""),
            "weight": data.get("weight", 1),
            "detail": self.item_detail(item_id),
            "slots": self.item_slots(item_id),  # 能拖到哪些装备位上
            "weapon": bool(data.get("weapon")),
            # 快捷栏点一下默认做什么：能吃能喝就使用，武器就装备，其它就查看
            "quick": self.quick_action(item_id),
            "stackable": limit > 1,   # 只有带 stack 词条的物品才拆得开
            "max": limit,
        }
        if stack is not None:
            payload["sid"] = stack["sid"]
            payload["count"] = stack["count"]
            payload["auto"] = stack["auto"]  # 拆出来的那堆不会再被自动堆叠
            payload["total_weight"] = round(data.get("weight", 1) * stack["count"], 2)
        return payload

    def inventory_state(self):
        """背包按“一格一堆”下发，界面照着一堆一个图标画。"""
        return [self.item_payload(s["id"], s) for s in self.game.inventory]

    def item_detail(self, item_id):
        """物品方框里那一行小字：护甲写护甲值，武器写伤害，其它写重量分类。"""
        data = self.world.items[item_id]
        if data.get("armor"):
            return f"护甲 +{stats.armor_value(data)}"
        weapon = data.get("weapon")
        hold = stats.HOLD_TYPES.get(stats.hold_type(data), "")
        if weapon:
            kind = ("代用" if weapon.get("improvised") else "") + self.world.weapon_types.get(weapon["type"], weapon["type"])
            return f"{hold}{kind} {stats.weapon_damage(data)}"
        if "shield" in data:
            return f"{hold}盾牌"
        gear = data.get("gear")
        if gear and gear.get("weight_reduction"):
            return f"减重 {gear['weight_reduction']}%"
        return f"{data.get('weight', 1)} kg"

    def item_slots(self, item_id):
        """这件东西能装在哪些位置（前端据此判断拖过去合不合法）。"""
        if self.world.wear_candidates(item_id):
            return self.world.wear_candidates(item_id)
        return stats.hold_slots(self.world.items[item_id])

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
                    "cooldown": skill_rules.cooldown_text(skill),
                    "ap_cost": skill_rules.ap_cost(skill),
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
            # 死了：界面弹“你死了”菜单（读档 / 返回菜单）
            "death": ({"cause": stats.DEATH_CAUSES.get(game.death_cause, game.death_cause)}
                      if game.death_cause else None),
        }
        if not self.started or not game.character:
            return snap

        world = self.world
        room = world.rooms[game.current_room]
        inventory = self.inventory_state()
        bag_total = sum(item["count"] for item in inventory)

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
                "hp_max": self.options.max_hp(c),
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
                "label": stats.load_label(game._carried_weight(),
                                          stats.carry_capacity(c.attributes)),
                "slots": bag_total,          # 一共几件（堆里的都算）
                "stacks": len(inventory),    # 占背包几格（一格一堆）
            },
            "stamina": {
                "value": c.stamina,
                "max": stats.stamina_max(c.attributes),
                "exhausted": stats.is_exhausted(c),
            },
            "needs": {"food": c.food, "water": c.water, "max": stats.NEED_MAX,
                      "food_stage": game.need_stage("food"), "water_stage": game.need_stage("water")},
            "conditions": game.conditions(),
            "attack_penalty": stats.attack_penalty(c),
            "combat": {
                "ap_per_turn": stats.ap_per_turn(c.attributes, game.armor_ap_penalty()),
                "ap_cap": stats.ap_cap(c.attributes, game.armor_ap_penalty()),
                "armor_ap_penalty": game.armor_ap_penalty(),
                "armor": game.armor_total(),
                "worn": [
                    {"slot": world.armor_slots[s], "name": world.items[i]["name"],
                     "value": stats.armor_value(world.items[i])}
                    for s, i in game.worn.items() if i and world.items[i].get("armor")
                ],
                "attack_cost": stats.ATTACK_AP_COST,
                "move_cost": (lambda cost: "无法移动" if cost is None else
                              f"{cost}/格" + ("（超重）" if cost != stats.MOVE_AP_COST else ""))(
                    stats.move_ap_cost(game._carried_weight(), stats.carry_capacity(c.attributes))),
                "item_cost": stats.USE_ITEM_AP_COST,
                "dodge": game.dodge(),
                "initiative": stats.initiative(c.attributes),
                "sight": game.sight_range(),
                "weapons": game.weapon_summary(),
            },
            "equipment": {
                slot: (world.items[i]["name"] if i else None)
                for slot, i in game.equipment.items()
            },
            "equip_slots": self.equip_slots(),
            "scene": game.scene_state(),
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

    def to_menu(self):
        """死了以后点“返回菜单”：结束这一局，回到主菜单（存档不动）。"""
        with self.lock:
            self.game.death_cause = None
            self.started = False
            self.mode = "menu"
            return {"type": "menu", "lines": [], "state": self.state()}

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
            self.closed = True   # 服务由 handler 停掉，别让看门狗再关一次
            self.pages = {}
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
        self._on_close = None

    def set_on_close(self, callback):
        """记下“怎么把服务停掉”；Session 还没建就先存着，建的时候再交给它。"""
        with self._lock:
            self._on_close = callback
            if self._session is not None:
                self._session.on_close = callback

    def get(self):
        with self._lock:
            if self._session is None:
                self._session = Session()
                self._session.on_close = self._on_close
            return self._session

    def closed_by_page(self):
        """服务是不是因为页面关了（或点了退出）才停的；没建过 Session 就不算。"""
        with self._lock:
            return bool(self._session and self._session.closed)

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
        page = str(payload.get("page") or "")
        try:
            if path == "/api/bye":
                # 页面要关了：先回到它（浏览器会等这个 beacon 发完），再开始倒计时
                self._json(self.session.page_closed(page))
                return
            if path != "/api/heartbeat":
                # 心跳自己会记一笔；其它请求也说明页面还在，顺手记上
                self.session.page_seen(page)
            if path == "/api/new":
                self._json(self.session.start_creation())
            elif path == "/api/answer":
                self._json(self.session.answer(str(payload.get("value", ""))))
            elif path == "/api/continue":
                self._json(self.session.continue_game())
            elif path == "/api/menu":
                self._json(self.session.to_menu())
            elif path == "/api/save":
                self._json(self.session.save_to(int(payload.get("slot") or 1)))
            elif path == "/api/load":
                self._json(self.session.load_slot(int(payload.get("slot") or 1)))
            elif path == "/api/clear":
                self._json(self.session.clear_slot(int(payload.get("slot") or 1)))
            elif path == "/api/heartbeat":
                self._json(self.session.heartbeat(page))
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
    pages = (info or {}).get("pages") or 0
    print("=== 封城第七天 · 网页版 ===")
    print("游戏已经在运行了，地址还是：%s" % url)
    if args.no_browser:
        print("（--no-browser：自己打开上面的地址就行）")
    elif args.open or not pages or idle is None or idle > IDLE_LIMIT:
        # 服务自己知道还有没有页面在看：一个都没有就一定会帮你打开，不再猜
        print("这个地址上好像没有开着的页面，帮你打开。")
        webbrowser.open(url)
    else:
        print("页面还开着（%d 个，%.0f 秒前还有活动），这次就不另开标签页了。" % (pages, idle))
        print("想强制再开一个页面就加 --open。")
    return EXIT_ALREADY_RUNNING


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
    session = LazySession()
    handler = make_handler(session)

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
    print("在这个窗口按 Ctrl+C 结束服务；关掉网页、或者点游戏里的“退出游戏”，也会结束它。")
    if not args.no_browser:
        # 服务已经绑好端口了，这里只留一丁点时间让 print 刷出来就开浏览器
        threading.Timer(0.15, webbrowser.open, args=(url,)).start()

    # 游戏里点“退出游戏”、或者页面全关掉时，用这两个回调把服务停掉
    handler.stop_server = server.shutdown
    session.set_on_close(server.shutdown)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    if session.closed_by_page():
        return EXIT_PAGE_CLOSED   # 页面关了 / 点过退出：启动器看到这个码就不用再等按键
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
