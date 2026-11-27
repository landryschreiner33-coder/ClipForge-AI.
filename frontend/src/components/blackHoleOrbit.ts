/**
 * The black hole seen from the ship as it orbits (the owner, 2026-11-25: "the ship and camera visibly orbit the black
 * hole … use Interstellar as a visual reference … visible light bending above and below the shadow").
 *
 * Every pixel follows its ray of light backwards from the camera, bent by the hole's gravity (a Schwarzschild hole:
 * the bending of light, a = -3/2 h² r / |r|⁵ with the hole's radius as the unit, the way the Interstellar paper
 * arXiv:1502.03808 and many small shaders after it trace light). Where a ray crosses the disk it picks up the disk's
 * light; where it falls into the hole it is black; where it leaves, it shows the stars behind, bent into a ring
 * round the shadow. So the far side of the disk shows bent over the top of the shadow and, fainter, under it, and
 * the whole picture changes as the camera goes round: the tilt of the disk, its brighter side, the bent stars.
 *
 * The camera rides with the ship round the hole in ORBIT seconds, rising and sinking a little each time round so the
 * disk is seen from different heights. `orbitPose` says where it is at a moment; the ship drawn in front
 * (shipArt.ts) banks with the same numbers. Drawn smaller than the screen and stretched (the disk is soft), at most
 * MAX_PIXELS a frame; a computer that cannot keep up gets the lighter hole (blackHoleGl.ts) instead.
 */

/** Seconds for one turn round the hole: slow enough to be calm, quick enough to see it move in a few seconds. */
export const ORBIT = 150;
/**
 * The camera's distance from the hole, in the hole's radius. Far enough that the near side of the disk is a thin band
 * across the shadow, with the shadow black above and below it (as in Interstellar); from closer the near side looms
 * over the lower half of the shadow like a bowl.
 */
const DIST = 70;
/** The disk's inner and outer edge, in the hole's radius (the inner edge is the last stable orbit, 3). */
const RIN = 3.0, ROUT = 10.5;
/** Where the light is traced step by step, in the hole's radius: further out it runs straight enough to skip. */
const NEAR = 25;
/** The size of the hole's shadow seen from far away, in the hole's radius (√27 / 2). */
const SHADOW = 2.598;
/** Seconds of turning after which the shader's time starts again (see `draw`). */
const WRAP = 1800;
/** At most this many pixels are traced a frame; the picture is stretched to the canvas. */
const MAX_PIXELS = 240_000;

export type OrbitPose = {
  /** how far round the hole, radians */
  phi: number;
  /** the camera's height above the disk, radians */
  incl: number;
  /** the ship's bank, radians */
  roll: number;
};

/** The camera's usual height above the disk, radians (about 4.5°): low, so the disk reads as a thin band. */
export const TILT = 0.08;

/** Where the camera (and the ship) is `t` seconds into the orbit. */
export function orbitPose(t: number): OrbitPose {
  const phi = (t / ORBIT) * Math.PI * 2;
  return {
    phi,
    // from about 2° to about 7.5° above the disk and back, twice a turn: the disk opens and closes
    incl: TILT + 0.05 * Math.sin(phi * 2 + 0.6),
    roll: 0.07 * Math.sin(phi * 2 + 2.2),
  };
}

const VS = `
attribute vec2 aCorner;
void main() { gl_Position = vec4(aCorner, 0.0, 1.0); }`;

