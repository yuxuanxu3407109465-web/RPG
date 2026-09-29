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


# ---------- 体力与时间 ----------
#
# 体力上限：体质、力量各每点 30（5+5 时正好 300）。属性上限 10 只约束
# 创建角色时的分配，后期属性可以涨过 10，下面这些公式照样适用。

STAMINA_PER_POINT = 30        # 体质 / 力量 每点给的体力上限
STAMINA_MIN_CAP = 180         # 体力上限的下限（体质与力量都只有 3 时）
STAMINA_COST_FLOOR = 0.5      # 行动消耗最多降到一半
STAMINA_LOW_RATIO = 0.1       # 体力低于上限的这个比例就力竭
EXHAUSTED_DAMAGE_PENALTY = -50  # 力竭时攻击力 -50%
MOVE_COST_INDOOR = 2          # 建筑物内走一步的体力
MOVE_COST_OUTDOOR = 10        # 建筑物外走一步的体力
MOVE_MINUTES_INDOOR = 1       # 建筑物内走一步花的时间（分钟）
MOVE_MINUTES_OUTDOOR = 5      # 建筑物外走一步花的时间（分钟）
REST_MINUTES_PER_TICK = 30    # 每休息半小时算一档
REST_RECOVER_RATIO = 0.1      # 每档恢复 10% 上限
SHOCK_WAKE_RATIO = 0.3        # 休克后强制休息到这个比例才醒
START_DAY = 7                 # 游戏从封城第七天开始
START_MINUTES = 14 * 60       # 14:00
MINUTES_PER_DAY = 24 * 60


def stamina_max(a):
    """体力（行动力）上限。"""
    return max(STAMINA_MIN_CAP, STAMINA_PER_POINT * (a["constitution"] + a["strength"]))


def stamina_cost_multiplier(a):
    """每次行动消耗体力的倍率。

    敏捷 5 是基准：低于 5 时每点 +5%（3 点正好 +10%）；高于 5 时每满 5 点
    -10%（7 点不减、10 点 -10%）；最低降到 50%。
    """
    agility = a["agility"]
    if agility < 5:
        multiplier = 1 + 0.05 * (5 - agility)
    else:
        multiplier = 1 - 0.1 * ((agility - 5) // 5)
    return max(STAMINA_COST_FLOOR, multiplier)


def move_cost(a, outdoor):
    """走一个方向要花多少体力。"""
    base = MOVE_COST_OUTDOOR if outdoor else MOVE_COST_INDOOR
    return max(1, int(round(base * stamina_cost_multiplier(a))))


def move_minutes(outdoor):
    """走一个方向要花多少分钟。"""
    return MOVE_MINUTES_OUTDOOR if outdoor else MOVE_MINUTES_INDOOR


def rest_recovery(a, minutes):
    """休息一段时间恢复的体力（每半小时恢复 10% 上限）。"""
    return int(round(stamina_max(a) * REST_RECOVER_RATIO * minutes / REST_MINUTES_PER_TICK))


def is_exhausted(character):
    """体力低于上限的 10% → 力竭（攻击力 -50%），体力恢复后自动解除。"""
    if not character:
        return False
    return character.stamina < stamina_max(character.attributes) * STAMINA_LOW_RATIO


def attack_penalty(character):
    """当前攻击力增减（%）。力竭 -50%，战斗系统接进来时直接用这个值。"""
    return EXHAUSTED_DAMAGE_PENALTY if is_exhausted(character) else 0



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
