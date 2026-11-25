"""Full Cloud: Make clips projects run on the owner's own ClipForge worker (the final-release prompt, section 6).

Settings → Processing chooses where clip-making runs:

* **Local**: everything on this computer.
* **Hybrid**: clip-making on this computer, pictures and video for shorts on the cloud computer (Settings → Cloud
  computer, engines/remote.py).
* **Full Cloud**: the whole clip pipeline (getting the video, transcription, finding the moments, framing,
  captions and rendering) on a ClipForge worker: the same ClipForge, started on a rented computer with
  ``CLIPFOUNDRY_WORKER_KEY`` set (deploy/WORKER.md). This computer uploads the video (or sends the link, and the
  worker downloads it), follows the job, and brings the finished clips back into the project, which then works like
  any other: edit, render again, publish.

Parts: worker_api.py (the worker's side), client.py (this computer talking to it), runner.py (a project on the
worker: upload, follow, stop, bring back, pick up again after a restart), usage.py (worker time, estimates and the
monthly limit), testjob.py (the private test job) and routes.py (Settings → Processing).

What never leaves this computer: accounts and publishing, Autopilot, live streams, animated shorts, Text Stories,
Make a YouTube video and FilmCraft, ClipForge AI's own settings and keys, and the Brain. The worker uses its own
transcription model and its own AI setup; the clip choices of Settings (lengths, captions, framing, sound) go with
each job.
"""
