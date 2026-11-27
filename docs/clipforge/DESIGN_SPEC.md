# ClipForge design specification

ClipForge looks like the room it stands in for: an edit bay. Dark, layered surfaces lit from their top edge, sunken
wells for the things you put media into (drop zones, timelines, chats, lists), lifted controls, and the pictures the
brightest thing on every page. One accent colour is for the action that moves work forward and the place you are in;
everything else is quiet. It is **dark only**: there is no light theme and no "follow system" theme (a saved Light or
System choice is dropped and every other choice kept). Pixel art stays in the robot office; every essential control
uses the readable system font.

Where it lives:

- `frontend/src/styles.css` is the design system: fonts, type scale, spacing, shape, light and depth, and every
  shared component (shell, buttons, panels, forms, media, editors, dialogs, loading and empty states, the office).
- `frontend/src/theme.css` holds only what Customize studio can change: the four palettes, the six accents, density,
  text size and reduced motion, switched by `data-palette`, `data-accent`, `data-density`, `data-text` and
  `data-motion` on `<html>`. `tests/test_theme_contrast.py` reads it.
- Page stylesheets (`pages/editor.css`, `library.css`, `posts.css`, `Brain.css`, `BrainGraph.css`,
  `office/studio.css`, `components/TikTokSetup.css`) hold only a page's own layout and are drawn from the same tokens.
- `index.html` sets `color-scheme: dark` and the canvas colour inline, and `public/appearance-boot.js` applies the saved
  palette, accent, spacing and text size before the app's script runs, so there is no flash. Customize studio is the one
  place these are changed (see [STUDIO_UPGRADE_MATRIX.md](STUDIO_UPGRADE_MATRIX.md), CF2-21).

Before and after pictures of the November 2026 redesign are in [ui-redesign/](ui-redesign/).

## Colour tokens

Contrast ratios use the WCAG 2.1 formula. `tests/test_theme_contrast.py` fails if any palette or accent drops below
4.5:1 for text (including status words and accent links) or 3:1 for focus rings and control borders, so the values
below cannot drift without a failing test.

Studio palette (default):

| Token | Value | Use |
| --- | --- | --- |
| `--canvas` | `#0A0C12` | page background |
| `--surface` | `#11151E` | panels and cards |
| `--raised` | `#181D28` | controls, menus, inner rows that stand up |
| `--hover` | `#202633` | hover fills |
| `--well` | canvas 62 % + surface | sunken areas: drop zones, timelines, chats, inner lists (computed in `styles.css`) |
| `--frame` | `#05060A` | the stage behind a video player |
| `--text` / `--text-2` / `--text-3` | `#F5F6FA` / `#D0D5E0` / `#A8B2C5` | body, secondary and quiet text (quiet text never below 6:1) |
| `--good` / `--warn` / `--bad` / `--info` | `#46D6C4` / `#F2B84B` / `#FF7A85` / `#6FB8FF` | status, always with a word and an icon; each has a `-tint` fill |
| `--focus` | `#7FD3FF` | focus ring (2 px, offset 2 px) |
| `--control-border` | `#7D879B` | input outlines (3:1) |
| `--on-primary` | `#0B0D14` | text on accent buttons |

Other palettes change only the surfaces; text, status and accent colours stay the same and are checked on each:

| Palette | Canvas | Surface | Raised | Hover | Lowest `--text-3` ratio |
| --- | --- | --- | --- | --- | --- |
| Studio | `#0A0C12` | `#11151E` | `#181D28` | `#202633` | 7.10 |
| Midnight | `#070B18` | `#0E1529` | `#151D3B` | `#1C2548` | 6.99 |
| Graphite | `#0D0E10` | `#151619` | `#1C1D21` | `#24262B` | 7.09 |
| Plum | `#0F0A16` | `#180F22` | `#20162D` | `#2A1F3A` | 7.26 |

Accents (`data-accent`), lowest ratio as text on any palette's canvas, surface or raised layer, and on the accent's
own tint:

| Accent | Primary | Hover | Tint | Lowest on surfaces | On its tint |
| --- | --- | --- | --- | --- | --- |
| Violet (default) | `#9A7CFF` | `#B29BFF` | `#241D45` | 5.27 | 5.01 |
| Teal | `#2DD4BF` | `#5EEAD4` | `#0F2E2B` | 8.88 | 7.80 |
| Blue | `#4FA3FF` | `#7DBBFF` | `#12263F` | 6.31 | 5.83 |
| Coral | `#FF8A5B` | `#FFA884` | `#3A2117` | 7.11 | 6.41 |
| Green | `#3DD68C` | `#6BE3A8` | `#10301F` | 8.81 | 7.64 |
| Pink | `#FF6FB5` | `#FF96C8` | `#3A1730` | 6.45 | 6.09 |

Status is never colour alone: pills and banners carry a word and an icon. The robots' own colours (`--cyan`,
`--magenta`, `--violet`, `--mint`, `--orange`) mark equipment and the office, never the main action.

## Light and depth

Every layer says what it is by how it catches light, not by a heavier border:

- **Lit surfaces** (`--lift`): panels, cards and menus have a 1 px lighter line along their top edge (`--edge`), a
  1 px border (`--line`) and a soft shadow that falls down and away. `--lift-sm` is the same for buttons and small rows.
- **Wells** (`--sink` on `--well`): the places you put media into or read along sink into their surface with an inset
  shadow: drop zones, the timeline track, the transcript words, chats, inner lists, the sequence, choice cards before
  they are chosen. A chosen card rises to the accent tint and loses the inset.
