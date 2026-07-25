# UI variants — revert kit

The live UI is the **Drawing Sheet** direction (light drafting paper,
blue-line grid, title blocks, dimension-line gantts). The previous
dark-dashboard UI is preserved here verbatim.

## To go back to the dark original

```bash
cp ui_variants/01_dark_original/config.toml   .streamlit/config.toml
cp ui_variants/01_dark_original/gantt_html.py programme/gantt_html.py
cp ui_variants/01_dark_original/app.py        app.py
```

Then re-run `python3 test_ui.py` to confirm.

Only these three files carry the visual identity:

| File | Holds |
|---|---|
| `.streamlit/config.toml` | Streamlit's own palette (base, primary, background, text) |
| `programme/gantt_html.py` | Both gantt renderers — the hierarchy gantt and the as-planned/as-built comparison |
| `app.py` | The injected stylesheet (`_inject_theme_css`) plus page chrome |

Everything else — every engine, every test — is styling-agnostic and
untouched by a theme swap.

## Variants

- `01_dark_original/` — near-black canvas, blueprint-blue accent.
  The state of the UI up to commit 48f976a.
