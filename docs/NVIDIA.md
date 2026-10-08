# Optional NVIDIA AI (build.nvidia.com)

ClipFoundry works fully without it. When it is on, an NVIDIA-hosted text model can help rank transcript moments and
write titles. Everything else stays on your PC: transcription, timing, face tracking, rendering and captions.

A text model reads only text. It doesn't see the video or hear the audio, doesn't know what is trending, and can't
check the finished clip.

Code: `clipfoundry/pipeline/nvidia.py`. Tests: `tests/test_nvidia.py`, which use a mocked transport with no key and no
network.

## Status

| Part | Status |
| --- | --- |
| Adapter, budgets, validation, fallback, Integrations card | Implemented and tested (mocked) |
| A real request to NVIDIA | **Implemented; live verification pending.** No key was used during development |
| Model `nvidia/nemotron-3.5-lightning-30b-a3b` | A candidate to evaluate, not a proven best choice. Its availability can change |
| NVIDIA's terms for your use | **Needs user action.** They were not reviewed in this development session; record what you checked in *Terms checked* |

## Set it up

1. Open the [NVIDIA API Catalog](https://build.nvidia.com/explore/discover) and the
   [model page](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b). Sign in, then get an API key through
   NVIDIA's own flow. Read the current [terms](https://developer.nvidia.com/legal/terms) and the
   [prototyping guidance](https://docs.api.nvidia.com/nim/docs/run-anywhere): catalog access is for development and
   prototyping, and it isn't unlimited.
2. In ClipFoundry go to **Settings → Integrations → NVIDIA AI (optional)**. Paste the key into the masked field, or set
   `NVIDIA_API_KEY` in the environment that starts ClipFoundry. Never paste it into a chat, a screenshot or a file in
   this repository.
3. Turn on **Enable**, then tick **Cloud AI opt-in**. That means short transcript excerpts and the titles or
   descriptions of approved clips are sent to NVIDIA. Never sent: keys, account tokens, media files or links, viewer
   names or emails.
4. Set **AI scoring provider** to *NVIDIA* (Settings → Advanced → AI scoring) if you want it used for scoring and post
   text.
5. Press **Run small AI test**. It sends one harmless sentence and uses a little of today's budget. Nothing is ever
   tested automatically, whether on page load, when you save a key, or at start-up.
6. **Disconnect** clears the saved key and stops new calls. Your clips and the usage history stay.

## Limits that always apply

- **Experimental / development** (the default mode) is used only for things you start yourself, never for unattended
  Autopilot jobs. Autopilot then uses local analysis.
- **Production** mode needs all of these:
  - an HTTPS endpoint you configured whose terms allow production use;
  - your confirmation of those terms;
  - a known price per million tokens;
  - for a paid endpoint, a daily **spending cap** above $0. The cap defaults to $0.

  An unknown price is never treated as free.
- Every request **reserves** its worst case against today's request, token and spend limits before it is sent, so
  concurrent jobs can't overspend. Retries and the one repair request count. A timeout keeps the worst case counted,
  because it may have been processed.
- The key is sent only over HTTPS to `integrate.api.nvidia.com`, or to your configured production host. Redirects are
  never followed.
- Every answer is checked locally:
  - segment IDs exist;
  - times are not reversed;
  - scores are in range;
  - evidence refers to given segments.

  An invalid answer gets **one** repair request, then local analysis is used. Nothing is invented.
- Repeated failures, rate limits (with `Retry-After`) or server errors pause the integration for 15 minutes. Other
  work goes on.
- Results are cached by model, prompt/schema version and transcript content, so the same source isn't paid for twice.

Adding this adapter doesn't change which model or account Claude Code (the coding assistant) uses, and no
subscription credit covers these requests.
