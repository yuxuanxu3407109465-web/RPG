"""姿态：学会特定技能后可以切换的战斗姿态，同时只能开启一个。

姿态数据在 skill_trees.json 的 stances 里：
  skill        学会哪个技能后可用
  weapon_type  需要手持的武器类型（例如 long_blade）
  modifiers    提供的增益，数值 = base + per_attribute × 技能所属技能树对应的属性
"""

# 姿态可以影响的数值：显示名、单位
STAT_NAMES = {
    "melee_damage_bonus": ("近战伤害", "%"),
    "accuracy": ("精准", ""),  # 只加在姿态要求的那类武器上
    "dodge": ("闪避", ""),
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


def describe_granted(character, skill, trees, options):
    """学会 skill 能获得的姿态，每个一行：当前数值（公式）：说明。"""
    tree = trees.tree(skill["tree"])
    attribute_id = tree.get("attribute")
    attribute_name = options.attribute_name(attribute_id) if attribute_id else ""
    lines = []
    for stance in trees.stances:
        if stance["skill"] != skill["id"]:
            continue
        values = stance_bonuses(character, stance, trees)
        parts = []
        for m in stance["modifiers"]:
            name, unit = STAT_NAMES[m["stat"]]
            text = f"{name} {values[m['stat']]:+d}{unit}"
            if m.get("per_attribute") and attribute_name:  # 随属性变化时才附上公式
                text += f"（{m['base']} + {attribute_name}×{m['per_attribute']}）"
            parts.append(text)
        lines.append(f"[{stance['name']}] " + "、".join(parts) + f"：{stance['description']}")
    return lines


def format_bonuses(bonuses):
    parts = []
    for stat, value in bonuses.items():
        name, unit = STAT_NAMES[stat]
        parts.append(f"{name} {value:+d}{unit}")
    return "、".join(parts)
