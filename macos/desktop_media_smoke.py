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

    decoders = subprocess.check_output([ffmpeg_bin(), '-hide_banner', '-decoders'], stderr=subprocess.STDOUT).decode()
    assert 'libdav1d' in decoders, 'AV1 inputs need the bundled software decoder'
    av1 = Path(__file__).parent / 'desktop/av1-smoke.ivf'
    subprocess.run([ffmpeg_bin(), '-hide_banner', '-loglevel', 'error', '-c:v', 'libdav1d', '-i', str(av1),
                    '-f', 'null', '-'], check=True, timeout=15)
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
    link_import_joins_separate_streams()


def link_import_joins_separate_streams():
    """A video link whose picture and sound come separately (as YouTube serves them) is joined by the bundled
    yt-dlp with the bundled ffmpeg, with only the PATH a Finder-opened app gets. Served from memory: no network."""
    import ipaddress

    import httpx
    from clipfoundry import db, media_import, netguard
    from clipfoundry.jobs import fetch_public_video
    from clipfoundry.pipeline.ffmpeg_utils import ffmpeg_bin, probe

    with tempfile.TemporaryDirectory(prefix='clipfoundry link import ') as tmp:
        folder = Path(tmp)
        os.environ['CLIPFOUNDRY_DATA'] = str(folder / 'profile')
        db.init()
        both = folder / 'both.mp4'
        subprocess.run([ffmpeg_bin(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                        '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=10:duration=2',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2:sample_rate=44100',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', str(both)], check=True, timeout=30)
        files = {}
        for name, keep in (('picture.mp4', '-an'), ('sound.m4a', '-vn')):
            subprocess.run([ffmpeg_bin(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', str(both),
                            keep, '-c', 'copy', str(folder / name)], check=True, timeout=30)
            files['/' + name] = (folder / name).read_bytes()
        files['/watch'] = (b'<html><head><title>Separate streams</title></head><body><video>'
                           b'<source src="/streams.mpd" type="application/dash+xml"></video></body></html>')
        files['/streams.mpd'] = (
            '<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" '
            'mediaPresentationDuration="PT2S" profiles="urn:mpeg:dash:profile:isoff-on-demand:2011"><Period>'
            '<AdaptationSet mimeType="video/mp4"><Representation id="picture" codecs="avc1.64000d" width="320" '
            'height="180" bandwidth="300000"><BaseURL>https://public.example/picture.mp4</BaseURL></Representation>'
            '</AdaptationSet><AdaptationSet mimeType="audio/mp4" lang="en"><Representation id="sound" '
            'codecs="mp4a.40.2" bandwidth="96000" audioSamplingRate="44100"><BaseURL>https://public.example/'
            'sound.m4a</BaseURL></Representation></AdaptationSet></Period></MPD>').encode()
        types = {'/watch': 'text/html', '/streams.mpd': 'application/dash+xml', '/picture.mp4': 'video/mp4',
                 '/sound.m4a': 'audio/mp4'}

        def serve(request):
            body = files.get(request.url.path)
            if body is None:
                return httpx.Response(404, content=b'missing')
            return httpx.Response(200, headers={'Content-Type': types[request.url.path]},
                                  content=b'' if request.method == 'HEAD' else body)

        real_client, real_resolve, real_path = httpx.Client, netguard.resolve, os.environ.get('PATH', '')
        media_import.httpx.Client = lambda **kw: real_client(transport=httpx.MockTransport(serve), **kw)
        netguard.resolve = lambda host: [ipaddress.ip_address('8.8.8.8')]
        os.environ['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'  # a Finder-opened app's PATH: no ffmpeg on it
        try:
            path, _ = fetch_public_video('https://public.example/watch', folder / 'download', max_bytes=50_000_000,
                                         refuse_live=True)
        finally:
            media_import.httpx.Client, netguard.resolve = real_client, real_resolve
            os.environ['PATH'] = real_path
        joined = probe(path)
        assert joined['has_audio'] and joined['width'] == 320 and 1.8 <= joined['duration'] <= 2.2, joined
    print('Bundled link import: separate picture and sound joined by the bundled ffmpeg.', flush=True)
    youtube_javascript_runtime()


def youtube_javascript_runtime():
    """yt-dlp finds the bundled Deno and the yt-dlp-ejs solver it needs for YouTube, with a Finder-opened app's
    PATH, and Deno runs code without any file access (yt-dlp gives it no permissions)."""
    import sysconfig

    import yt_dlp_ejs  # noqa: F401 - the solver yt-dlp runs in Deno
    from clipfoundry import media_import

    real_path = os.environ.get('PATH', '')
    os.environ['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
    try:
        with media_import.public_extractor() as ydl:
            runtime = ydl._js_runtimes.get('deno')
            deno = runtime.info if runtime else None
    finally:
        os.environ['PATH'] = real_path
    assert deno and deno.supported, 'yt-dlp cannot find a usable bundled Deno'
    assert Path(deno.path).parent == Path(sysconfig.get_path('scripts')), deno.path  # the bundled one
    script = 'console.log(6 * 7); try { Deno.readTextFileSync("/etc/hosts"); console.log("read") } ' \
             'catch { console.log("no file access") }'
    out = subprocess.run([deno.path, 'run', '--no-prompt', '--no-remote', '-'], input=script, text=True,
                         capture_output=True, timeout=60, check=True).stdout.split()
    assert out[0] == '42' and 'read' not in out, out
    print(f'Bundled YouTube support: yt-dlp uses Deno {deno.version} (no file access) and yt-dlp-ejs.', flush=True)


if __name__ == '__main__':
    main()
