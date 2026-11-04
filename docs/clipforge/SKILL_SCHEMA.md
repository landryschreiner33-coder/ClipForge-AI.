# ClipForge skill format (`clipforge.skill/v1`)

A skill is a small text file of editing instructions. ClipForge reads the editing choices it actually applies and
shows everything else. **Nothing in a skill is ever executed**: no shell commands, scripts, code blocks, tools,
links or network requests. A skill can never use secrets, change accounts, approve or publish posts, bypass a
check or limit, or reach another workspace; such text is listed as *refused*.

## Accepted files

- `.md`, `.markdown`, `.txt` (UTF-8, at most 200 KB). A Claude-style `SKILL.md` with `name:` and `description:`
  frontmatter is read the same way; its bundled scripts are never run, and full Agent Skills compatibility is not
  claimed.
- `.json` in the versioned schema below.
- ZIP files are not imported.

## JSON schema

```json
{
  "schema": "clipforge.skill/v1",
  "id": "story-captions",
  "name": "Story captions",
  "version": "1",
  "description": "Calm storytelling edits with readable lower captions.",
  "modes": ["highlights", "full_stories", "full_video"],
  "topics": ["travel"],
  "preferences": { "caption_position": "bottom", "feel": "calm", "transition": "dissolve" },
  "instructions": "Any text. Supported lines are recognized; the rest is shown as not applied.",
  "unsupported": [{ "text": "kept from an earlier export", "why": "not applied" }]
}
```

Unknown top-level fields are kept and shown as unsupported; they are not dropped on export.

## Supported choices (the capability registry, `clipfoundry/studio/capabilities.py`)

| Field | Values | Modes |
| --- | --- | --- |
| `caption_style` | clean, bold, high_energy, minimal | all |
| `caption_position` | bottom, middle, top | all |
| `caption_emphasis` | true / false | Highlights, Full stories |
| `captions` | true / false | Full video |
| `pacing` | safe_cuts, continuous | Highlights |
| `layout` | fill, fit | all |
| `tracking` | auto, center, face, speaker, screen | Highlights, Full stories |
| `feel` | calm, balanced, energetic | Full video |
| `transition` | cut, dissolve, fade | Full video |
| `aspect_ratio` | 16:9, 9:16, 1:1, 4:5 | Full video |
| `target_duration_s` | 0 (use your judgment) to 14400 | Full video |
| `music` | none, supplied | Full video |
| `music_level_db` | -36 to -6 | Full video |
| `title_card` | true / false | Full video |

Plain-language lines such as "Keep captions in the lower third", "Use a calm, storytelling pace", "Join clips with
short dissolves" or "Open with a title card" are recognized. Two lines that disagree about the same choice cancel each
other and are shown as contradictory.

## How a skill is used

Import → preview (what it would change, what is not applied, what was refused) → switch it on. Enabled skills apply
to new projects at the skill level of the guidance order: project choice > style > skills chosen for the project >
enabled skills > Brain notes > Settings. Two skills at the same level that disagree are shown as a conflict and
neither wins. Each project records the skill's ID and revision in its guidance snapshot; editing a skill later does
not change projects that already used it. Export writes this same format.

The bundled example is `clipfoundry/studio/examples/story-captions.skill.md` (Brain → Skills → Add the example skill).
