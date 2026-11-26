"""Cancel upload on the two uploads that had none (Landry, point 4: "cancel an upload as it's uploading so it doesn't
stall"): a Text Story's background clip and a separate face cam recording. Checked in the page code: the button
stops the transfer, and for chunked uploads the server is asked to delete what arrived."""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "frontend" / "src"


def test_a_text_story_background_upload_can_be_canceled_and_the_server_drops_what_arrived():
    page = (SRC / "pages" / "TextStories.tsx").read_text()
    assert "import { cancelUpload, uploadFile }" in page
    assert "now.ctl.signal" in page and "now.ctl.abort()" in page   # the transfer stops
    assert "await cancelUpload(now.id, now.file)" in page             # and the server deletes the parts it has
    assert "Cancel upload</button>" in page
    assert "Nothing was kept; your file is still on this computer." in page


def test_a_face_cam_recording_upload_can_be_canceled_before_it_is_lined_up():
    api = (SRC / "api.ts").read_text()
    start = api.index("export function uploadCamera(")
    body = api[start:api.index("\n}\n", start)]
    assert "signal?: AbortSignal" in body and "xhr.abort()" in body and "xhr.onabort" in body
    assert "export class UploadCanceled extends Error" in api
    cam = (SRC / "components" / "faceCam.tsx").read_text()
    assert "uploadCamera(project.id, file, \"\", setUpload, ctl.signal)" in cam
    assert "sending.current?.abort()" in cam and "Cancel upload</button>" in cam
    assert "{upload < 1 && <button" in cam   # once every byte is sent the server is lining it up: no Cancel then
