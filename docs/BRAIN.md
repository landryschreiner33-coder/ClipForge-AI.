# The Brain: test feedback and careful learning

The Brain (`clipfoundry/brain.py`, API `/api/brain`) remembers what your **selected test viewers** did with each clip.
Only under strict guards does it change one thing: the Autopilot's **target clip length**.

It is not an autonomous agent. It never touches code, keys, privacy, audience settings, spending caps or safety
limits, and it never claims that learning made clips better.

## Where evidence comes from (kept apart)

| Source | What it is | How it gets in |
| --- | --- | --- |
| **Platform API** | Numbers the platform's API reported | Automatically, from the existing statistics refresh |
| **Your import** | Numbers you read on the platform's own screens or exports | Clips → Test feedback form, or a CSV import |
| **Tester feedback** | What a tester told you: ratings 1–5 for hook, context, payoff, captions and overall, a comment, and where they stopped watching | The same form, under *What a tester told me*. It is labeled **self-reported** and is never shown as measured watch time |

- A number nobody reported stays empty. It is never stored as zero.
- Importing the same reading twice stores it once.
- A different value for the same reading is a **correction**. It replaces the old value as a new version and is never
  added to it.
- **YouTube API numbers** steer nothing until you confirm that Google approved derived metrics for your project. That
  is the existing `youtube_derived_metrics_approved` setting, which follows YouTube's Developer Policies. Your own
  imports and tester answers are not API data.

## Test groups (cohorts)

Results are grouped by who saw the clip:

| Group | Example id |
| --- | --- |
| YouTube invited viewers | `selected:youtube:invited:v1` |
| TikTok approved followers | `selected:tiktok:followers:v1` |
| Only-me staging | `owner:youtube`. Not a test group |
| Older public posts | `public:youtube`. Never mixed with test groups, and never changed by them |

When you change who is in a group, raise its **group version** in the audience settings. Results from the new group
are then kept separate from the old one.

> A handful of invited friends is not the public. Their results show how *this* group responded, not how a wide
> audience would.

## The one thing it learns: clip length

The Brain can move the target length when all of these hold:

- at least **30** clips from at least **10** different source videos;
- each clip has at least **3** viewers;
- each clip's results are at least **48 h** old;
- when tester ratings are used, at least **5** different testers. The same few people rating many clips is not
  independent evidence.

Then:

1. Clips are grouped as short (<25 s), medium (25–45 s) and long (≥45 s). Clips from the same source are averaged
   first.
2. The best group must beat the rest by more than **two standard errors**. Otherwise the result is *No clear difference
   yet* and nothing changes.
3. The target moves toward the better length by **at most 10 %** per update, within 12–90 s. For example, 30 s becomes
   27 s, not 15 s.
4. The change is saved as a **strategy version** with its evidence. New Autopilot projects record which version they
   used (`strategy_version` in the project's options).
5. **Rollback**: Brain Room → *Roll back* reactivates the previous version, or the baseline. Nothing is deleted.

Without enough evidence it says **Not enough evidence yet** and keeps the baseline (the *target length* setting).

The guards are settings (`brain_*` in `config.py`) and can only be made stricter. For example, the minimum is 30 clips
and the largest step is 10 %.

## Brain states

| State | Meaning |
| --- | --- |
| Cold start | No observations yet |
| Collecting data | Observations exist; not enough for a change |
| Evaluating | Enough clips in a group; the next learning run compares them |
| Strategy updated | A change was applied in the last 7 days |
| Paused | Learning is off (Autopilot settings) |
| Error | The last evaluation failed; other work continues |

Per clip, Test feedback shows one of:

- *Awaiting viewer access*
- *Awaiting observations*
- *API data available*
- *Manual feedback available*
- *Insufficient evidence*
- *Analytics unavailable*

## CSV import

Use **Preview** first. Every row is checked before anything is stored. If any row has a problem, nothing is imported
until you fix it.

Long format (one number per row):

```csv
clip_id,platform,observed_at,metric,value,sample_size
a1b2c3d4e5f6,youtube,2026-10-07T18:00,avg_view_percentage,61.5,7
```

Wide format (one column per metric):

```csv
clip_id,platform,observed_at,views,avg_view_percentage,likes
a1b2c3d4e5f6,youtube,2026-10-07T18:00,14,61.5,
```

- `platform_video_id` can replace `clip_id` for an upload ClipFoundry knows.
- Known metrics: `views`, `watch_time_minutes`, `avg_view_duration_s`, `avg_view_percentage`, `completion_rate`,
  `rewatches`, `likes`, `comments`, `shares`, `impressions`, `ctr`, `audience_size`.
- Optional columns: `window_start`, `window_end`, `unit`, `audience_group`.

## Experiments

`assign_variant` gives each clip a stable variant. At most 10 % of clips are explored. `compare_arms` declares a winner
only with at least 20 clips per variant and a difference beyond two standard errors. Otherwise the result is
*inconclusive*.
