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


STRENGTH_DAMAGE_PERCENT = 15  # 力量每比 5 多 / 少 1 点，近战伤害 ±15%


def melee_damage_bonus(a, per_point=STRENGTH_DAMAGE_PERCENT, penalty_per_point=STRENGTH_DAMAGE_PERCENT):
    """近战伤害加成（%）：力量每比 5 多 1 点 +15%，每少 1 点 −15%（力量 3 为 −30%）。
    适用于所有近战武器（锐器、钝器、武术），不适用于枪械。
    技能可以分别改加值和惩罚的每点数值（势大力沉：加值每点 20%，惩罚每点 10%）。"""
    diff = a["strength"] - 5
    return diff * (per_point if diff > 0 else penalty_per_point)


# ---------- 战斗（d20：d20 + 精准 ≥ 闪避 即命中） ----------

AP_PER_AGILITY = 2  # 每回合获得的行动点 = 敏捷 × 2
AP_CAP_MULTIPLIER = 2  # 没用完的行动点留到下回合，最多存到每回合获得量的 2 倍
ATTACK_AP_COST = 6  # 一次普通攻击消耗的行动点
MOVE_AP_COST = 1  # 战斗中每移动一格消耗的行动点
OVERWEIGHT_MOVE_AP_COST = 2  # 超重时移动能力减半：每格 2 点
IMMOBILE_WEIGHT_MULTIPLIER = 2  # 超过负重上限的 2 倍就完全无法移动
USE_ITEM_AP_COST = 3  # 使用一次物品（例如用绷带包扎）消耗的行动点
PICKUP_AP_COST = 1  # 拾取（搜刮）一件东西
HOLD_AP_COST = 1  # 拿起 / 收起 / 换手武器、盾牌这类手持物
ARMOR_AP_COST = 6  # 穿上 / 脱下一件护甲
GEAR_AP_COST = 1  # 背包、饰品、披风的穿脱（暂定，和手持物一样）
BAG_AP_COST = 1  # 背包里其余会实际改变物品的操作（例如放下 / 丢弃），暂定；查看、拆分、堆叠这类不改变物品的不花
# 一堆同种物品最多摞多少个。只有物品数据里带 stack 词条的才摞得起来，
# 别的物品一格一件、也不能拆分（见 engine.py 的背包部分）。
STACK_MAX = 5
UNARMED_DAMAGE = "1d2"  # 徒手伤害骰

# 护甲：每件护甲穿在一个部位，所有部位的护甲值相加，受到的伤害按总值固定减免
ARMOR_CLASSES = {
    "clothing": ("寻常服装", 0, 0),  # 类别 id -> (名字, 护甲值下限, 上限)
    "light": ("轻甲", 1, 3),  # 按部位定：胸甲 3、鞋子 1
    "heavy": ("重甲", 2, 6),  # 会降低每回合的行动点（每件的 ap_penalty，每点 −5%）
}
DODGE_MULTIPLIER = 1.5
UNARMED = "unarmed"  # 没拿武器时按徒手（武术）算
MELEE_RANGE = 1  # 近战武器默认射程（格）；踢击这类特殊攻击可以更远

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


CRIT_DAMAGE_BONUS = 50  # 暴击额外伤害（%），在其他修正之后结算；“要害”标签的武器是 80

# 武器标签：一件武器的具体特性由它带的标签决定（world.json 里武器的 "tags"）
WEAPON_TAGS = {
    "reach": ("长柄", "攻击范围 1 → 2 格"),
    "armor_piercing": ("破甲", "无视 2 点护甲"),
    "deadly": ("要害", "暴击增伤 50% → 80%"),
    "sharp": ("锋利", "伤害 +15%"),
    "backstab": ("背刺", "偷袭时伤害 +200%"),
    "bleed": ("流血", "命中时给目标施加 1 层流血"),
    "parry": ("招架", "闪避 +1"),
    "heavy": ("沉重", "精准 −6，伤害 +60%"),
}
REACH_RANGE = 2
TAG_ARMOR_IGNORE = 2
DEADLY_CRIT_DAMAGE_BONUS = 80
SHARP_DAMAGE_PERCENT = 15
BACKSTAB_DAMAGE_PERCENT = 200
PARRY_DODGE = 1
HEAVY_ACCURACY = -6
HEAVY_DAMAGE_PERCENT = 60


