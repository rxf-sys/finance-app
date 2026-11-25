# Design: Orynthia Finance

Status: 25.11.2026. Tokens live in `frontend/src/index.css` (light on `:root`, dark under
`prefers-color-scheme` and `[data-theme="dark"]`). The app belongs to the Orynthia family
together with the planned Orynthia Everyday; both share neutrals and rules, each has its
own primary colour.

## Rules

- One primary colour (fir green). Copper (`--accent`) is only used for small hint icons.
- No violet or lavender anywhere (accent, charts, gradients).
- Status is never colour alone: amounts carry a sign, states carry text or an icon.
- Contrast is calculated (WCAG 2.x relative luminance), not estimated.

## Contrast

| Pair | Light | Dark | Target |
|---|---|---|---|
| `--text` on `--background` | 15.69 | 15.82 | ≥ 7 |
| `--text` on `--surface` | 17.00 | 14.54 | ≥ 7 |
| `--text-muted` on `--background` | 6.32 | 7.79 | ≥ 4.5 |
| `--text-muted` on `--surface-muted` | 5.81 | 6.38 | ≥ 4.5 |
| `--primary` as text on `--surface` | 6.37 | 8.07 | ≥ 4.5 |
| `--on-primary` on `--primary` | 6.37 | 8.88 | ≥ 4.5 |
| `--positive` on `--surface` | 5.77 | 7.69 | ≥ 4.5 |
| `--negative` on `--surface` | 5.43 | 5.99 | ≥ 4.5 |
| `--warning` on `--surface` | 5.57 | 8.94 | ≥ 4.5 |
| `--info` on `--surface` | 6.09 | 6.68 | ≥ 4.5 |
| `--accent` (icons) on `--surface` | 5.45 | 7.77 | ≥ 3 |

Chart colours (`--chart-1` to `--chart-8`: fir green, copper, blue, ochre, rose, teal,
brown, grey) reach at least 4.06:1 (light) and 6.68:1 (dark) against `--surface`, above
the 3:1 needed for graphical objects. Categories store the token name, so changing a
value never needs a data migration.
