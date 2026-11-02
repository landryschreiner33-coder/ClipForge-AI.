"""Exercise the shipped renderer, captions and audio clock using synthetic media."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import numpy as np
    from clipfoundry import db
    from clipfoundry.pipeline import audio_timing, render
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import ffmpeg_bin, probe

    with tempfile.TemporaryDirectory(prefix='clipfoundry native render ') as tmp:
        folder = Path(tmp)
        os.environ['CLIPFOUNDRY_DATA'] = str(folder / 'profile')
        db.init()
        source = folder / 'synthetic source.mp4'
        subprocess.run([ffmpeg_bin(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                        '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=10:duration=3',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3:sample_rate=44100',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', str(source)], check=True, timeout=30)
        meta = probe(source)
        project = {'id': 'native-check', 'name': 'Synthetic local media', 'source_path': str(source),
                   'dir': str(folder / 'project'), 'info': meta, 'options': {}, **meta}
        clip = {'id': 'native-clip', 'project_id': project['id'], 'start': .2, 'end': 2.7, 'hook': '',
                'edit': {'tracking': 'center', 'silence': 'off', 'auto_zoom': False, 'hook_overlay': False}}
        words = [{'w': word, 'start': .3 + i * .45, 'end': .65 + i * .45}
                 for i, word in enumerate(('Your', 'next', 'great', 'clip.'))]
        result = render.render_clip(project, clip, words,
                                    {**db.get_settings(), 'encoder': 'x264', 'x264_preset': 'ultrafast'}, JobContext())
        target = Path(result['output_path'])
        audio_timing.require_valid(target)
        assert probe(target)['width'] == 1080 and probe(target)['height'] == 1920
        ass = (target.parent / 'captions.ass').read_text()
        assert 'Dialogue:' in ass and 'clip.' in ass.lower()
        decoded = subprocess.check_output([ffmpeg_bin(), '-hide_banner', '-loglevel', 'error', '-i', str(target),
                                           '-vn', '-ac', '1', '-ar', '48000', '-f', 'f32le', 'pipe:1'], timeout=30)
        samples = np.frombuffer(decoded, dtype='<f4')
        def rms(a, b):
            return float(np.sqrt(np.mean(samples[int(a*48000):int(b*48000)] ** 2)))
        assert rms(.15, .45) > .005
        assert .90 < rms(.15, .45) / rms(1.2, 1.5) < 1.10, 'Audio changed level after startup'
        assert result['render_info']['audio_processing']['packet_timing']['valid']
    print('Bundled production renderer: 1080x1920 captions, stable startup audio and raw AAC timing passed.', flush=True)


if __name__ == '__main__':
    main()
