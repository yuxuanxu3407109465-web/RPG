"""属性与成长规则：由六项属性推导出的各项数值、经验和升级。

属性范围 1~10，5 是普通人水平。想调整平衡，直接改下面的公式。
"""

REGEN_INTERVAL = 10  # 每走多少回合恢复一次生命


# ---------- 衍生数值（参数 a 是属性字典） ----------

def carry_capacity(a):
    """负重上限（kg）。"""
    return 10 + a["strength"] * 4


def melee_damage_bonus(a):
    """近战伤害加成（%），力量 5 为 0。"""
    return (a["strength"] - 5) * 10


def melee_accuracy(a):
    """近战命中率（%）。"""
    return 50 + a["agility"] * 4


def ranged_accuracy(a):
    """远程命中率（%）。"""
    return 50 + a["perception"] * 4


def dodge(a):
    """闪避率（%）。"""
    return a["agility"] * 2 + a["perception"]


def initiative(a):
    """先攻：战斗中谁先行动，数值高的先动。"""
    return a["agility"] + a["perception"]


def max_hp(a, level):
    """生命值上限，每升一级增加等同体质的数值。"""
    return 50 + a["constitution"] * 10 + (level - 1) * a["constitution"]


def hp_regen(a):
    """每 REGEN_INTERVAL 回合恢复的生命值。"""
    return a["constitution"]


def xp_multiplier(a):
    """经验获取倍率，智力 5 为 1.0。"""
    return 1 + (a["intelligence"] - 5) * 0.1


def skill_points_per_level(a):
    """每次升级获得的技能点（暂定）：智力 1~3 得 1 点，4~6 得 2 点，7~9 得 3 点，10 得 4 点。"""
    return 1 + (a["intelligence"] - 1) // 3


def companion_limit(a):
    """最多能带几个同伴。"""
    return a["charisma"] // 3


# ---------- 经验与升级 ----------

def xp_to_next_level(level, options):
    return level * options.progression["xp_per_level"]


def gain_xp(character, amount, options):
    """获得经验（受智力倍率影响），可能连升多级。返回要显示给玩家的文字。"""
    gained = round(amount * xp_multiplier(character.attributes))
    character.xp += gained
    lines = [f"获得 {gained} 点经验。"]
    while character.xp >= xp_to_next_level(character.level, options):
        character.xp -= xp_to_next_level(character.level, options)
        character.level += 1
        points = skill_points_per_level(character.attributes)
        character.skill_points += points
        character.hp = max_hp(character.attributes, character.level)
        lines.append(
            f"★ 升级了！现在是 {character.level} 级，生命值回满，获得 {points} 个技能点。"
        )
    return "\n".join(lines)
