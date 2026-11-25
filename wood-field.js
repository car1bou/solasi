(() => {
  const canvases = [...document.querySelectorAll("canvas[data-wood]")];
  if (!canvases.length) return;
  const film = document.querySelector(".film");
  const stage = film.querySelector(".film-stage");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const mouse = matchMedia("(hover: hover) and (pointer: fine)");
  const clamp = (v, min, max) => Math.min(max, Math.max(min, v));
  const vertex = `
    attribute vec2 corner;
    varying vec2 uv;
    void main() {
      uv = vec2(corner.x * .5 + .5, .5 - corner.y * .5);
      gl_Position = vec4(corner, 0., 1.);
    }`;
  const fragment = `
    #ifdef GL_FRAGMENT_PRECISION_HIGH
    precision highp float;
    #else
    precision mediump float;
    #endif
    varying vec2 uv;
    uniform sampler2D photo;
    uniform vec4 crop; // UV origin and extent of the photograph behind this canvas
    uniform vec2 texel;
    uniform vec4 view; // visible part of the photographic plate at the opening
    uniform vec3 point;
    uniform vec4 state; // clock, signed scroll velocity, journey, surface aspect

    float bell(float x) { return exp2(-x*x); }
    float luma(vec2 p) { return dot(texture2D(photo, p).rgb, vec3(.30,.58,.12)); }

    void main() {
      float t = state.x;
      vec2 scene = (uv-view.xy)/view.zw;
      vec2 p = vec2((scene.x-.5)*state.w+.5, scene.y);
      vec2 d = vec2((scene.x-point.x)*state.w, scene.y-point.y);
      float touch = exp2(-dot(d*vec2(2.85,3.9), d*vec2(2.85,3.9))) * point.z;
      float x = p.x + .23*sin(state.z*2.4) + state.y*.035;
      float y = p.y + .24*state.z + state.y*.041;
      float bend = .154*sin(2.95*x+.36*t+y*.92)
                 + .076*sin(5.5*x-.27*t-2.4*y)
                 + .044*sin(4.3*x+.48*t+3.1*y);
      float h = y+bend + touch*(.156+.03*sin(x*4.-t)) + state.y*.045*sin(x*4.+y);
      float first = (h-.20-.104*sin(x*1.85-.42*t))*5.7;
      float second = (h-.82+.115*sin(x*2.55+.34*t))*6.7;
      float sideA = .52+.48*bell((x-.24-.26*sin(.36*t))*1.6);
      float sideB = .57+.43*bell((x-.78-.24*sin(.31*t))*1.8);
      float shoulder = max(bell(first)*sideA, bell(second)*sideB);
      float edge = max(bell((first+.43)*2.4)*sideA, bell((second-.34)*2.7)*sideB);

      // Broad curls carry a comb of fine ridges; the photographed pores break their symmetry.
      vec2 sampleAt = crop.xy+uv*crop.zw;
      float tone = luma(sampleAt);
      float pores = tone-luma(sampleAt+vec2(texel.x*2.,texel.y*2.8));
      float relief = clamp(.42 + 4.1*pores + .95*tone, .1, 1.);
      float cuts = h + .024*sin(8.3*x-3.*y+t*.09) + .014*sin(14.*y+2.*x) + .016*tone;
      float ribbon = .5+.5*sin(cuts*194.+2.7*sin(cuts*47.+x*3.7));
      float fine = .5+.5*sin(cuts*457.+x*5.+tone*8.);
      float glints = ribbon*ribbon*(.40+.60*fine);
      float opening = .73+.27*smoothstep(.05,.50,abs(scene.x-.50));
      float lit = opening * ((.33*shoulder + .37*edge + .17*shoulder*glints)*(.37+.77*relief)
                + touch*(.075+.16*glints)*(.55+.55*relief));
      float shade = .38*bell((h-.52)*4.9) + .12*(1.-shoulder);
      float level = lit-shade;
      vec3 color = mix(vec3(.067,.038,.029), vec3(.88,.595,.337)+.08*edge, step(0.,level));
      gl_FragColor = vec4(color, clamp(abs(level), 0., .78));
    }`;

  function makePainter(canvas, img) {
    const gl = canvas.getContext("webgl", {
      alpha: true, premultipliedAlpha: false, antialias: false, depth: false,
      stencil: false, powerPreference: "low-power"
    });
    if (!gl) return softLight(canvas);
    const program = gl.createProgram();
    for (const [type, code] of [[gl.VERTEX_SHADER, vertex], [gl.FRAGMENT_SHADER, fragment]]) {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, code);
      gl.compileShader(shader);
      gl.attachShader(program, shader);
      gl.deleteShader(shader);
    }
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
    gl.useProgram(program);
    const triangle = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, triangle);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,3,-1,-1,3]), gl.STATIC_DRAW);
    const corner = gl.getAttribLocation(program, "corner");
    gl.enableVertexAttribArray(corner);
    gl.vertexAttribPointer(corner, 2, gl.FLOAT, false, 0, 0);
    const uniforms = Object.fromEntries(["texel","crop","point","state","view"].map(name => [name, gl.getUniformLocation(program, name)]));
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    const neutral = new Uint8Array([70,55,43,255]);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, neutral);
    let source;
    return (t, velocity, travel, aspect, px, py, intensity, crop, view) => {
      gl.uniform4fv(uniforms.view, view);
      if (!img.complete || !img.naturalWidth || gl.isContextLost()) return;
      if (source !== img.currentSrc) {
        // Photo color is already present in the DOM; only a small relief map is needed.
        const relief = document.createElement("canvas");
        const scale = Math.min(1, 1280 / Math.max(img.naturalWidth, img.naturalHeight));
        relief.width = Math.max(1, Math.round(img.naturalWidth * scale));
        relief.height = Math.max(1, Math.round(img.naturalHeight * scale));
        relief.getContext("2d").drawImage(img, 0, 0, relief.width, relief.height);
        try {
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, relief);
          gl.uniform2f(uniforms.texel, 1 / relief.width, 1 / relief.height);
        } catch (error) {
          // Local file previews can forbid reading the photograph into a texture.
          if (error.name !== "SecurityError") throw error;
        }
        source = img.currentSrc;
      }
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform4fv(uniforms.crop, crop);
      gl.uniform3f(uniforms.point, px, py, intensity);
      gl.uniform4f(uniforms.state, t, velocity, travel, aspect);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };
  }

  // On a browser without WebGL the same warm side-light can be drawn as soft curved ribbons.
  function softLight(canvas) {
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    return (t, velocity, travel, aspect, px, py, intensity, crop, view) => {
      const w = canvas.width, h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.save();
      ctx.translate(view[0]*w,view[1]*h);
      ctx.scale(view[2],view[3]);
      const touchX = (px-.5)*aspect+.5;
      const bend = (x, y) => {
        const ridge = y - .13*Math.sin(x*3.2+t*.36+y) - .065*Math.sin(x*6.1-t*.27-y*2.4);
        return ridge - intensity*.14*Math.exp(-((x-touchX)**2*12+(ridge-py)**2*24));
      };
      for (const band of [.20,.52,.82]) {
        const shadow = band === .52;
        const y = band - travel*.18 + velocity*.045;
        for (let i=0; i<25; i++) {
          const offset = (i/24-.5)*(shadow ? .33 : .25);
          const opacity = 1-Math.abs(i/12-1);
          ctx.beginPath();
          for (let j=0; j<=72; j++) {
            const x = -.75+j/28;
            const pos = bend((x-.5)*aspect+.5, y+offset)*h;
            if (j) ctx.lineTo(x*w,pos); else ctx.moveTo(x*w,pos);
          }
          ctx.lineWidth = (i%5 === 0 ? .012 : .021)*h;
          ctx.strokeStyle = shadow ? `rgba(33,17,12,${opacity*.15})` : `rgba(224,166,102,${.013+opacity*.155})`;
          ctx.stroke();
        }
      }
      ctx.restore();
    };
  }

  const surfaces = canvases.map(canvas => {
    const surface = { canvas, hero: canvas.dataset.wood === "hero", img: canvas.parentElement.querySelector("img"), paint: undefined };
    canvas.addEventListener("webglcontextlost", event => { event.preventDefault(); surface.paint = null; });
    canvas.addEventListener("webglcontextrestored", () => { surface.paint = undefined; start(); });
    return surface;
  });
  let frame = 0, last = 0, clock = 0, velocity = 0, previousScroll = scrollY;
  let x = innerWidth*.4, y = innerHeight*.5, targetX = x, targetY = y, strength = 0, targetStrength = 0;

  function update(now) {
    frame = 0;
    if (document.hidden || reduced.matches || document.querySelector("dialog[open]")) return;
    const dt = clamp((now-last)/1000,.001,.05);
    last = now;
    clock = (clock + dt*.89) % (Math.PI*200);
    const follow = 1-Math.exp(-dt*5.5);
    x += (targetX-x)*follow;
    y += (targetY-y)*follow;
    strength += (targetStrength-strength)*follow;
    const scroll = scrollY;
    const speed = clamp((scroll-previousScroll)/(innerHeight*dt), -2, 2);
    velocity += (speed-velocity)*(1-Math.exp(-dt*3.5));
    previousScroll = scroll;
    const travel = scroll / Math.max(1, document.documentElement.scrollHeight-innerHeight);
    const bottom = film.getBoundingClientRect().bottom;
    let active = false;
    for (const surface of surfaces) {
      if (surface.hero ? bottom <= 0 || stage.classList.contains("inside-screen") : bottom >= innerHeight) continue;
      const {canvas, img, hero} = surface;
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) continue;
      const scale = Math.min(devicePixelRatio, 1440/Math.max(canvas.clientWidth,canvas.clientHeight), Math.sqrt(880000/(canvas.clientWidth*canvas.clientHeight)));
      const w = Math.max(1, Math.round(canvas.clientWidth*scale)), h = Math.max(1, Math.round(canvas.clientHeight*scale));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      if (surface.paint === undefined) surface.paint = makePainter(canvas,img);
      if (!surface.paint) continue;
      active = true;
      let crop = [0,0,1,1];
      if (!hero && img.naturalWidth) {
        const b = img.getBoundingClientRect();
        const fit = Math.max(b.width/img.naturalWidth,b.height/img.naturalHeight);
        const iw = img.naturalWidth*fit, ih = img.naturalHeight*fit;
        crop = [(rect.left-b.left+(iw-b.width)/2)/iw, (rect.top-b.top+(ih-b.height)/2)/ih, rect.width/iw, rect.height/ih];
      }
      // The camera publishes its opening crop even when a visitor arrives at a deep link.
      const framing = canvas.parentElement.dataset.woodView;
      if (framing && framing !== surface.framing) {
        surface.view = framing.split(" ").map(Number);
        surface.framing = framing;
      }
      const view = surface.view || [-rect.left/rect.width, -rect.top/rect.height, innerWidth/rect.width, innerHeight/rect.height];
      surface.paint(clock, velocity, travel, clamp(innerWidth/innerHeight,.8,1.95),
        ((x-rect.left)/rect.width-view[0])/view[2], ((y-rect.top)/rect.height-view[1])/view[3],
        strength, crop, view);
    }
    if (active) frame = requestAnimationFrame(update);
  }
  function start() {
    if (!frame && !document.hidden && !reduced.matches && !document.querySelector("dialog[open]")) {
      last = performance.now();
      previousScroll = scrollY;
      frame = requestAnimationFrame(update);
    }
  }
  document.addEventListener("pointermove", event => {
    if (!mouse.matches || event.pointerType !== "mouse") return;
    targetX = event.clientX; targetY = event.clientY; targetStrength = 1;
  }, {passive:true});
  function release() { targetStrength = 0; }
  document.documentElement.addEventListener("pointerleave", release);
  window.addEventListener("blur", release);
  mouse.addEventListener("change", release);
  for (const name of ["scroll","resize","pageshow"]) window.addEventListener(name, start, {passive:true});
  // An instant anchor jump can update the camera after the last sleeping material frame.
  new MutationObserver(start).observe(stage, {attributes: true, attributeFilter: ["class"]});
  document.addEventListener("visibilitychange", start);
  document.addEventListener("toggle", start, true);
  document.addEventListener("close", start, true);
  reduced.addEventListener("change", start);
  start();
})();
