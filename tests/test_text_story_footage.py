"""Text Stories: free background footage found from the page (Settings → Media sources), copied into your videos
with where it came from and its license, then put behind the story. Only footage whose license allows trimming and
use in any video is offered (the media search's own "fits" rule), and a required credit travels with the pick."""
from __future__ import annotations

from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "frontend/src/pages/TextStories.tsx"


def test_the_background_step_can_find_free_footage_and_use_it():
    page = PAGE.read_text(encoding="utf-8")
    assert "Find free footage" in page and "function FreeFootage" in page
    assert 'studio.searchMedia({ kind: "footage", query: words.trim(), filters: { license: "fits" } })' in page
    assert "r.fits.eligible" in page and "(r.duration_s ?? 0) >= 5" in page   # a background runs 5 s or more
    assert "studio.importMedia({ result_id: r.id })" in page and "studio.mediaImport(job.id)" in page
    assert "Free footage from ${r.provider_name} (${r.license_name})." in page and "Credit: ${r.credit}" in page
    assert "Settings → Media sources" in page
    # the copy can take minutes: the footage joins the backgrounds as they are then, and a remount keeps working
    assert "latestUse.current = onUse;" in page and "latestUse.current({ asset_id: job.asset_id" in page
    assert "alive.current = true;" in page


def test_an_imported_video_is_a_background_the_story_accepts(tmp_path, monkeypatch):
    """What an import leaves behind (a video in your videos) passes the story's own background check."""
    import subprocess

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.makers import textstory
    from clipfoundry.pipeline.ffmpeg_utils import ffmpeg_bin
    from clipfoundry.studio import uploads

    db.init()
    clip = tmp_path / "Waves at dusk.mp4"
    subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=180x320:r=24:d=6",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    asset = uploads.store_file("local", clip, clip.name)
    got = textstory._clean_backgrounds("local", [{"asset_id": asset["id"], "in_s": 0, "out_s": 6, "loop": True,
                                                   "why": "Free footage from Wikimedia Commons (CC BY 4.0)."}])
    assert got[0]["asset_id"] == asset["id"] and got[0]["out_s"] <= 6 and got[0]["why"].startswith("Free footage")
    assert any(b["asset_id"] == asset["id"] for b in textstory.usable_backgrounds("local"))
