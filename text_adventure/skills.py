"""技能树：玩家花技能点解锁技能。

每棵技能树可以分成几条分支（branches），分支只是侧重不同，玩家可以随意混着学。
技能用 branch 字段指定所属分支；不写 branch 的技能属于整棵树通用。

技能的 type 为 active 时是主动技能（战斗中使用），不写就是被动技能。
ap_cost 是使用 / 激活这个技能本身消耗的行动点；主动技能不写就默认 6（DEFAULT_AP_COST）。
cooldown 是冷却回合数：使用那一回合之后再等几回合（冷却 1 = 第 1 回合用，第 2 回合冷却，第 3 回合可以再用）；
主动技能不写就默认 1（DEFAULT_COOLDOWN）；主动攻击技能（attack: true）默认冷却到本回合结束（TURN_COOLDOWN）；
写 0 表示没有冷却。
所有技能在没有特别声明的情况下，一律视为用主手武器发动。
weapon_type 表示使用这个技能需要手持的武器类型。

每个技能可以设置这些解锁条件（都可省略）：
  cost           花费的技能点，默认 1
  requires       需要先学会的技能 id 列表
  attribute_min  所属技能树对应属性的最低要求
  level_min      最低等级
特殊技能树（special: true）不对应属性，只有选了特定背景（背景的 unlocks_trees）才能学习。
"""

import json
from pathlib import Path

import stances
import stats

DEFAULT_AP_COST = 6  # 主动技能没有特别说明时，默认花 6 行动点
DEFAULT_COOLDOWN = 1  # 主动技能没有特别说明时，默认冷却 1 回合
TURN_COOLDOWN = "turn"  # 冷却到本回合结束（本回合不能再用，下回合就能用）
DEFAULT_ATTACK_COOLDOWN = TURN_COOLDOWN  # 主动攻击技能（attack: true）默认冷却到本回合结束


def ap_cost(skill):
    """技能的行动点消耗；被动技能是 0。"""
    if skill.get("type") != "active":
        return skill.get("ap_cost", 0)
    return skill.get("ap_cost", DEFAULT_AP_COST)


def cooldown(skill):
    """技能的冷却：回合数，或 TURN_COOLDOWN（冷却到本回合结束）；被动技能是 0。"""
    if skill.get("type") != "active":
        return skill.get("cooldown", 0)
    default = DEFAULT_ATTACK_COOLDOWN if skill.get("attack") else DEFAULT_COOLDOWN
    return skill.get("cooldown", default)


def cooldown_text(skill):
    """冷却的说明文字，没有冷却就是空字符串。"""
    value = cooldown(skill)
    if value == TURN_COOLDOWN:
        return "冷却到本回合结束（本回合不能再用，下回合恢复）"
    if value:
        return f"冷却 {value} 回合：使用后再等 {value} 回合"
    return ""