# 伤害修正分两类：每一项写成 (来源, 百分比, 类别)
#   加算（ADD）：力量、武器标签（锋利、沉重、背刺）、技能（姿态、暗袭……）——这些百分比先相加
#   乘算（MUL）：perk（绝境……）、状态（力竭）——各自单独相乘
# 暴击另外再乘（damage_multiplier 的 crit）。
ADD = "add"
MUL = "mul"


def tag_damage_modifiers(tags, sneak=False):
    """武器标签带来的伤害修正：锋利、沉重，偷袭时再加背刺（都是加算）。"""
    mods = []
    if "sharp" in tags:
        mods.append(("锋利", SHARP_DAMAGE_PERCENT, ADD))
    if "heavy" in tags:
        mods.append(("沉重", HEAVY_DAMAGE_PERCENT, ADD))
    if sneak and "backstab" in tags:
        mods.append(("背刺", BACKSTAB_DAMAGE_PERCENT, ADD))
    return mods


def modifier_text(modifiers):
    """把修正写成说明文字，例如 “+45%（力量 +30%、锋利 +15%）×1.3（绝境 +30%）”。"""
    parts = []
    adds = [(n, v) for n, v, kind in modifiers if kind == ADD]
    if adds:
        total = sum(v for _, v in adds)
        parts.append(f"{total:+d}%（" + "、".join(f"{n} {v:+d}%" for n, v in adds) + "）")
    for n, v, kind in modifiers:
        if kind == MUL:
            parts.append(f"×{float(Fraction(100 + v, 100)):g}（{n} {v:+d}%）")
    return " ".join(parts)


def crit_damage_bonus(tags):
    return DEADLY_CRIT_DAMAGE_BONUS if "deadly" in tags else CRIT_DAMAGE_BONUS
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


# 手持物（武器、盾牌……）的类别：
#   one_hand  单手：主手、副手都能拿
#   two_hand  双手：只能拿在主手，并且强制占掉副手（副手原来的东西会被卸下）
#   main_hand 主手：只能拿在主手
#   off_hand  副手：只能拿在副手
# 主手 / 副手类只有在数据里明确写了 hold 才算；没写的武器、盾牌一律按单手。
HOLD_TYPES = {"one_hand": "单手", "two_hand": "双手", "main_hand": "主手", "off_hand": "副手"}


def hold_type(item):
    """手持物的类别：数据里写了 hold 就用它；没写的武器、盾牌一律按单手。不是手持物返回 None。"""
    if item.get("hold"):
        return item["hold"]
    if item.get("weapon"):
        return "two_hand" if item["weapon"].get("hands") == 2 else "one_hand"
    if "shield" in item:
        return "one_hand"
    return None


def hold_slots(item):
    """这件手持物能放进哪些手的位置。"""
    return {"one_hand": ["main_hand", "off_hand"], "two_hand": ["main_hand"],
            "main_hand": ["main_hand"], "off_hand": ["off_hand"]}.get(hold_type(item), [])


# 武器持握方式（Game.grip_style 返回 id）；技能效果用 grip 限定生效条件
GRIPS = {"unarmed": "徒手", "one_hand": "单手", "dual_wield": "双持", "two_hand": "双手", "shield": "持盾"}

BLOCKS_PER_TURN = 1  # 持盾时每回合默认能格挡几次
SHIELD_BASH_DAMAGE = "1d4"  # 盾击伤害（近战，吃力量修正）


def shield_bash_difficulty(a):
    """盾击时目标体质检定的难度 = 攻击者 体质 × 1.5（向下取整）+ 力量（和格挡修正同一个公式）。"""
    return block_modifier(a)


def block_modifier(a):
    """格挡修正 = 体质 × 1.5（向下取整）+ 力量。"""
    return check_modifier(a, "constitution") + a["strength"]

