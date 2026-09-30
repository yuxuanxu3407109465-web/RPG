"""抛骰系统：掷任意骰子（如 2d6+1），以及统一用 d20 的攻击判定和属性检定。

攻击：d20 + 精准 ≥ 闪避 即命中；命中且落在武器暴击范围内时再掷一次确认暴击。
检定：d20 + 属性修正（属性值 × 1.5）≥ 难度 即成功。
攻击和检定统一标准：大于等于就算成功。
两者都是掷出 20 必定成功、掷出 1 必定失败。
"""

import random
import re
from dataclasses import dataclass

DICE_PATTERN = re.compile(r"^(\d*)d(\d+)([+-]\d+)?$")
CRIT_RANGE_PATTERN = re.compile(r"^(\d+)(?:-20)?$")  # 暴击范围："19-20" 或 "20"


@dataclass
class Roll:
    expression: str
    rolls: list
    modifier: int

    @property
    def total(self):
        return sum(self.rolls) + self.modifier

    def describe(self):
        text = f"🎲 {self.expression}：" + " + ".join(str(r) for r in self.rolls)
        if self.modifier:
            text += f" {'+' if self.modifier > 0 else '-'} {abs(self.modifier)}"
        if len(self.rolls) > 1 or self.modifier:
            text += f" = {self.total}"
        return text


@dataclass
class CheckResult:
    success: bool
    critical: bool  # 掷出 20 或 1
    text: str  # 给玩家看的掷骰过程


@dataclass
class AttackResult:
    hit: bool
    crit: bool  # 暴击已确认
    text: str  # 给玩家看的掷骰过程（可能有两行：命中 + 暴击确认）
    total: float = 0  # 第一次命中判定的 d20 + 精准（格挡要和它比）


def crit_min(crit_range):
    """"19-20" -> 19，"20" -> 20。"""
    return int(CRIT_RANGE_PATTERN.match(crit_range).group(1))


def format_number(value):
    """16.0 显示成 16，小数照原样显示（数值本身已经在 stats 里取过整）。"""
    return f"{value:g}"


class Dice:
    def __init__(self, rng=None):
        self.rng = rng or random.Random()

    def roll(self, expression):
        """掷骰，例如 "1d20"、"2d6+1"、"d100"。格式不对时返回 None。"""
        expression = expression.strip().lower().replace(" ", "")
        match = DICE_PATTERN.match(expression)
        if not match:
            return None
        count = int(match.group(1) or 1)
        sides = int(match.group(2))
        modifier = int(match.group(3) or 0)
        if not (1 <= count <= 100 and 2 <= sides <= 1000):
            return None
        rolls = [self.rng.randint(1, sides) for _ in range(count)]
        return Roll(expression, rolls, modifier)

    def check(self, modifier, difficulty, label="修正"):
        """属性检定：d20 + 修正 ≥ 难度 即成功；掷出 20 必定成功，掷出 1 必定失败。"""
        value = self.rng.randint(1, 20)
        if value == 20:
            return CheckResult(True, True, "🎲 d20 = 20 → 必定成功")
        if value == 1:
            return CheckResult(False, True, "🎲 d20 = 1 → 必定失败")
        total = value + modifier
        success = total >= difficulty
        sign = "≥" if success else "<"
        text = (f"🎲 d20 = {value} + {label} {format_number(modifier)} = {format_number(total)} "
                f"{sign} 难度 {format_number(difficulty)} → {'成功' if success else '失败'}")
        return CheckResult(success, False, text)

    def attack(self, accuracy, dodge, crit_range="20", disadvantage=False):
        """攻击判定：d20 + 精准 ≥ 闪避 即命中。掷出 20 必定命中，掷出 1 必定落空。
        命中且掷出的点数落在武器的暴击范围内（例如 19-20）时，再掷一次确认：
        第二次也命中就是暴击，没命中就按普通命中处理。
        disadvantage：攻击方处于劣势，命中判定掷 2d20 取低（确认暴击那一次不受影响）。"""
        value, hit, text = self._attack_roll(accuracy, dodge, disadvantage)
        total = value + accuracy
        if not hit or value < crit_min(crit_range):
            return AttackResult(hit, False, text, total)
        text += f"，落在暴击范围（{crit_range}）内！"
        _, confirmed, confirm_text = self._attack_roll(accuracy, dodge)
        verdict = "暴击！" if confirmed else "没能确认，按普通命中处理"
        return AttackResult(True, confirmed, f"{text}\n确认暴击：{confirm_text} → {verdict}", total)

    def block(self, modifier, attack_total):
        """格挡检定：d20 + 格挡修正，敌人这次的命中（d20 + 精准）小于它就挡住。
        掷出 20 必定挡住，掷出 1 必定挡不住。"""
        value = self.rng.randint(1, 20)
        if value == 20:
            return CheckResult(True, True, "🛡 格挡：d20 = 20 → 必定挡住")
        if value == 1:
            return CheckResult(False, True, "🛡 格挡：d20 = 1 → 必定挡不住")
        total = value + modifier
        blocked = attack_total < total
        sign = "<" if blocked else "≥"
        return CheckResult(blocked, False,
                           f"🛡 格挡：d20 = {value} + 格挡修正 {modifier} = {total}，"
                           f"敌方命中 {format_number(attack_total)} {sign} {total} → {'挡住了！' if blocked else '没挡住'}")

    def _attack_roll(self, accuracy, dodge, disadvantage=False):
        """掷一次命中判定，返回 (骰子点数, 是否命中, 过程文字)。劣势时掷两次取低。"""
        if disadvantage:
            rolls = (self.rng.randint(1, 20), self.rng.randint(1, 20))
            value = min(rolls)
            dice = f"2d20 取低（{rolls[0]}、{rolls[1]}）= {value}"
        else:
            value = self.rng.randint(1, 20)
            dice = f"d20 = {value}"
        if value == 20:
            return value, True, f"🎲 {dice} → 必定命中"
        if value == 1:
            return value, False, f"🎲 {dice} → 必定落空"
        total = value + accuracy
        hit = total >= dodge
        sign = "≥" if hit else "<"
        text = (f"🎲 {dice} + 精准 {format_number(accuracy)} = {format_number(total)} "
                f"{sign} 闪避 {format_number(dodge)} → {'命中' if hit else '未命中'}")
        return value, hit, text
