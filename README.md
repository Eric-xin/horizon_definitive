# Horizon Definitive Algo

This is the Horizon Definitive Algorithm for Citadel C1 Terminal.

The original Horizon code is `horizon_definitive.py`. Other variations are made for Europe Terminal spring 2025.

The new strategy `rim definitive` is a new approach to the Europe Terminal, specifically targeting the `rim` region. More details will be provided in the future.

## Features

- **Turn Lifecycle**: Implements `on_game_start`, `on_turn`, and `on_action_frame`.  
- **Offense**: Decides when and where to send Scouts based on a fast path simulation.  
- **Defense**:  
    - Builds an initial turret + wall layout.  
    - Parses sector strengths and upgrades/builds in the weakest sector each turn.  
- **Support**: Periodically prunes and places shield‑support units around Scout attack paths.  
- **Far‑Side Walls**: Maintains corner walls every turn.  
- **Simulation**: Deep copy–based full path simulation to pick the best launch location.  
- **Utilities**: Helpers for grid sequences and Manhattan distance.  

## Prerequisites

- **Python**
- **Terminal C1 SDK**

## Code Overview

All logic lives in `main.py` (or whatever you rename this file to), under the `AlgoStrategy` class:

- **Lifecycle Hooks**  
    - `on_game_start(config)`: Reads unit shorthands & builds four triangular sectors and spawn points.  
    - `on_turn(turn_state)`: Orchestrates offense → defense → support → far‑side walls → submit.  
    - `on_action_frame(data)`: Tracks opponent breach events for reactive defense.  

- **Offense**  
    - `should_attack(state)`: Returns `(bool, location, num_scouts)` based on resources & simulated survival.  
    - `scout_attack(state, loc, num)`: Spawns Scouts at the chosen location.  

- **Defense**  
    - `_initial_defense(state)`: Turn‑0 turret and wall placement.  
    - `parse_defenses(state)`: Builds sector weights & counts for walls and turrets.  
    - `defense_heuristic(defs)`: Picks the weakest sector by weighted score.  
    - `improve_defense(state, sector, defense)`: Upgrades or spawns walls/turrets in that sector.  

- **Support**  
    - `_manage_support(state, scout_loc)`: Every 8 turns, prunes old shields and places/upgrades new ones along the Scout path.  

- **Far‑Side Walls**  
    - `_build_far_side_walls(state)`: Ensures a shallow wall layer in each far corner.  

- **Simulation**  
    - `full_sim(state, num_scouts)`: Copies the game state to simulate multiple scout paths and picks the best.  
    - `_simulate_path(...)`: Detailed per‐path simulation of damage exchange.  

- **Utilities**  
    - `column_sequence`, `row_sequence`, `upgrade_sequence`, `turret_sequence`: Grid‐based helper methods.  
    - `manhattan(a, b)`: Fast Manhattan distance.  


## Customization

- **Sector layout**: Change how `self.sectors` are built in `on_game_start`.  
- **Upgrade priority**: Adjust multipliers in `defense_heuristic`.  
- **Support cadence**: Modify the `(t - 3) % 8 == 0` check in `_manage_support`.  
- **Simulation depth**: Limit path length or adjust shield logic in `_simulate_path`.  

Use `gamelib.debug_write(...)` to log decisions and inspect turn‐by‐turn behavior.

## Contributing

1. Fork this repo.  
2. Create a branch for your feature or fix.  
3. Submit a pull request with a clear description of your changes.  

Please keep new code modular and document any new methods with concise docstrings.

## License

This project is licensed under the MIT License. Feel free to use, modify, and distribute!

Please note that some parts of the code may be subject to the Citadel C1 Terminal SDK license. Ensure compliance with all relevant licenses when using this code.

## Acknowledgments
- Thanks to the Citadel C1 Terminal community for their support and feedback.