# rivulet-mcp

Rivulet is a digital microfluidics platform for high-throughput biological experiments. This MCP server lets AI agents design DEP protocols programmatically.

## What this is

An MCP server and CLI that gives AI agents (Claude, custom Python agents) the ability to design and iterate on DEP microfluidics experiment protocols using natural language. Works with Claude Desktop out of the box.

## Requirements

```bash
python3 --version  # must show 3.11+
```

If you see 3.10 or earlier:

```bash
brew install pyenv && pyenv install 3.11 && pyenv global 3.11
```

## Install

**Primary (macOS + Linux):**

```bash
pipx install rivulet-mcp
```

**Fallback (Linux/conda envs where pipx is unavailable):**

```bash
pip install rivulet-mcp
```

## Claude Desktop quick start

Claude Desktop users do not need `pip install` or `pipx install`. The config snippet handles everything via `uvx`.

**Step 1.** Create (or edit) your Claude Desktop config:

```bash
mkdir -p ~/Library/Application\ Support/Claude
```

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rivulet": {
      "command": "uvx",
      "args": ["rivulet-mcp"],
      "env": {
        "ANTHROPIC_API_KEY": "YOUR_ANTHROPIC_API_KEY_HERE"
      }
    }
  }
}
```

> Never commit your API key. If you accidentally commit one, revoke it immediately at [console.anthropic.com](https://console.anthropic.com).

<details>
<summary>Config file location on other platforms</summary>

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

</details>

**Step 2.** Restart Claude Desktop.

**Step 3.** Ask Claude:

> Design a 3-step incubation protocol: 30 minutes at 37°C, then a wash step, then 45 minutes with secondary antibody.

Claude will call the `design_experiment` tool and return a structured ExperimentPlan you can iterate on.

> Post-ship TODO: Replace with a screenshot of Claude Desktop showing the tool call card in the conversation sidebar.

## CLI quick start

**Step 1.** Set your API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or add to .env file in your project root
```

**Step 2.** Design a protocol:

```bash
rivulet design "3-step incubation protocol: 30min at 37C, wash 5min, then 45min with secondary antibody"
```

**Step 3.** Expected output (pretty-print):

```json
{
  "mode": "protocol",
  "steps": [
    {"name": "incubation", "duration_real_s": 1800, "temperature_c": 37},
    {"name": "wash", "duration_real_s": 300},
    {"name": "secondary_antibody", "duration_real_s": 2700}
  ]
}
```

## Tool reference

| Tool | Description | Key args | Returns |
|------|-------------|----------|---------|
| `design_experiment` | Design a protocol from natural language | `prompt: str` | `ExperimentPlan` JSON |
| `iterate_protocol` | Revise an existing plan based on feedback | `plan: dict`, `feedback: str` | Revised `ExperimentPlan` JSON |
| `estimate_throughput` | Runtime and speedup estimates for a plan | `plan: dict` | `{run_time_min, compound_count, rivulet_speedup_x, WARNING}` |
| `run_experiment` | Submit plan for hardware execution (stub) | `plan: dict`, `chip_id: str` | `NotImplementedError` |
| `list_presets` | List the 5 built-in experiment presets | — | Array of preset objects |

### Example outputs

**`design_experiment` — drug_screen mode:**

```json
{
  "mode": "drug_screen",
  "drug_count": 5,
  "cell_type": "T-Cell",
  "total_combinations": 15
}
```

**`design_experiment` — protocol mode:**

```json
{
  "mode": "protocol",
  "steps": [
    {"name": "incubation", "duration_real_s": 1800, "temperature_c": 37},
    {"name": "wash", "duration_real_s": 300},
    {"name": "secondary_antibody", "duration_real_s": 2700}
  ]
}
```

**`estimate_throughput`:**

```json
{
  "run_time_min": 0.006,
  "compound_count": 5,
  "rivulet_speedup_x": 2400000,
  "WARNING": "Pre-validation estimate. Contact team for benchmarked numbers."
}
```

## CLI reference

| Command | Description | Example |
|---------|-------------|---------|
| `rivulet design` | Design an experiment from natural language | `rivulet design "screen 5 drugs against T-cells"` |
| `rivulet iterate` | Revise an existing ExperimentPlan | `rivulet iterate plan.json "add 3 more drug concentrations"` |
| `rivulet presets` | List built-in experiment presets | `rivulet presets` |

**`rivulet iterate` help** (the `plan.json|-` syntax is non-obvious):

```
Usage: rivulet iterate [OPTIONS] PLAN FEEDBACK

  Revise an ExperimentPlan based on feedback.

Arguments:
  PLAN      Path to ExperimentPlan JSON file, or '-' to read from stdin
  FEEDBACK  Feedback text describing what to change

Options:
  --json    Output raw JSON (for piping)
  --help    Show this message and exit

Examples:
  rivulet iterate plan.json "add 3 more drug concentrations"
  rivulet design "screen 5 drugs" | rivulet iterate - "add NK cells"
```

## Debug mode

Set `RIVULET_DEBUG=1` to write verbose logs to `~/.rivulet-mcp.log`:

```bash
export RIVULET_DEBUG=1
rivulet design "screen 5 drugs"
```

For Claude Desktop, add `"RIVULET_DEBUG": "1"` to the `env` block in `claude_desktop_config.json`.

## Not in scope

- Not a simulation API (the simulation runs in TypeScript in the browser)
- Not real hardware control (no hardware deployed at customer labs yet — see `run_experiment` stub)
- Not a replacement for the browser demo (complementary, not competing)

## Bugs / Issues

[Open an issue](https://github.com/AsmayGharia/rivulet-mcp/issues) for bugs and feature requests.

For hardware inquiries: [hello@rivulet.io](mailto:hello@rivulet.io)
