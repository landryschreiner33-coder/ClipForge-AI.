// The moving sky and the black hole behind the download page: the app's own Studio scenery (components/starSky.ts,
// blackHoleOrbit.ts and shipArt.ts in the app), written again without a build step. Decoration only: nothing on the
// page depends on it, and every link works without it.
//
// - The sky streams past to the left as if the ship were flying on: two tiles of small stars slide (moved by the
//   browser's compositor, see site.css), brighter stars twinkle and drift, specks of dust rush past and now and then
//   a shooting star crosses.
// - The black hole is ray traced on the graphics chip as the ship orbits it, with Landry's pixel ship in front.
//
// It holds still when the visitor asks for less motion, while the page is hidden, while the hero is off screen, and for
// good once a computer draws it too slowly. Without a graphics chip (or WebGL) the page keeps its still picture.
(function () {
  "use strict";
  var still = window.matchMedia("(prefers-reduced-motion: reduce)");
  var capture = /[?&]still\b/.test(location.search);  // used once to paint img/space/black-hole.webp
  var anyGl = capture || /[?&]gl\b/.test(location.search);  // checks in a browser without a graphics chip

  /* ------------------------------------------------------------------------------------------------ the sky */

  var DRIFT = [10, 18, 30];  // CSS pixels a second, far to near
  var TINTS = ["255, 255, 255", "206, 222, 255", "255, 228, 196", "176, 236, 255"];
  function random(seed) {
    var v = seed;
    return function () { v = (v * 16807) % 2147483647; return v / 2147483647; };
  }
  var stars = [], dust = [], meteors = [];
  (function () {
    var r = random(20261120);
    for (var i = 0; i < 260; i++) {
      var layer = r() < 0.5 ? 0 : r() < 0.62 ? 1 : 2, deep = r() < 0.35, t = r();
      stars.push({
        u: r(), v: r(), layer: layer,
        size: [0.55, 0.85, 1.15][layer] + r() * [0.35, 0.45, 0.65][layer],
        base: [0.45, 0.62, 0.8][layer] + r() * 0.2,
        amp: deep ? 0.55 + r() * 0.35 : 0.15 + r() * 0.3,
        freq: 0.08 + r() * 0.4, phase: r() * Math.PI * 2,
        tint: t < 0.58 ? 0 : t < 0.8 ? 1 : t < 0.94 ? 2 : 3,
        spikes: layer === 2 && r() < 0.16
      });
    }
    var d = random(90210);
    for (var j = 0; j < 30; j++) dust.push({ u: d(), v: d(), speed: 160 + d() * 100, alpha: 0.25 + d() * 0.35 });
  })();
  var nextMeteor = random(7121);
  function meteorsUpTo(t) {
    while (!meteors.length || meteors[meteors.length - 1].at < t + 20) {
      var r = nextMeteor, prev = meteors.length ? meteors[meteors.length - 1].at : 2;
      var angle = (12 + r() * 20) * Math.PI / 180;
      meteors.push({ at: prev + 7 + r() * 9, x: 0.35 + r() * 0.65, y: 0.03 + r() * 0.42, dx: -Math.cos(angle),
        dy: Math.sin(angle), speed: 620 + r() * 380, dur: 0.75 + r() * 0.4, tail: 140 + r() * 130 });
    }
    while (meteors.length > 1 && meteors[0].at + meteors[0].dur < t) meteors.shift();
  }
  var sprites = {};
  function sprite(kind, tint) {
    var key = kind + tint;
    if (sprites[key]) return sprites[key];
    var c = document.createElement("canvas"), S = kind === "dot" ? 32 : kind === "spikes" ? 96 : 64;
    c.width = S; c.height = kind === "streak" ? 8 : S;
    var g = c.getContext("2d"), m = S / 2, col = TINTS[tint], gr;
    if (kind === "streak") {
      gr = g.createLinearGradient(0, 0, S, 0);
      gr.addColorStop(0, "rgba(255, 255, 255, 1)");
      gr.addColorStop(0.2, "rgba(" + col + ", 0.75)");
      gr.addColorStop(1, "rgba(" + col + ", 0)");
      g.fillStyle = gr; g.fillRect(0, 2, S, 4); g.globalAlpha = 0.35; g.fillRect(0, 1, S, 6);
    } else if (kind === "dot") {
      gr = g.createRadialGradient(m, m, 0, m, m, m);
      gr.addColorStop(0, "rgba(255, 255, 255, 1)");
      gr.addColorStop(0.16, "rgba(" + col + ", 0.95)");
      gr.addColorStop(0.34, "rgba(" + col + ", 0.28)");
      gr.addColorStop(1, "rgba(" + col + ", 0)");
      g.fillStyle = gr; g.fillRect(0, 0, S, S);
    } else {
      [[0, m, S, m], [m, 0, m, S]].forEach(function (p) {
        var l = g.createLinearGradient(p[0], p[1], p[2], p[3]);
        l.addColorStop(0, "rgba(" + col + ", 0)");
        l.addColorStop(0.5, "rgba(" + col + ", 0.9)");
        l.addColorStop(1, "rgba(" + col + ", 0)");
        g.fillStyle = l;
        if (p[1] === p[3]) g.fillRect(0, m - 0.75, S, 1.5); else g.fillRect(m - 0.75, 0, 1.5, S);
      });
    }
    return (sprites[key] = c);
  }
  var wrap = function (x, span) { return ((x % span) + span) % span; };

  function Sky(canvas) {
    var g = canvas.getContext("2d"), w = 0, h = 0, dpr = 1;
    function size() {
      dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      w = window.innerWidth; h = window.innerHeight;
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    function put(img, cx, cy, wide, high, alpha) {
      if (alpha <= 0.01 || cx + wide < 0 || cy + high < 0 || cx - wide > w || cy - high > h) return;
      g.globalAlpha = Math.min(1, alpha);
      g.drawImage(img, (cx - wide / 2) * dpr, (cy - high / 2) * dpr, wide * dpr, high * dpr);
    }
    function paint(t, moving) {
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, canvas.width, canvas.height);
      var n = Math.min(stars.length, Math.max(50, Math.round(w * h / 9000))), spanX = w + 24;
      for (var i = 0; i < n; i++) {
        var s = stars[i];
        var x = wrap(s.u * spanX - DRIFT[s.layer] * t, spanX) - 12, y = s.v * h;
        var glow = s.base * (1 - s.amp * (0.5 + 0.5 * Math.sin(t * s.freq * Math.PI * 2 + s.phase)));
        put(sprite("dot", s.tint), x, y, s.size * 7, s.size * 7, glow);
        if (s.spikes) {
          var k = s.size * 9 * (0.55 + glow * 0.6);
          put(sprite("spikes", s.tint), x, y, k, k, glow * 0.8);
        }
      }
      if (!moving) return;
      var nd = Math.min(dust.length, Math.max(5, Math.round(w * h / 80000)));
      for (var j = 0; j < nd; j++) {
        var d = dust[j], len = d.speed * 0.1, span = w + len + 24;
        var dx = wrap(d.u * span - d.speed * t, span) - len - 12;
        put(sprite("streak", 1), dx + len / 2, d.v * h, len, 2.4, d.alpha);
      }
      meteorsUpTo(t);
      meteors.forEach(function (m) {
        if (t < m.at || t > m.at + m.dur) return;
        var age = t - m.at, run = m.speed * age;
        var fade = Math.min(1, age / 0.12) * Math.min(1, (m.at + m.dur - t) / (m.dur * 0.4));
        var hx = m.x * w + m.dx * run, hy = m.y * h + m.dy * run, len = Math.min(m.tail, run);
        g.save();
        g.globalAlpha = Math.max(0, fade);
        g.translate(hx * dpr, hy * dpr);
        g.rotate(Math.atan2(-m.dy, -m.dx));
        g.drawImage(sprite("streak", 0), 0, -1.6 * dpr, len * dpr, 3.2 * dpr);
        g.restore();
      });
    }
    size();
    return { size: size, paint: paint };
  }

  /* --------------------------------------------------------------------------------------- the black hole */

  var ORBIT = 150, DIST = 70, RIN = 3.0, ROUT = 10.5, NEAR = 25, SHADOW = 2.598, WRAP = 1800, TILT = 0.08;
  var MAX_PIXELS = 500000;
  function pose(t) {
    var phi = (t / ORBIT) * Math.PI * 2;
    return { phi: phi, incl: TILT + 0.05 * Math.sin(phi * 2 + 0.6), roll: 0.07 * Math.sin(phi * 2 + 2.2) };
  }
  var VS = "attribute vec2 aCorner;\nvoid main() { gl_Position = vec4(aCorner, 0.0, 1.0); }";
  var FS = [
    "#ifdef GL_FRAGMENT_PRECISION_HIGH", "precision highp float;", "#else", "precision mediump float;", "#endif",
    "uniform vec2 uRes; uniform vec2 uMid; uniform vec3 uCam; uniform vec3 uRight; uniform vec3 uUp; uniform vec3 uFwd;",
    "uniform float uTan; uniform float uTimeA; uniform float uTimeB; uniform float uMix; uniform float uRing;",
    "const float RIN = " + RIN.toFixed(3) + "; const float ROUT = " + ROUT.toFixed(3) + ";",
    "const float NEAR = " + NEAR.toFixed(1) + ";",
    "float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }",
    "float bend(float b, float u1, float u2) {",
    "  return b < 0.5 ? 0.0 : (u2 * (3.0 - u2 * u2) - u1 * (3.0 - u1 * u1)) / (2.0 * b); }",
    "vec3 turned(vec3 pos, vec3 vel, float a) {",
    "  vec3 side = pos - dot(pos, vel) * vel; float l = length(side);",
    "  return l > 0.0 ? normalize(vel - side / l * a) : vel; }",
    "float noise(vec2 p, float n) {",
    "  vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);",
    "  float i1 = mod(i.x + 1.0, n), i0 = mod(i.x, n);",
    "  float a = hash(vec2(i0, i.y)), b = hash(vec2(i1, i.y));",
    "  float c = hash(vec2(i0, i.y + 1.0)), d = hash(vec2(i1, i.y + 1.0));",
    "  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y); }",
    "vec3 diskRgb(float x) {",
    "  vec3 c0 = vec3(1.0, 0.933, 0.808), c1 = vec3(1.0, 0.816, 0.557), c2 = vec3(0.98, 0.651, 0.337);",
    "  vec3 c3 = vec3(0.886, 0.471, 0.227), c4 = vec3(0.549, 0.243, 0.165);",
    "  if (x < 0.1) return mix(c0, c1, x / 0.1);",
    "  if (x < 0.26) return mix(c1, c2, (x - 0.1) / 0.16);",
    "  if (x < 0.5) return mix(c2, c3, (x - 0.26) / 0.24);",
    "  return mix(c3, c4, clamp((x - 0.5) / 0.5, 0.0, 1.0)); }",
    "float streaks(vec3 p, float r, float t) {",
    "  float turns = (atan(p.z, p.x) + 1.63 * pow(r, -1.5) * t) / 6.28318;",
    "  return noise(vec2(turns * 10.0, r * 9.0), 10.0) * 0.5 + noise(vec2(turns * 26.0, r * 23.0), 26.0) * 0.35",
    "    + noise(vec2(turns * 4.0, r * 2.5), 4.0) * 0.3; }",
    "vec4 disk(vec3 p, vec3 dir) {",
    "  float r = length(p.xz); float x = (r - RIN) / (ROUT - RIN);",
    "  float n = mix(streaks(p, r, uTimeB), streaks(p, r, uTimeA), uMix);",
    "  float lanes = 0.9 + 0.1 * sin(r * 17.0 + n * 4.0);",
    "  float level = smoothstep(0.0, 0.05, x) * exp(-x * 2.4) * (1.0 - smoothstep(0.85, 1.0, x));",
    "  vec3 v = normalize(vec3(-p.z, 0.0, p.x)); float beta = sqrt(0.5 / r); float toward = dot(v, -dir);",
    "  float g = sqrt(1.0 - beta * beta) / (1.0 - beta * toward);",
    "  float beam = mix(1.0, g * g * g, 0.55) * sqrt(1.0 - 1.0 / r);",
    "  float s = clamp(level * (0.3 + n) * lanes * beam * 3.0, 0.0, 4.0);",
    "  return vec4(diskRgb(x + (n - 0.6) * 0.08) * s, clamp(s * 0.9, 0.0, 0.96)); }",
    "vec3 stars(vec3 d) {",
    "  vec2 sph = vec2(atan(d.z, d.x), asin(clamp(d.y, -1.0, 1.0))); vec2 cell = floor(sph * 90.0);",
    "  float h = hash(cell); if (h < 0.965) return vec3(0.0);",
    "  vec2 c = fract(sph * 90.0) - 0.5; float b = (h - 0.965) / 0.035; float glow = exp(-dot(c, c) * 30.0) * b;",
    "  return mix(vec3(0.75, 0.85, 1.0), vec3(1.0, 0.92, 0.8), hash(cell + 7.0)) * glow * 1.4; }",
    "void main() {",
    "  vec2 px = gl_FragCoord.xy - uMid;",
    "  vec3 dir = normalize(uFwd + uRight * px.x * uTan + uUp * px.y * uTan);",
    "  vec3 pos = uCam, vel = dir; vec3 hv = cross(pos, vel); float h2 = dot(hv, hv), b = sqrt(h2);",
    "  float s1 = dot(pos, vel), s2 = b < NEAR ? -sqrt(NEAR * NEAR - h2) : 0.0;",
    "  if (s1 < s2) { vel = turned(pos, vel, bend(b, s1 / length(pos), s2 / NEAR)); pos += dir * (s2 - s1); }",
    "  vec3 col = vec3(0.0); float alpha = 0.0, closest = 100.0; bool fell = false;",
    "  for (int i = 0; i < 150; i++) {",
    "    float r2 = dot(pos, pos), r = sqrt(r2); closest = min(closest, r);",
    "    float dt = clamp(0.085 * r, 0.04, 2.5);",
    "    vel += -1.5 * h2 * pos / (r2 * r2 * r) * dt; vec3 next = pos + vel * dt;",
    "    if (pos.y * next.y < 0.0) {",
    "      vec3 hit = mix(pos, next, pos.y / (pos.y - next.y)); float rh = length(hit.xz);",
    "      if (rh > RIN && rh < ROUT) {",
    "        vec4 d = disk(hit, normalize(vel)); col += (1.0 - alpha) * d.rgb; alpha += (1.0 - alpha) * d.a;",
    "        if (alpha > 0.98) break; } }",
    "    pos = next;",
    "    if (dot(pos, pos) < 1.0) { fell = true; break; }",
    "    if (r > NEAR && dot(pos, vel) > 0.0) {",
    "      vec3 v = normalize(vel);",
    "      vel = turned(pos, v, bend(length(pos - dot(pos, v) * v), dot(pos, v) / length(pos), 1.0)); break; } }",
    "  if (fell) { alpha = 1.0; } else {",
    "    vec3 d = normalize(vel); float ring = exp(-max(0.0, closest - 1.5) * uRing) * 0.9;",
    "    float near = 1.0 - smoothstep(2.4, 3.6, length(px) * uTan * " + DIST.toFixed(1) + " / " + SHADOW.toFixed(3) + ");",
    "    vec3 light = vec3(1.0, 0.88, 0.7) * ring + stars(d) * near;",
    "    float a = clamp(max(light.r, max(light.g, light.b)), 0.0, 1.0);",
    "    col += (1.0 - alpha) * light; alpha += (1.0 - alpha) * a; }",
    "  float far = length(px) * uTan * " + DIST.toFixed(1) + ";",
    "  float glow = smoothstep(3.0, 6.0, far) * (1.0 - smoothstep(0.35, 0.9, length(px / (uRes * 0.5)))) * 0.07;",
    "  col += (1.0 - alpha) * vec3(0.32, 0.6, 0.95) * glow; alpha += (1.0 - alpha) * glow;",
    "  col = 1.0 - exp(-col * 1.5);",
    "  vec2 e = gl_FragCoord.xy / uRes;",
    "  float edge = smoothstep(0.0, 0.12, e.x) * smoothstep(0.0, 0.12, 1.0 - e.x) * smoothstep(0.0, 0.1, e.y)",
    "    * smoothstep(0.0, 0.1, 1.0 - e.y);",
    "  gl_FragColor = vec4(min(col, vec3(1.0)) * edge, alpha * edge); }"
  ].join("\n");

  function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function unit(a) { var l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; }
  function camera(p) {
    var flat = DIST * Math.cos(p.incl);
    var cam = [flat * Math.sin(p.phi), DIST * Math.sin(p.incl), flat * Math.cos(p.phi)];
    var fwd = unit(sub([0, 0, 0], cam)), right0 = unit(cross(fwd, [0, 1, 0])), up0 = cross(right0, fwd);
    var c = Math.cos(p.roll), s = Math.sin(p.roll);
    return { cam: cam, fwd: fwd,
      right: [right0[0] * c + up0[0] * s, right0[1] * c + up0[1] * s, right0[2] * c + up0[2] * s],
      up: [up0[0] * c - right0[0] * s, up0[1] * c - right0[1] * s, up0[2] * c - right0[2] * s] };
  }

  function Hole(canvas) {
    var gl = canvas.getContext("webgl", { alpha: true, premultipliedAlpha: true, antialias: false, depth: false,
      stencil: false, preserveDrawingBuffer: capture, failIfMajorPerformanceCaveat: !anyGl });
    if (!gl) return null;
    // a graphics chip drawn in software keeps the still picture: it would take the visitor's processor
    if (!anyGl) {
      var info = gl.getExtension("WEBGL_debug_renderer_info");
      var chip = String(gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER) || "");
      if (/SwiftShader|llvmpipe|softpipe|Software|Basic Render/i.test(chip)) return null;
    }
    var prog = gl.createProgram(), ok = true;
    [[gl.VERTEX_SHADER, VS], [gl.FRAGMENT_SHADER, FS]].forEach(function (p) {
      var sh = gl.createShader(p[0]);
      gl.shaderSource(sh, p[1]); gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) ok = false;
      gl.attachShader(prog, sh);
    });
    gl.linkProgram(prog);
    if (!ok || !gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
    var corners = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, corners);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    var corner = gl.getAttribLocation(prog, "aCorner"), U = {};
    ["uRes", "uMid", "uCam", "uRight", "uUp", "uFwd", "uTan", "uTimeA", "uTimeB", "uMix", "uRing"].forEach(function (n) {
      U[n] = gl.getUniformLocation(prog, n);
    });
    var tw = 0, th = 0, scale = 1;
    return {
      gl: gl,
      resize: function (w, h) {
        scale = capture ? 1 : Math.min(1, Math.sqrt(MAX_PIXELS / Math.max(1, w * h)));
        var nw = Math.max(1, Math.round(w * scale)), nh = Math.max(1, Math.round(h * scale));
        if (nw !== tw || nh !== th) { tw = canvas.width = nw; th = canvas.height = nh; }
      },
      draw: function (diskT, orbitT) {
        if (!tw || gl.isContextLost()) return;
        var c = camera(pose(orbitT)), R = Math.min(th * 0.2, tw * 0.085), f = (diskT / WRAP) % 1;
        gl.viewport(0, 0, tw, th);
        gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
        gl.useProgram(prog);
        gl.bindBuffer(gl.ARRAY_BUFFER, corners);
        gl.enableVertexAttribArray(corner);
        gl.vertexAttribPointer(corner, 2, gl.FLOAT, false, 0, 0);
        gl.uniform2f(U.uRes, tw, th);
        gl.uniform2f(U.uMid, tw * 0.5, th * 0.5);
        gl.uniform3fv(U.uCam, c.cam); gl.uniform3fv(U.uRight, c.right); gl.uniform3fv(U.uUp, c.up);
        gl.uniform3fv(U.uFwd, c.fwd);
        gl.uniform1f(U.uTan, (SHADOW / DIST) / R);
        gl.uniform1f(U.uTimeA, f * WRAP);
        gl.uniform1f(U.uTimeB, ((f + 0.5) % 1) * WRAP);
        gl.uniform1f(U.uMix, 1 - Math.abs(2 * f - 1));
        gl.uniform1f(U.uRing, Math.max(4.5, 9.0 * scale));
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      }
    };
  }

  /* --------------------------------------------------------------------------------------------- the ship */

  var FLAME = 0.22, ships = [], shipLoaded = null;
  ["img/space/flyer-192.png", "img/space/flyer-384.png"].forEach(function (src) {
    var img = new Image();
    img.decoding = "async";
    img.onload = function () {
      ships.push(img);
      ships.sort(function (a, b) { return a.naturalWidth - b.naturalWidth; });
      if (shipLoaded) shipLoaded();
    };
    img.src = src;
  });
  function shipWidth(w) { return Math.min(260, Math.max(120, w * 0.26)); }
  function paintShip(g, w, h, dpr, p, t, x) {
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, g.canvas.width, g.canvas.height);
    var sw = shipWidth(w) * dpr;
    var art = ships.filter(function (s) { return s.naturalWidth >= sw; })[0] || ships[ships.length - 1];
    if (!art) return;
    if (!g.canvas.parentNode.classList.contains("ship-on")) g.canvas.parentNode.classList.add("ship-on");
    var sh = sw * art.naturalHeight / art.naturalWidth, split = Math.round(art.naturalWidth * FLAME);
    var engines = -sw / 2 + sw * split / art.naturalWidth;
    var bob = t === null ? 0 : Math.sin(t * 0.9) * h * dpr * 0.012;
    g.translate((x || w * 0.76) * dpr, h * dpr * 0.76 + bob);
    g.rotate(-p.roll * 1.6 + (p.incl - TILT) * 0.3);
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
    var flick = t === null ? 0.5 : 0.25 + 0.75 * Math.abs(Math.sin(t * 13.0) * Math.sin(t * 7.3));
    var flame = (engines + sw / 2) * (0.88 + 0.24 * flick);
    g.globalAlpha = t === null ? 1 : 0.8 + 0.2 * flick;
    g.drawImage(art, 0, 0, split, art.naturalHeight, engines - flame + 1, -sh / 2, flame, sh);
    g.globalAlpha = 1;
    g.drawImage(art, split, 0, art.naturalWidth - split, art.naturalHeight, engines, -sh / 2, sw / 2 - engines, sh);
    var warm = 0.16 + 0.12 * Math.cos(p.phi);
    g.globalCompositeOperation = "source-atop";
    var grad = g.createLinearGradient(sw / 2, -sh / 2, engines, sh / 2);
    grad.addColorStop(0, "rgba(255, 200, 120, " + warm.toFixed(2) + ")");
    grad.addColorStop(1, "rgba(255, 200, 120, 0)");
    g.fillStyle = grad;
    g.fillRect(engines, -sh / 2, sw / 2 - engines, sh);
    g.globalCompositeOperation = "source-over";
  }

  /* -------------------------------------------------------------------------------------------- the clock */

  function start() {
    var skyCanvas = document.querySelector(".sky-canvas");
    var scene = document.querySelector(".hero-scene");
    var holeCanvas = scene && scene.querySelector(".hole");
    var shipCanvas = scene && scene.querySelector(".ship");
    var sky = skyCanvas && !capture ? Sky(skyCanvas) : null;
    var hole = holeCanvas ? Hole(holeCanvas) : null;
    var shipG = shipCanvas ? shipCanvas.getContext("2d") : null;
    var heroOn = true, slow = false, frames = [], raf = 0, last = 0, clock = 0, sw = 0, sh = 0, sdpr = 1, sx = 0;
    var seen = 0, queued = false, boxKey = "";
    // the orbit starts where the disk shows well: its bright side towards the ship, the camera a little above it
    var T0 = 31;

    function sizeScene() {
      if (!scene) return;
      var box = scene.getBoundingClientRect();
      sw = box.width; sh = box.height;
      var room = (document.documentElement.clientWidth || window.innerWidth) - box.left;
      sx = Math.max(sw * 0.5, Math.min(sw * 0.76, room - shipWidth(sw) / 2 - 24));
      if (hole) hole.resize(sw, sh);
      if (shipCanvas) {
        sdpr = Math.min(window.devicePixelRatio || 1, 2);
        shipCanvas.width = Math.round(sw * sdpr); shipCanvas.height = Math.round(sh * sdpr);
      }
    }
    function drawScene(t, moving) {
      drawHole(t);
      if (shipG) paintShip(shipG, sw, sh, sdpr, pose(T0 + t), moving ? t : null, sx);
    }
    function drawHole(t) { if (hole && !slow) hole.draw(T0 + t, T0 + t); }
    function frame(now) {
      raf = 0;
      var moving = !still.matches && !document.hidden && !capture;
      if (!moving) { drawAll(false); return; }
      var raw = last ? (now - last) / 1000 : 0, dt = Math.min(0.1, raw);
      // at most 30 pictures a second: the sky and the disk are slow, and the visitor's computer has other work
      if (last && now - last < 31) { raf = requestAnimationFrame(frame); return; }
      last = now;
      clock += dt;
      if (sky) sky.paint(clock, true);
      if (heroOn) {
        drawScene(clock, true);
        if (hole && !slow && raw) watch(raw);
      }
      raf = requestAnimationFrame(frame);
    }
    // A computer that cannot keep 20 pictures a second for the black hole gets the still picture back: judged on
    // the first six pictures, on any two very late pictures in a row, and on the last 45.
    function watch(raw) {
      seen += 1;
      frames.push(raw);
      if (frames.length > 45) frames.shift();
      var avg = frames.reduce(function (a, b) { return a + b; }, 0) / frames.length;
      var late = frames.length > 1 && frames[frames.length - 1] > 0.25 && frames[frames.length - 2] > 0.25;
      if ((seen === 6 && avg > 0.05) || late || (frames.length === 45 && avg > 0.05)) {
        slow = true;
        scene.classList.remove("live");
      }
    }
    function drawAll(moving) {
      if (sky) sky.paint(clock, moving);
      drawScene(clock, moving);
    }
    function kick() {
      last = 0; frames = [];
      if (!raf) raf = requestAnimationFrame(frame);
    }

    sizeScene();
    shipLoaded = function () { if (shipG) paintShip(shipG, sw, sh, sdpr, pose(T0 + clock), null); };
    if (hole) {
      drawScene(0, false);
      // the still picture under the canvas gives way once the canvas has its first picture
      requestAnimationFrame(function () { scene.classList.add("live"); });
      // after a graphics-chip reset the still picture shows until the canvas has drawn again
      holeCanvas.addEventListener("webglcontextlost", function (e) { e.preventDefault(); scene.classList.remove("live"); });
      holeCanvas.addEventListener("webglcontextrestored", function () {
        hole = Hole(holeCanvas);
        if (!hole) return;
        boxKey = ""; sizeScene(); drawScene(clock, false);
        if (!slow) requestAnimationFrame(function () { scene.classList.add("live"); });
        kick();
      });
    }
    if (capture) { document.documentElement.classList.add("captured"); return; }
    if (sky) document.documentElement.classList.add("sky-live");
    // one redraw per picture however many resize events arrive, and only when the scene's box really changed
    window.addEventListener("resize", function () {
      if (queued) return;
      queued = true;
      requestAnimationFrame(function () {
        queued = false;
        if (sky) sky.size();
        var box = scene ? scene.getBoundingClientRect() : null;
        var key = box ? [box.left, box.width, box.height, window.devicePixelRatio].join() : "";
        if (key !== boxKey) { boxKey = key; sizeScene(); }
        if (sky) sky.paint(clock, !still.matches);
        if (heroOn) drawScene(clock, !still.matches);
      });
    });
    document.addEventListener("visibilitychange", function () { if (!document.hidden) kick(); });
    if (still.addEventListener) still.addEventListener("change", kick);
    if (scene && "IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) { heroOn = entries[0].isIntersecting; }).observe(scene);
    }
    drawAll(false);
    kick();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
