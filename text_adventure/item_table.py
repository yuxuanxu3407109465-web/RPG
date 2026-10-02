"""物品表：data/items.csv（Excel / Numbers / WPS 都能直接打开编辑）。

每一行是一件物品，第一行是表头（中文列名）。游戏启动时读这张表，转成引擎用的物品数据
（和以前写在 world.json 里的 "items" 完全一样的格式），所以引擎、界面都不用改。

规则只在这里：列名、取值的中文写法 → 内部 id。表格写错了，启动时会列出
“第几行、哪一列、怎么错的”，不会带着错的数据跑起来。列的说明见 `物品表说明.md`。
"""

import csv
import re

import stats

# 列名（表头必须一字不差；顺序随意，多出来的列会被忽略，可以当备注用）
COLUMNS = [
    "ID", "名称", "别名", "描述", "重量", "可堆叠", "物品标签", "等阶",
    "持握", "武器类型", "伤害骰", "暴击范围", "武器标签", "代用武器", "劣质", "盾牌",
    "护甲部位", "护甲类别", "护甲值", "行动点惩罚", "视野惩罚",
    "穿戴位", "减重率",
    "使用效果", "使用提示", "使用描述", "用后保留",
]
REQUIRED = ["ID", "名称", "重量"]

# 中文写法 → 内部 id（也接受直接写英文 id）
ITEM_TAGS = {"食物": "food", "寻常医疗物资": "basic_medical"}
CONDITIONS = {"流血": "bleeding", "力竭": "exhausted", "中毒": "poisoned"}
EFFECTS = {"食物": "food", "水源": "water", "体力": "stamina", "生命": "hp"}
GEAR_KINDS = {"饰品": "accessory", "披风": "cloak", "背包": "backpack"}
YES = {"是", "有", "√", "✓", "y", "yes", "true", "1"}
NO = {"", "否", "无", "×", "n", "no", "false", "0"}
SEPARATORS = r"[、，,；;/]+"


class ItemTableError(ValueError):
    """物品表有错：message 里逐条列出第几行哪一列。"""


def _split(text):
    return [p.strip() for p in re.split(SEPARATORS, text or "") if p.strip()]


def _reverse(table):
    """{id: 中文名} → {中文名: id, id: id}。"""
    out = {}
    for key, name in table.items():
        out[name] = key
        out[key] = key
    return out


