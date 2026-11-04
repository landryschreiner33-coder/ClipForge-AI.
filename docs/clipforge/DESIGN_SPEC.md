# ClipForge design specification

The studio shell replaces the ClipFoundry top-tab layout. It is a calm, dark-first studio with a light theme of
the same structure. Pixel art stays in the Office; every essential control uses the readable system font.
Tokens live in `frontend/src/theme.css` as CSS custom properties and are switched by `data-theme`,
`data-accent`, `data-density` and `data-motion` on `<html>`.

## Colour tokens

Contrast ratios were computed with the WCAG 2.1 formula (`scripts` not needed; values below are the results).
Every text token reaches at least 4.5:1 on all three surfaces of its theme.

| Token | Dark | Light | Lowest ratio on its surfaces |
| --- | --- | --- | --- |
| `--bg` | `#0B0D14` | `#F5F6FA` | — |
| `--surface` | `#151A25` | `#FFFFFF` | — |
| `--raised` | `#1D2331` | `#EEF0F6` | — |
| `--text` | `#F5F6FA` | `#12141C` | 14.5 / 16.1 |
| `--muted` | `#A8B2C5` | `#4A5263` | 7.4 / 6.9 |
| `--disabled` | `#8C95A8` | `#5F6779` | 5.2 / 5.0 |
| `--accent` (violet, default) | `#9A7CFF` | `#5B3FD0` | 5.0 / 6.0 |
| `--success` | `#46D6C4` | `#0B6E64` | 8.7 / 5.4 |
| `--warn` | `#F2B84B` | `#8A5A00` | 8.8 / 5.2 |
| `--danger` | `#FF7A85` | `#B3261E` | 6.3 / 5.7 |
| `--on-accent` | `#0B0D14` | `#FFFFFF` | 6.2 / 6.9 |

Accent choices (`data-accent`): violet (above), blue `#4FA3FF` / `#1F5FBF`, coral `#FF8A5B` / `#B2461A`,
green `#3DD68C` / `#0E7A45`, pink `#FF6FB5` / `#B0246E`. Each was checked at ≥ 4.5:1 against the dark surfaces;
light coral and light green are 4.87 and 4.74 on `--raised`, so they are used only for borders and icons there.
Status is never colour alone: badges carry a word and an icon.

## Type, spacing and shape

- Font: the system UI stack (`system-ui, -apple-system, "Segoe UI", Roboto, …`); no web-font download.
- Base body 16 px / 1.5; small 14 px; labels 13 px semibold; page title 28 px; section title 20 px.
- 8 px spacing scale: `--s1` 4, `--s2` 8, `--s3` 12, `--s4` 16, `--s5` 24, `--s6` 32, `--s7` 48.
- Radius 10 px (controls), 14 px (cards); borders 1 px `--line`; one restrained shadow for raised layers.
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

## Components

Buttons (primary, secondary, quiet, danger), icon buttons with labels, segmented control (mode selectors),
cards, status badges (word + icon), progress bars (measured progress only), inline field errors, toasts,
dialogs with focus trap, drawers, tabs, empty states with one next action, and the destination picker
(exact account names and avatars, never just a platform icon).
