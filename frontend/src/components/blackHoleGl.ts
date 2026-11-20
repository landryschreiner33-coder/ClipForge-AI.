import { FLAT, INNER, MESH_STRIDE, paintShadow, paintUnder, SPIN, streakMesh, TILT } from "./blackHoleArt";

/** The disk's speed numbers as the shader is written with them; the hourly move (turnedOn) uses the very same, or
 * the disk would jump on the hour. */
const SPIN_GL = SPIN.toFixed(4), INNER_GL = INNER.toFixed(4);

/**
 * The turning black hole on the graphics chip (the owner, 2026-11-20: "give the background animation like the stars
 * and black hole"). Every streak of blackHoleArt.ts is drawn again each frame where it has turned to, the inner
 * streaks faster, with the same widths, colours and adding-up light as the still picture, so the disk looks the
 * same and moves. The page's own work per frame is a handful of calls; the chip does the rest.
 *
 * Order: the glow and the thin image, then the shadow and its photon ring over them, then every streak at once,
 * adding up. The far side of the disk and the arch are behind the shadow, so where the shadow is they show only as
 * much as the shadow lets through: the same picture as drawing them before the shadow, in one pass instead of three.
 */

const LINES_VS = `
precision highp float;
attribute vec2 aPos;      // radius (shadow radii), angle at the start of this hour of turning
attribute float aSide;    // the streak's width, signed for the side of the line this point is on
attribute float aAlpha;   // the streak's strength
attribute vec3 aColor;
uniform vec2 uView;       // canvas size, pixels
uniform vec2 uCenter;     // the hole's centre, pixels
uniform float uR;         // the shadow's radius, pixels
uniform float uTime;      // seconds of turning since the start of this hour
uniform float uWide;      // how much wider than the streak (the soft light round it is wider)
uniform float uFaint;     // how much fainter than the streak
uniform float uArch;      // 1: the arch over the top; 0: the disk
varying vec4 vColor;
varying float vAcross;
varying float vHalf;
varying float vSin;
void main() {
  float a = aPos.x;
  // round it goes, the inner streaks faster (Kepler), the way the still picture's travelling light went
  float psi = aPos.y - ${SPIN_GL} * pow(${INNER_GL} / a, 1.5) * uTime;
  float rx = a, ry = a * ${FLAT.toFixed(4)};
  if (uArch > 0.5) {
    ry = 1.045 + 0.25 * (a - ${INNER_GL});
    rx = ry * (1.0 + 0.17 * (a - ${INNER_GL}));
  }
  float c = cos(psi), s = sin(psi);
  float ct = cos(${TILT.toFixed(4)}), st = sin(${TILT.toFixed(4)});
  vec2 e = vec2(rx * c, ry * s), d = vec2(-rx * s, ry * c);
  vec2 p = vec2(e.x * ct - e.y * st, e.x * st + e.y * ct) * uR;
  vec2 t = normalize(vec2(d.x * ct - d.y * st, d.x * st + d.y * ct));
  vec2 n = vec2(-t.y, t.x);
  // the same width as the canvas line: at least half a pixel, drawn a pixel wide and fainter when thinner
  float w = max(0.5, abs(aSide) * uR / 64.0 * uWide);
  float hw = max(w, 1.0) * 0.5;
  float reach = hw + 1.0;
  vec2 pos = uCenter + p + n * sign(aSide) * reach;
  gl_Position = vec4(pos.x / uView.x * 2.0 - 1.0, 1.0 - pos.y / uView.y * 2.0, 0.0, 1.0);
  vAcross = sign(aSide) * reach;
  vHalf = hw;
  vSin = s;
  // brighter on the side turning towards us; the arch fades out where its ends meet the disk
  float beam = 1.0 - (uArch > 0.5 ? 0.3 : 0.35) * c;
  float ends = uArch > 0.5 ? clamp(-s / 0.5, 0.0, 1.0) : 1.0;
  vColor = vec4(aColor, min(1.0, aAlpha * uFaint * beam) * ends * min(1.0, w));
}`;