const FS = (steps: number) => `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform vec2 uRes;     // traced pixels
uniform vec2 uMid;     // where the hole's centre is, in traced pixels
uniform vec3 uCam;     // the camera, in the hole's radius; the disk lies in y = 0
uniform vec3 uRight;
uniform vec3 uUp;
uniform vec3 uFwd;
uniform float uTan;    // tan of the angle one traced pixel spans
uniform float uTimeA;  // seconds of turning, wrapped (WRAP): one picture of the disk ...
uniform float uTimeB;  // ... and another half a wrap apart
uniform float uMix;    // how much of the first: none as it wraps, so the disk never jumps
const float RIN = ${RIN.toFixed(3)};
const float ROUT = ${ROUT.toFixed(3)};
const float NEAR = ${NEAR.toFixed(1)};

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

// Far from the hole light runs almost straight: the pull the steps below add up falls off as 1/r⁴. Between s1 and s2
// along a straight line that passes the hole at b (s = 0 nearest the hole, r = √(b² + s²)) it turns the light
// towards the hole by ∫ 1.5 b³ / r⁵ ds = [u (3 - u²) / 2b] with u = s / r; this is that sum.
float bend(float b, float s1, float s2) {
  if (b < 0.5) return 0.0;
  float u1 = s1 / sqrt(b * b + s1 * s1), u2 = s2 / sqrt(b * b + s2 * s2);
  return (u2 * (3.0 - u2 * u2) - u1 * (3.0 - u1 * u1)) / (2.0 * b);
}

// turns the ray at pos going along vel (unit) towards the hole by the angle a
vec3 turned(vec3 pos, vec3 vel, float a) {
  vec3 side = pos - dot(pos, vel) * vel;
  float l = length(side);
  return l > 0.0 ? normalize(vel - side / l * a) : vel;
}

// value noise that wraps round the disk: x is the angle in 1/n turns
float noise(vec2 p, float n) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float i1 = mod(i.x + 1.0, n), i0 = mod(i.x, n);
  float a = hash(vec2(i0, i.y)), b = hash(vec2(i1, i.y));
  float c = hash(vec2(i0, i.y + 1.0)), d = hash(vec2(i1, i.y + 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

// the disk's colour from the inner edge outwards: white hot, gold, orange, a dull red (as blackHoleArt.ts)
vec3 diskRgb(float x) {
  vec3 c0 = vec3(1.0, 0.933, 0.808), c1 = vec3(1.0, 0.816, 0.557), c2 = vec3(0.98, 0.651, 0.337);
  vec3 c3 = vec3(0.886, 0.471, 0.227), c4 = vec3(0.549, 0.243, 0.165);
  if (x < 0.1) return mix(c0, c1, x / 0.1);
  if (x < 0.26) return mix(c1, c2, (x - 0.1) / 0.16);
  if (x < 0.5) return mix(c2, c3, (x - 0.26) / 0.24);
  return mix(c3, c4, clamp((x - 0.5) / 0.5, 0.0, 1.0));
}

// the disk's streaks at p after t seconds of turning: the inner edge goes round in about 20 seconds, further out
// slower (Kepler)
float streaks(vec3 p, float r, float t) {
  float turns = (atan(p.z, p.x) + 1.63 * pow(r, -1.5) * t) / 6.28318;
  // long arcs: slow round the disk, quick across it
  return noise(vec2(turns * 10.0, r * 9.0), 10.0) * 0.5 + noise(vec2(turns * 26.0, r * 23.0), 26.0) * 0.35
    + noise(vec2(turns * 4.0, r * 2.5), 4.0) * 0.3;
}

// the disk's light where a ray crosses it at p, travelling along dir: colour (already times strength) and strength
vec4 disk(vec3 p, vec3 dir) {
  float r = length(p.xz);
  float x = (r - RIN) / (ROUT - RIN);
  float n = mix(streaks(p, r, uTimeB), streaks(p, r, uTimeA), uMix);
  float lanes = 0.9 + 0.1 * sin(r * 17.0 + n * 4.0);
  // a sharp rise at the inner edge and a long fade outwards
  float level = smoothstep(0.0, 0.05, x) * exp(-x * 2.4) * (1.0 - smoothstep(0.85, 1.0, x));
  // the side turning towards us is brighter (the disk turns anticlockwise seen from above)
  vec3 v = normalize(vec3(-p.z, 0.0, p.x));
  float beta = sqrt(0.5 / r);
  float toward = dot(v, -dir);
  float g = sqrt(1.0 - beta * beta) / (1.0 - beta * toward);
  float beam = mix(1.0, g * g * g, 0.55) * sqrt(1.0 - 1.0 / r);
  float s = clamp(level * (0.3 + n) * lanes * beam * 3.0, 0.0, 4.0);
  return vec4(diskRgb(x + (n - 0.6) * 0.08) * s, clamp(s * 0.9, 0.0, 0.96));
}

vec3 stars(vec3 d) {
  vec2 sph = vec2(atan(d.z, d.x), asin(clamp(d.y, -1.0, 1.0)));
  vec2 cell = floor(sph * 90.0);
  float h = hash(cell);
  if (h < 0.965) return vec3(0.0);
  vec2 c = fract(sph * 90.0) - 0.5;
  float b = (h - 0.965) / 0.035;
  float glow = exp(-dot(c, c) * 30.0) * b;
  return mix(vec3(0.75, 0.85, 1.0), vec3(1.0, 0.92, 0.8), hash(cell + 7.0)) * glow * 1.4;
}

void main() {
  vec2 px = gl_FragCoord.xy - uMid;
  vec3 dir = normalize(uFwd + uRight * px.x * uTan + uUp * px.y * uTan);
  vec3 pos = uCam, vel = dir;
  vec3 hv = cross(pos, vel);
  float h2 = dot(hv, hv), b = sqrt(h2);
  // from the camera to NEAR from the hole in one go, turned by the little it bends on the way (bend), so the steps are
  // spent where the light really bends; the same on the way out. It draws faster than the closer camera did.
  float s1 = dot(pos, vel), s2 = b < NEAR ? -sqrt(NEAR * NEAR - h2) : 0.0;
  if (s1 < s2) {
    vel = turned(pos, vel, bend(b, s1, s2));
    pos += dir * (s2 - s1);
  }
  vec3 col = vec3(0.0);
  float alpha = 0.0, closest = 100.0;
  bool fell = false, left = false;
  for (int i = 0; i < ${steps}; i++) {
    float r2 = dot(pos, pos), r = sqrt(r2);
    closest = min(closest, r);
    float dt = clamp(0.085 * r, 0.04, 2.5);
    vel += -1.5 * h2 * pos / (r2 * r2 * r) * dt;
    vec3 next = pos + vel * dt;
    if (pos.y * next.y < 0.0) {
      vec3 hit = mix(pos, next, pos.y / (pos.y - next.y));
      float rh = length(hit.xz);
      if (rh > RIN && rh < ROUT) {
        vec4 d = disk(hit, normalize(vel));
        col += (1.0 - alpha) * d.rgb;
        alpha += (1.0 - alpha) * d.a;
        if (alpha > 0.98) break;
      }
    }
    pos = next;
    if (dot(pos, pos) < 1.0) { fell = true; break; }
    if (r > NEAR && dot(pos, vel) > 0.0) {
      // on its way out past NEAR: the rest of its bending in one go, as on the way in
      vec3 v = normalize(vel);
      float bOut = length(pos - dot(pos, v) * v), sOut = dot(pos, v);
      vel = turned(pos, v, bend(bOut, sOut, 1e4));
      left = true;
      break;
    }
  }
  if (fell) {
    alpha = 1.0;
  } else {
    vec3 d = normalize(vel);
    // a thin bright ring where light went round the hole before leaving (the photon ring)
    float ring = exp(-max(0.0, closest - 1.5) * 9.0) * 0.9;
    // the bent stars, only close round the shadow, where the bending shows; further out the page's own sky shows
    // through. They stop short of the ring (about 4.5 shadows out) where the bending draws each star out into a long
    // thin arc: at this size those arcs look like scratches on the picture, not like stars.
    float near = 1.0 - smoothstep(2.4, 3.6, length(px) * uTan * ${DIST.toFixed(1)} / ${SHADOW.toFixed(3)});
    vec3 light = vec3(1.0, 0.88, 0.7) * ring + stars(d) * near;
    float a = clamp(max(light.r, max(light.g, light.b)), 0.0, 1.0);
    col += (1.0 - alpha) * light;
    alpha += (1.0 - alpha) * a;
  }
  // a faint blue haze well round the hole, the studio's colour, so the scene sits in the blue sky; it is gone well
  // before the edges of the box, so the box never shows as a band or a rectangle
  float far = length(px) * uTan * ${DIST.toFixed(1)};
  vec2 e2 = (gl_FragCoord.xy / uRes - 0.5) * 2.0;
  float glow = smoothstep(3.0, 6.0, far) * (1.0 - smoothstep(0.35, 0.9, length(e2))) * 0.07;
  col += (1.0 - alpha) * vec3(0.32, 0.6, 0.95) * glow;
  alpha += (1.0 - alpha) * glow;
  // bright light rolls off instead of clipping to flat white
  col = 1.0 - exp(-col * 1.5);
  // fade out towards the edges of the box, so it has no hard edge as the disk swings round
  vec2 e = gl_FragCoord.xy / uRes;
  float edge = smoothstep(0.0, 0.12, e.x) * smoothstep(0.0, 0.12, 1.0 - e.x) * smoothstep(0.0, 0.1, e.y)
    * smoothstep(0.0, 0.1, 1.0 - e.y);
  gl_FragColor = vec4(min(col, vec3(1.0)) * edge, alpha * edge);
}`;