class SkillTrees:
    """技能树数据，从 JSON 文件加载。"""

    def __init__(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.trees = data["trees"]
        self.skills = data["skills"]
        self.stances = data.get("stances", [])
        self._validate()

    def _validate(self):
        """检查数据里的引用是否都存在，写错了就在启动时直接报出来。"""
        tree_ids = {t["id"] for t in self.trees}
        skill_ids = {s["id"] for s in self.skills}
        for s in self.skills:
            where = f"skill_trees.json 里的技能 {s['id']}"
            if s["tree"] not in tree_ids:
                raise ValueError(f"{where}：技能树 {s['tree']} 不存在")
            branch = s.get("branch")
            if branch and branch not in {b["id"] for b in self.tree(s["tree"]).get("branches", [])}:
                raise ValueError(f"{where}：技能树 {s['tree']} 里没有分支 {branch}")
            for r in s.get("requires", []):
                if r not in skill_ids:
                    raise ValueError(f"{where}：前置技能 {r} 不存在")
            if s.get("value") and s["value"] not in SKILL_VALUES:
                raise ValueError(f"{where}：数值 {s['value']} 在 skills.SKILL_VALUES 里没有定义")
            if s.get("grip") and s["grip"] not in stats.GRIPS:
                raise ValueError(f"{where}：持握方式要是 {'、'.join(stats.GRIPS)} 之一")
            for effect in s.get("effects", []):
                if effect.get("type") not in stats.PASSIVE_EFFECTS:
                    raise ValueError(f"{where}：效果类型要是 {'、'.join(stats.PASSIVE_EFFECTS)} 之一")
                if effect.get("grip") and effect["grip"] not in stats.GRIPS:
                    raise ValueError(f"{where}：持握方式要是 {'、'.join(stats.GRIPS)} 之一")
            for stance_id in s.get("stance_effects", {}):
                if stance_id not in {st["id"] for st in self.stances}:
                    raise ValueError(f"{where}：姿态 {stance_id} 不存在")
        for st in self.stances:
            if st["skill"] not in skill_ids:
                raise ValueError(f"skill_trees.json 里的姿态 {st['id']}：技能 {st['skill']} 不存在")

    def tree(self, tree_id):
        return next(t for t in self.trees if t["id"] == tree_id)

    def skills_in(self, tree_id, branch=None):
        """某棵树的技能；给了 branch 就只要这个分支的（branch="" 表示通用技能）。"""
        skills = [s for s in self.skills if s["tree"] == tree_id]
        if branch is not None:
            skills = [s for s in skills if s.get("branch", "") == branch]
        return skills

    def find_tree(self, name):
        return next((t for t in self.trees if name in (t["name"], t["id"])), None)

    def find_skill(self, name):
        return next((s for s in self.skills if name in (s["name"], s["id"])), None)

    def stance(self, stance_id):
        return next(s for s in self.stances if s["id"] == stance_id)


def tree_unlocked(character, tree):
    return not tree.get("special") or tree["id"] in character.unlocked_trees


def unmet_requirements(character, skill, trees, options):
    """返回还没满足的解锁条件（文字列表），空列表表示可以学习。"""
    tree = trees.tree(skill["tree"])
    unmet = []
    missing = [r for r in skill.get("requires", []) if r not in character.learned_skills]
    if missing:
        names = "、".join(trees.find_skill(r)["name"] for r in missing)
        unmet.append(f"先学会{names}")
    attribute_min = skill.get("attribute_min", 0)
    if tree.get("attribute") and character.attributes[tree["attribute"]] < attribute_min:
        unmet.append(f"{options.attribute_name(tree['attribute'])} ≥ {attribute_min}")
    level_min = skill.get("level_min", 1)
    if character.level < level_min:
        unmet.append(f"等级 ≥ {level_min}")
    cost = skill.get("cost", 1)
    if character.skill_points < cost:
        unmet.append(f"技能点 ≥ {cost}")
    return unmet


def learn(character, skill, trees, options):
    if skill["id"] in character.learned_skills:
        return f"你已经学会{skill['name']}了。"
    tree = trees.tree(skill["tree"])
    if not tree_unlocked(character, tree):
        return f"还不能学习{skill['name']}：{tree['name']}{tree.get('locked_message', '尚未解锁')}。"
    unmet = unmet_requirements(character, skill, trees, options)
    if unmet:
        return f"还不能学习{skill['name']}：需要" + "、".join(unmet) + "。"
    cost = skill.get("cost", 1)
    character.skill_points -= cost
    character.learned_skills.append(skill["id"])
    return f"学会了{skill['name']}！花费 {cost} 点，剩余技能点：{character.skill_points}"


def _tree_title(tree, options):
    if tree.get("attribute"):
        return f"{tree['name']}（{options.attribute_name(tree['attribute'])}）"
    if tree.get("special"):
        return f"{tree['name']}（特殊）"
    return tree["name"]  # 不对应属性、也不特殊（例如武器掌握）


def format_overview(character, trees, options):
    """所有技能树的概览。"""
    lines = [f"======== 技能树 ========    可用技能点：{character.skill_points}"]
    for tree in trees.trees:
        skills = trees.skills_in(tree["id"])
        if tree_unlocked(character, tree):
            learned = sum(1 for s in skills if s["id"] in character.learned_skills)
            status = f"已学 {learned}/{len(skills)}"
        else:
            status = tree.get("locked_message", "尚未解锁")
        lines.append(f"  {_tree_title(tree, options)}  {status}")
    lines.append("\n输入“技能 树名”查看某棵技能树（例如：技能 锐器），“学习 技能名”解锁技能")
    return "\n".join(lines)


def format_tree(character, tree, trees, options, weapon_types):
    """一棵技能树里每个技能的花费、条件和状态。"""
    lines = [
        f"======== {_tree_title(tree, options)} ========    可用技能点：{character.skill_points}",
        tree["description"],
    ]
    branches = tree.get("branches", [])
    if branches:
        lines.append("分支：" + "、".join(b["name"] for b in branches) + "（可以随意混着学）")

    groups = [("通用", trees.skills_in(tree["id"], ""))]
    groups += [(b["name"], trees.skills_in(tree["id"], b["id"])) for b in branches]
    for title, group in groups:
        if title == "通用" and not group:
            continue
        if branches:
            lines.append(f"\n—— {title} ——")
        if not group:
            lines.append("  （还没有技能）")
        for skill in group:
            lines.append(_format_skill(character, skill, tree, trees, options, weapon_types))
    return "\n".join(lines)


def _format_skill(character, skill, tree, trees, options, weapon_types):
    if skill["id"] in character.learned_skills:
        status = "[已学会]"
    elif not tree_unlocked(character, tree):
        status = f"[{tree.get('locked_message', '尚未解锁')}]"
    else:
        unmet = unmet_requirements(character, skill, trees, options)
        status = "[可学习]" if not unmet else "[需要 " + "、".join(unmet) + "]"
    kind = "【主动】" if skill.get("type") == "active" else ""
    weapon = f"（需要手持{weapon_types[skill['weapon_type']]}武器）" if skill.get("weapon_type") else ""
    if skill.get("grip"):
        weapon += f"（需要{stats.GRIPS[skill['grip']]}）"
    if ap_cost(skill):
        weapon += f"（消耗 {ap_cost(skill)} 行动点）"
    if cooldown_text(skill):
        weapon += f"（{cooldown_text(skill)}）"
    lines = [f"  {kind}{skill['name']}  {skill.get('cost', 1)} 点  {status}", f"    {skill['description']}{weapon}"]
    lines += [f"    {line}" for line in skill_details(character, skill, trees, options)]
    return "\n".join(lines)


# 技能数据里写 "value": "名字"，技能树就按角色当前属性算出数值显示
SKILL_VALUES = {
    "psionic_heal": lambda c: f"按你现在的属性：回复 {stats.psionic_heal(c.attributes, c.level)} 点生命",
    "riposte": lambda c: f"按你现在的属性：每回合最多反击 {stats.riposte_per_turn(c.attributes)} 次",
    "sneak_attack": lambda c: (f"按你现在的属性：偷袭时命中 +{stats.sneak_attack_accuracy_bonus(c.attributes)}，"
                               f"伤害 +{stats.SNEAK_ATTACK_DAMAGE_PERCENT}%"),
    "psionic_bolt": lambda c: (f"按你现在的属性：范围 {stats.incinerate_range(c.attributes)} 格，"
                               f"造成 {stats.psionic_bolt_damage(c.level)} 点火焰伤害"),
    "bleed": lambda c: (f"按你现在的属性：无视 {stats.blade_armor_ignore(c.attributes)} 点护甲，"
                        f"流血最多叠 {stats.bleed_max_stacks(c.attributes)} 层"),
    "long_slash": lambda c: (f"按你现在的属性：撤步后撤 {stats.sidestep_distance(c.attributes)} 米，"
                             f"卸刃无视 {stats.blade_armor_ignore(c.attributes)} 点护甲、"
                             f"缴械难度 {stats.disarm_difficulty(c.attributes)}"),
}


def skill_details(character, skill, trees, options):
    """技能描述之外的详细数值：能获得的姿态（按当前属性算好），以及各姿态下的额外效果。"""
    details = stances.describe_granted(character, skill, trees, options)
    if skill.get("value"):
        details.append(SKILL_VALUES[skill["value"]](character))
    for stance_id, effect in skill.get("stance_effects", {}).items():
        details.append(f"[{trees.stance(stance_id)['name']}] {effect}")
    return details
