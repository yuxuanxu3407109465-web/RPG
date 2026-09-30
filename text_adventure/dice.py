"""抛骰系统：掷任意骰子（如 2d6+1），以及 D20 / D100 两种检定规则。

检定统一用"成功率"（百分比）来调用，具体用哪种骰子由 data/rules.json 决定：
  D100：掷 1~100，小于等于成功率即成功
  D20 ：成功率换算成调整值，掷 1d20 + 调整值，大于等于难度 11 即成功
两种方式的成功概率一致（D20 以 5% 为一档），只是手感和显示不同。
两种方式都有大成功和大失败：无论成功率多少，大成功必定成功，大失败必定失败。
"""

import json
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path

DICE_PATTERN = re.compile(r"^(\d*)d(\d+)([+-]\d+)?$")
CRIT_RANGE_PATTERN = re.compile(r"^(\d+)(?:-20)?$")  # 暴击范围："19-20" 或 "20"
D20_BASE_DC = 11  # 调整值为 0 时的难度，正好是 50%


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
    critical: bool  # 大成功或大失败
    text: str  # 给玩家看的掷骰过程


@dataclass
class AttackResult:
    hit: bool
    crit: bool  # 暴击已确认
    text: str  # 给玩家看的掷骰过程（可能有两行：命中 + 暴击确认）


def crit_min(crit_range):
    """"19-20" -> 19，"20" -> 20。"""
    return int(CRIT_RANGE_PATTERN.match(crit_range).group(1))


class Dice:
    def __init__(self, rules_path, rng=None):
        rules = json.loads(Path(rules_path).read_text(encoding="utf-8"))["dice"]
        self.system = rules["system"]
        self.d100_crit_success = rules["d100_critical_success_max"]
        self.d100_crit_fail = rules["d100_critical_failure_min"]
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

    def check(self, chance):
        """按当前骰子系统做一次检定，chance 是成功率（%）。"""
        if self.system == "d20":
            return self._check_d20(chance)
        return self._check_d100(chance)

    def attack(self, accuracy, dodge, crit_range="20"):
        """攻击判定（不受骰子系统设置影响，固定用 d20）：d20 + 精准 > 闪避 即命中。
        掷出 20 必定命中，掷出 1 必定落空。
        命中且掷出的点数落在武器的暴击范围内（例如 19-20）时，再掷一次确认：
        第二次也命中就是暴击，没命中就按普通命中处理。"""
        value, hit, text = self._attack_roll(accuracy, dodge)
        if not hit or value < crit_min(crit_range):
            return AttackResult(hit, False, text)
        text += f"，落在暴击范围（{crit_range}）内！"
        _, confirmed, confirm_text = self._attack_roll(accuracy, dodge)
        verdict = "暴击！" if confirmed else "没能确认，按普通命中处理"
        return AttackResult(True, confirmed, f"{text}\n确认暴击：{confirm_text} → {verdict}")

    def _attack_roll(self, accuracy, dodge):
        """掷一次命中判定，返回 (骰子点数, 是否命中, 过程文字)。"""
        value = self.rng.randint(1, 20)
        if value == 20:
            return value, True, "🎲 d20 = 20 → 必定命中"
        if value == 1:
            return value, False, "🎲 d20 = 1 → 必定落空"
        total = value + accuracy
        hit = total > dodge
        sign = ">" if hit else "≤"
        text = (f"🎲 d20 = {value} + 精准 {format_number(accuracy)} = {format_number(total)} "
                f"{sign} 闪避 {format_number(dodge)} → {'命中' if hit else '未命中'}")
        return value, hit, text

    def _check_d100(self, chance):
        value = self.rng.randint(1, 100)
        if value <= self.d100_crit_success:
            return CheckResult(True, True, f"🎲 d100 = {value} → 大成功！")
        if value >= self.d100_crit_fail:
            return CheckResult(False, True, f"🎲 d100 = {value} → 大失败！")
        success = value <= chance
        sign = "≤" if success else ">"
        return CheckResult(success, False, f"🎲 d100 = {value} {sign} {chance} → {'成功' if success else '失败'}")

    def _check_d20(self, chance):
        modifier = d20_modifier(chance)
        value = self.rng.randint(1, 20)
        if value == 20:
            return CheckResult(True, True, "🎲 d20 = 20 → 大成功！")
        if value == 1:
            return CheckResult(False, True, "🎲 d20 = 1 → 大失败！")
        total = value + modifier
        success = total >= D20_BASE_DC
        sign = "≥" if success else "<"
        text = f"🎲 d20 = {value}，{modifier:+d} = {total} {sign} {D20_BASE_DC} → {'成功' if success else '失败'}"
        return CheckResult(success, False, text)


def format_number(value):
    """16.0 显示成 16，16.5 保持 16.5。"""
    return f"{value:g}"


def d20_modifier(chance):
    """成功率换算成 D20 调整值：50% 为 +0，每 5% 为 1 点（四舍五入）。"""
    return math.floor((chance - 50) / 5 + 0.5)
