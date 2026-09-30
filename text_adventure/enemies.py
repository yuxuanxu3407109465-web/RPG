"""敌人：按 data/enemies.json 里的模板生成，再按等阶（普通 / 精英 / 首领）加强。

敌人和玩家用同一套战斗公式（精准、闪避、先攻、行动点、生命值、伤害修正都在 stats.py）。
等阶加成见 stats.ENEMY_TIERS：精英的力量、敏捷、体质 +3、生命上限 +20，首领 +6、+40；
加成可以把属性推到 10 以上。
"""

import json
from dataclasses import dataclass
from pathlib import Path

import dice as dice_rules
import stats


@dataclass
class Enemy:
    template_id: str
    tier: str
    name: str
    level: int
    attributes: dict
    max_hp: int
    hp: int
    attack: dict  # {"name", "type", "damage", 可选 "crit_range"}
    armor: int
    description: str

    @property
    def tier_name(self):
        return stats.ENEMY_TIERS[self.tier][0]

    def accuracy(self):
        return stats.accuracy(self.attributes, self.attack["type"])

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
        if self.attack["type"] in stats.MELEE_WEAPON_TYPES:
            bonus = stats.melee_damage_bonus(self.attributes)
            return [("力量", bonus)] if bonus else []
        return []


class EnemyBook:
    """敌人模板，从 JSON 文件加载；启动时检查数据。"""

    def __init__(self, path, attribute_ids):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.templates = data["enemies"]
        for enemy_id, t in self.templates.items():
            where = f"enemies.json 里的敌人 {enemy_id}"
            missing = [a for a in attribute_ids if a not in t.get("attributes", {})]
            if missing:
                raise ValueError(f"{where}：缺少属性 {'、'.join(missing)}")
            attack = t.get("attack", {})
            if attack.get("type") not in stats.WEAPON_ATTRIBUTES:
                raise ValueError(f"{where}：攻击类型要是 {'、'.join(stats.WEAPON_ATTRIBUTES)} 之一")
            if not dice_rules.DICE_PATTERN.match(attack.get("damage", "")):
                raise ValueError(f"{where}：伤害骰要写成 1d4、1d8 这样的格式")

    def find(self, name):
        """按名字、别名或 id 找模板，找不到返回 None。"""
        for enemy_id, t in self.templates.items():
            if name in [enemy_id, t["name"]] + t.get("aliases", []):
                return enemy_id
        return None

    def create(self, template_id, tier="normal"):
        """生成一个敌人：模板属性 + 等阶加成，生命值 = 玩家同款公式 + 等阶加成。"""
        t = self.templates[template_id]
        tier_name, physical_bonus, hp_bonus = stats.ENEMY_TIERS[tier]
        attributes = dict(t["attributes"])
        for attribute_id in stats.PHYSICAL_ATTRIBUTES:
            attributes[attribute_id] += physical_bonus
        level = t.get("level", 1)
        max_hp = stats.max_hp(attributes, level) + hp_bonus
        name = t["name"] if tier == "normal" else f"{tier_name}{t['name']}"
        return Enemy(template_id, tier, name, level, attributes, max_hp, max_hp,
                     dict(t["attack"]), t.get("armor", 0), t.get("description", ""))


def format_enemy(enemy, options, weapon_types):
    """敌人资料卡。"""
    a = enemy.attributes
    mods = enemy.damage_modifiers()
    multiplier = stats.damage_multiplier([value for _, value in mods])
    damage = enemy.attack["damage"] + (f" ×{float(multiplier):g}" if multiplier != 1 else "")
    lines = [
        f"======== {enemy.name}（{enemy.tier_name}，{enemy.level} 级） ========",
        enemy.description,
        f"生命 {enemy.hp}/{enemy.max_hp}    护甲 {enemy.armor}",
        "属性：" + "   ".join(f"{attr['name']} {a[attr['id']]}" for attr in options.attributes),
        f"攻击：{enemy.attack['name']}（{weapon_types[enemy.attack['type']]}）"
        f"  精准 {enemy.accuracy():g}  伤害 {damage}  暴击 {enemy.crit_range()}",
        f"闪避 {dice_rules.format_number(enemy.dodge())}    先攻 {enemy.initiative()}"
        f"    行动点 每回合 {enemy.ap_per_turn()}（上限 {stats.ap_cap(a)}）",
    ]
    return "\n".join(line for line in lines if line)
