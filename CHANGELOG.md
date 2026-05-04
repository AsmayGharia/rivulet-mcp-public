# Changelog

## 0.1.0 — Initial release

- `design_experiment`: NL → ExperimentPlan via Claude
- `iterate_protocol`: stateless plan revision (caller passes plan back, server holds no state)
- `estimate_throughput`: runtime + speedup estimates (pre-validation)
- `run_experiment`: hardware stub (contact asmay@rivulet.bio)
- `list_presets`: 5 built-in experiment presets
- CLI: `rivulet design` / `rivulet iterate` / `rivulet presets`
- MIT license
