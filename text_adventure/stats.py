"""属性与成长规则：由六项属性推导出的各项数值、经验和升级。

属性范围 1~10，5 是普通人水平。想调整平衡，直接改下面的公式。
**所有计算结果一律向下取整**（带小数的倍率先用 Fraction 精确算，再取整，避免浮点误差）。
"""

import math
from fractions import Fraction

REGEN_INTERVAL = 10  # 每走多少回合恢复一次生命


# ---------- 衍生数值（参数 a 是属性字典） ----------

def carry_capacity(a):
    """负重上限（kg）。"""
    return 10 + a["strength"] * 4


def melee_damage_bonus(a):
    """近战伤害加成（%）：力量每比 5 多 1 点 +10%，每少 1 点 −10%（力量 3 为 −20%）。
    适用于所有近战武器（锐器、钝器、武术），不适用于枪械。"""
    return (a["strength"] - 5) * 10


# ---------- 战斗（d20：d20 + 精准 ≥ 闪避 即命中） ----------

AP_PER_AGILITY = 2  # 每回合获得的行动点 = 敏捷 × 2
AP_CAP_MULTIPLIER = 2  # 没用完的行动点留到下回合，最多存到每回合获得量的 2 倍
ATTACK_AP_COST = 6  # 一次普通攻击消耗的行动点
MOVE_AP_COST = 1  # 战斗中每移动一格消耗的行动点
OVERWEIGHT_MOVE_AP_COST = 2  # 超重时移动能力减半：每格 2 点
IMMOBILE_WEIGHT_MULTIPLIER = 2  # 超过负重上限的 2 倍就完全无法移动
USE_ITEM_AP_COST = 3  # 战斗中使用一次物品（例如用绷带包扎）消耗的行动点
UNARMED_DAMAGE = "1d4"  # 徒手伤害骰

# 护甲：每件护甲穿在一个部位，所有部位的护甲值相加，受到的伤害按总值固定减免
ARMOR_CLASSES = {
    "clothing": ("寻常服装", 0, 0),  # 类别 id -> (名字, 护甲值下限, 上限)
    "light": ("轻甲", 1, 3),  # 按部位定：胸甲 3、鞋子 1
    "heavy": ("重甲", 2, 6),  # 会降低每回合的行动点（每件的 ap_penalty）
}
DODGE_MULTIPLIER = 1.5
UNARMED = "unarmed"  # 没拿武器时按徒手（武术）算

# 武器类型 -> 精准取哪项属性：锐器看敏捷、钝器看力量、枪械看感知、武术（徒手）看体质
WEAPON_ATTRIBUTES = {
    "long_blade": "agility",
    "short_blade": "agility",
    "blunt": "strength",
    "firearm": "perception",
    UNARMED: "constitution",
}


# 近战武器：吃力量伤害修正；枪械不吃
MELEE_WEAPON_TYPES = {"long_blade", "short_blade", "blunt", UNARMED}


CRIT_DAMAGE_BONUS = 50  # 暴击额外伤害（%），在其他修正之后结算
# 各类武器的默认暴击范围；单件武器可以在 world.json 里用 crit_range 覆盖
# （例如弯刀、反曲刀这类宽暴击范围的锐器写 "18-20"，基础伤害相应降到 1d6）
CRIT_RANGES = {
    "long_blade": "19-20",
    "short_blade": "19-20",
    "blunt": "20",
    UNARMED: "20",  # 徒手按钝器算
}
DEFAULT_CRIT_RANGE = "20"  # 没列出的类型（例如枪械，尚未设计）


def widen_crit_range(crit_range, multiplier):
    """暴击范围扩大到原来的几倍：18-20（3 个点数）翻倍是 6 个点数 → 15-20；最低到 2（掷出 1 必定落空）。"""
    size = (21 - int(crit_range.split("-")[0])) * multiplier
    low = max(2, 21 - size)
    return "20" if low == 20 else f"{low}-20"