export type OrbitRenderer = {
  resize(w: number, h: number): void;
  /** one frame: `disk` seconds of the disk's turning, `orbit` seconds along the orbit */
  draw(disk: number, orbit: number): void;
  dispose(): void;
};

function compile(gl: WebGLRenderingContext, vs: string, fs: string): WebGLProgram | null {
  const prog = gl.createProgram();
  if (!prog) return null;
  for (const [type, src] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]] as const) {
    const sh = gl.createShader(type);
    if (!sh) return null;
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) return null;
    gl.attachShader(prog, sh);
  }
  gl.linkProgram(prog);
  return gl.getProgramParameter(prog, gl.LINK_STATUS) ? prog : null;
}

type V3 = [number, number, number];
const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = (a: V3): V3 => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};

/** The camera for a pose: on its orbit, looking at the hole, banked with the ship. */
export function orbitCamera(p: OrbitPose): { cam: V3; right: V3; up: V3; fwd: V3 } {
  const flat = DIST * Math.cos(p.incl);
  const cam: V3 = [flat * Math.sin(p.phi), DIST * Math.sin(p.incl), flat * Math.cos(p.phi)];
  const fwd = unit(sub([0, 0, 0], cam));
  const right0 = unit(cross(fwd, [0, 1, 0]));
  const up0 = cross(right0, fwd);
  const c = Math.cos(p.roll), s = Math.sin(p.roll);
  const right: V3 = [right0[0] * c + up0[0] * s, right0[1] * c + up0[1] * s, right0[2] * c + up0[2] * s];
  const up: V3 = [up0[0] * c - right0[0] * s, up0[1] * c - right0[1] * s, up0[2] * c - right0[2] * s];
  return { cam, right, up, fwd };
}

