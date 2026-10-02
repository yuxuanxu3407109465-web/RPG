"""游戏入口：运行 `python3 main.py` 开始游戏。"""

from pathlib import Path

from character import CharacterCreator, CharacterOptions, Prompter
from dice import Dice
from engine import Game, World, SLOT_COUNT
from skills import SkillTrees

BASE_DIR = Path(__file__).parent


def choose_slot(game, ask):
    """列出有存档的槽位让玩家挑一个，返回槽位号。"""
    slots = [n for n in range(1, SLOT_COUNT + 1) if game.slot_path(n).exists()]
    if len(slots) == 1:
        return slots[0]
    labels = []
    for n in slots:
        info = game.slot_info(n) or {}
        labels.append("%d 号槽：%s · %s 级 · %s · %s" % (
            n, info.get("name", "?"), info.get("level", "?"),
            info.get("room", "?"), info.get("time", "?"),
        ))
    return slots[ask.choice("选择编号：", labels)]


def main_menu(game, ask, options, skill_trees, world):
    """主菜单：新游戏，或者（有存档时）继续存档。"""
    print(f"=== {world.title} ===\n")
    if game.has_save() and ask.choice("选择编号：", ["新游戏", "继续存档"]) == 1:
        print(game.cmd_load(str(choose_slot(game, ask))))
        return
    tree_names = {t["id"]: t["name"] for t in skill_trees.trees}
    character = CharacterCreator(options, world.items, tree_names, ask).run()
    game.start_new(character)
    background = options.background(character.background)
    print(f"\n你是{character.name}，{background['name']}。")
    print(world.intro)
    print("（输入“帮助”查看指令）\n")
    print(game.describe_room())


def death_menu(game, ask):
    """死了：读档，或者回主菜单。返回 True 表示要回主菜单。"""
    choice = ask.choice("\n选择编号：", ["读档", "返回主菜单"])
    if choice == 0 and game.has_save():
        print(game.cmd_load(str(choose_slot(game, ask))))
        return False
    if choice == 0:
        print("还没有存档，只能回到主菜单。")
    game.death_cause = None
    return True


def main():
    try:
        world = World(BASE_DIR / "data" / "world.json")
    except ValueError as e:  # 物品表（data/items.csv）等写错了：说清楚哪里错，不往下跑
        print("游戏数据有错，没法启动：\n" + str(e))
        return
    options = CharacterOptions(BASE_DIR / "data" / "character_options.json")
    skill_trees = SkillTrees(BASE_DIR / "data" / "skill_trees.json")
    dice = Dice()
    game = Game(world, options, skill_trees, dice, BASE_DIR / "saves" / "save.json")
    ask = Prompter()

    main_menu(game, ask, options, skill_trees, world)
    while game.running:
        text = input("\n> ")
        output = game.handle(text)
        if output:
            print(output)
        if game.death_cause and death_menu(game, ask):
            print()
            main_menu(game, ask, options, skill_trees, world)


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print()
