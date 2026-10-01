"""角色系统：玩家自定义主角和同伴。"""

import json
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Dict, List

import stats


@dataclass
class Companion:
    name: str
    gender: str
    age: int
    relationship: str
    appearance: str


@dataclass
class Character:
    name: str
    gender: str
    age: int
    height: int
    appearance: str
    background: str  # 背景 id，对应 character_options.json 里的 backgrounds
    attributes: Dict[str, int]  # 属性 id -> 数值（1~10）
    companions: List[Companion] = field(default_factory=list)
    level: int = 1
    xp: int = 0  # 当前等级内累积的经验
    skill_points: int = 0  # 还没使用的技能点
    learned_skills: List[str] = field(default_factory=list)  # 已学会的技能 id
    unlocked_trees: List[str] = field(default_factory=list)  # 背景解锁的特殊技能树 id（如灵能）
    perks: List[str] = field(default_factory=list)  # 开卡时选的 perk id
    hp: int = 0
    stamina: int = 0  # 当前体力，上限由体质和力量推导（stats.stamina_max）
    food: int = 100  # 食物（stats.NEED_MAX 上限），随时间下降
    water: int = 100  # 水源，随时间下降
    # 异常状态列表。体力不足造成的力竭不放在这里，它由体力实时推导（stats.is_exhausted）
    conditions: List[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        # 旧存档只有一个 companion 字段
        old = data.pop("companion", None)
        if old and "companions" not in data:
            data["companions"] = [old]
        data["companions"] = [Companion(**c) for c in data.get("companions", [])]
        data.setdefault("attributes", {})
        data.pop("skill_allocation", None)  # 旧版数值型技能，已废弃
        return cls(**data)


def check_attributes(attributes, rules):
    """检查一份属性分配是否合法，返回错误文字；没问题返回 None。

    控制台和网页版都走这里，规则只有一份。rules 来自 data/character_options.json
    里的 attribute_rules（min / max / total），其中 max 只约束创建角色时的分配，
    后期属性成长不受它限制。
    """
    low, high, total = rules["min"], rules["max"], rules["total"]
    for value in attributes.values():
        if not low <= value <= high:
            return f"每项属性要在 {low}~{high} 之间。"
    remaining = total - sum(attributes.values())
    if remaining > 0:
        return f"还有 {remaining} 点没分配。"
    if remaining < 0:
        return f"点数超了 {-remaining} 点。"
    return None


class CharacterOptions:
    """角色相关的设定数据（属性、背景、预设同伴、各项范围），从 JSON 文件加载。"""

    def __init__(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.limits = data["limits"]
        self.genders = data["genders"]
        self.attribute_rules = data["attribute_rules"]
        self.attributes = data["attributes"]
        self.progression = data["progression"]
        self.backgrounds = data["backgrounds"]
        self.companions = data["companions"]
        self.perks = data.get("perks", [])

    def background(self, background_id):
        return next(b for b in self.backgrounds if b["id"] == background_id)

    def attribute_name(self, attribute_id):
        return next(a["name"] for a in self.attributes if a["id"] == attribute_id)

    def default_attributes(self):
        return {a["id"]: self.attribute_rules["default"] for a in self.attributes}

    def perk(self, perk_id):
        return next(p for p in self.perks if p["id"] == perk_id)

    def perk_cost(self, perk):
        """perk 的花费：写了 cost 就用它；没写时正面 perk（positive）花 1 点，有正有负的（mixed）不花点。"""
        if "cost" in perk:
            return perk["cost"]
        return 1 if perk.get("kind", "positive") == "positive" else 0

    def perk_effect(self, perk_ids, key):
        """几个 perk 的某项效果：数值相加，开关类只要有一个是 True 就算。"""
        values = [self.perk(p).get("effects", {}).get(key) for p in perk_ids]
        values = [v for v in values if v is not None]
        if values and isinstance(values[0], bool):
            return any(values)
        if values and isinstance(values[0], dict):
            return values[0]  # 例如踢击这种“替换攻击方式”的效果
        return sum(values)

    def max_hp(self, character):
        """玩家的生命上限（含顽强这类 perk 的每级加成）。"""
        return stats.max_hp(character.attributes, character.level,
                            self.perk_effect(character.perks, "hp_per_level"))

    def xp_multiplier(self, character):
        """经验倍率 = 智力倍率 × perk 倍率（早熟 −20%），不同来源相乘。"""
        intelligence = Fraction(stats.xp_multiplier(character.attributes)).limit_denominator(100)
        return intelligence * Fraction(100 + self.perk_effect(character.perks, "xp_percent"), 100)

    def companion_limit(self, character):
        """同伴上限：魅力决定；选了“无法携带同伴”的 perk 就是 0。"""
        if self.perk_effect(character.perks, "no_companions"):
            return 0
        return stats.companion_limit(character.attributes) + self.perk_effect(character.perks, "companion_limit_bonus")


def format_sheet(character, options, items, carried_weight=None, tree_names=None, bonuses=None,
                 armor_penalty=0, overweight=False):
    """角色卡：创建完成时确认用，游戏中也可以随时查看。bonuses 是姿态等带来的临时加成。"""
    a = character.attributes
    bonuses = bonuses or {}

    def with_bonus(stat, base, signed=False, unit="%"):
        """数值加上姿态加成，例如：95%（含姿态 +13）。"""
        extra = bonuses.get(stat, 0)
        total = f"{base + extra:g}"
        value = ("+" if signed and base + extra >= 0 else "") + total + unit
        return value + (f"（含姿态 {extra:+g}）" if extra else "")
    background = options.background(character.background)
    hp_max = options.max_hp(character)
    stamina_cap = stats.stamina_max(a)
    stamina_now = character.stamina or stamina_cap
    lines = [
        "======== 角色卡 ========",
        f"{character.name} · {character.gender} · {character.age} 岁 · {character.height} cm",
        f"等级 {character.level}（经验 {character.xp}/{stats.xp_to_next_level(character.level, options)}）"
        f"    生命值 {character.hp or hp_max}/{hp_max}    体力 {stamina_now}/{stamina_cap}"
        f"    食物 {character.food}/{stats.NEED_MAX}    水源 {character.water}/{stats.NEED_MAX}"
        f"    未使用技能点 {character.skill_points}",
        f"样貌：{character.appearance}",
        f"背景：{background['name']}",
        f"  {background['description']}",
    ]
    starting = [items[i]["name"] for i in background.get("starting_items", [])]
    if starting:
        lines.append("  初始物品：" + "、".join(starting))
    if character.unlocked_trees and tree_names:
        lines.append("  解锁技能树：" + "、".join(tree_names[t] for t in character.unlocked_trees))

    if character.perks:
        lines.append("Perk：" + "、".join(options.perk(p)["name"] for p in character.perks))
    limit = options.companion_limit(character)
    if character.companions:
        lines.append(f"同伴（上限 {limit}）：")
        for c in character.companions:
            lines.append(f"  {c.name}（{c.relationship}） · {c.gender} · {c.age} 岁：{c.appearance}")
    else:
        lines.append(f"同伴（上限 {limit}）：无，独自行动")

    lines.append("\n【属性】")
    lines.append("  " + "   ".join(f"{attr['name']} {a[attr['id']]}" for attr in options.attributes))
    lines.append("  检定修正：" + "   ".join(
        f"{attr['name']} +{stats.check_modifier(a, attr['id']):g}" for attr in options.attributes))

    capacity = stats.carry_capacity(a)
    weight = f"{carried_weight:g}/{capacity}" if carried_weight is not None else f"{capacity}"
    lines += [
        "\n【衍生数值】",
        f"  负重 {weight} kg    近战伤害 {with_bonus('melee_damage_bonus', stats.melee_damage_bonus(a), signed=True)}",
        f"  闪避 {with_bonus('dodge', stats.dodge(a), unit='')}    先攻 {stats.initiative(a)}"
        f"    行动点 每回合 {stats.ap_per_turn(a, armor_penalty)}（上限 {stats.ap_cap(a, armor_penalty)}"
        + (f"，重甲 −{stats.armor_ap_percent(armor_penalty)}%" if armor_penalty else "") + "）",
        f"  生命恢复 每 {stats.REGEN_INTERVAL} 回合 +{stats.hp_regen(a)}",
        f"  体力上限 {stamina_cap}"
        f"（移动：每 {stats.INDOOR_STEPS_PER_COST} 步 {stats.move_cost(overweight)} 点体力、"
        f"每格 {stats.OVERWEIGHT_MOVE_AP_COST if overweight else stats.MOVE_AP_COST} 点行动点"
        + ("，超重翻倍" if overweight else "") + "）",
        f"  经验倍率 ×{float(options.xp_multiplier(character)):g}    每级技能点 {stats.skill_points_per_level(a)}",
    ]
    return "\n".join(lines)


class Prompter:
    """带输入检查的提问工具，输入不合法时会重新提问。"""

    def __init__(self, input_fn=input, print_fn=print):
        self.input = input_fn
        self.print = print_fn

    def text(self, prompt, max_length=None, default=None):
        while True:
            value = self.input(prompt).strip()
            if not value and default is not None:
                return default
            if not value:
                self.print("  不能为空，请重新输入。")
            elif max_length and len(value) > max_length:
                self.print(f"  太长了，最多 {max_length} 个字。")
            else:
                return value

    def number(self, prompt, low, high):
        while True:
            value = self.input(prompt).strip()
            if value.isdigit() and low <= int(value) <= high:
                return int(value)
            self.print(f"  请输入 {low} 到 {high} 之间的整数。")

    def choice(self, prompt, labels):
        """列出编号选项，返回玩家选中的下标（从 0 开始）。"""
        for i, label in enumerate(labels, 1):
            self.print(f"  {i}. {label}")
        return self.number(prompt, 1, len(labels)) - 1

    def confirm(self, prompt):
        while True:
            value = self.input(prompt + "（y/n）").strip().lower()
            if value in ("y", "yes", "是", "确认"):
                return True
            if value in ("n", "no", "否", "不"):
                return False
            self.print("  请输入 y 或 n。")

    def perks(self, entries, base, check):
        """选 perk，返回选中的 id 列表。控制台里输编号切换选中 / 取消，输“完成”结束；
        网页版会覆盖成勾选框 + “继续”按钮。check(选择) -> (剩余点数, 错误或 None)。"""
        chosen = []
        self.print("\n【Perk】开卡时可以用 perk 点选择特质。输入编号选中 / 取消，选好后输入“完成”。")
        for i, p in enumerate(entries, 1):
            self.print(f"  {i}. {p['name']}（消耗 {p['cost']} 点）：{p['description']}")
        while True:
            names = "、".join(p["name"] for p in entries if p["id"] in chosen) or "无"
            value = self.input(f"剩余 perk 点 {check(chosen)[0]}，已选：{names}。编号 / 完成：").strip()
            if value in ("完成", "done", ""):
                return chosen
            if not value.isdigit() or not 1 <= int(value) <= len(entries):
                self.print(f"  请输入 1~{len(entries)} 的编号，或者“完成”。")
                continue
            perk_id = entries[int(value) - 1]["id"]
            trial = [p for p in chosen if p != perk_id] if perk_id in chosen else chosen + [perk_id]
            error = check(trial)[1]
            if error:
                self.print("  " + error)
                continue
            chosen = trial

    def attributes(self, attributes, rules, attribute_defs):
        """分配属性，返回分配好的属性字典。

        控制台里逐个输入“编号 数值”；网页版会覆盖这个方法，改用加减号按钮。
        校验统一交给 check_attributes，两个界面规则一致。
        """
        attrs = dict(attributes)
        low, high = rules["min"], rules["max"]
        self.print(f"\n【属性】每项 {low}~{high}，5 是普通人水平。降低某项可以把点数挪给别的属性。")
        while True:
            remaining = rules["total"] - sum(attrs.values())
            self.print(f"\n剩余点数：{remaining}")
            for i, attr in enumerate(attribute_defs, 1):
                self.print(f"  {i}. {attr['name']} {attrs[attr['id']]:>2}   {attr['description']}")
            value = self.input("输入“编号 数值”调整（例如：1 7），分配完输入“完成”：").strip()

            if value in ("完成", "done"):
                error = check_attributes(attrs, rules)
                if error:
                    self.print("  " + error)
                    continue
                return attrs
            parts = value.split()
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                self.print("  格式不对，例如输入：1 7")
                continue
            index, new = int(parts[0]) - 1, int(parts[1])
            if not 0 <= index < len(attribute_defs):
                self.print(f"  编号要在 1~{len(attribute_defs)} 之间。")
                continue
            if not low <= new <= high:
                self.print(f"  每项属性要在 {low}~{high} 之间。")
                continue
            attr_id = attribute_defs[index]["id"]
            needed = new - attrs[attr_id]
            if needed > remaining:
                self.print(f"  点数不够，还差 {needed - remaining} 点。可以先调低别的属性。")
                continue
            attrs[attr_id] = new


class CharacterCreator:
    """一步步引导玩家创建角色，最后确认；不满意可以从头再来。"""

    def __init__(self, options, items, tree_names, prompter=None):
        self.options = options
        self.items = items
        self.tree_names = tree_names  # 技能树 id -> 名字，用来显示背景解锁的技能树
        self.ask = prompter or Prompter()

    def run(self):
        while True:
            character = self._create()
            self.ask.print("\n" + format_sheet(character, self.options, self.items, tree_names=self.tree_names))
            if self.ask.confirm("\n确认使用这个角色吗？"):
                character.hp = self.options.max_hp(character)
                character.stamina = stats.stamina_max(character.attributes)
                return character
            self.ask.print("\n好的，重新创建。")

    def _create(self):
        limits = self.options.limits
        self.ask.print("\n======== 创建角色 ========")
        name = self.ask.text("名字：", max_length=limits["name_max_length"])
        gender = self._gender()
        age = self.ask.number(f"年龄（{limits['age'][0]}~{limits['age'][1]}）：", *limits["age"])
        height = self.ask.number(
            f"身高 cm（{limits['height'][0]}~{limits['height'][1]}）：", *limits["height"]
        )
        self.ask.print("\n【样貌】自由描述你的外貌，比如发型、穿着、特征（直接回车跳过）")
        appearance = self.ask.text("样貌：", max_length=100, default="没什么特别的，扔进人群里就找不到。")
        background = self._background()
        perks = self._perks()
        attributes = self._attributes(self.options.perk_effect(perks, "attribute_points"))
        if self.options.perk_effect(perks, "no_companions"):
            names = "、".join(self.options.perk(p)["name"] for p in perks if self.options.perk(p)["effects"].get("no_companions"))
            self.ask.print(f"\n【同伴】你选择了{names}，不会带同伴。")
            companions = []
        else:
            limit = stats.companion_limit(attributes) + self.options.perk_effect(perks, "companion_limit_bonus")
            picks = 1 + self.options.perk_effect(perks, "extra_starting_companions")  # 受欢迎：开局多带一个
            companions = self._companions(limit, picks)
        character = Character(name, gender, age, height, appearance, background, attributes, companions)
        character.perks = perks
        character.skill_points = self.options.progression["starting_skill_points"]
        character.unlocked_trees = list(self.options.background(background).get("unlocks_trees", []))
        return character

    def _gender(self):
        self.ask.print("\n性别：")
        labels = self.options.genders + ["自定义"]
        index = self.ask.choice("选择编号：", labels)
        if index == len(self.options.genders):
            return self.ask.text("请输入性别：", max_length=8)
        return self.options.genders[index]

    def _background(self):
        self.ask.print("\n【背景故事】末日之前，你是做什么的？")
        labels = []
        for bg in self.options.backgrounds:
            perks = []
            starting = [self.items[i]["name"] for i in bg.get("starting_items", [])]
            if starting:
                perks.append("初始物品：" + "、".join(starting))
            perks += [f"解锁{self.tree_names[t]}技能树" for t in bg.get("unlocks_trees", [])]
            extra = f"（{'；'.join(perks)}）" if perks else ""
            labels.append(f"{bg['name']}{extra}\n     {bg['description']}")
        index = self.ask.choice("选择编号：", labels)
        return self.options.backgrounds[index]["id"]

    def _perks(self):
        """选 perk：可以反复点选 / 取消，perk 点不能变成负数；有的 perk 会给额外的 perk 点。"""
        if not self.options.perks:
            return []
        base = self.options.progression.get("starting_perk_points", 0)
        entries = [{
            "id": p["id"], "name": p["name"], "description": p["description"],
            "cost": self.options.perk_cost(p),
            "perk_points": (p.get("effects") or {}).get("perk_points", 0),
            "conflicts": p.get("conflicts", []),
        } for p in self.options.perks]
        return self.ask.perks(entries, base, self._check_perks)

    def _check_perks(self, selection):
        """检查一组 perk 能不能同时选：返回 (剩余 perk 点, 错误说明或 None)。两个界面共用。"""
        base = self.options.progression.get("starting_perk_points", 0)
        left = (base + self.options.perk_effect(selection, "perk_points")
                - sum(self.options.perk_cost(self.options.perk(p)) for p in selection))
        if len(set(selection)) != len(selection):
            return left, "每个 perk 只能选一次。"
        for p in selection:
            clash = [q for q in selection if q in self.options.perk(p).get("conflicts", [])]
            if clash:
                return left, f"{self.options.perk(p)['name']}和{self.options.perk(clash[0])['name']}冲突，不能同时选。"
        if left < 0:
            return left, "perk 点不够。"
        return left, None

    def _attributes(self, extra_points=0):
        rules = dict(self.options.attribute_rules)
        rules["total"] += extra_points  # perk 可能给额外的可支配属性点
        if extra_points:
            self.ask.print(f"\n（perk 额外给了 {extra_points} 点可支配属性点）")
        return self.ask.attributes(self.options.default_attributes(), rules, self.options.attributes)

    def _companions(self, limit, picks=1):
        """选同伴：一般开局最多带 1 个，受欢迎这类 perk 可以多带；总数不超过同伴上限。"""
        if limit == 0:
            self.ask.print("\n【同伴】你的魅力太低（至少需要 5），没有人愿意跟你一起行动。")
            return []
        picks = min(picks, limit)
        chosen = []
        while len(chosen) < picks:
            left = picks - len(chosen)
            self.ask.print(f"\n【同伴】要带同伴一起行动吗？（还能带 {left} 个，同伴上限：{limit}）")
            presets = [c for c in self.options.companions if c["name"] not in {x.name for x in chosen}]
            labels = ["不带了" if chosen else "不带同伴，独自行动"]
            labels += [f"{c['name']}（{c['relationship']}）：{c['appearance']}" for c in presets]
            labels.append("自定义同伴")
            index = self.ask.choice("选择编号：", labels)
            if index == 0:
                break
            chosen.append(Companion(**presets[index - 1]) if index <= len(presets) else self._custom_companion())
        return chosen

    def _custom_companion(self):
        limits = self.options.limits
        self.ask.print("\n======== 自定义同伴 ========")
        name = self.ask.text("同伴的名字：", max_length=limits["name_max_length"])
        gender = self._gender()
        age = self.ask.number(
            f"同伴的年龄（{limits['companion_age'][0]}~{limits['companion_age'][1]}）：",
            *limits["companion_age"],
        )
        relationship = self.ask.text("TA 和你是什么关系（例如：妹妹、同事、你养的猫）：", max_length=12)
        self.ask.print("\n【同伴样貌】自由描述同伴的外貌（直接回车跳过）")
        appearance = self.ask.text("样貌：", max_length=100, default="没什么特别的。")
        return Companion(name, gender, age, relationship, appearance)