# 被动技能效果类型（skill_trees.json 里技能的 effects）
PASSIVE_EFFECTS = {
    "crit_range_multiplier": "暴击范围倍数",  # 多个同时生效时相乘
    "armor_ignore": "无视护甲",  # 多个同时生效时相加
    "offhand_attack_ap_percent": "副手追击行动点",
    "extra_blocks": "每回合额外格挡次数",  # 多个同时生效时相加
    "strength_damage_percent": "每点力量的伤害加值",  # 取最高的那个
    "strength_penalty_percent": "力量低于 5 时每点的伤害惩罚",  # 取最低的那个  # 主手攻击后，副手追击的行动点 = 普通攻击 × 这个百分比
}


# 装备等阶：以“普通”为基准，每高一阶 +1、每低一阶 −1
#   护甲：护甲值 ±1；武器：精准 ±1、伤害 ±1（例如精良开山刀 1d8+1，破旧开山刀 1d8-1）
QUALITIES = {"worn": ("破旧", -1), "normal": ("普通", 0), "fine": ("精良", 1), "legendary": ("传说", 2)}


def quality_name(item):
    return QUALITIES[item.get("quality", "normal")][0]


def quality_bonus(item):
    """装备等阶带来的加减值（普通 0、精良 +1、传说 +2、破旧 −1）。"""
    return QUALITIES[item.get("quality", "normal")][1]


# 武器伤害分档（写数据时参考，按武器本身的形制定）：
#   1d4   匕首
#   1d6   高暴击范围的单手武器、双手长柄武器
#   1d8   寻常单手武器
#   1d10  寻常双手武器
# 代用武器：本质是工具、不适合当武器用的东西（撬棍、手电筒、水果刀、擀面杖……），
# 武器数据写 "improvised": true，最终伤害比所写的档位低一档（撬棍 1d10 → 1d8）。
DAMAGE_TIERS = ("1d2", "1d4", "1d6", "1d8", "1d10")


def tier_down(damage):
    """伤害降一档：1d10 → 1d8 → 1d6 → 1d4 → 1d2（最低 1d2）。"""
    index = DAMAGE_TIERS.index(damage)
    return DAMAGE_TIERS[max(0, index - 1)]


def weapon_damage(item):
    """武器的实际伤害骰：代用武器先降一档，再加等阶的固定加减（"1d8" + 精良 → "1d8+1"）。"""
    damage = item["weapon"]["damage"]
    if item["weapon"].get("improvised"):
        damage = tier_down(damage)
    bonus = quality_bonus(item)
    if not bonus:
        return damage
    base, _, flat = damage.replace("-", "+-").partition("+")
    total = (int(flat) if flat else 0) + bonus
    return base if total == 0 else f"{base}{total:+d}"


def armor_value(item):
    """护甲实际提供的护甲值 = 基础值 + 等阶加成，最低 0。"""
    armor = item["armor"]
    return max(0, armor["value"] + QUALITIES[item.get("quality", "normal")][1])


def sight_range_with(a, penalty=0):
    """视野范围（格）减去装备带来的惩罚，最低 0。"""
    return max(0, sight_range(a) - penalty)


def crit_range(weapon_type, weapon=None):
    """武器的暴击范围：单件武器写了就用它的，否则按武器类型。"""
    if weapon and weapon.get("crit_range"):
        return weapon["crit_range"]
    return CRIT_RANGES.get(weapon_type, DEFAULT_CRIT_RANGE)


def damage_multiplier(modifiers, crit=False, crit_bonus=None):
    """总伤害倍率：加算类先相加（力量 +30%、锋利 +15% → ×1.45），乘算类各自相乘（绝境 ×1.3），
    暴击再乘（×1.5，要害 ×1.8）。modifiers 是 [(来源, 百分比, ADD/MUL)]。
    用分数计算，避免 7 × 1.2 算成 8.3999999 这类浮点误差影响取整。"""
    multiplier = Fraction(100 + sum(v for _, v, kind in modifiers if kind == ADD), 100)
    for _, percent, kind in modifiers:
        if kind == MUL:
            multiplier *= Fraction(100 + percent, 100)
    if crit:
        multiplier *= Fraction(100 + (CRIT_DAMAGE_BONUS if crit_bonus is None else crit_bonus), 100)
    return multiplier


