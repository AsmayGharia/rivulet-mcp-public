# Changelog

## [0.1.0.2] - 2026-05-05

### Fixed
- README title corrected to `rivulet-mcp-public` (was `rivulet-mcp`, the private repo name)

## [0.1.0.1] - 2026-05-04

### Changed
- Updated contact email to asmay@rivulet.bio across all user-facing surfaces

## 0.1.0 — Initial release

- `design_experiment`: NL → ExperimentPlan via Claude
- `iterate_protocol`: stateless plan revision (caller passes plan back, server holds no state)
- `estimate_throughput`: runtime + speedup estimates (pre-validation)
- `run_experiment`: hardware stub (contact asmay@rivulet.bio)
- `list_presets`: 5 built-in experiment presets
- CLI: `rivulet design` / `rivulet iterate` / `rivulet presets`
- MIT license
