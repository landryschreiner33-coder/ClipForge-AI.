# ClipForge design specification

The studio shell replaces the ClipFoundry top-tab layout. It is a calm studio and it is **dark only**: there is no
light theme and no "follow system" theme (a saved Light or System choice is dropped and every other choice kept).
Pixel art stays in the Office; every essential control uses the readable system font. Tokens live in
`frontend/src/theme.css` as CSS custom properties and are switched by `data-palette`, `data-accent`, `data-density`,
`data-text` and `data-motion` on `<html>`. `index.html` sets `color-scheme: dark` and the dark background inline, and
`public/appearance-boot.js` applies the saved palette, accent, spacing and text size before the app's script runs.
Customize studio is the one place these are changed (see [STUDIO_UPGRADE_MATRIX.md](STUDIO_UPGRADE_MATRIX.md),
CF2-21).

## Colour tokens

Contrast ratios use the WCAG 2.1 formula. `tests/test_theme_contrast.py` reads `theme.css` and fails if any palette
or accent drops below 4.5:1 for text (including status words and accent links) or 3:1 for focus rings and control
borders, so the values below cannot drift without a failing test.

Studio palette (default):

| Token | Value | Use |
| --- | --- | --- |
| `--canvas` | `#0B0D14` | page background |
| `--surface` | `#151A25` | cards and panels |
| `--raised` | `#1D2331` | controls, inner panels |
| `--hover` | `#252C3D` | hover fills |
| `--text` | `#F5F6FA` | body text |
| `--text-2` | `#D0D5E0` | secondary text |
| `--text-3` | `#A8B2C5` | quiet text (lowest 6.5:1 on any surface) |
| `--good` / `--warn` / `--bad` / `--info` | `#46D6C4` / `#F2B84B` / `#FF7A85` / `#6FB8FF` | status, always with a word and an icon |
| `--focus` | `#7FD3FF` | focus ring |
| `--control-border` | `#7D879B` | control outlines (3:1) |
| `--on-primary` | `#0B0D14` | text on accent buttons |

Other palettes change only the canvas, surface, raised, hover and border colours:

| Palette | Canvas | Surface | Raised | Lowest `--text-3` ratio |
| --- | --- | --- | --- | --- |
| Studio | `#0B0D14` | `#151A25` | `#1D2331` | 6.53 |
| Midnight | `#070B18` | `#0F1730` | `#172142` | 6.45 |
| Graphite | `#0E0F11` | `#18191C` | `#212226` | 6.55 |
| Plum | `#100B17` | `#1A1325` | `#231A31` | 6.97 |

Accents (`data-accent`), lowest ratio as text on any palette's surfaces, and on the accent's own tint:

| Accent | Primary | Hover | Tint | Lowest on surfaces | On its tint |
| --- | --- | --- | --- | --- | --- |
| Violet (default) | `#9A7CFF` | `#B29BFF` | `#241D45` | 5.01 | 5.01 |
| Teal | `#2DD4BF` | `#5EEAD4` | `#0F2E2B` | 8.44 | 7.80 |
| Blue | `#4FA3FF` | `#7DBBFF` | `#12263F` | 5.99 | 5.83 |
| Coral | `#FF8A5B` | `#FFA884` | `#3A2117` | 6.76 | 6.41 |
| Green | `#3DD68C` | `#6BE3A8` | `#10301F` | 8.37 | 7.64 |
| Pink | `#FF6FB5` | `#FF96C8` | `#3A1730` | 6.13 | 6.09 |

Status is never colour alone: badges carry a word and an icon.

## Type, spacing and shape

- Font: the system UI stack (`system-ui, -apple-system, "Segoe UI", Roboto, …`); no web-font download.
- Base body 16 px / 1.5; small 14 px; labels 13 px semibold; page title 28 px; section title 20 px.
- 8 px spacing scale: `--s1` 4, `--s2` 8, `--s3` 12, `--s4` 16, `--s5` 24, `--s6` 32, `--s7` 48.
- Radius 10 px (controls), 14 px (cards); borders 1 px `--line`; one restrained shadow for raised layers.
- Text size: standard, large (112.5 %) or larger (125 %), set on `<html>`; type sizes are in rem, so the office
  and every page scale with it (office labels never go below 11 px).
- Density: comfortable (default) or compact (controls 36 px instead of 44 px on desktop; touch targets stay
  44 × 44 px on coarse pointers whatever the density).

## Layout

- Desktop: 232 px collapsible sidebar, 64 px top bar, fluid content up to 1440 px, previews get the widest column.
- 1024 px: sidebar collapses to icons (labels in tooltips and accessible names).
- 768 px and below: navigation drawer, stacked cards, the Make button stays in the top bar.
- 390 px and 320 px: single column, no horizontal page scroll; wide tables become cards.
- Panels on Create, Review and Office can be reordered, hidden and resized (desktop). Layout records are saved
  per device class (`desktop`, `tablet`, `phone`) with a schema version; a phone never inherits desktop sizes.
  At least one panel always stays visible and Reset layout restores the preset without touching edits, styles
  or robot names.

## Motion

Follow system (default), Full or Reduced. Reduced removes decorative motion and keeps state changes as instant
cross-fades. Decorative animation never sits on an essential editing control.
The choice is saved for each browser (the existing Animations setting, `frontend/src/motion.tsx`), never synced from
the account, so one device's accessibility setting is never overridden by another's.

## Components

Buttons (primary, secondary, quiet, danger), icon buttons with labels, segmented control (mode selectors),
cards, status badges (word + icon), progress bars (measured progress only), inline field errors, toasts,
dialogs with focus trap, drawers, tabs, empty states with one next action, and the destination picker
(exact account names and avatars, never just a platform icon).