# 伤害类型：护甲（伤害减免）只对物理伤害生效
DAMAGE_TYPES = {"physical": "物理", "fire": "火焰", "bleed": "流血", "acid": "强酸"}


def final_damage(raw, modifiers, armor, crit=False, damage_type="physical", crit_bonus=None):
    """最终伤害：骰出的伤害 × 修正（加算 / 乘算）×（暴击 1.5，要害 1.8），向下取整，再减护甲，最低为 0。
    护甲只减物理伤害；火焰等其他类型的伤害不受护甲影响。"""
    scaled = math.floor(raw * damage_multiplier(modifiers, crit, crit_bonus))
    return max(0, scaled - armor) if damage_type == "physical" else max(0, scaled)


def load_level(weight, capacity):
    """负重状态：normal（正常）、overweight（超过上限）、immobile（超过上限 2 倍，无法移动）。"""
    if weight > capacity * IMMOBILE_WEIGHT_MULTIPLIER:
        return "immobile"
    if weight > capacity:
        return "overweight"
    return "normal"


# 负重占上限的比例：不超过 30% 是轻载，30~70% 是中载，70~100% 是重载
LOAD_RATIO_LIGHT = 30
LOAD_RATIO_MEDIUM = 70


def load_label(weight, capacity):
    """负重状态的中文说法，给界面显示用：轻载 / 中载 / 重载（超过上限才额外说超重）。"""
    if capacity <= 0:
        return "轻载"
    ratio = weight / capacity * 100
    if ratio > 100 * IMMOBILE_WEIGHT_MULTIPLIER:
        return "严重超重"
    if ratio > 100:
        return "超重"
    if ratio > LOAD_RATIO_MEDIUM:
        return "重载"
    if ratio > LOAD_RATIO_LIGHT:
        return "中载"
    return "轻载"


def is_stackable(item):
    """这件物品能不能摞成一堆（物品数据里写了 stack 词条才行）。"""
    return bool(item.get("stack"))


def stack_max(item):
    """一堆最多几个：带 stack 词条的按 STACK_MAX，别的一格一件。"""
    if not is_stackable(item):
        return 1
    value = item.get("stack")
    if isinstance(value, int) and not isinstance(value, bool):
        return max(1, value)
    return STACK_MAX


def move_ap_cost(weight, capacity):
    """移动一格的行动点；无法移动时返回 None。"""
    level = load_level(weight, capacity)
    if level == "immobile":
        return None
    return OVERWEIGHT_MOVE_AP_COST if level == "overweight" else MOVE_AP_COST


ARMOR_AP_PERCENT_PER_POINT = 5  # 重甲的 ap_penalty 每 1 点 = 每回合行动点 −5%（胸甲 3 点 → −15%）


def armor_ap_percent(armor_penalty):
    """重甲让每回合行动点减少的百分比（各件的 ap_penalty 相加 × 5%）。"""
    return armor_penalty * ARMOR_AP_PERCENT_PER_POINT