/**
 * A renderer on `canvas`, or null when the browser has no WebGL that draws on a graphics chip (the caller then uses
 * the lighter hole).
 */
export function makeOrbitRenderer(canvas: HTMLCanvasElement): OrbitRenderer | null {
  const gl = canvas.getContext("webgl", {
    alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false,
    preserveDrawingBuffer: false, powerPreference: "default", failIfMajorPerformanceCaveat: true,
  }) as WebGLRenderingContext | null;
  if (!gl) return null;
  const prog = compile(gl, VS, FS(150));
  const corners = prog ? gl.createBuffer() : null;
  if (!prog || !corners) {
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    return null;
  }
  gl.bindBuffer(gl.ARRAY_BUFFER, corners);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const corner = gl.getAttribLocation(prog, "aCorner");
  const u = (name: string) => gl.getUniformLocation(prog, name);
  const U = { res: u("uRes"), mid: u("uMid"), cam: u("uCam"), right: u("uRight"), up: u("uUp"), fwd: u("uFwd"),
    tan: u("uTan"), timeA: u("uTimeA"), timeB: u("uTimeB"), mix: u("uMix") };
  let w = 0, h = 0, tw = 0, th = 0;

  const resize = (nw: number, nh: number) => {
    if (nw === w && nh === h) return;
    w = nw; h = nh;
    const scale = Math.min(1, Math.sqrt(MAX_PIXELS / Math.max(1, w * h)));
    tw = Math.max(1, Math.round(w * scale));
    th = Math.max(1, Math.round(h * scale));
    canvas.width = tw;
    canvas.height = th;
  };

  const draw = (disk: number, orbit: number) => {
    if (!tw || !th || gl.isContextLost()) return;
    const { cam, right, up, fwd } = orbitCamera(orbitPose(orbit));
    // the shadow smaller than the lighter hole's (blackHoleArt.holeGeometry) and a little below the middle: the light
    // bent over the top reaches about 2.2 shadows up, and must fade out inside the box rather than be cut off by it
    const R = Math.min(th * 0.21, tw * 0.078);
    const tan = (SHADOW / DIST) / R;
    gl.viewport(0, 0, tw, th);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, corners);
    gl.enableVertexAttribArray(corner);
    gl.vertexAttribPointer(corner, 2, gl.FLOAT, false, 0, 0);
    gl.uniform2f(U.res, tw, th);
    gl.uniform2f(U.mid, tw * 0.5, th * 0.478);  // counted from the bottom
    gl.uniform3f(U.cam, ...cam);
    gl.uniform3f(U.right, ...right);
    gl.uniform3f(U.up, ...up);
    gl.uniform3f(U.fwd, ...fwd);
    gl.uniform1f(U.tan, tan);
    // The chip counts in 32-bit numbers, which lose the fine steps of a large time, so it is given the time within a
    // wrap. A plain wrap would make the disk jump; two pictures half a wrap apart, each faded out as it wraps, do not.
    const f = (disk / WRAP) % 1;
    gl.uniform1f(U.timeA, f * WRAP);
    gl.uniform1f(U.timeB, ((f + 0.5) % 1) * WRAP);
    gl.uniform1f(U.mix, 1 - Math.abs(2 * f - 1));
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.disableVertexAttribArray(corner);
  };

  const dispose = () => {
    gl.deleteBuffer(corners);
    gl.deleteProgram(prog);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  };

  return { resize, draw, dispose };
}