const LINES_FS = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform sampler2D uShadow; // the shadow picture
uniform vec2 uPx;          // canvas size, pixels
varying vec4 vColor;
varying float vAcross;
varying float vHalf;
varying float vSin;
void main() {
  float al = vColor.a * clamp(vHalf + 0.5 - abs(vAcross), 0.0, 1.0);
  // the far side (and the arch, which is all far side) shows only as much as the shadow in front lets through
  if (vSin < 0.0) al *= 1.0 - texture2D(uShadow, vec2(gl_FragCoord.x / uPx.x, 1.0 - gl_FragCoord.y / uPx.y)).a;
  gl_FragColor = vec4(vColor.rgb * al, al);
}`;

const PICTURE_VS = `
attribute vec2 aCorner;
varying vec2 vUv;
void main() {
  vUv = vec2(aCorner.x * 0.5 + 0.5, 0.5 - aCorner.y * 0.5);
  gl_Position = vec4(aCorner, 0.0, 1.0);
}`;

const PICTURE_FS = `
precision mediump float;
uniform sampler2D uPicture;
varying vec2 vUv;
void main() { gl_FragColor = texture2D(uPicture, vUv); }`;

type Mesh = { buffer: WebGLBuffer; count: number };

/**
 * The chip counts in 32-bit numbers, which lose the fine steps of a large time: after a day of turning the disk would
 * jitter, after a week stutter. So the chip is given the time since the start of the hour, and at each new hour every
 * point's starting angle is moved on, here in 64-bit numbers, by as far as it has turned in the hours before: the
 * disk carries on without a jump.
 */
const HOUR = 3600;
const TURN = 2 * Math.PI;

/** A copy of a strip whose points start where `hours` whole hours of turning have taken them. */
function turnedOn(data: ArrayBuffer, hours: number): ArrayBuffer {
  const out = data.slice(0), f = new Float32Array(out), per = MESH_STRIDE / 4;
  const spin = Number(SPIN_GL), inner = Number(INNER_GL);
  // the same speed as the vertex shader's, from the same 32-bit radius it reads
  for (let i = 0; i < f.length; i += per) {
    f[i + 1] = (f[i + 1] - spin * Math.pow(inner / f[i], 1.5) * HOUR * hours) % TURN;
  }
  return out;
}

/** Points every so many radians along a streak: the coarsest that keeps a curve within about a third of a pixel of
 * the true ellipse for a shadow of radius `R` canvas pixels (the soft light round the streaks, being wide and faint,
 * takes twice the step). */
const STEPS = [0.045, 0.06, 0.09, 0.13, 0.18];
const stepFor = (R: number) => STEPS.reduce((best, s) => (s <= Math.sqrt(1.4 / Math.max(1, R)) ? s : best), STEPS[0]);

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

/** The streak meshes depend only on the step: built once each, for every hole. */
const meshes = new Map<string, ReturnType<typeof streakMesh>>();
const meshFor = (kind: "disk" | "arch", step: number) => {
  const key = `${kind}${step}`;
  let m = meshes.get(key);
  if (!m) meshes.set(key, (m = streakMesh(kind, step)));
  return m;
};

export type HoleRenderer = {
  /** A new size in canvas pixels: repaints the still parts. */
  resize(w: number, h: number): void;
  /** One frame at `t` seconds of turning on the shared clock. */
  draw(t: number): void;
  dispose(): void;
};

/**
 * A renderer on `canvas`, or null when the browser has no WebGL, or only a slow one drawn without a graphics chip
 * (the caller then paints the canvas picture, on a fresh canvas: one offered WebGL never draws 2D).
 */
export function makeHoleRenderer(canvas: HTMLCanvasElement): HoleRenderer | null {
  const gl = canvas.getContext("webgl", {
    alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false,
    preserveDrawingBuffer: false, powerPreference: "low-power", failIfMajorPerformanceCaveat: true,
  }) as WebGLRenderingContext | null;
  if (!gl) return null;
  const lines = compile(gl, LINES_VS, LINES_FS), picture = compile(gl, PICTURE_VS, PICTURE_FS);
  const corners = lines && picture ? gl.createBuffer() : null;
  if (!lines || !picture || !corners) {
    // let the half-made drawing go at once: the caller paints on a fresh canvas instead
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    return null;
  }
  gl.bindBuffer(gl.ARRAY_BUFFER, corners);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);

  const at = (p: WebGLProgram, name: string) => gl.getAttribLocation(p, name);
  const un = (p: WebGLProgram, name: string) => gl.getUniformLocation(p, name);
  const L = {
    pos: at(lines, "aPos"), side: at(lines, "aSide"), alpha: at(lines, "aAlpha"), color: at(lines, "aColor"),
    view: un(lines, "uView"), center: un(lines, "uCenter"), R: un(lines, "uR"), time: un(lines, "uTime"),
    wide: un(lines, "uWide"), faint: un(lines, "uFaint"), arch: un(lines, "uArch"), shadow: un(lines, "uShadow"),
    px: un(lines, "uPx"),
  };
  const P = { corner: at(picture, "aCorner"), picture: un(picture, "uPicture") };

  // the still parts, painted by the canvas painter and kept as two pictures
  const paper = document.createElement("canvas");
  const textures = [gl.createTexture(), gl.createTexture()];
  let w = 0, h = 0;

  // the streaks for this size and hour of turning, fine and soft, for the disk and the arch: built at the first frame
  // that needs them, so a hole that appears late in an hour builds them once
  let step = 0, hour = 0;
  let strips: { disk: Mesh; diskSoft: Mesh; arch: Mesh; archSoft: Mesh } | null = null;
  const upload = (m: ReturnType<typeof streakMesh>): Mesh => {
    const buffer = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, hour ? turnedOn(m.data, hour) : m.data, gl.STATIC_DRAW);
    return { buffer, count: m.count };
  };
  const dropStrips = () => {
    if (strips) for (const m of Object.values(strips)) gl.deleteBuffer(m.buffer);
    strips = null;
  };
  const makeStrips = () => {
    dropStrips();
    const soft = Math.min(0.36, step * 2);
    return (strips = {
      disk: upload(meshFor("disk", step)), diskSoft: upload(meshFor("disk", soft)),
      arch: upload(meshFor("arch", step)), archSoft: upload(meshFor("arch", soft)),
    });
  };

  const radius = () => Math.min(h * 0.29, w * 0.107);

  const resize = (nw: number, nh: number) => {
    if (nw === w && nh === h) return;
    w = nw; h = nh;
    canvas.width = w; canvas.height = h;
    const s = stepFor(radius());
    if (s !== step) {
      dropStrips();
      step = s;
    }
    paper.width = w; paper.height = h;
    const g = paper.getContext("2d");
    if (!g) return;
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    [paintUnder, paintShadow].forEach((paint, i) => {
      paint(g, w, h);
      gl.bindTexture(gl.TEXTURE_2D, textures[i]);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, paper);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    });
    // the canvas pixels are not needed once the chip has them
    paper.width = paper.height = 1;
  };

  const drawPicture = (i: number) => {
    gl.useProgram(picture);
    gl.bindBuffer(gl.ARRAY_BUFFER, corners);
    gl.enableVertexAttribArray(P.corner);
    gl.vertexAttribPointer(P.corner, 2, gl.FLOAT, false, 0, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, textures[i]);
    gl.uniform1i(P.picture, 0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.disableVertexAttribArray(P.corner);
  };

  const drawLines = (fine: Mesh, soft: Mesh, arch: boolean) => {
    gl.enableVertexAttribArray(L.pos);
    gl.enableVertexAttribArray(L.side);
    gl.enableVertexAttribArray(L.alpha);
    gl.enableVertexAttribArray(L.color);
    gl.uniform1f(L.arch, arch ? 1 : 0);
    // the soft light round the streaks, then the fine streaks
    for (const [m, wide, faint] of arch ? [[soft, 6, 0.05], [fine, 1.15, 1]] as const
      : [[soft, 5, 0.05], [fine, 1, 1]] as const) {
      gl.bindBuffer(gl.ARRAY_BUFFER, m.buffer);
      gl.vertexAttribPointer(L.pos, 2, gl.FLOAT, false, MESH_STRIDE, 0);
      gl.vertexAttribPointer(L.side, 1, gl.FLOAT, false, MESH_STRIDE, 8);
      gl.vertexAttribPointer(L.alpha, 1, gl.FLOAT, false, MESH_STRIDE, 12);
      gl.vertexAttribPointer(L.color, 3, gl.UNSIGNED_BYTE, true, MESH_STRIDE, 16);
      gl.uniform1f(L.wide, wide);
      gl.uniform1f(L.faint, faint);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, m.count);
    }
    for (const a of [L.pos, L.side, L.alpha, L.color]) gl.disableVertexAttribArray(a);
  };

  const draw = (t: number) => {
    if (!w || !h || gl.isContextLost()) return;
    const k = Math.floor(t / HOUR);
    let these = strips;
    if (!these || k !== hour) {
      hour = k;
      these = makeStrips();
    }
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    // the glow and thin image, then the shadow over them
    gl.blendFunc(gl.ONE, gl.ONE);
    drawPicture(0);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    drawPicture(1);
    // every streak, light adding up as the canvas's "lighter" does; the shadow picture says how much of the far side
    // shows through
    gl.blendFunc(gl.ONE, gl.ONE);
    gl.useProgram(lines);
    gl.uniform2f(L.view, w, h);
    gl.uniform2f(L.px, w, h);
    gl.uniform2f(L.center, w / 2, h / 2);
    gl.uniform1f(L.R, radius());
    gl.uniform1f(L.time, t - k * HOUR);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, textures[1]);
    gl.uniform1i(L.shadow, 0);
    drawLines(these.disk, these.diskSoft, false);
    drawLines(these.arch, these.archSoft, true);
  };

  const dispose = () => {
    dropStrips();
    gl.deleteBuffer(corners);
    textures.forEach((t) => gl.deleteTexture(t));
    gl.deleteProgram(lines);
    gl.deleteProgram(picture);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  };

  return { resize, draw, dispose };
}
