"""游戏入口：运行 `python3 main.py` 开始游戏。"""

from pathlib import Path

from character import CharacterCreator, CharacterOptions, Prompter
from dice import Dice
from engine import Game, World
from skills import SkillTrees

BASE_DIR = Path(__file__).parent


def main():
    world = World(BASE_DIR / "data" / "world.json")
    options = CharacterOptions(BASE_DIR / "data" / "character_options.json")
    skill_trees = SkillTrees(BASE_DIR / "data" / "skill_trees.json")
    dice = Dice(BASE_DIR / "data" / "rules.json")
    game = Game(world, options, skill_trees, dice, BASE_DIR / "saves" / "save.json")
    ask = Prompter()

    print(f"=== {world.title} ===\n")
    if game.save_path.exists() and ask.choice("选择编号：", ["新游戏", "继续存档"]) == 1:
        print(game.cmd_load(""))
    else:
        tree_names = {t["id"]: t["name"] for t in skill_trees.trees}
        character = CharacterCreator(options, world.items, tree_names, ask).run()
        game.start_new(character)
        background = options.background(character.background)
        print(f"\n你是{character.name}，{background['name']}。")
        print(world.intro)
        print("（输入“帮助”查看指令）\n")
        print(game.describe_room())

    while game.running:
        text = input("\n> ")
        output = game.handle(text)
        if output:
            print(output)


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print()
