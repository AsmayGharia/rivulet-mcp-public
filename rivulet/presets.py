"""
Built-in experiment presets. Static — no Anthropic call required.
Sourced from DMF-sandbox-3/frontend/src/simulation/planner.ts GALLERY_TILES.
"""

PRESETS: list[dict] = [
    {
        "id": "drug_screen",
        "name": "Drug Screen",
        "mode": "drug_screen",
        "category": "Pair screen",
        "description": "Screen drug candidates against target cells — measure hit rate across 100 interactions.",
        "prompt": "Screen 10 million drug droplets against T-cells, identify hits by impedance shift. Collect hits in output 0 and all else in output 9.",
    },
    {
        "id": "tcell_screen",
        "name": "Cell-Cell Interaction",
        "mode": "tcell_screen",
        "category": "Immune assay",
        "description": "Pair NK cells with target cells — measure cytotoxicity events per encounter.",
        "prompt": "Pair 10,000 NK cells with myeloid targets and measure kill rate. Collect hits in output 0 and all else in output 9.",
    },
    {
        "id": "combo_screen",
        "name": "Combinatorial Assay",
        "mode": "combo_screen",
        "category": "4-arm",
        "description": "Four-condition screen: Drug A alone, Drug B alone, A+B combination, control. Detects synergy via Bliss independence model.",
        "prompt": "Run a combo screen for Drug A and Drug B against 500 myeloid cells. Collect synergistic hits in output 0, Drug A hits in output 2, Drug B hits in output 3, and all else in output 9.",
    },
    {
        "id": "mixed_sort",
        "name": "Mixed Population Sort",
        "mode": "mixed_sort",
        "category": "DEP sort",
        "description": "Sort heterogeneous cell populations by dielectric signature — no labels needed.",
        "prompt": "Sort 100,000 T-cells from myeloid cells then collect sorted fractions.",
    },
    {
        "id": "protocol",
        "name": "Proteomics Sample Prep",
        "mode": "protocol",
        "category": "Protocol",
        "description": "Automated multi-step protocol: load cells, lyse, reduce, digest, and quench — 8.5h manual workflow in minutes.",
        "prompt": "Run a proteomics sample prep protocol: load 55 nL PBS + cells, add 25 nL lysis buffer, lyse 5 min, add 50 nL reducing agent, denature 20 min, add 20 nL digest solution, digest 90 min, add 300 nL acidic quench and mix briefly.",
    },
]