def ap_per_turn(a, armor_penalty=0):
    """每回合获得的行动点 = 敏捷 × 2 ×（1 − 重甲减少的百分比），向下取整，最少 1 点（不会扣到 0）。
    不分战斗内外：每回合（1 分钟）开始时获得。"""
    base = a["agility"] * AP_PER_AGILITY
    if not armor_penalty:
        return base
    return max(min(1, base), base * max(0, 100 - armor_ap_percent(armor_penalty)) // 100)


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
    """先攻值 =（敏捷 + 感知）× 1.5，向下取整。战斗开始时掷先攻检定：1d20 + 先攻值，高的先行动。"""
    return math.floor((a["agility"] + a["perception"]) * Fraction(CHECK_MODIFIER_MULTIPLIER))


def max_hp(a, level, bonus_per_level=0):
    """生命值上限 = 10 +（体质 ÷ 2 + 每级额外加成）× 等级（顽强：每级额外 +2）。"""
    return 10 + (a["constitution"] // 2 + bonus_per_level) * level


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
STAMINA_LOW_RATIO = 0.1       # 体力低于上限的这个比例就力竭
EXHAUSTED_DAMAGE_PENALTY = -50  # 力竭时攻击力 -50%
MOVE_COST = 1                 # 每走 INDOOR_STEPS_PER_COST 步消耗的体力（室内外一样）
INDOOR_STEPS_PER_COST = 10    # 每 10 步才消耗一次体力
WAIT_MINUTES = 1              # 战斗外原地等待一回合花的时间（分钟）
MOVE_MINUTES = 1              # （已不用：时间改为按回合走，走路只花行动点）
REST_MINUTES_PER_TICK = 30    # 每休息半小时算一档
REST_RECOVER_RATIO = 0.1      # 每档恢复 10% 上限
SHOCK_WAKE_RATIO = 0.3        # 休克后强制休息到这个比例才醒
START_DAY = 7                 # 游戏从封城第七天开始
START_MINUTES = 14 * 60       # 14:00
MINUTES_PER_DAY = 24 * 60


def stamina_max(a):
    """体力（行动力）上限。"""
    return max(STAMINA_MIN_CAP, STAMINA_PER_POINT * (a["constitution"] + a["strength"]))


OVERWEIGHT_TRAVEL_MULTIPLIER = 2  # 战斗外超重：走路的体力消耗和时间都翻倍


def move_cost(overweight=False):
    """走一步的体力消耗：室内外一样，每 INDOOR_STEPS_PER_COST 步扣一次；超重翻倍。
    饥饿 / 口渴的倍率在 Game._pay_move 里按分数再乘（不同来源相乘）。"""
    cost = max(1, MOVE_COST)
    if overweight:
        cost *= OVERWEIGHT_TRAVEL_MULTIPLIER
    return cost


# ---------- 死亡 ----------

DEATH_CAUSES = {
    "hunger": "饥饿",
    "thirst": "口渴",
    "zombie": "死于僵尸",
    "raider": "死于掠夺者",
    "sickness": "生病",
    "bleeding": "失血过多",
}


# ---------- 食物与水源 ----------

NEED_MAX = 100  # 食物、水源的上限，新角色满值开局
FOOD_MINUTES_PER_POINT = 30  # 食物每 30 分钟 −1（每小时 −2）
WATER_MINUTES_PER_POINT = 15  # 水源每 15 分钟 −1（每小时 −4）
# 降到上限的这些百分比及以下，进入对应等级（1 / 2 / 3）
NEED_STAGE_THRESHOLDS = (50, 30, 10)
NEED_STAGE_NAMES = {
    "food": ("有点饿", "饥饿", "饿死了！"),
    "water": ("有点渴", "口渴", "渴死了！"),
}
NEED_STAGE_STAMINA_PERCENT = (25, 50, 50)  # 各等级体力消耗增加的百分比
NEED_STARVING_HP_PER_TURN = 1  # 最高等级时每回合掉血


def need_stage(value, maximum=NEED_MAX):
    """食物 / 水源的等级：0 正常，1 有点饿 / 渴（≤50%），2 饥饿 / 口渴（≤30%），3 饿 / 渴死了（≤10%）。"""
    stage = 0
    for i, threshold in enumerate(NEED_STAGE_THRESHOLDS, 1):
        if value * 100 <= maximum * threshold:
            stage = i
    return stage


def need_stamina_multiplier(stage):
    """某个等级的体力消耗倍率（分数）。"""
    if not stage:
        return Fraction(1)
    return Fraction(100 + NEED_STAGE_STAMINA_PERCENT[stage - 1], 100)


def move_minutes(overweight=False):
    """走一步要花多少分钟（室内外一样）；超重翻倍。"""
    minutes = MOVE_MINUTES
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

LAST_STAND_HP_PERCENT = 30  # 绝境（perk）：生命不高于上限的 30% 时……
LAST_STAND_BONUS = 3  # ……闪避、精准 +3
LAST_STAND_DAMAGE_PERCENT = 30  # ……伤害 +30%

BLEED_DAMAGE = 4  # 每层流血在目标回合开始时的伤害（流血伤害，不受护甲减免）
BLEED_TURNS = 3
BLEED_STACKS_PER_HIT = 2  # 放血一次施加的层数


DOT_STACK_DAMAGE_PERCENT = 15  # 剜创：目标身上每层持续伤害，伤害 +15%


def riposte_per_turn(a):
    """反刃每回合能触发几次 = 敏捷 ÷ 4。"""
    return a["agility"] // 4


def blade_armor_ignore(a):
    """卸刃无视的护甲点数 = 4 + 敏捷 ÷ 4。"""
    return 4 + a["agility"] // 4


DOT_MAX_STACKS = 5  # 持续伤害最多叠 5 层（流血、灼烧……）
DOT_OVERFLOW_PERCENT = 50  # 满层时再叠一层：最老的那层把剩下的伤害按 50% 立刻结算，然后被顶替


def bleed_max_stacks(a=None):
    """流血最多叠几层：统一 5 层（以前是施加者的敏捷）。"""
    return DOT_MAX_STACKS


def dot_overflow_damage(damage_per_turn, turns_left):
    """满层后再叠一层时，最老那层立刻结算的伤害 = 每回合伤害 × 剩余回合 × 50%，向下取整。
    例：每回合 4 点、还剩 2 回合的流血 → 4 × 2 × 50% = 4。"""
    return damage_per_turn * turns_left * DOT_OVERFLOW_PERCENT // 100


def disarm_difficulty(a):
    """缴械：目标用 敏捷 × 1.5 做检定，难度 =（攻击者力量 + 敏捷）× 1.5，向下取整。"""
    return math.floor((a["strength"] + a["agility"]) * Fraction(CHECK_MODIFIER_MULTIPLIER))


def sidestep_distance(a):
    """撤步后撤的距离（格）= 4 + 敏捷 ÷ 4。"""
    return 4 + a["agility"] // 4


# ---------- 潜行 ----------

SNEAK_ATTACK_DAMAGE_PERCENT = 100  # 暗袭：偷袭时伤害 +100%（伤害增益之后、暴击之前结算）
STEALTH_RANGE_REDUCTION = 2  # 潜踪：目标的听觉范围和警觉范围各减 2 格


def sneak_attack_accuracy_bonus(a):
    """暗袭：偷袭时命中加值 =（敏捷 + 感知）÷ 2，向下取整。"""
    return (a["agility"] + a["perception"]) // 2


# ---------- 射程 ----------

# 各类枪械的原始射程（格，暂定）；枪械的其余设计暂缓
BLADE_TYPES = ("long_blade", "short_blade")  # 重刃、轻刃（刀锋舞者把它们互相视为对方）

FIREARM_BASE_RANGES = {
    "shotgun": ("霰弹枪", 2),
    "pistol": ("手枪", 6),
    "assault_rifle": ("突击步枪", 6),
    "sniper_rifle": ("狙击枪", 10),
}


def ranged_attack_range(a, base_range):
    """远程武器的攻击范围（格）= 武器原始射程 + 感知 ÷ 4（向下取整）。"""
    return base_range + a["perception"] // 4


def sight_range(a):
    """角色的视野范围（格）= 4 + 感知。"""
    return 4 + a["perception"]


def effective_ranged_range(a, base_range):
    """实际能打多远：射程不能超过视野（以后可能加瞄准 / 侦察来突破）。"""
    return min(ranged_attack_range(a, base_range), sight_range(a))


def incinerate_range(a):
    """焚化的施放范围（格）= 4 + 感知。"""
    return 4 + a["perception"]


def psionic_bolt_damage(level):
    """焚化（灵能·塑能系）的火焰伤害 = 6 + 等级。"""
    return 6 + level


def psionic_heal(a, level):
    """再生（灵能·生物系）的回复量 = 5 +（体质 ÷ 4）× 等级，向下取整。"""
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
    gained = math.floor(amount * options.xp_multiplier(character))
    character.xp += gained
    lines = [f"获得 {gained} 点经验。"]
    while character.xp >= xp_to_next_level(character.level, options):
        character.xp -= xp_to_next_level(character.level, options)
        character.level += 1
        points = skill_points_per_level(character.attributes)
        character.skill_points += points
        character.hp = options.max_hp(character)
        lines.append(
            f"★ 升级了！现在是 {character.level} 级，生命值回满，获得 {points} 个技能点。"
        )
    return "\n".join(lines)
