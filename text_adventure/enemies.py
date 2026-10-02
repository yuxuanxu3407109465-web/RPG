"""敌人：按 data/enemies.json 里的模板生成，再按等阶（普通 / 精英 / 首领）加强。

敌人和玩家用同一套战斗公式（精准、闪避、先攻、行动点、生命值、伤害修正都在 stats.py）。
等阶加成见 stats.ENEMY_TIERS：精英的力量、敏捷、体质 +2、生命上限 +20，首领 +4、+40。
模板里的是原始属性（1~10）；等阶加成算 buff，显示成“力量 12（9 + 精英 3）”。

每个僵尸个体的武器、护甲、四肢是否完整都是随机的（模板的 loadout 指向 loadouts 里的一张随机表）：
  weapons  按权重抽一件武器（item 为 null 表示空手，按徒手算）
  armor    每一项独立按 chance（%）判定有没有穿
  limbs    每条胳膊 / 腿独立按 missing_arm / missing_leg（%）判定是否缺失
断了胳膊拿不了武器：两条都在才能用双手武器，只剩一条只能用单手武器，都没了只能撕咬
（模板的 armless_attack；撕咬是劣质武器，poor: true，精准只按属性 × 1 算）。
武器、护甲直接引用物品表（data/items.csv）里的物品，伤害、暴击范围、护甲值都跟玩家用的一样。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import dice as dice_rules
import stats

LIMBS = {"left_arm": "左臂", "right_arm": "右臂", "left_leg": "左腿", "right_leg": "右腿"}


@dataclass
class Enemy:
    template_id: str
    tier: str
    name: str
    level: int
    attributes: dict  # 实际属性（原始 + buff），战斗公式都用它
    max_hp: int
    hp: int
    attack: dict  # {"name", "type", "damage", 可选 "crit_range"}
    armor: int
    description: str
    weapon: str = None  # 拿着的武器（物品 id），空手是 None
    armor_items: list = field(default_factory=list)  # 穿着的护甲（物品 id）
    missing_limbs: list = field(default_factory=list)  # 缺失的肢体（LIMBS 的 key）
    base_attributes: dict = field(default_factory=dict)  # 原始属性（不超过 10）
    buffs: dict = field(default_factory=dict)  # {属性 id: [(来源, 数值), ...]}
    mutations: list = field(default_factory=list)  # 变异 id（僵尸独有的强化）

    @property
    def tier_name(self):
        return stats.ENEMY_TIERS[self.tier][0]

    def accuracy(self):
        base = stats.accuracy(self.attributes, self.attack["type"], self.attack.get("poor", False))
        heavy = stats.HEAVY_ACCURACY if "heavy" in self.attack.get("tags", []) else 0
        return base + self.attack.get("accuracy_bonus", 0) + heavy  # 武器等阶、沉重标签

    def dodge(self):
        return stats.dodge(self.attributes)

    def initiative(self):
        return stats.initiative(self.attributes)

    def ap_per_turn(self):
        return stats.ap_per_turn(self.attributes)

    def crit_range(self):
        return stats.crit_range(self.attack["type"], self.attack)

    def damage_modifiers(self):
        """伤害修正（%），和玩家一样：近战吃力量修正。"""
        mods = []
        if self.attack["type"] in stats.MELEE_WEAPON_TYPES:
            bonus = stats.melee_damage_bonus(self.attributes)
            if bonus:
                mods.append(("力量", bonus, stats.ADD))
        return mods + stats.tag_damage_modifiers(self.attack.get("tags", []))


class EnemyBook:
    """敌人模板和随机装备表，从 JSON 文件加载；启动时检查数据。"""

    def __init__(self, path, attribute_ids, items):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.templates = data["enemies"]
        self.loadouts = data.get("loadouts", {})
        self.mutations = data.get("mutations", {})  # 变异 id -> {name, description, armor ...}
        self.items = items
        for enemy_id, t in self.templates.items():
            where = f"enemies.json 里的敌人 {enemy_id}"
            missing = [a for a in attribute_ids if a not in t.get("attributes", {})]
            if missing:
                raise ValueError(f"{where}：缺少属性 {'、'.join(missing)}")
            for attribute_id, value in t["attributes"].items():
                if not stats.ATTRIBUTE_MIN <= value <= stats.ATTRIBUTE_MAX:
                    raise ValueError(f"{where}：原始属性 {attribute_id} 要在 "
                                     f"{stats.ATTRIBUTE_MIN}~{stats.ATTRIBUTE_MAX} 之间（加成请用等阶 buff）")
            attack = t.get("attack", {})
            if attack.get("type") not in stats.WEAPON_ATTRIBUTES:
                raise ValueError(f"{where}：攻击类型要是 {'、'.join(stats.WEAPON_ATTRIBUTES)} 之一")
            if not dice_rules.DICE_PATTERN.match(attack.get("damage", "")):
                raise ValueError(f"{where}：伤害骰要写成 1d4、1d8 这样的格式")
            armless = t.get("armless_attack")
            if armless and (armless.get("type") not in stats.WEAPON_ATTRIBUTES
                            or not dice_rules.DICE_PATTERN.match(armless.get("damage", ""))):
                raise ValueError(f"{where}：armless_attack 的类型或伤害骰写得不对")
            for entry in t.get("mutations", []):
                if entry["id"] not in self.mutations:
                    raise ValueError(f"{where}：变异 {entry['id']} 不存在")
            if t.get("loadout") and t["loadout"] not in self.loadouts:
                raise ValueError(f"{where}：随机装备表 {t['loadout']} 不存在")
        for loadout_id, table in self.loadouts.items():
            where = f"enemies.json 里的随机装备表 {loadout_id}"
            for entry in table.get("weapons", []):
                if entry["item"] and "weapon" not in items.get(entry["item"], {}):
                    raise ValueError(f"{where}：{entry['item']} 不是物品表里的武器")
            for entry in table.get("armor", []):
                if "armor" not in items.get(entry["item"], {}):
                    raise ValueError(f"{where}：{entry['item']} 不是物品表里的护甲")

    def find(self, name):
        """按名字、别名或 id 找模板，找不到返回 None。"""
        for enemy_id, t in self.templates.items():
            if name in [enemy_id, t["name"]] + t.get("aliases", []):
                return enemy_id
        return None

    def find_mutation(self, name):
        return next((m for m, info in self.mutations.items() if name in (m, info["name"])), None)

    def min_level(self, template_id):
        """这种敌人允许生成的最低等级。"""
        return self.templates[template_id].get("min_level", 1)

    def create(self, template_id, tier, rng, forced_mutations=None, level=None):
        """生成一个敌人：模板属性 + 等阶加成 + 随机的武器、护甲、缺失肢体、变异。
        forced_mutations 给了就用它（测试用），否则按模板的 mutations 概率随机。"""
        t = self.templates[template_id]
        tier_name, physical_bonus, hp_bonus = stats.ENEMY_TIERS[tier]
        base = dict(t["attributes"])
        buffs = {a: [(tier_name, physical_bonus)] for a in stats.PHYSICAL_ATTRIBUTES} if physical_bonus else {}
        attributes = stats.apply_buffs(base, buffs)
        level = max(level or 1, self.min_level(template_id))  # 不能低于这种敌人的最低等级
        max_hp = stats.max_hp(attributes, level) + hp_bonus
        name = t["name"] if tier == "normal" else f"{tier_name}{t['name']}"

        table = self.loadouts.get(t.get("loadout"), {})
        limb_chance = table.get("limbs", {})
        missing = [limb for limb in LIMBS
                   if rng.random() * 100 < limb_chance.get("missing_arm" if "arm" in limb else "missing_leg", 0)]
        arms = sum(1 for limb in ("left_arm", "right_arm") if limb not in missing)

        weapon = self._pick_weapon(table.get("weapons", []), rng)
        if weapon and (2 if stats.hold_type(self.items[weapon]) == "two_hand" else 1) > arms:
            weapon = None  # 胳膊不够，拿不了这件武器
        armor_items = [e["item"] for e in table.get("armor", []) if rng.random() * 100 < e["chance"]]
        armor = sum(stats.armor_value(self.items[i]) for i in armor_items)

        if weapon:
            w = self.items[weapon]["weapon"]
            item = self.items[weapon]
            quality = stats.quality_bonus(item)
            weapon_name = item["name"] if not quality else f"{stats.quality_name(item)} {item['name']}"
            attack = {"name": weapon_name, "type": w["type"], "damage": stats.weapon_damage(item),
                      "accuracy_bonus": quality, "tags": list(w.get("tags", []))}
            if w.get("crit_range"):
                attack["crit_range"] = w["crit_range"]
        else:
            attack = dict(t["attack"])
            if arms == 0 and t.get("armless_attack"):
                attack = dict(t["armless_attack"])  # 两条胳膊都没了：撕咬
        if forced_mutations is None:
            mutations = [e["id"] for e in t.get("mutations", []) if rng.random() * 100 < e["chance"]]
        else:
            mutations = list(forced_mutations)
        armor += sum(self.mutations[m].get("armor", 0) for m in mutations)
        # 变异一律算 buff：属性加成挂在 buffs 上，不改原始属性
        for m in mutations:
            for attribute_id, value in self.mutations[m].get("attributes", {}).items():
                buffs.setdefault(attribute_id, []).append((self.mutations[m]["name"], value))
        attributes = stats.apply_buffs(base, buffs)
        max_hp = stats.max_hp(attributes, level) + hp_bonus
        return Enemy(template_id, tier, name, level, attributes, max_hp, max_hp, attack, armor,
                     t.get("description", ""), weapon, armor_items, missing, base, buffs, mutations)

    @staticmethod
    def _pick_weapon(entries, rng):
        total = sum(e["weight"] for e in entries)
        if not total:
            return None
        roll = rng.random() * total
        for entry in entries:
            roll -= entry["weight"]
            if roll < 0:
                return entry["item"]
        return entries[-1]["item"]


def _attribute_text(enemy, attr):
    """“力量 12（9 + 精英 3）”：实际值，有 buff 时括号里拆开原始属性和各项 buff。"""
    attribute_id = attr["id"]
    text = f"{attr['name']} {enemy.attributes[attribute_id]}"
    buffs = enemy.buffs.get(attribute_id, [])
    if buffs:
        detail = str(enemy.base_attributes[attribute_id])
        for source, value in buffs:
            detail += f" {'+' if value >= 0 else '−'} {source} {abs(value)}"
        text += f"（{detail}）"
    return text


def mutation_text(mutation, enemy):
    """变异描述里的 {体质x3}、{体质检定} 这类占位符，按这只僵尸的实际属性填上数字。"""
    con = enemy.attributes["constitution"]
    return mutation["description"].format(
        体质x3=con * 3,
        体质检定=stats.check_modifier(enemy.attributes, "constitution"),
        盾牌格挡难度=stats.check_modifier(enemy.attributes, "constitution") + 10,
    )


def format_enemy(enemy, options, weapon_types, items, book):
    """敌人资料卡。"""
    a = enemy.attributes
    mods = enemy.damage_modifiers()
    multiplier = stats.damage_multiplier(mods)
    damage = enemy.attack["damage"] + (f" ×{float(multiplier):g}" if multiplier != 1 else "")
    armor = "、".join(f"{items[i]['name']} +{stats.armor_value(items[i])}" for i in enemy.armor_items)
    mutation_armor = [(book.mutations[m]["name"], book.mutations[m].get("armor", 0)) for m in enemy.mutations]
    armor = "、".join(([armor] if armor else []) + [f"{n} +{v}" for n, v in mutation_armor if v])
    lines = [
        f"======== {enemy.name}（{enemy.tier_name}，{enemy.level} 级） ========",
        enemy.description,
        f"生命 {enemy.hp}/{enemy.max_hp}    护甲 {enemy.armor}" + (f"（{armor}）" if armor else ""),
        "属性：" + "   ".join(_attribute_text(enemy, attr) for attr in options.attributes),
        f"攻击：{enemy.attack['name']}（{weapon_types[enemy.attack['type']]}）"
        f"  精准 {enemy.accuracy():g}  伤害 {damage}  暴击 {enemy.crit_range()}",
        f"闪避 {dice_rules.format_number(enemy.dodge())}    先攻 {enemy.initiative()}"
        f"    行动点 每回合 {enemy.ap_per_turn()}（上限 {stats.ap_cap(a)}）",
        "肢体：" + ("缺了" + "、".join(LIMBS[x] for x in enemy.missing_limbs) if enemy.missing_limbs else "完整"),
        "变异：" + ("；".join(f"{book.mutations[m]['name']}（{mutation_text(book.mutations[m], enemy)}）"
                              for m in enemy.mutations) if enemy.mutations else "无"),
    ]
    return "\n".join(line for line in lines if line)
