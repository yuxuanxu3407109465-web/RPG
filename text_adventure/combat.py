"""战斗：不分战斗内外，地图上的僵尸每回合都会行动。

一轮（= 1 回合 = 1 分钟）的顺序：
  先攻比你高的敌人 → 你（花行动点做事，直到结束回合 / 行动点花光）→ 先攻比你低的敌人 → 下一轮。
  眩晕的一方这一轮排到最后；震慑跳过这一轮（行动点照拿）。
先攻在“视野里从没有敌人到出现第一个敌人”的时候掷（一次遭遇掷一次）：你和这个场景里的每个敌人
各掷 1d20 + 先攻值；还没掷过先攻的敌人一律排在你后面。

视野里出现第一个敌人时，强制打断当前行动（走路、休息……），等玩家下一步指示：
引擎把 interrupted 置为 True，网页版看到就停下自动寻路。

敌人（僵尸）的行动：没发现你就站着不动；发现你以后（它的视野 4 + 感知 格内、视线没被墙挡住）
每回合用行动点朝你走过来，够得着就攻击（普通攻击 6 行动点）。
敌人打死了，手上的武器和身上的护甲掉在它倒下的地方。击杀经验暂时不给（数值待定）。

这是核心流程：技能还没接进来（下一步逐个接），借机攻击也还没做。
"""

import stats

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
STEPS_4 = ((1, 0), (-1, 0), (0, 1), (0, -1))  # 和玩家一样只走东南西北


def distance(a, b):
    """两格之间的距离（格）：斜着也算 1 格（和拾取、近战范围同一个算法）。"""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