- **Lifted controls**: `.btn` stands on `--raised` with `--lift-sm`, presses with `--sink`; the primary button has an
  inner highlight and an accent-coloured shadow. Inputs are wells with `--control-border`; focus turns the border to
  the accent and adds the ring.
- **The stage**: players sit on `--frame`, the darkest surface, with a 1 px light ring and a deep shadow, so the
  footage is the brightest thing in the editor. Thumbnails are lit wells with a hairline ring.
- **Overlays** (`--shadow-overlay`): dialogs, menus, the save bar and toasts float with one long shadow; the save bar
  and the top bar blur what passes behind them.
- **Glow** (`--glow`): only the accent's own things glow: the frame shapes on the Studio page and a drop zone while a
  file is over it.

## Type, spacing and shape

- **Display face:** Poppins SemiBold (`--font-display`, bundled in `frontend/src/assets/fonts/`, the same face ClipForge
  burns into captions) for page titles, section titles and the few numbers that matter. **Body:** the system UI
  stack (`system-ui, -apple-system, "Segoe UI", Roboto, …`). **Pixel face** (`--font-pixel`): only the robot office's
  titles and names.
- Scale: body 15 px / 1.5 (`--fs-body`), supporting 13 px (`--fs-small`), timestamps and counters 12 px (`--fs-tiny`,
  the smallest text anywhere), card title 15 px (`--fs-h3`), section title 17 px (`--fs-h2`), page title 28 px
  (`--fs-title`, 24 px on narrow windows). Titles are sentence case; no all-caps labels.
- 8 px spacing scale: `--s1` 4, `--s2` 8, `--s3` 12, `--s4` 16, `--s5` 24, `--s6` 32, `--s7` 48; panel padding 22 px;
  page gap 24 px.
- Radius: 8 px controls and inputs (`--r-control`), 12 px panels and cards (`--r-panel`), 16 px the big things
  (`--r-lg`: drop zones, dialogs, the Studio's choices, empty states), 6 px small tags, pills round.
- Controls are 36 px tall (`--control`); compact density makes them 32 px; on a coarse pointer they are 44 px whatever
  the density. Small buttons are 30 px (40 px on touch).
- Text size: standard, large (112.5 %) or larger (125 %), set on `<html>`; type sizes are in rem, so the office and
  every page scale with it.

## Layout

- **Shell:** 236 px collapsible sidebar (212 px under 1366 px wide; 72 px icon rail when collapsed) on `--surface`,
  56 px blurred top bar, content up to 1280 px wide with 32 px around it. The place you are in is marked in the rail
  with the accent tint and a 3 px accent bar.
- **Page head:** the page's kind in small quiet text, one title, one supporting line, the actions at the right, a
  hairline under it. Breadcrumbs above it where the page has a parent.
- **Settings:** the sections as a side list (196 px, sticky) with the same accent mark as the rail; content up to 860 px
  (Appearance uses the full width). Under 900 px the list becomes the usual scrolling tab row.
- **Editors:** the stage and the timeline on the left, the desk (tabs and the save bar) on the right; under 1100 px
  they stack. Panels on Review are placed by `LayoutFlow` (`components/AppearanceSettings.tsx`), which packs sized
  panels into columns: a panel goes under the earlier panel with the same place and width, so the player sits above the
  look settings while the long sequence runs down the other column, with no hole beside a tall panel. Default widths
  (`prefs.py REVIEW_SIZE`): preview 0.6, outputs 0.4, transcript 0.6, guidance 0.4.
- 1023 px and below: navigation drawer, the Make button stays in the top bar. 639 px and below: every panel column is
  full width. 390 px and 320 px: single column, no horizontal page scroll; wide tables become cards.
- Panels on the Studio page and Review can be reordered, hidden and resized (desktop). Layout records are saved per
  device class (`desktop`, `tablet`, `phone`) with a schema version; a phone never inherits desktop sizes. At least one
  panel always stays visible and Reset layout restores the preset without touching edits, styles or robot names.

## Motion

Follow system (default), Full or Reduced. Reduced removes decorative motion and keeps state changes as instant
cross-fades. Decorative animation never sits on an essential editing control. The choice is saved for each browser
(the existing Animations setting, `frontend/src/motion.tsx`), never synced from the account, so one device's
accessibility setting is never overridden by another's. Loading skeletons shimmer once per 1.6 s and pause when the
tab is hidden.

## Components

Buttons (primary, secondary, quiet, danger; small; icon), segmented controls and switches on wells, choice cards
(well → accent tint when chosen), pills (word + icon), tags, lit panels and cards, banners with a 4 px tone bar,
progress bars (measured progress only), inline field errors, toasts, dialogs with focus trap, drawers, tabs
(underline, or the side list), the destination picker (exact account names and avatars, never just a platform icon),
skeleton pages (title block, then panel-shaped blocks, never a spinner on a blank page), and empty states: a 56 px
accent disc with the icon, one sentence that says what will appear here, one next action.

## The robot office

The office sits on the same surfaces as the rest of the app, so the owner's palette reaches it. What stays its own:
the pixel face for titles and robot names, each robot's and room's colour (set inline as `--accent` and used for the
panel's top edge, the team cards' left edge and the room signs), and a brass caption colour for the small notes over
the map. The map is a framed window with its legend as the bottom rail; on a laptop-height window the whole office,
details and controls fit without scrolling (`office/studio.css`).
