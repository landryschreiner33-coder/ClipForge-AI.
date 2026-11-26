/**
 * The robot office's Taser (the owner, 2026-11-25: "clicking it on a robot plays a brief cartoon spark and a funny
 * reaction"). Purely for fun: nothing is sent anywhere and the robot's job carries on. The spark is drawn by
 * OfficeMap (space.css .taser-zap); under Reduced motion it shows as a still spark. The sound plays only when
 * Settings → Appearance → Sound effects is on.
 */

const REACTIONS = [
  "Bzzt! My circuits!",
  "Hey! I was rendering!",
  "That tickles!",
  "Ow, my bolts!",
  "Totally fine. Totally fine.",
  "Was that a firmware update?",
  "My antenna is buzzing!",
  "I'll put that in my report.",
  "Static cling! Static cling!",
  "Rebooting my dignity…",
];

let last = -1;
/** A reaction, never the same one twice in a row. */
export function reaction(): string {
  let k = Math.floor(Math.random() * REACTIONS.length);
  if (k === last) k = (k + 1) % REACTIONS.length;
  last = k;
  return REACTIONS[k];
}

let audio: AudioContext | null = null;

/** A short cartoon zap: crackling noise and a falling buzz, about a quarter of a second, quiet. */
export function zapSound() {
  try {
    const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
    if (!Ctor) return;
    audio ||= new Ctor();
    const ctx = audio, now = ctx.currentTime, length = 0.28;
    const out = ctx.createGain();
    out.gain.setValueAtTime(0.0001, now);
    out.gain.exponentialRampToValueAtTime(0.16, now + 0.01);
    out.gain.exponentialRampToValueAtTime(0.0001, now + length);
    out.connect(ctx.destination);
    // the crackle: noise through a band-pass filter
    const noise = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * length), ctx.sampleRate);
    const data = noise.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (Math.random() < 0.3 ? 1 : 0.2);
    const crackle = ctx.createBufferSource();
    crackle.buffer = noise;
    const band = ctx.createBiquadFilter();
    band.type = "bandpass";
    band.frequency.value = 2400;
    band.Q.value = 0.8;
    crackle.connect(band).connect(out);
    // the buzz: a sawtooth falling in pitch
    const buzz = ctx.createOscillator();
    buzz.type = "sawtooth";
    buzz.frequency.setValueAtTime(880, now);
    buzz.frequency.exponentialRampToValueAtTime(110, now + length);
    const quiet = ctx.createGain();
    quiet.gain.value = 0.35;
    buzz.connect(quiet).connect(out);
    crackle.start(now);
    buzz.start(now);
    crackle.stop(now + length);
    buzz.stop(now + length);
  } catch {
    /* no sound: the spark still shows */
  }
}