class CombatMixin:
    """混进 engine.Game：敌人的生成、视野、先攻、回合顺序、敌我攻击、持续伤害。"""

    def _reset_combat(self):
        self.room_enemies = {}  # 房间 id -> [Enemy]（只有活着的）
        self.next_enemy_uid = 1
        self.player_dots = []  # 玩家身上的持续伤害（流血、灼烧、强酸腐蚀）
        self.player_init = None  # 这一次遭遇里玩家的先攻；None = 现在没有遭遇
        self.seen_enemy_ids = []  # 上一次检查时视野里有哪些敌人（uid），用来判断“新进入视野”
        self.interrupted = False  # 这一步被“发现敌人”打断了（网页版据此停下自动寻路）
        self.blocks_left = 0  # 这一轮还能格挡几次

    # ---------- 生成 ----------

    def spawn_room_enemies(self, room_id):
        """第一次走进某个地点时放上敌人：enemies 是固定的（写了位置），random_enemies 随机个数、随机位置。"""
        room = self.world.rooms[room_id]
        if not self.room_grid(room_id):
            return
        for spec in room.get("enemies", []):
            self._place_enemy(room_id, spec, spec.get("pos"))
        for spec in room.get("random_enemies", []):
            count = self.dice.rng.randint(int(spec.get("min", 1)), int(spec.get("max", 1)))
            for _ in range(count):
                self._place_enemy(room_id, spec, None)

    def _place_enemy(self, room_id, spec, pos):
        level = spec.get("level", 1)
        if isinstance(level, list):
            level = self.dice.rng.randint(level[0], level[-1])
        enemy = self.enemies.create(spec["id"], spec.get("tier", "normal"), self.dice.rng, None, level)
        enemy.uid = self.next_enemy_uid
        self.next_enemy_uid += 1
        same = [e for e in self.room_enemies.get(room_id, []) if e.name == enemy.name]
        enemy.label = enemy.name + LETTERS[len(same) % len(LETTERS)]
        enemy.pos = list(pos) if pos else self._random_enemy_tile(room_id)
        enemy.ap = enemy.ap_per_turn()
        self.room_enemies.setdefault(room_id, []).append(enemy)
        return enemy

    def _random_enemy_tile(self, room_id):
        """随机找一格空地：不是墙 / 障碍物 / 门，离门至少 3 格（别一进门就贴脸），不和别的敌人重叠。"""
        grid = self.room_grid(room_id)
        width, height = self.grid_size(grid)
        doors = [tuple(c[:2]) for c in (grid.get("doors") or {}).values()]
        taken = {tuple(e.pos) for e in self.room_enemies.get(room_id, []) if e.pos}
        free = [(x, y) for y in range(height) for x in range(width)
                if self.tile_walkable(grid, x, y) and not self.tile_is_door(grid, x, y)
                and (x, y) not in taken and all(distance((x, y), d) >= 3 for d in doors)]
        if not free:
            free = [(x, y) for y in range(height) for x in range(width)
                    if self.tile_walkable(grid, x, y) and (x, y) not in taken]
        x, y = self.dice.rng.choice(free)
        return [x, y]

    # ---------- 查找 ----------

    def alive_enemies(self, room_id=None):
        return [e for e in self.room_enemies.get(room_id or self.current_room, []) if e.hp > 0]

    def enemy_at(self, pos):
        return next((e for e in self.alive_enemies() if e.pos and tuple(e.pos) == tuple(pos)), None)

    def find_enemy(self, name):
        """按称呼找敌人：“行尸A”精确匹配；只写“行尸”就挑看得见的里面最近的那只。"""
        name = (name or "").strip()
        visible = self.visible_enemies()
        for e in visible:
            if name.lower() == e.label.lower():
                return e
        here = self.player_pos()
        matches = [e for e in visible if name and name in e.label]
        if not matches:
            return None
        return min(matches, key=lambda e: distance(e.pos, here))

    # ---------- 视野 ----------

    def line_of_sight(self, a, b):
        """a 到 b 的视线有没有被墙（#）挡住；障碍物（~）不挡视线。两端的格子本身不算。"""
        grid = self.room_grid()
        if not grid:
            return True
        x0, y0 = a
        x1, y1 = b
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        x, y = x0, y0
        while (x, y) != (x1, y1):
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy
            if (x, y) != (x1, y1) and self.tile_at(grid, x, y) == "#":
                return False
        return True

    def visible_enemies(self):
        """你看得见的敌人：在你的视野范围内，并且视线没被墙挡住。"""
        if not self.character or not self.room_grid():
            return []
        here = self.player_pos()
        sight = self.sight_range()
        return [e for e in self.alive_enemies()
                if distance(e.pos, here) <= sight and self.line_of_sight(here, e.pos)]

    def _enemy_sees_player(self, enemy):
        here = self.player_pos()
        return (distance(enemy.pos, here) <= stats.sight_range(enemy.attributes)
                and self.line_of_sight(enemy.pos, here))

    def check_enemies(self):
        """每做完一步、每过一回合都查一次：
        · 看得见你的敌人从此盯上你（aware）；
        · 视野里从“没有敌人”变成“有敌人”：打断当前行动，掷先攻。返回这一下有没有打断。"""
        if not self.character or self.death_cause:
            return False
        for e in self.alive_enemies():
            if not e.aware and self._enemy_sees_player(e):
                e.aware = True
                self.pending_notes.append(f"{e.label}发现了你！")
        visible = self.visible_enemies()
        new = [e for e in visible if e.uid not in self.seen_enemy_ids]
        first = bool(visible) and not self.seen_enemy_ids  # 首个敌人进入视野 = 进入战斗
        broke = False
        if first:
            self._roll_initiative()
        elif new and self.player_init is not None:
            for e in new:  # 遭遇中途新看见的敌人：这时候才掷它的先攻
                if e.init_roll is None:
                    self.pending_notes.append("先攻：" + self._roll_enemy_initiative(e))
        # 默认只在首个敌人进入视野时打断；设置里打开“每个敌人”后，每有敌人新进入视野都打断
        if first or (new and self.settings.get("interrupt_every_enemy")):
            broke = True
            self.interrupted = True
            here = self.player_pos()
            spotted = "、".join(f"{e.label}（第 {e.pos[0] + 1} 列，第 {e.pos[1] + 1} 行，{distance(e.pos, here)} 格外）"
                                for e in (visible if first else new))
            self.pending_notes.append(f"⚠ 视野里出现了敌人：{spotted}。当前行动被打断。")
        self.seen_enemy_ids = [e.uid for e in visible]
        if not visible and not any(e.aware for e in self.alive_enemies()):
            self.player_init = None  # 这一次遭遇结束了，下次遇到重新掷先攻
        return broke

    def _roll_initiative(self):
        """遭遇开始：你和这个场景里的每个敌人各掷一次先攻。
        和你同分的敌人：你们俩重掷，直到分出先后——重掷的数只决定它和你谁先，
        你和其他敌人比较时仍然用第一次掷的结果。"""
        advantage = self.options.perk_effect(self.character.perks, "initiative_advantage")
        mine = stats.initiative(self.character.attributes)
        self.player_init, _ = self.dice.initiative(mine, advantage)
        parts = [f"你 {self.player_init}"] + [self._roll_enemy_initiative(e) for e in self.alive_enemies()]
        self.pending_notes.append("先攻：" + "、".join(parts) + "（比你高的每回合先于你行动）")

    def _roll_enemy_initiative(self, e):
        """给一个敌人掷先攻（和你同分就双方重掷，只决定你俩的先后），返回说明文字。"""
        advantage = self.options.perk_effect(self.character.perks, "initiative_advantage")
        e.init_roll, _ = self.dice.initiative(e.initiative())
        e.init_tiebreak = 0
        text = f"{e.label} {e.init_roll}"
        if e.init_roll == self.player_init:
            while True:
                me, _ = self.dice.initiative(stats.initiative(self.character.attributes), advantage)
                it, _ = self.dice.initiative(e.initiative())
                if me != it:
                    break
            e.init_tiebreak = 1 if it > me else -1
            text += f"（和你同分，重掷 你 {me} : {it}，{'它' if it > me else '你'}先）"
        return text

    # ---------- 回合顺序 ----------

    def _player_stunned_now(self):
        return any(x.get("id") == "stunned" and x.get("turn", self.turns) < self.turns
                   for x in self.character.conditions)

    def _player_order_key(self):
        return (0 if self._player_stunned_now() else 1, self.player_init or 0, 0)

    def _enemy_order_key(self, e):
        """排序用：(没眩晕, 第一次的先攻, 和你同分时的重掷结果)。敌人之间只看前两项。"""
        stunned = e.stun == "stunned" and e.stun_turn < self.turns
        return (0 if stunned else 1, e.init_roll if e.init_roll is not None else -1, e.init_tiebreak)

    def _enemy_phase(self, before_player):
        """让这一轮还没行动的敌人行动。before_player=True 只动排在玩家前面的。"""
        if not self.character:
            return
        mine = self._player_order_key()
        queue = sorted((e for e in self.alive_enemies() if not e.acted),
                       key=self._enemy_order_key, reverse=True)
        for e in queue:
            if self.death_cause:
                return
            if e.hp <= 0 or (before_player and not self._enemy_order_key(e) > mine):
                continue
            e.acted = True
            self._enemy_turn(e)

    def _new_round(self):
        """新一轮开始：敌人补行动点、重新排队；你的格挡次数重置。"""
        self.blocks_left = self.blocks_per_turn()
        for e in self.alive_enemies():
            e.acted = False
            e.ap = min(stats.ap_cap(e.attributes), e.ap + e.ap_per_turn())

    # ---------- 敌人的回合 ----------

    def _enemy_turn(self, e):
        notes = self.pending_notes
        # 1. 持续伤害在它自己的回合开始时结算
        hurt = stats.tick_dots(e.dots)
        if hurt:
            total = sum(hurt.values())
            e.hp = max(0, e.hp - total)
            names = "、".join(f"{stats.DOT_KINDS[k][0]} {v}" for k, v in hurt.items())
            notes.append(f"{e.label}受到持续伤害（{names}），生命 {e.hp}/{e.max_hp}。")
            if e.hp <= 0:
                notes.append(self._kill_enemy(e))
                return
        # 2. 眩晕 / 震慑
        if e.stun == "dazed" and e.stun_turn < self.turns:
            e.stun = None
            notes.append(f"{e.label}被震慑，这一回合动弹不得。")
            return
        clear_stun = e.stun == "stunned" and e.stun_turn < self.turns
        try:
            # 3. 没发现你就不动
            if not e.aware:
                if not self._enemy_sees_player(e):
                    return
                e.aware = True
                notes.append(f"{e.label}发现了你！")
            # 4. 倒地先爬起来
            if e.knocked_down:
                if e.ap < stats.GET_UP_AP_COST:
                    return
                e.ap -= stats.GET_UP_AP_COST
                e.knocked_down = False
                notes.append(f"{e.label}从地上爬了起来。")
            # 5. 走过来、够得着就打
            moved = 0
            while not self.death_cause and e.hp > 0:
                here = self.player_pos()
                if distance(e.pos, here) <= e.attack_range():
                    if e.ap < stats.ATTACK_AP_COST:
                        break
                    if moved:
                        notes.append(self._moved_text(e, moved))
                        moved = 0
                    e.ap -= stats.ATTACK_AP_COST
                    notes.append(self._enemy_attack(e))
                    continue
                if e.ap < stats.MOVE_AP_COST:
                    break
                step = self._enemy_next_step(e)
                if not step:
                    break
                e.pos = list(step)
                e.ap -= stats.MOVE_AP_COST
                moved += 1
            if moved:
                notes.append(self._moved_text(e, moved))
        finally:
            if clear_stun:
                e.stun = None

    def _moved_text(self, e, moved):
        return f"{e.label}朝你走了 {moved} 格（现在在第 {e.pos[0] + 1} 列，第 {e.pos[1] + 1} 行）。"

    def _enemy_next_step(self, e):
        """往你身边走一格：按最短路找一格能够着你的位置，走它的第一步；不穿墙、不穿门、不压别人。"""
        grid = self.room_grid()
        here = self.player_pos()
        blocked = {tuple(o.pos) for o in self.alive_enemies() if o is not e} | {tuple(here)}
        start = tuple(e.pos)
        first = {start: None}
        frontier = [start]
        while frontier:
            nxt = []
            for cell in frontier:
                if distance(cell, here) <= e.attack_range() and cell != start:
                    step = cell
                    while first[step] != start and first[step] is not None:
                        step = first[step]
                    return step
                for dx, dy in STEPS_4:
                    n = (cell[0] + dx, cell[1] + dy)
                    if n in first or n in blocked:
                        continue
                    if not self.tile_walkable(grid, n[0], n[1]) or self.tile_is_door(grid, n[0], n[1]):
                        continue
                    first[n] = cell
                    nxt.append(n)
            frontier = nxt
        return None

    def _enemy_attack(self, e):
        """敌人打你一次：命中 → 格挡（持盾）→ 伤害减护甲 → 扣血。返回过程文字。"""
        c = self.character
        result = self.dice.attack(e.accuracy(), self.dodge(), e.crit_range())
        self.sfx("hurt" if result.hit else "miss")   # 挨打 / 它挥空，声音不一样
        lines = [f"{e.label}用{e.attack['name']}攻击你：" + result.text]
        if result.hit and self.blocks_left > 0:
            self.blocks_left -= 1
            block = self.dice.block(stats.block_modifier(c.attributes), result.total)
            lines.append(block.text)
            if block.success:
                self.sfx("block")
                return "\n".join(lines)
        if not result.hit:
            return "\n".join(lines)
        tags = e.attack.get("tags", [])
        weapon = {"name": e.attack["name"], "damage": e.attack["damage"],
                  "damage_modifiers": e.damage_modifiers(), "crit_bonus": stats.crit_damage_bonus(tags)}
        text, damage = self._roll_damage(weapon, self.armor_total(), result.crit,
                                         stats.TAG_ARMOR_IGNORE if "armor_piercing" in tags else 0)
        lines.append(text)
        # 酸蚀变异：徒手攻击额外 1d4 强酸（不吃护甲）+ 1 层强酸腐蚀
        if e.weapon is None:
            for m in e.mutations:
                info = self.enemies.mutations[m]
                extra = info.get("unarmed_extra_damage")
                if extra:
                    roll = self.dice.roll(extra["damage"])
                    damage += roll.total
                    lines.append(f"{info['name']}：强酸 {roll.describe()}（不受护甲减免）")
                applies = info.get("applies")
                if applies:
                    burst = stats.add_dot(self.player_dots, "acid", applies["damage"], applies["turns"])
                    lines.append(f"你身上多了 1 层{stats.DOT_KINDS['acid'][0]}"
                                 + (f"（满层，最老的那层立刻结算 {burst} 点）" if burst else ""))
                    damage += burst
        if damage:
            self.damage_player(damage, "zombie")
        lines.append(f"你的生命 {c.hp}/{self.options.max_hp(c)}")
        return "\n".join(lines)

    # ---------- 你的持续伤害 ----------

    def _tick_player_dots(self):
        hurt = stats.tick_dots(self.player_dots)
        if not hurt or self.death_cause:
            return
        for kind, value in hurt.items():
            self.damage_player(value, stats.DOT_KINDS[kind][1])
            if self.death_cause:
                break
        names = "、".join(f"{stats.DOT_KINDS[k][0]} {v}" for k, v in hurt.items())
        c = self.character
        self.pending_notes.append(f"你受到持续伤害（{names}），生命 {c.hp}/{self.options.max_hp(c)}。")

    def dot_conditions(self):
        """身上的持续伤害，按种类合成异常状态（给角色卡 / 网页版显示，也能被绷带这类东西清掉）。"""
        out = []
        for kind, (name, _) in stats.DOT_KINDS.items():
            stacks = [d for d in self.player_dots if d["kind"] == kind]
            if stacks:
                cid = "bleeding" if kind == "bleed" else kind
                out.append({"id": cid, "name": name, "source": "dot",
                            "effect": f"{len(stacks)} 层，每回合 {sum(d['damage'] for d in stacks)} 点",
                            "note": f"最久还剩 {max(d['turns'] for d in stacks)} 回合"})
        return out

    def clear_dot(self, condition_id):
        """解除持续伤害类状态（例如绷带止血）：清掉就返回说明，没有这种状态返回 None。"""
        kind = "bleed" if condition_id == "bleeding" else condition_id
        if kind not in stats.DOT_KINDS:
            return None
        if not any(d["kind"] == kind for d in self.player_dots):
            return None
        self.player_dots = [d for d in self.player_dots if d["kind"] != kind]
        return f"{stats.DOT_KINDS[kind][0]}止住了。"

    # ---------- 你的攻击 ----------

    def cmd_attack(self, arg):
        """攻击 <敌人> [副手]：用主手（或副手）的武器打一下。不写目标就打够得着的最近的那只。"""
        if not self.character:
            return "还没有创建角色。"
        parts = (arg or "").split()
        offhand = "副手" in parts
        name = " ".join(p for p in parts if p not in ("副手", "主手"))
        visible = self.visible_enemies()
        if not visible:
            return "附近看不到敌人。"
        weapons = self.weapon_summary()
        weapon = next((w for w in weapons if w["hand"] == "副手"), None) if offhand else weapons[0]
        if offhand and not weapon:
            return "你副手没拿武器。"
        here = self.player_pos()
        reach = weapon.get("range") or stats.MELEE_RANGE
        if name:
            target = self.find_enemy(name)
            if not target:
                return f"看不到叫“{name}”的敌人。看得见的：{'、'.join(e.label for e in visible)}。"
        else:
            in_reach = [e for e in visible if distance(e.pos, here) <= reach]
            if not in_reach:
                return f"够不着任何敌人。看得见的：{'、'.join(e.label for e in visible)}。"
            target = min(in_reach, key=lambda e: distance(e.pos, here))
        far = distance(target.pos, here)
        if far > reach:
            return f"够不着：{target.label}在 {far} 格外，{weapon['name']}的攻击距离是 {reach} 格。先走近一点。"

        sneak = not target.aware  # 它还没发现你：这一下算偷袭
        weapon = self._sneak_weapon(weapon) if sneak else dict(weapon)
        result = self.dice.attack(weapon["accuracy"], target.dodge(), weapon["crit_range"])
        self.sfx("crit" if (result.hit and result.crit) else ("hit" if result.hit else "miss"))
        lines = [f"你用{weapon['name']}{'偷袭' if sneak else '攻击'}{target.label}"
                 f"（闪避 {target.dodge()}、护甲 {target.armor}）：" + result.text]
        if result.hit:
            text, damage = self._roll_damage(weapon, target.armor, result.crit,
                                             self.armor_ignore() + weapon["armor_ignore"])
            lines.append(text)
            target.hp = max(0, target.hp - damage)
            if "bleed" in weapon.get("tags", []) and target.hp > 0:  # 流血标签：命中叠 1 层流血
                burst = stats.add_dot(target.dots, "bleed", self.bleed_damage(), stats.BLEED_TURNS)
                target.hp = max(0, target.hp - burst)
                lines.append(f"{target.label}开始流血" + (f"（满层，最老的那层立刻结算 {burst} 点）" if burst else ""))
            if target.hp <= 0:
                lines.append(self._kill_enemy(target))
            else:
                lines.append(f"{target.label} 生命 {target.hp}/{target.max_hp}")
        if target.hp > 0 and not target.aware:
            target.aware = True
            lines.append(f"{target.label}发现了你！")
        cost = (self.offhand_attack_cost() or stats.ATTACK_AP_COST) if offhand else stats.ATTACK_AP_COST
        self.check_enemies()
        return "\n".join(lines) + self.spend_ap(cost)

    def _sneak_weapon(self, weapon):
        """偷袭（目标还没发现你）：暗袭技能命中 +（敏捷 + 感知）÷ 2、伤害 +100%；背刺标签伤害 +200%。"""
        weapon = dict(weapon)
        if "sneak_attack" in self.character.learned_skills:
            weapon["accuracy"] += stats.sneak_attack_accuracy_bonus(self.character.attributes)
            weapon["damage_modifiers"] = weapon["damage_modifiers"] + [("暗袭", stats.SNEAK_ATTACK_DAMAGE_PERCENT, stats.ADD)]
        if "backstab" in weapon.get("tags", []):
            weapon["damage_modifiers"] = weapon["damage_modifiers"] + stats.tag_damage_modifiers(["backstab"], sneak=True)
        return weapon

    def _kill_enemy(self, e):
        """敌人死了：从场景里拿掉，武器和护甲掉在它倒下的地方。"""
        e.hp = 0
        room = self.current_room
        self.room_enemies[room] = [x for x in self.room_enemies.get(room, []) if x is not e]
        self.sfx("kill")
        drops = ([e.weapon] if e.weapon else []) + list(e.armor_items)
        for item_id in drops:
            self._drop_at(item_id, e.pos)
        text = f"{e.label}倒下了，不再动弹。"
        if drops:
            text += "掉落：" + "、".join(self.world.items[i]["name"] for i in drops) + "。"
        self.check_enemies()
        return text

    def _drop_at(self, item_id, pos):
        """把一件东西放在某一格（被占了就放最近的空格子）。"""
        grid = self.room_grid()
        table = self.ground_positions_in()
        occupied = {tuple(c) for c in table if c}
        spot = tuple(pos) if tuple(pos) not in occupied else self._nearest_free_tile(grid, tuple(pos), occupied)
        self.room_items[self.current_room].append(item_id)
        table.append([spot[0], spot[1]] if spot else None)

    def cmd_spawn_test(self, arg):
        """试刷怪 <敌人> [等级] [等阶]：在当前场景随机放一只敌人（测试用）。"""
        if not self.character:
            return "还没有创建角色。"
        parts = (arg or "").split()
        template = self.enemies.find(parts[0]) if parts else None
        if not template or not self.room_grid():
            names = "、".join(t["name"] for t in self.enemies.templates.values())
            return f"用法：试刷怪 敌人 [等级] [等阶]，例如：试刷怪 行尸 2（已有：{names}）"
        spec = {"id": template}
        for p in parts[1:]:
            if p.rstrip("级").isdigit():
                spec["level"] = int(p.rstrip("级"))
            tier = next((t for t, info in stats.ENEMY_TIERS.items() if p in (t, info[0])), None)
            if tier:
                spec["tier"] = tier
        e = self._place_enemy(self.current_room, spec, None)
        self.check_enemies()
        return f"（测试）{e.label}出现在第 {e.pos[0] + 1} 列，第 {e.pos[1] + 1} 行。"

    def enemy_state(self):
        """看得见的敌人，打包给网页版。"""
        here = self.player_pos() if self.room_grid() else (0, 0)
        return [{"id": f"e{e.uid}", "name": e.label, "hp": e.hp, "max_hp": e.max_hp,
                 "x": e.pos[0], "y": e.pos[1], "aware": e.aware, "distance": distance(e.pos, here)}
                for e in self.visible_enemies()]
