# templates/

Version-controlled YAML experiment configurations. Each template declares the grid, physics, forcing, and time parameters for a named experiment. Override parameters at init time with `-o key=value`.

Scheme identity is declared with `ocean.recipe` — a named legoESM recipe (catalog name, recipe_map tag, or DINO card, depending on the lane). See "Recipes (scheme identity)" in the root README.md and AGENTS.md for the per-lane rules; `scripts/validate_templates.py` verifies every declaration against the pinned legoESM.
