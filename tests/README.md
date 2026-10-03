# tests

Stdlib `unittest`, no dependencies (node, when present, runs the page's JS checks).

```sh
python3 -m unittest discover tests            # everything
python3 -m unittest tests.test_sim -v         # one file
tools/golden.py --check                       # drawings vs tests/golden/ (exit 1 on drift)
tools/golden.py --update                      # rewrite them after an intended change
tools/regen_docs.py --check                   # README / examples.md drawings up to date
tools/regen_docs.py                           # regenerate them
```

Update goldens only when a drawing is meant to change, and read the diff first.

## What covers what

| Subsystem | Files |
|---|---|
| language core, dialect loading | `test_core.py`, `test_composition.py` |
| `lint.py` | `test_lint_parsing.py`, `test_lint_hardening.py`, `test_lint_deep.py` |
| `render.py` (parser, graph model, Mermaid) | `test_render_model.py`, `test_render_graph.py`, `test_render_parsing.py` |
| `scene.py` | `test_scene.py` |
| `sim.py` | `test_sim.py` |
| `check.py` and its rule modules | `test_check_core.py`, `test_check_flow.py`, `test_check_state.py`, `test_check_inv.py`, `test_check_trace.py`, `test_dialects_checks.py` |
| `view_graph.py` | `test_view_graph_scene.py`, `test_view_graph_calls.py`, `test_view_graph_land.py`, `test_view_graph_sim.py` |
| `view_tree.py` | `test_view_tree.py`, `test_view_tree_calls.py`, `test_view_tree_sim.py` |
| `view.py` (the app, CLI, module split) | `test_view.py`, `test_view_constructs.py`, `test_view_fit.py`, `test_view_split.py`, `test_view_app_cli.py`, `test_view_app_calls.py`, `test_view_app_events.py`, `test_view_app_pan.py`, `test_view_app_sim.py`, `test_view_checks.py`, `test_view_sim_batch.py` |
| `themes.py`, `dialects.py` | `test_themes.py`, `test_themes_dialects_parsing.py` |
| golden drawings | `test_golden.py` (inputs × options vs `golden/`) |
| `build.py` and `install.sh` | `test_build.py`, `test_build_robustness.py` |
| `highlight/` | `test_lexer.py`, `test_highlight_grammars.py` |
| `site/` | `test_site.py`, `test_coin.py` |

## Data

- `fixtures/` — inputs: `coverage.sigil` (every construct; audited in
  `docs/coverage-notes.md`), `executions.sigil`, `checks/` and `lint/` cases,
  `yaml_cases.json`, `dialect_pack_resilience.py`.
- `golden/` — expected drawings, written by `tools/golden.py --update`.