def read_rows(path):
    """读 CSV：先按 UTF-8（带不带 BOM 都行），不行再按 GBK（Windows Excel 默认的“CSV”格式）。"""
    for encoding in ("utf-8-sig", "gbk"):
        try:
            with open(path, encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise ItemTableError(f"{path} 的编码认不出来：请在 Excel 里“另存为 → CSV UTF-8”。")


def load(path, world_data):
    """读物品表，返回 {物品 id: 物品数据}。有错就抛 ItemTableError，列出全部错误。"""
    rows = read_rows(path)
    lookups = {
        "武器类型": _reverse(world_data.get("weapon_types", {})),
        "护甲部位": {**_reverse(world_data.get("armor_slots", {})),
                   **{name.replace("防具", ""): sid for sid, name in world_data.get("armor_slots", {}).items()}},
        "持握": _reverse(stats.HOLD_TYPES),
        "等阶": _reverse({k: v[0] for k, v in stats.QUALITIES.items()}),
        "护甲类别": _reverse({k: v[0] for k, v in stats.ARMOR_CLASSES.items()}),
        "武器标签": _reverse({k: v[0] for k, v in stats.WEAPON_TAGS.items()}),
        "物品标签": _reverse({v: k for k, v in ITEM_TAGS.items()}),
        "穿戴位": _reverse({v: k for k, v in GEAR_KINDS.items()}),
    }
    errors = []
    items = {}
    seen = set()
    if rows:
        missing = [c for c in REQUIRED if c not in rows[0]]
        if missing:
            raise ItemTableError(f"{path} 缺少列：{'、'.join(missing)}（表头要和 物品表说明.md 里写的一字不差）")
    for number, row in enumerate(rows, start=2):  # 第 1 行是表头
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        if not any(row.values()):
            continue  # 空行
        problems = []
        try:
            item_id, item = _row_to_item(row, lookups, problems)
        except _RowError as e:
            problems.append(str(e))
            item_id, item = row.get("ID"), None
        if item_id and item_id in seen:
            problems.append(f"ID “{item_id}” 和前面的物品重复了")
        seen.add(item_id)
        errors += [f"  第 {number} 行（{row.get('名称') or row.get('ID') or '?'}）：{p}" for p in problems]
        if item and not problems:
            items[item_id] = item
    if errors:
        raise ItemTableError(f"物品表 {path} 有 {len(errors)} 处要改：\n" + "\n".join(errors))
    return items


class _RowError(ValueError):
    pass


def _row_to_item(row, lookups, problems):
    def get(col):
        return row.get(col, "")

    def number(col, kind=int, default=None):
        text = get(col)
        if not text:
            return default
        try:
            value = kind(text)
        except ValueError:
            problems.append(f"“{col}”要填数字，现在是“{text}”")
            return default
        if kind is float and value == int(value):
            value = int(value)  # 2.0 → 2
        return value

    def flag(col):
        text = get(col).lower()
        if text in YES:
            return True
        if text not in NO:
            problems.append(f"“{col}”只能填 是 / 否（留空 = 否），现在是“{get(col)}”")
        return False

    def pick(col, text=None):
        text = get(col) if text is None else text
        value = lookups[col].get(text)
        if value is None:
            choices = "、".join(sorted({k for k in lookups[col] if not k.isascii()}))
            problems.append(f"“{col}”填的“{text}”认不出来，可以填：{choices}")
        return value

    item_id = get("ID")
    if not item_id:
        raise _RowError("ID 不能空")
    if not re.fullmatch(r"[A-Za-z0-9_]+", item_id):
        raise _RowError(f"ID 只能用英文字母、数字和下划线，现在是“{item_id}”")
    if not get("名称"):
        problems.append("名称不能空")
    item = {"name": get("名称")}
    if get("别名"):
        item["aliases"] = _split(get("别名"))
    if get("描述"):
        item["description"] = get("描述")
    weight = number("重量", float)
    item["weight"] = weight if weight is not None else 0
    if not get("重量"):
        problems.append("重量不能空（没有重量写 0）")

    stack = get("可堆叠")
    if stack.isdigit() and int(stack) > 1:
        item["stack"] = int(stack)
    elif flag("可堆叠"):
        item["stack"] = True
    if get("物品标签"):
        item["tags"] = [pick("物品标签", t) for t in _split(get("物品标签"))]
    if get("等阶") and pick("等阶") not in (None, "normal"):
        item["quality"] = pick("等阶")
    if get("持握"):
        item["hold"] = pick("持握")

    # 武器：填了武器类型就是武器
    if get("武器类型"):
        weapon = {"type": pick("武器类型")}
        dice = get("伤害骰").lower()
        if dice:
            if not re.fullmatch(r"\d+d\d+", dice):
                problems.append(f"“伤害骰”要写成 1d8 这种格式，现在是“{get('伤害骰')}”")
            weapon["damage"] = dice
        crit = get("暴击范围").replace("—", "-").replace("~", "-").replace("～", "-")
        if crit:
            if not re.fullmatch(r"\d+(-\d+)?", crit):
                problems.append(f"“暴击范围”要写成 18-20 或 20，现在是“{get('暴击范围')}”")
            weapon["crit_range"] = crit
        if get("武器标签"):
            weapon["tags"] = [pick("武器标签", t) for t in _split(get("武器标签"))]
        if flag("代用武器"):
            weapon["improvised"] = True
        if flag("劣质"):
            weapon["poor"] = True
        item["weapon"] = weapon
    else:
        for col in ("伤害骰", "暴击范围", "武器标签"):
            if get(col):
                problems.append(f"填了“{col}”但没填“武器类型”")
        flag("代用武器") and problems.append("勾了“代用武器”但没填“武器类型”")
        flag("劣质") and problems.append("勾了“劣质”但没填“武器类型”")
    if flag("盾牌"):
        item["shield"] = {}

    # 护甲：填了护甲部位就是护甲
    if get("护甲部位"):
        armor = {"slot": pick("护甲部位"), "class": pick("护甲类别") if get("护甲类别") else "clothing",
                 "value": number("护甲值", default=0)}
        for col, key in (("行动点惩罚", "ap_penalty"), ("视野惩罚", "sight_penalty")):
            value = number(col)
            if value:
                armor[key] = value
        item["armor"] = armor
    else:
        for col in ("护甲类别", "护甲值", "行动点惩罚", "视野惩罚"):
            if get(col):
                problems.append(f"填了“{col}”但没填“护甲部位”")

    # 背包、饰品、披风
    if get("穿戴位"):
        gear = {"slot": pick("穿戴位")}
        reduction = number("减重率")
        if reduction:
            gear["weight_reduction"] = reduction
        item["gear"] = gear
    elif get("减重率"):
        problems.append("填了“减重率”但没填“穿戴位”（只有背包有减重率）")

    # 使用效果
    if get("使用效果"):
        use = {"effects": [_effect(text, problems) for text in _split(get("使用效果"))]}
        use["effects"] = [e for e in use["effects"] if e]
        use["hint"] = get("使用提示") or "、".join(_split(get("使用效果")))
        if get("使用描述"):
            use["message"] = get("使用描述")
        if flag("用后保留"):
            use["consume"] = False
        item["use"] = use
    else:
        for col in ("使用提示", "使用描述"):
            if get(col):
                problems.append(f"填了“{col}”但没填“使用效果”")
    return item_id, item


def _effect(text, problems):
    """一条使用效果：食物 +30 / 水源 +30 / 生命 +5 / 体力 25% / 解除 流血。"""
    m = re.fullmatch(r"解除\s*(\S+)", text)
    if m:
        cond = CONDITIONS.get(m.group(1), m.group(1) if m.group(1).isascii() else None)
        if not cond:
            problems.append(f"“使用效果”里的“{text}”：不认识的状态，可以写：{'、'.join(CONDITIONS)}")
            return None
        return {"type": "cure", "condition": cond}
    m = re.fullmatch(r"(\S+?)\s*\+?\s*(\d+)\s*(%?)", text)
    if m and m.group(1) in EFFECTS:
        effect = {"type": EFFECTS[m.group(1)]}
        if m.group(3):
            if effect["type"] in ("food", "water"):
                problems.append(f"“使用效果”里的“{text}”：食物 / 水源只能写点数（例如 食物 +30）")
                return None
            effect["ratio"] = int(m.group(2)) / 100
        else:
            effect["amount"] = int(m.group(2))
        return effect
    problems.append(f"“使用效果”里的“{text}”看不懂，例如：食物 +30、水源 +30、生命 +5、体力 25%、解除 流血")
    return None


def to_rows(items, world_data):
    """把物品数据转回表格的一行行（导出现有物品时用）。"""
    weapon_types = world_data.get("weapon_types", {})
    armor_slots = world_data.get("armor_slots", {})
    inv_items = {v: k for k, v in ITEM_TAGS.items()}
    inv_gear = {v: k for k, v in GEAR_KINDS.items()}
    inv_cond = {v: k for k, v in CONDITIONS.items()}
    inv_eff = {v: k for k, v in EFFECTS.items()}
    rows = []
    for item_id, it in items.items():
        row = {c: "" for c in COLUMNS}
        row.update({"ID": item_id, "名称": it["name"], "别名": "、".join(it.get("aliases", [])),
                    "描述": it.get("description", ""), "重量": f"{it.get('weight', 0):g}"})
        stack = it.get("stack")
        row["可堆叠"] = str(stack) if isinstance(stack, int) and not isinstance(stack, bool) else ("是" if stack else "")
        row["物品标签"] = "、".join(inv_items.get(t, t) for t in it.get("tags", []))
        if it.get("quality"):
            row["等阶"] = stats.QUALITIES[it["quality"]][0]
        if it.get("hold"):
            row["持握"] = stats.HOLD_TYPES[it["hold"]]
        w = it.get("weapon")
        if w:
            row["武器类型"] = weapon_types.get(w["type"], w["type"])
            row["伤害骰"] = w.get("damage", "")
            row["暴击范围"] = w.get("crit_range", "")
            row["武器标签"] = "、".join(stats.WEAPON_TAGS[t][0] for t in w.get("tags", []))
            row["代用武器"] = "是" if w.get("improvised") else ""
            row["劣质"] = "是" if w.get("poor") else ""
        row["盾牌"] = "是" if "shield" in it else ""
        a = it.get("armor")
        if a:
            row["护甲部位"] = armor_slots[a["slot"]].replace("防具", "")
            row["护甲类别"] = stats.ARMOR_CLASSES[a.get("class", "clothing")][0]
            row["护甲值"] = str(a.get("value", 0))
            row["行动点惩罚"] = str(a.get("ap_penalty", "") or "")
            row["视野惩罚"] = str(a.get("sight_penalty", "") or "")
        g = it.get("gear")
        if g:
            row["穿戴位"] = inv_gear.get(g["slot"], g["slot"])
            row["减重率"] = str(g.get("weight_reduction", "") or "")
        u = it.get("use")
        if u:
            parts = []
            for e in u.get("effects", []):
                if e["type"] == "cure":
                    parts.append(f"解除 {inv_cond.get(e['condition'], e['condition'])}")
                elif "ratio" in e:
                    parts.append(f"{inv_eff[e['type']]} {round(e['ratio'] * 100):g}%")
                else:
                    parts.append(f"{inv_eff[e['type']]} +{e.get('amount', 0)}")
            row["使用效果"] = "、".join(parts)
            row["使用提示"] = u.get("hint", "") if u.get("hint", "") != row["使用效果"] else ""
            row["使用描述"] = u.get("message", "")
            row["用后保留"] = "是" if u.get("consume") is False else ""
        rows.append(row)
    return rows


def write(path, rows):
    """写成带 BOM 的 UTF-8 CSV：Windows 上的 Excel 直接双击打开中文也不会乱码。"""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
