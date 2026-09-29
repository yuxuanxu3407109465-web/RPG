"""姿态：学会特定技能后可以切换的战斗姿态，同时只能开启一个。

姿态数据在 skill_trees.json 的 stances 里：
  skill        学会哪个技能后可用
  weapon_type  需要手持的武器类型（例如 long_blade）
  modifiers    提供的增益，数值 = base + per_attribute × 技能所属技能树对应的属性
"""

# 姿态可以影响的数值：显示名、单位
STAT_NAMES = {
    "melee_damage_bonus": ("近战伤害", "%"),
    "melee_accuracy": ("近战精准", "%"),
    "dodge": ("闪避", "%"),
}


def available_stances(character, trees):
    """已经学会、可以使用的姿态。"""
    return [s for s in trees.stances if s["skill"] in character.learned_skills]


def find_stance(name, character, trees):
    return next((s for s in available_stances(character, trees) if name in (s["name"], s["id"])), None)


def stance_bonuses(character, stance, trees):
    """姿态提供的增益 {数值 id: 加成}，随对应属性提高。"""
    if not stance:
        return {}
    tree = trees.tree(trees.find_skill(stance["skill"])["tree"])
    attribute = character.attributes[tree["attribute"]] if tree.get("attribute") else 0
    return {m["stat"]: m["base"] + m.get("per_attribute", 0) * attribute for m in stance["modifiers"]}


def format_bonuses(bonuses):
    parts = []
    for stat, value in bonuses.items():
        name, unit = STAT_NAMES[stat]
        parts.append(f"{name} {value:+d}{unit}")
    return "、".join(parts)
