"""物品的使用效果。

效果写在 `data/world.json` 里物品的 `use` 字段上，规则放在这里：

    "use": {
      "consume": true,                        // 用掉后是否消耗物品，默认 true
      "message": "你撕开包装，几口吞了下去。",   // 可选，使用时的描述
      "effects": [                            // 可以写一个对象，也可以写一个列表
        {"type": "stamina", "ratio": 0.5},    // 按上限的比例恢复体力
        {"type": "stamina", "amount": 100},   // 按固定点数恢复体力
        {"type": "hp", "ratio": 0.3},         // 恢复生命值
        {"type": "cure", "condition": "bleeding"}   // 解除某个异常状态
      ]
    }

加新效果只要往 EFFECTS 里注册一个函数，不用改引擎和界面。
物品信息和公式都来自数据与 stats.py，这里只负责“把效果套到角色身上”。
"""

import stats


def _amount(effect, cap):
    """写 ratio 就按上限的比例算，写 amount 就用固定点数。"""
    if "ratio" in effect:
        return int(round(cap * effect["ratio"]))
    return int(effect.get("amount", 0))


def _effect_stamina(game, character, effect):
    cap = stats.stamina_max(character.attributes)
    before = character.stamina
    character.stamina = min(cap, character.stamina + _amount(effect, cap))
    return f"体力 +{character.stamina - before}（{character.stamina}/{cap}）"


def _effect_hp(game, character, effect):
    cap = stats.max_hp(character.attributes, character.level)
    before = character.hp
    character.hp = min(cap, character.hp + _amount(effect, cap))
    return f"生命值 +{character.hp - before}（{character.hp}/{cap}）"


def _effect_cure(game, character, effect):
    """解除异常状态。体力不足引起的力竭清不掉，会由 clear_condition 说明原因。"""
    return game.clear_condition(effect.get("condition"))


EFFECTS = {
    "stamina": _effect_stamina,
    "hp": _effect_hp,
    "cure": _effect_cure,
}


def is_usable(item):
    """这件物品有没有写使用效果（界面据此决定要不要给“使用”按钮）。"""
    return bool(item.get("use"))


def effect_list(use_data):
    """把 effects 统一成一个列表。"""
    effects = use_data.get("effects", [])
    if isinstance(effects, dict):
        return [effects]
    return list(effects)


def use(game, character, item_id):
    """使用一件物品，返回要显示的文字。"""
    item = game.world.items[item_id]
    use_data = item.get("use")
    if not use_data:
        return f"{item['name']}现在派不上用场。"

    lines = []
    if use_data.get("message"):
        lines.append(use_data["message"])
    for effect in effect_list(use_data):
        handler = EFFECTS.get(effect.get("type"))
        if not handler:
            lines.append(f"（“{effect.get('type')}”这个效果还没实现）")
            continue
        text = handler(game, character, effect)
        if text:
            lines.append(text)

    if use_data.get("consume", True):
        game._unequip(item_id)
        game.inventory.remove(item_id)
        lines.append(f"{item['name']}用掉了。")
    return "\n".join(lines)
