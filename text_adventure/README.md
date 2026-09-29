# 封城第七天

现代丧尸末世背景的文字冒险游戏，开放世界、CRPG 风格的角色构筑。

## 运行

需要 Python 3.9 或更新版本（macOS 自带的 `python3` 就可以），不需要安装任何第三方库。

```
python3 main.py
```

进入游戏后输入 `帮助` 查看所有指令。

## 文件说明

| 文件 | 内容 |
|---|---|
| `main.py` | 程序入口：开场、角色创建、主循环 |
| `engine.py` | 游戏状态与所有玩家指令 |
| `character.py` | 角色、同伴、角色创建流程、角色卡 |
| `stats.py` | 属性衍生数值、经验与升级的公式 |
| `skills.py` | 技能树：解锁条件、学习、显示 |
| `stances.py` | 姿态（长刃分支） |
| `dice.py` | 抛骰与 D20 / D100 检定 |
| `map_view.py` | 文字地图 |
| `data/world.json` | 地点、物品、NPC、对话、地图位置 |
| `data/character_options.json` | 属性、背景、预设同伴、成长数值 |
| `data/skill_trees.json` | 技能树、分支、技能、姿态 |
| `data/rules.json` | 骰子系统设置 |

大部分游戏内容都写在 `data/` 里的 JSON 文件中，加地点、物品、技能通常不需要改代码。

设计决定和开发约定见 [CLAUDE.md](CLAUDE.md)。
