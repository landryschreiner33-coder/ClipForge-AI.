"""First-run native import and AAC-clock check; uses only temporary synthetic media."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    print("Checking native Mac dependencies and video/audio tools…", flush=True)
    import ctranslate2
    import cv2
    import faster_whisper
    import av
    import onnxruntime
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from keyring.backends.macOS import Keyring

    # Import checks must not create a Keychain item or download the speech model.
    assert ctranslate2.get_supported_compute_types("cpu")
    assert AESGCM and Keyring and cv2 and faster_whisper and av and onnxruntime
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with tempfile.TemporaryDirectory(prefix="clipfoundry-check-") as scratch:
        os.environ["CLIPFOUNDRY_DATA"] = scratch
        os.environ["CLIPFOUNDRY_WORKERS"] = "off"
        from clipfoundry import db
        from clipfoundry.pipeline.ffmpeg_utils import ffmpeg_bin
        db.init()
        output = Path(scratch) / "test.mp4"
        subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-f", "lavfi", "-i", "color=s=256x256:d=1:r=30", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=1:sample_rate=48000", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-af", "asettb=1/48000,asetpts=N/SR/TB",
                        "-c:a", "aac", "-profile:a", "aac_low", "-ar", "48000", "-ac", "2",
                        "-movflags", "+faststart", str(output)], check=True, timeout=60)
        from clipfoundry.pipeline.audio_timing import require_valid
        require_valid(output)
    print("Native dependencies and synthetic H.264/AAC encoding passed.", flush=True)


if __name__ == "__main__":
    main()
