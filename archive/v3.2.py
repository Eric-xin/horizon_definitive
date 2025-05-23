import gamelib
import random
import math
import copy
import json
from sys import maxsize
from gamelib import GameState, GameMap, GameUnit

# Shorthand constants set in on_game_start
WALL = SUPPORT = TURRET = SCOUT = DEMOLISHER = INTERCEPTOR = None
MP = SP = None

class AlgoStrategy(gamelib.AlgoCore):
    """
    A clearer, more modular single-file version of the starter algo.
    Methods are grouped by responsibility: lifecycle, offense, defense,
    support, simulation, and utilities.
    """
    def __init__(self):
        super().__init__()
        seed = random.randrange(maxsize)
        random.seed(seed)
        gamelib.debug_write(f"Random seed: {seed}")
        # State
        self.support_locations = []
        self.scored_on = []
        self.sectors = []
        self.start_points = []

        # turn number
        self.last_turn = 0

        # LAST RESORT
        self.resort = False
        self.resort_remove = False

    # ------------------------
    # Lifecycle hooks
    # ------------------------
    def on_game_start(self, config):
        """Initialize config, unit shorthands, sectors & start points."""
        self.config = config
        ui = config["unitInformation"]
        global WALL, SUPPORT, TURRET, SCOUT, DEMOLISHER, INTERCEPTOR, MP, SP
        WALL, SUPPORT, TURRET, SCOUT, DEMOLISHER, INTERCEPTOR = (
            ui[0]["shorthand"],
            ui[1]["shorthand"],
            ui[2]["shorthand"],
            ui[3]["shorthand"],
            ui[4]["shorthand"],
            ui[5]["shorthand"],
        )
        MP, SP = 1, 0

        # Build 4 triangular sectors
        self.sectors = [[], [], [], []]
        for c in range(28):
            group = c // 7
            rows = (
                range(14 - c - 1, 14) if c < 14
                else range(c - 14, 14)
            )
            for r in rows:
                self.sectors[group].append([c, r])

        # Four spawn points for scouts
        # self.start_points = [[4,12], [10,12], [17,12], [23,12]]
        self.start_points = [[2,12], [5,12], [8,12], [11,12], [14,12], [17,12], [20,12], [23,12], [25,12]]

    def on_turn(self, turn_state):
        """Main turn entry: offense, defense, support."""
        state = GameState(self.config, turn_state)
        gamelib.debug_write(f"Turn {state.turn_number}")
        state.suppress_warnings(True)

        # Update turn number
        self.last_turn = state.turn_number

        # ——— Last‑resort trigger: health <10 & >15 breaches on one wide edge ———
        # Define the “wide” edges
        left_edge  = {(0,13), (1,12), (2,11)}
        right_edge = {(27,13),(26,12),(25,11)}
        # Count breaches you’ve recorded in those zones
        left_hits  = sum(1 for b in self.scored_on if b["loc"] in left_edge)
        right_hits = sum(1 for b in self.scored_on if b["loc"] in right_edge)

        if (not self.resort
            and (left_hits > 15 or right_hits > 15)):
            # enter last‑resort mode on the side with more hits
            side = "left" if left_hits > right_hits else "right"
            gamelib.debug_write(f"🚨 Entering LAST‑RESORT EDGE MODE ({side}) 🚨")
            self.resort = True

            # immediately run edge defense and finish turn
            self._resort_defense_mode(state, side)
            state.submit_turn()
            return
        
        # rim defense
        self._check_diagonal_edge_hits(state)

        # --- Offense ---
        if state.turn_number == 0:
            self._initial_defense(state)
        else:
            attack, loc, num = self.should_attack(state)
            if attack:
                self.scout_attack(state, loc, num)
        
        # --- Far-side walls ---
        self._build_far_side_walls(state)

        # --- Defense improvements ---
        max_improvements = 15
        for _ in range(max_improvements):
            if state.get_resource(SP) < 2:
                break
            if not self._try_improve_defense(state):
                break

        # --- Support management ---
        self._manage_support(state, loc if 'loc' in locals() else None)

        state.submit_turn()

    def on_action_frame(self, turn_str):
        """Stamp breaches with turn so we know where+when they happen."""
        data = json.loads(turn_str)
        for breach in data.get("events", {}).get("breach", []):
            loc, owner = tuple(breach[0]), breach[4]
            if owner != 1:
                # record both location and the turn number
                self.scored_on.append({
                    "loc": loc,
                    "turn": self.last_turn  # we'll set last_turn in on_turn
                })
                gamelib.debug_write(f"Opponent breached at {loc} on turn {self.last_turn}")

    # ------------------------
    # Initial defense
    # ------------------------
    def _initial_defense(self, state: GameState):
        """Basic turret + wall setup on turn 0."""
        state.attempt_spawn(TURRET, self.start_points)
        # state.attempt_upgrade(self.start_points) # No upgrade of turrets based on the current rule
        # walls = [[4,13], [10,13], [17,13], [23,13]]
        # walls = [[x, y + 1] for x, y in self.start_points]
        walls = [[2,13], [5,13], [8,13], [11,13], [14,13], [17,13], [20,13], [23,13], [25,13]]
        state.attempt_spawn(WALL, walls)

    # ------------------------
    # Defense improvement
    # ------------------------
    def _try_improve_defense(self, state: GameState) -> bool:
        """Parse and upgrade/build in the weakest sector."""
        defenses = self.parse_defenses(state)
        sector = self.defense_heuristic(defenses)
        return self.improve_defense(state, sector, defenses[sector])

    def parse_defenses(self, state: GameState):
        """Return per-sector [[weights], [counts]] for walls & turrets."""
        results = []
        for sector in self.sectors:
            w_counts = [0,0,0,0]  # [wall, wall+, turret, turret+]
            n_counts = [0,0,0,0]
            for loc in sector:
                unit = state.contains_stationary_unit(loc)
                if not unit:
                    continue
                idx = {"W":0,"W+":1,"T":2,"T+":3}[(
                    "W+" if unit.unit_type==WALL and unit.upgraded else
                    "W"  if unit.unit_type==WALL else
                    "T+" if unit.unit_type==TURRET and unit.upgraded else
                    "T"
                )]
                w_counts[idx] += unit.health / unit.max_health
                n_counts[idx] += 1
            results.append([w_counts, n_counts])
        return results

    def defense_heuristic(self, defenses):
        """Choose sector with lowest weighted strength."""
        best_i, best_v = 0, float("inf")
        for i, (w, _) in enumerate(defenses):
            """
            Weights:
            - reinforced turrets: 8 (original 12)
            - reinforced walls:   3 (original 5)
            - turrets:            6 (original 6)
            - walls:             1 (original 1)
            """
            val = w[3]*8 + w[2]*6 + w[1]*3 + w[0]
            if w[1] < 1:  # few upgraded walls → prioritize
                val *= 0.5
            if val < best_v:
                best_v, best_i = val, i
        return best_i

    def improve_defense(self, state: GameState, sector: int, defense):
        """
        1) Repair any wall under 25% on row 13.
        2a) After turn ≥10, fill edges x=1–5 & 23–27 with a wall+turret pair.
        2b) Symmetric expansion from sides toward centre, placing a wall on row 13
            and a turret behind it on row 12, leaving at most one adjacent wall.
        3) Upgrade all walls after turn ≥7.
        4) Build only the 2nd turret row (y=start_row–2), where a wall sits at y+1.
        5) Seal gaps on row 13 except at x=14 once turn ≥15.
        6) Funnel layers from turn ≥20.
        """
        turn = state.turn_number
        start = self.start_points[sector]
        centre = 14

        # Precompute row 13 cells & existing walls
        row13 = [[x, 13] for x in range(28)]
        existing = {
            tuple(loc)
            for loc in row13
            if (u := state.contains_stationary_unit(loc)) and u.unit_type == WALL
        }

        # 1a) Repair weak walls
        for loc in row13:
            unit = state.contains_stationary_unit(loc)
            if unit and unit.unit_type == WALL and unit.health < 0.25 * unit.max_health:
                state.attempt_remove(loc)
                if state.can_spawn(WALL, loc):
                    state.attempt_spawn(WALL, loc)
                    state.attempt_upgrade(loc)
                return True
        
        # 1b) Fix initial walls and turrets, install if destroyed
        for loc in self.start_points:
            # turret sits at the start point
            turret_loc = loc
            # wall directly in front of it
            wall_loc   = [loc[0], loc[1] + 1]

            # rebuild missing wall first
            if not state.contains_stationary_unit(wall_loc) and state.can_spawn(WALL, wall_loc):
                state.attempt_spawn(WALL, wall_loc)
                state.attempt_upgrade(wall_loc)
                return True

            # then rebuild missing turret
            if not state.contains_stationary_unit(turret_loc) and state.can_spawn(TURRET, turret_loc):
                state.attempt_spawn(TURRET, turret_loc)
                return True

        # 2) Ensure wall+turret sets at designated locations, symmetric side→centre
        # key_positions = [[4,13],[6,13],[8,13],[12,13],[14,13],[16,13],[19,13],[22,13],[24,13]]
        # # build symmetric order: (4,24),(6,22),(8,19),(12,16),(14)
        # ordered = []
        # n = len(key_positions)
        # for i in range(n // 2):
        #     ordered.append(key_positions[i])
        #     ordered.append(key_positions[-i-1])
        # if n % 2 == 1:
        #     ordered.append(key_positions[n // 2])
        key_positions = [[4,13], [24,13], [6,13], [22,13], [8,13], [19,13], [12,13], [16,13], [14,13]]

        for wloc in key_positions:
            tloc = [wloc[0], 12]
            wall_unit   = state.contains_stationary_unit(wloc)
            turret_unit = state.contains_stationary_unit(tloc)

            # 1) Spawn missing wall, then upgrade it
            if not wall_unit and state.can_spawn(WALL, wloc):
                if state.attempt_spawn(WALL, wloc):
                    state.attempt_upgrade(wloc)
                return True

            # 2) Upgrade any unupgraded wall
            if wall_unit and wall_unit.unit_type == WALL and not wall_unit.upgraded:
                state.attempt_upgrade(wloc)
                return True

            # 3) Then spawn missing turret
            if not turret_unit and wall_unit and state.can_spawn(TURRET, tloc):
                state.attempt_spawn(TURRET, tloc)
                return True

        # 3) Build only the 2nd turret row
        mp = state.get_resource(MP)
        if mp >= 3:
            tur_cells = self.turret_sequence(start)
            start_row = start[1]
            y2 = start_row - 2
            for loc in tur_cells:
                if loc[1] != y2:
                    continue
                if (state.contains_stationary_unit([loc[0], y2 + 1])
                    and state.can_spawn(TURRET, loc)):
                    state.attempt_spawn(TURRET, loc)
                    return True

        # 4) Seal gaps on row 13 except at centre
        if turn >= 15:
            hole = [centre, 13]
            if state.contains_stationary_unit(hole):
                state.attempt_remove(hole)
                return True
            for loc in row13:
                if loc[0] == centre:
                    continue
                if not state.contains_stationary_unit(loc) and state.can_spawn(WALL, loc):
                    state.attempt_spawn(WALL, loc)
                    return True

        # 5) Funnel layers from turn 20 onward
        if turn >= 20:
            layer = min(turn - 20, 2)
            start_row = start[1]
            wall_y   = start_row - 1 - layer
            turret_y = start_row - 2 - layer
            for dx in (-1, 1):
                wpos = [centre + dx * (1 + layer), wall_y]
                if state.can_spawn(WALL, wpos):
                    state.attempt_spawn(WALL, wpos)
                    return True
            for dx in (-1, 1):
                tpos = [centre + dx * (2 + layer), turret_y]
                if state.can_spawn(TURRET, tpos):
                    state.attempt_spawn(TURRET, tpos)
                    return True

        return False

    def try_build_upgraded_turret(self, state: GameState, seq):
        if state.get_resource(MP) < 8:
            return False
        for loc in seq:
            if not state.contains_stationary_unit(loc):
                if state.attempt_spawn(TURRET, loc):
                    return state.attempt_upgrade(loc) > 0
        return False

    def try_upgrade(self, state: GameState, loc):
        unit = state.contains_stationary_unit(loc)
        if not unit:
            return False
        if unit.unit_type == TURRET and unit.health >= 0.75 * unit.max_health:
            return state.attempt_upgrade(loc) > 0
        if unit.unit_type == WALL:
            return state.attempt_upgrade(loc) > 0
        return False

    def _spawn_and_upgrade_wall(self, state, seq):
        for loc in seq:
            pos = [loc[0], 13]
            if not state.contains_stationary_unit(pos):
                state.attempt_spawn(WALL, pos)
                return state.attempt_upgrade(pos) > 0
        return False

    def _spawn_wall(self, state, seq):
        for loc in seq:
            pos = [loc[0], 13]
            if not state.contains_stationary_unit(pos):
                return state.attempt_spawn(WALL, pos)
        return False

    # ------------------------
    # Support management
    # ------------------------
    def _manage_support(self, state: GameState, scout_loc):
        """Every 5 turns starting turn 3, prune & place shields around scouts."""
        t = state.turn_number
        if scout_loc and t >= 5:
            path = state.find_path_to_edge(scout_loc)
            rng = self.config["unitInformation"][1]["shieldRange"]
            # prune
            kept = []
            for loc in self.support_locations:
                unit = state.contains_stationary_unit(loc)
                if unit and any(self.manhattan(loc, p) <= rng for p in path):
                    kept.append(loc)
                else:
                    state.attempt_remove(loc)
            self.support_locations = kept
            # place new
            for loc in state.game_map.get_locations_in_range(scout_loc, rng):
                if loc not in kept and loc not in path and state.can_spawn(SUPPORT, loc):
                    if state.attempt_spawn(SUPPORT, loc):
                        self.support_locations.append(loc)
                        state.attempt_upgrade(loc)
        # upgrade all shields
        for loc in list(self.support_locations):
            state.attempt_upgrade(loc)

    # ------------------------
    # Far-side walls
    # ------------------------
    def _build_far_side_walls(self, state: GameState):
        spots = [[0,13], [1,13], [2,13], [25,13], [26,13], [27,13]]
        for loc in spots:
            if state.can_spawn(WALL, loc):
                state.attempt_spawn(WALL, loc)
            unit = state.contains_stationary_unit(loc)
            if unit and unit.unit_type == WALL and not unit.upgraded:
                state.attempt_upgrade(loc)

    # ------------------------
    # Offense logic
    # ------------------------
    def should_attack(self, state: GameState):
        mp = state.get_resource(MP)
        scouts = int(mp)
        loc, survived = self.full_sim(state, scouts)
        # conditions to go all-in
        if mp >= 8 and state.enemy_health <= 7 and state.enemy_health - survived < -3:
            return True, loc, scouts
        if mp < 15 + state.turn_number // 10 and (survived <= scouts * 0.6 or mp < 8):
            return False, [], 0
        return True, loc, scouts

    def scout_attack(self, state: GameState, loc, num):
        state.attempt_spawn(SCOUT, loc, num)

    # ------------------------
    # Simulation helpers
    # ------------------------
    def full_sim(self, orig_state: GameState, num_scouts: int):
        """
        Simulate num_scouts scouts from all deploy points, return best (loc, survived).
        """
        options = []
        for i in range(14):
            for pt in ([i,13-i], [14+i,i]):
                if orig_state.can_spawn(SCOUT, pt):
                    options.append(pt)

        best = (-1, None, None)  # (survived, loc, attackers_set)
        for loc in options:
            state = copy.deepcopy(orig_state)
            survive, _, _, _, _, _, atk = self._simulate_path(state, loc, num_scouts)
            if survive > best[0]:
                best = (survive, loc, atk)

        return best[1], best[0]

    def _simulate_path(self, state, loc, num_scouts):
        """Helper to simulate a single scout path. Returns tuple of metrics + attackers set."""
        temp = copy.deepcopy(state)
        scout_unit = GameUnit(SCOUT, state.config)
        SC_HP, SC_DMG = scout_unit.max_health, scout_unit.damage_f
        sup_info = self.config["unitInformation"][1]
        shield_amt = sup_info.get("shieldAmount", 0)
        base_rng   = sup_info.get("attackRange", 0)

        edge = temp.get_target_edge(loc)
        path = temp.find_path_to_edge(loc)
        dead = 0
        dmg_turret = dmg_wall = dmg_support = dmg_to_scout = 0
        attackers = set()
        cur_hp = SC_HP

        idx = 0
        while idx < len(path):
            pt = path[idx]
            atkers = temp.get_attackers(pt, 0)
            temp.game_map.add_unit(SCOUT, pt)

            # shield buff
            for sup_loc in self.support_locations:
                sup = temp.contains_stationary_unit(sup_loc)
                if sup and sup.unit_type == SUPPORT:
                    rng = base_rng + (1 if sup.upgraded else 0)
                    if self.manhattan(sup_loc, pt) <= rng:
                        cur_hp = min(cur_hp + shield_amt, SC_HP + shield_amt)
                        break

            rem = num_scouts - dead
            # scouts attack structures
            while rem > 0:
                tgt = temp.get_target(temp.game_map[pt][0])
                if not tgt:
                    break
                maxd = rem * SC_DMG
                if tgt.health <= maxd:
                    # record damage by type
                    if tgt.unit_type == TURRET:   dmg_turret += tgt.health
                    elif tgt.unit_type == WALL:    dmg_wall   += tgt.health
                    elif tgt.unit_type == SUPPORT: dmg_support+= tgt.health
                    temp.game_map.remove_unit([tgt.x, tgt.y])
                    path = temp.find_path_to_edge(pt, edge)
                    idx = -1
                    rem -= math.ceil(tgt.health / SC_DMG)
                    break
                else:
                    tgt.health -= maxd
                    if tgt.unit_type == TURRET:   dmg_turret += maxd
                    elif tgt.unit_type == WALL:    dmg_wall   += maxd
                    elif tgt.unit_type == SUPPORT: dmg_support+= maxd
                    break

            temp.game_map.remove_unit(pt)
            # turrets attack scouts
            for atk in atkers:
                attackers.add((atk.x, atk.y))
                dmg_to_scout += min(atk.damage_i, cur_hp)
                cur_hp -= atk.damage_i
                if cur_hp <= 0:
                    dead += 1
                    cur_hp = SC_HP + shield_amt
                    if dead >= num_scouts:
                        break
            if dead >= num_scouts:
                break
            idx += 1

        survived = num_scouts - dead
        if not path or path[-1] not in state.game_map.get_edge_locations(edge):
            survived = 0

        return survived, dmg_to_scout, dmg_turret, dmg_wall, dmg_support, loc, attackers
    
    # ------------------------
    # Edge defense [LAST RESORT] 
    # ------------------------
    # def _breaches_on_both_edges(self):
    #     xs = [loc[0] for loc in self.scored_on]
    #     return 0 in xs and 27 in xs

    def _resort_defense_mode(self, state: GameState, side: str):
        """
        Last‑resort edge defense.  Waits until enough MP to build
        the full interceptor+scout wave before doing anything.
        """
        # --- 0) Compute MP needed for full wave ---
        MP_current = state.get_resource(MP)
        _, interceptor_cost = state.type_cost(INTERCEPTOR)
        _, scout_cost       = state.type_cost(SCOUT)
        required_MP = 2 * interceptor_cost + 15 * scout_cost

        # If we don't have enough MP yet, bail and wait
        if MP_current < required_MP:
            gamelib.debug_write(
                f"Waiting for MP: have {MP_current}, need {required_MP}"
            )
            return

        # --- 1) remove all existing walls/turrets ---
        if not self.resort_remove:
            self.resort_remove = True
            for x in range(28):
                for y in range(28):
                    u = state.contains_stationary_unit([x, y])
                    if u and u.unit_type in (WALL, TURRET):
                        state.attempt_remove([x, y])
            return

        # --- 2) build the diagonal support accelerator (or walls fallback) ---
        if side == "right":
            diag = [[13+i, (i+1)] for i in range(13)]
            inter_pos   = [25,11]
            scout_spots = [[20,6],[18,4],[16,2],[15,1]]
        else:
            diag = [[27-(13+i), (i+1)] for i in range(13)]
            inter_pos   = [2,11]
            scout_spots = [[7,6],[9,4],[11,2],[12,1]]

        for loc in diag:
            if state.can_spawn(SUPPORT, loc):
                if state.attempt_spawn(SUPPORT, loc):
                    state.attempt_upgrade(loc)
            elif state.can_spawn(WALL, loc):
                state.attempt_spawn(WALL, loc)

        # --- 3) spawn exactly 5 INTERCEPTORS ---
        state.attempt_spawn(INTERCEPTOR, inter_pos, 2)
        MP_current -= 2 * interceptor_cost

        # --- 4) spawn 15 SCOUTS in waves of 5 at each spot ---
        scouts_to_send = 15
        for spot in scout_spots:
            if scouts_to_send <= 0:
                break
            num = min(3, scouts_to_send, MP_current)
            if num > 0 and state.can_spawn(SCOUT, spot):
                state.attempt_spawn(SCOUT, spot, num)
                scouts_to_send -= num
                MP_current    -= num

        # --- 5) any leftover MP → dump the rest of scouts at the last spot ---
        if MP_current > 0 and scouts_to_send > 0:
            last = scout_spots[-1]
            state.attempt_spawn(SCOUT, last, min(MP_current, scouts_to_send))
    
    # ------------------------
    # Real time interoceptor
    # ------------------------
    def _check_diagonal_edge_hits(self, state: GameState):
        """
        Watch the two diagonal “rim” lines:
        • left:  [(0,13),(1,12)…(13,0)]
        • right: [(27,13),(26,12)…(14,0)]
        Slide a window of 4 along each. If in each of the last 3 turns
        there was ≥1 breach in that 4‑cell window, OR if this turn saw ≥5
        breaches there, spawn 1 INTERCEPTOR at the window’s 2nd cell.
        """
        cur = state.turn_number

        # build the two diagonals
        left_diag  = [(i, 13 - i)       for i in range(14)]
        right_diag = [(27 - i, 13 - i)  for i in range(14)]

        for diag in (left_diag, right_diag):
            # 11 windows of size 4
            for i in range(len(diag) - 3):
                window = diag[i : i + 4]

                # 1) 3‑turn streak?
                streak = all(
                    any(b["turn"] == cur - dt and b["loc"] in window
                        for b in self.scored_on)
                    # for dt in (0, 1, 2)
                    for dt in (1, 2, 3)
                )
                # 2) heavy damage this turn?
                heavy = sum(
                    1 for b in self.scored_on
                    # if b["turn"] == cur and b["loc"] in window
                    if b["turn"] == cur - 1 and b["loc"] in window
                ) >= 5

                if not (streak or heavy):
                    continue

                # 3) spawn one interceptor at the window’s “center” (index 1)
                spawn = list(window[1])
                if state.can_spawn(INTERCEPTOR, spawn):
                    state.attempt_spawn(INTERCEPTOR, spawn, 1)
                    gamelib.debug_write(
                        f"{'STREAK' if streak else 'HEAVY'} breach on diagonal {window} "
                        f"→ interceptor at {spawn}"
                    )
                # bail so we only fire one interceptor this turn
                return

    # ------------------------
    # Utility sequences
    # ------------------------
    def column_sequence(self, c):
        """Alternating columns around c within its sector block."""
        block = (c // 7) * 7
        rng = range(block + 1, block + 7) if c < 14 else range(block, block + 6)
        seq = [c]
        for i in range(1,7):
            for nc in (c - i, c + i):
                if nc in rng:
                    seq.append(nc)
        return seq

    def row_sequence(self, r0):
        """Rows: r0..13 then r0-1..0."""
        return list(range(r0,14)) + list(range(r0-1,-1,-1))

    def upgrade_sequence(self, pt):
        """Grid of all cells around pt for upgrades."""
        cols = self.column_sequence(pt[0])
        rows = self.row_sequence(pt[1])
        return [[c,r] for r in rows for c in cols]

    def turret_sequence(self, pt):
        """All cells in vertical band above pt for turret placement."""
        cols = self.column_sequence(pt[0])
        return [[c, pt[1]-i] for i in range(pt[1]) for c in cols]

    @staticmethod
    def manhattan(a, b):
        return abs(a[0]-b[0]) + abs(a[1]-b[1])

if __name__ == "__main__":
    AlgoStrategy().start()