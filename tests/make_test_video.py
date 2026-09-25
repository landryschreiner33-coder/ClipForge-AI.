"""Build a synthetic 'talking head' test video with speech + an SRT transcript.

Speech comes from espeak-ng (if installed); the picture is a real face photo
that drifts around a 16:9 frame with a few hard cuts, so face tracking, scene
cut handling, captions and silence cleanup are all exercised.

    python tests/make_test_video.py out_dir [face.png]
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SCRIPT = [
    "Here's the biggest mistake most people make when they start a business.",
    "They spend months building a product nobody asked for.",
    "I did exactly that. I spent a whole year and all my savings on it.",
    "And when we launched, we got three customers. Three.",
    "So what changed? I started talking to people before building anything.",
    "That's why my second company made money in the first month.",
    "The lesson is simple. Talk to customers first, then build.",
    "Um, okay, let's move on to something else.",
    "People ask me about the weather in the mountains a lot.",
    "It is usually cold. Sometimes it rains. That is about it.",
    "Why do most diets fail after two weeks?",
    "Because willpower is a terrible strategy.",
    "Your environment beats your motivation every single time.",
    "If there is no junk food in your house, you simply cannot eat it.",
    "That is the whole secret. Change the environment, not your mindset.",
    "Anyway, uh, that was a lot of talking.",
    "Let me tell you a story about the worst day of my career.",
    "I was on stage in front of two thousand people and my laptop died.",
    "No slides. No notes. Nothing.",
    "So I just told the truth about how scared I was.",
    "And it turned out to be the best talk I ever gave.",
    "Honestly, the audience loved it because it was real.",
    "In the end, being honest beat being perfect.",
    "Next week we will talk about the schedule and some logistics.",
    "The meeting is on Tuesday. Bring your notes. That's all for today.",
]

W, H, FPS = 1280, 720, 25


def synth(out_dir: Path) -> tuple[Path, Path, float]:
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if not espeak:
        raise SystemExit("espeak-ng is required to build the test video")
    sr = 22050
    audio = []
    cues = []
    t = 0.6
    audio.append(np.zeros(int(sr * t), dtype=np.int16))
    for i, line in enumerate(SCRIPT):
        tmp = out_dir / f"_s{i}.wav"
        subprocess.run([espeak, "-s", "165", "-w", str(tmp), line], check=True)
        with wave.open(str(tmp)) as wf:
            data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
            rate = wf.getframerate()
        tmp.unlink()
        if rate != sr:
            idx = np.linspace(0, len(data) - 1, int(len(data) * sr / rate)).astype(int)
            data = data[idx]
        # trim espeak's own leading/trailing silence
        nz = np.where(np.abs(data) > 300)[0]
        if len(nz):
            data = data[max(0, nz[0] - 200): nz[-1] + 200]
        dur = len(data) / sr
        cues.append((t, t + dur, line))
        audio.append(data)
        gap = 1.6 if line.startswith(("Um", "Anyway")) else (0.35 if i % 3 else 0.7)
        audio.append(np.zeros(int(sr * gap), dtype=np.int16))
        t += dur + gap
    wav = out_dir / "speech.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(np.concatenate(audio).tobytes())

    def ts(x: float) -> str:
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    srt = out_dir / "speech.srt"
    srt.write_text("\n".join(f"{k}\n{ts(a)} --> {ts(b)}\n{txt}\n" for k, (a, b, txt) in enumerate(cues, 1)))
    return wav, srt, t


def render(out_dir: Path, wav: Path, total: float, face_path: Path | None) -> Path:
    import cv2

    face = cv2.imread(str(face_path)) if face_path and face_path.exists() else None
    if face is not None:
        face = cv2.resize(face, (300, 300))
    n = int(total * FPS)
    out = out_dir / "talk.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-framerate", str(FPS), "-i", "pipe:0", "-i", str(wav), "-c:v", "libx264", "-preset", "ultrafast",
           "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    yy, xx = np.mgrid[0:H, 0:W]
    scenes = [0.0, total * 0.33, total * 0.66]
    for k in range(n):
        t = k / FPS
        scene = sum(1 for s in scenes if t >= s) - 1
        base = np.zeros((H, W, 3), np.uint8)
        hue = [(40, 30, 90), (90, 50, 30), (30, 80, 40)][scene]
        base[:] = hue
        base[..., 0] = (base[..., 0] + (xx / W * 60)).astype(np.uint8)
        # face drifts slowly; each scene places it somewhere else
        anchor = [0.25, 0.7, 0.45][scene]
        x = int((anchor + 0.12 * np.sin(t / 4.0)) * W) - 150
        y = H // 2 - 150 + int(20 * np.sin(t / 1.7))
        if face is not None:
            x = max(0, min(W - 300, x))
            base[y:y + 300, x:x + 300] = face
        cv2.putText(base, f"scene {scene + 1}", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
        proc.stdin.write(base.tobytes())
    proc.stdin.close()
    proc.wait()
    return out


if __name__ == "__main__":
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "test_media")
    out_dir.mkdir(parents=True, exist_ok=True)
    face = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    wav, srt, total = synth(out_dir)
    video = render(out_dir, wav, total, face)
    print(video, srt, f"{total:.1f}s")