# 武器持握方式（Game.grip_style 返回 id）；技能效果用 grip 限定生效条件
GRIPS = {"unarmed": "徒手", "one_hand": "单手", "dual_wield": "双持", "two_hand": "双手", "shield": "持盾"}

BLOCKS_PER_TURN = 1  # 持盾时每回合默认能格挡几次
SHIELD_BASH_DAMAGE = "1d4"  # 盾击伤害（近战，吃力量修正）


def shield_bash_difficulty(a):
    """盾击时目标体质检定的难度 = 攻击者（力量 + 体质）× 1.5，向下取整。"""
    return math.floor((a["strength"] + a["constitution"]) * Fraction(CHECK_MODIFIER_MULTIPLIER))


def block_modifier(a):
    """格挡修正 =（力量 ÷ 2 + 感知 ÷ 2）× 1.5，每一步都向下取整。"""
    return math.floor((a["strength"] // 2 + a["perception"] // 2) * Fraction(CHECK_MODIFIER_MULTIPLIER))

# 被动技能效果类型（skill_trees.json 里技能的 effects）
PASSIVE_EFFECTS = {
    "crit_range_multiplier": "暴击范围倍数",  # 多个同时生效时相乘
    "armor_ignore": "无视护甲",  # 多个同时生效时相加
    "offhand_attack_ap_percent": "副手追击行动点",
    "extra_blocks": "每回合额外格挡次数",  # 多个同时生效时相加  # 主手攻击后，副手追击的行动点 = 普通攻击 × 这个百分比
}


def crit_range(weapon_type, weapon=None):
    """武器的暴击范围：单件武器写了就用它的，否则按武器类型。"""
    if weapon and weapon.get("crit_range"):
        return weapon["crit_range"]
    return CRIT_RANGES.get(weapon_type, DEFAULT_CRIT_RANGE)


def damage_multiplier(modifiers, crit=False):
    """各来源的修正（%）相乘，例如 +20% 和 +20% 是 ×1.2×1.2 = ×1.44；暴击再 ×1.5。
    用分数计算，避免 7 × 1.2 算成 8.3999999 这类浮点误差影响取整。"""
    multiplier = Fraction(1)
    for percent in modifiers:
        multiplier *= Fraction(100 + percent, 100)
    if crit:
        multiplier *= Fraction(100 + CRIT_DAMAGE_BONUS, 100)
    return multiplier


# 伤害类型：护甲（伤害减免）只对物理伤害生效
DAMAGE_TYPES = {"physical": "物理", "fire": "火焰"}


def final_damage(raw, modifiers, armor, crit=False, damage_type="physical"):
    """最终伤害：骰出的伤害 × 各项修正（相乘）×（暴击 1.5），向下取整，再减护甲，最低为 0。
    护甲只减物理伤害；火焰等其他类型的伤害不受护甲影响。"""
    scaled = math.floor(raw * damage_multiplier(modifiers, crit))
    return max(0, scaled - armor) if damage_type == "physical" else max(0, scaled)


def load_level(weight, capacity):
    """负重状态：normal（正常）、overweight（超过上限）、immobile（超过上限 2 倍，无法移动）。"""
    if weight > capacity * IMMOBILE_WEIGHT_MULTIPLIER:
        return "immobile"
    if weight > capacity:
        return "overweight"
    return "normal"


def move_ap_cost(weight, capacity):
    """战斗中移动一格的行动点；无法移动时返回 None。"""
    level = load_level(weight, capacity)
    if level == "immobile":
        return None
    return OVERWEIGHT_MOVE_AP_COST if level == "overweight" else MOVE_AP_COST


def ap_per_turn(a, armor_penalty=0):
    """每回合获得的行动点 = 敏捷 × 2 − 重甲惩罚。行动点只在战斗中存在，开战第一回合就获得。"""
    return max(0, a["agility"] * AP_PER_AGILITY - armor_penalty)


def ap_cap(a, armor_penalty=0):
    """行动点上限 = 每回合获得量 × 2。"""
    return ap_per_turn(a, armor_penalty) * AP_CAP_MULTIPLIER


def gain_ap(a, current, armor_penalty=0):
    """新回合开始：加上本回合的行动点，超出上限的部分作废。"""
    return min(current + ap_per_turn(a, armor_penalty), ap_cap(a, armor_penalty))


POOR_ACCURACY_MULTIPLIER = 1  # 劣质武器（例如僵尸的撕咬）：精准只按属性 × 1 算


ATTRIBUTE_MAX = 10  # 所有角色的原始属性都不能超过 10；超出的部分只能来自 buff
ATTRIBUTE_MIN = 1


def apply_buffs(base, buffs):
    """实际属性 = 原始属性 + 各项 buff。buffs 是 {属性 id: [(来源, 数值), ...]}。"""
    return {k: v + sum(value for _, value in buffs.get(k, [])) for k, v in base.items()}


def accuracy(a, weapon_type, poor=False):
    """精准 = 所用武器对应的属性 × 1.5，向下取整（和属性修正一样）；劣质武器只 × 1。"""
    attribute = a[WEAPON_ATTRIBUTES[weapon_type]]
    if poor:
        return math.floor(attribute * Fraction(POOR_ACCURACY_MULTIPLIER))
    return check_modifier(a, WEAPON_ATTRIBUTES[weapon_type])


def dodge(a):
    """闪避 =（敏捷 + 感知）× 1.5，向下取整（例如 11 × 1.5 = 16.5 → 16）。"""
    return math.floor((a["agility"] + a["perception"]) * Fraction(DODGE_MULTIPLIER))


def initiative(a):
    """先攻 = 敏捷 + 感知，数值高的先行动。"""
    return a["agility"] + a["perception"]


def max_hp(a, level):
    """生命值上限 = 10 +（体质 ÷ 2）× 等级。"""
    return 10 + (a["constitution"] // 2) * level


def hp_regen(a):
    """每 REGEN_INTERVAL 回合恢复的生命值 = 体质 ÷ 2（向下取整）。"""
    return a["constitution"] // 2


def xp_multiplier(a):
    """经验获取倍率，智力 5 为 1.0。"""
    return 1 + (a["intelligence"] - 5) * 0.1


def skill_points_per_level(a):
    """每次升级获得的技能点（暂定）：智力 1~3 得 1 点，4~6 得 2 点，7~9 得 3 点，10 得 4 点。"""
    return 1 + (a["intelligence"] - 1) // 3


def companion_limit(a):
    """最多能带几个同伴：魅力每比 3 多 2 点多带 1 个（3 → 0、5 → 1、7 → 2、9 → 3）。"""
    return max(0, (a["charisma"] - 3) // 2)


CHECK_MODIFIER_MULTIPLIER = 1.5  # 属性检定的修正值 = 属性值 × 1.5


def check_modifier(a, attribute_id):
    """属性检定修正值 = 属性 × 1.5，向下取整（例如敏捷 7 → 10.5 → 10）。"""
    return math.floor(a[attribute_id] * Fraction(CHECK_MODIFIER_MULTIPLIER))


# ---------- 体力与时间 ----------
#
# 体力上限 = 10 ×（体质 + 力量）。属性带 buff 后可能超过 10，下面这些公式照样适用。

STAMINA_PER_POINT = 10        # 体力上限 = 10 ×（体质 + 力量）
STAMINA_MIN_CAP = 60          # 体力上限的下限（体质与力量都只有 3 时）
STAMINA_COST_FLOOR = 0.5      # 行动消耗最多降到一半
STAMINA_LOW_RATIO = 0.1       # 体力低于上限的这个比例就力竭
EXHAUSTED_DAMAGE_PENALTY = -50  # 力竭时攻击力 -50%
MOVE_COST_INDOOR = 1          # 建筑物内每走 INDOOR_STEPS_PER_COST 步消耗的体力
INDOOR_STEPS_PER_COST = 10    # 建筑物内每 10 步才消耗一次体力
WAIT_MINUTES = 1              # 战斗外原地等待一回合花的时间（分钟）
MOVE_COST_OUTDOOR = 1         # 建筑物外走一步的体力
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


OVERWEIGHT_TRAVEL_MULTIPLIER = 2  # 战斗外超重：走路的体力消耗和时间都翻倍


def move_cost(a, outdoor, overweight=False):
    """扣体力的那一步要花多少体力（室外每步都扣，室内每 10 步扣一次）；超重翻倍。"""
    base = MOVE_COST_OUTDOOR if outdoor else MOVE_COST_INDOOR
    cost = max(1, math.floor(Fraction(base) * Fraction(stamina_cost_multiplier(a)).limit_denominator(100)))
    return cost * OVERWEIGHT_TRAVEL_MULTIPLIER if overweight else cost


def move_minutes(outdoor, overweight=False):
    """走一个方向要花多少分钟；超重翻倍。"""
    minutes = MOVE_MINUTES_OUTDOOR if outdoor else MOVE_MINUTES_INDOOR
    return minutes * OVERWEIGHT_TRAVEL_MULTIPLIER if overweight else minutes


def rest_recovery(a, minutes):
    """休息一段时间恢复的体力（每半小时恢复 10% 上限）。"""
    ratio = Fraction(REST_RECOVER_RATIO).limit_denominator(100)
    return math.floor(stamina_max(a) * ratio * minutes / REST_MINUTES_PER_TICK)


def is_exhausted(character):
    """体力低于上限的 10% → 力竭（攻击力 -50%），体力恢复后自动解除。"""
    if not character:
        return False
    return character.stamina < stamina_max(character.attributes) * STAMINA_LOW_RATIO


def attack_penalty(character):
    """当前攻击力增减（%）。力竭 -50%，战斗系统接进来时直接用这个值。"""
    return EXHAUSTED_DAMAGE_PENALTY if is_exhausted(character) else 0



# ---------- 锐器技能的数值 ----------

BLEED_DAMAGE = 4  # 每层流血每回合的伤害
BLEED_TURNS = 3
BLEED_STACKS_PER_HIT = 2  # 放血一次施加的层数


def blade_armor_ignore(a):
    """放血、卸刃无视的护甲点数 = 4 + 敏捷 ÷ 4。"""
    return 4 + a["agility"] // 4


def bleed_max_stacks(a):
    """流血最多叠几层 = 施加者的敏捷。"""
    return a["agility"]


def sidestep_distance(a):
    """撤步后撤的距离（米）= 4 + 敏捷 ÷ 4。"""
    return 4 + a["agility"] // 4


def psionic_heal(a, level):
    """灵愈的回复量 = 5 +（体质 ÷ 4）× 等级，向下取整。"""
    return 5 + (a["constitution"] // 4) * level


# ---------- 敌人等阶 ----------

PHYSICAL_ATTRIBUTES = ("strength", "agility", "constitution")  # 肉体属性
# 等阶 id -> (名字, 肉体属性加成, 生命上限加成)；属性加成算 buff，不改原始属性
ENEMY_TIERS = {
    "normal": ("普通", 0, 0),
    "elite": ("精英", 2, 20),
    "boss": ("首领", 4, 40),
}


# ---------- 经验与升级 ----------

def xp_to_next_level(level, options):
    return level * options.progression["xp_per_level"]


def gain_xp(character, amount, options):
    """获得经验（受智力倍率影响），可能连升多级。返回要显示给玩家的文字。"""
    gained = math.floor(amount * Fraction(xp_multiplier(character.attributes)).limit_denominator(100))
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
