/* Sigil site — themes from YAML, the live-coding editor, the 3D background and
   the playground (the repo's own Python, run by Pyodide).
   No dependencies. The background frames are view.py's own output (frames.json,
   made by build_site.py), coloured by theme role so they follow a theme change. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  // Reduced motion can change while the page is open: listeners stop the tilt
  // and pause the typing.
  const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");
  let reduceMotion = motionQuery.matches;
  const motionListeners = [];
  motionQuery.addEventListener?.("change", (e) => {
    reduceMotion = e.matches;
    motionListeners.forEach((fn) => fn(reduceMotion));
  });

  // Symbols Departure Mono lacks: they fall back to another font inside a fixed
  // 1ch cell (.fb), so a row's columns stay aligned. index.html loads the fallback
  // font for exactly these characters.
  const FALLBACK = /[↺↻⇱↩⇢∗▸▾◀▶◆◇◉○◎●✖✱◦✦∥⊘✕⎫⎪⎭①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]/g;
  const wrapFallback = (html) => html.replace(FALLBACK, '<span class="fb">$&</span>');

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  // ------------------------------------------------------------------ YAML subset
  // Exactly the subset themes.py reads (its module docstring is the contract;
  // tests/fixtures/yaml_cases.json checks both): nested maps, plain / "JSON-
  // escaped" / 'single-quoted' scalars, # comments, space indentation. Lists,
  // flow collections, tabs in the indent, duplicate and empty keys are errors.
  // Maps have no prototype, so a key like __proto__ is just a key.

  // What Python's str.isspace() calls whitespace (BMP), for the indent check.
  const PY_SPACE = /[\t\n\v\f\r\x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/;
  const stripTabs = (s) => s.replace(/^[ \t]+|[ \t]+$/g, "");

  /** s[i] opens a quote: the index just past its close (s.length if unclosed). */
  function skipQuoted(s, i) {
    const q = s[i];
    i++;
    while (i < s.length) {
      const ch = s[i];
      if (q === '"' && ch === "\\") { i += 2; continue; }
      if (ch === q) {
        if (q === "'" && s[i + 1] === "'") { i += 2; continue; }
        return i + 1;
      }
      i++;
    }
    return s.length;
  }

  function stripComment(line) {
    let i = 0;
    while (i < line.length) {
      const ch = line[i];
      if ((ch === '"' || ch === "'") && (i === 0 || " \t:".includes(line[i - 1]))) {
        i = skipQuoted(line, i);
        continue;
      }
      if (ch === "#" && (i === 0 || line[i - 1] === " " || line[i - 1] === "\t")) return line.slice(0, i);
      i++;
    }
    return line;
  }

  function singleQuoted(text, where) {
    let out = "";
    for (let i = 1; i < text.length; i++) {
      if (text[i] !== "'") { out += text[i]; continue; }
      if (text[i + 1] === "'") { out += "'"; i++; continue; }
      if (i + 1 !== text.length) throw new Error(`${where}: text after a closing single quote`);
      return out;
    }
    throw new Error(`${where}: unterminated single-quoted string`);
  }

  function scalar(text, where) {
    text = stripTabs(text);
    if (text[0] === '"') {
      let value;
      try { value = JSON.parse(text); } catch { value = null; }
      if (typeof value !== "string") throw new Error(`${where}: bad double-quoted string ${text}`);
      return value;
    }
    if (text[0] === "'") return singleQuoted(text, where);
    return text;
  }

  /** The key/value colon (followed by a space or the end), past a quoted key; -1 if none. */
  function findColon(body) {
    for (let i = body[0] === '"' || body[0] === "'" ? skipQuoted(body, 0) : 0; i < body.length; i++) {
      if (body[i] === ":" && (i + 1 === body.length || body[i + 1] === " ")) return i;
    }
    return -1;
  }

  function parseYaml(text, source = "theme") {
    if (text[0] === "\ufeff") text = text.slice(1);
    const root = Object.create(null);
    const stack = [[0, root]];                         // [indent, map], innermost last
    let pending = null;                                // a `key:` that may open a map
    text.replace(/\r\n/g, "\n").split("\n").forEach((raw, n) => {
      const where = `${source}:${n + 1}`;
      const line = stripComment(raw).replace(/[ \t]+$/, "");
      if (!stripTabs(line)) return;
      const indent = line.length - line.replace(/^ +/, "").length;
      if (PY_SPACE.test(line[indent])) throw new Error(`${where}: indent with spaces only`);
      const body = line.slice(indent);
      if (/^(- |\[|\{)/.test(body) || body === "-") {
        throw new Error(`${where}: lists and flow collections are not supported`);
      }
      if (pending) {
        const [pIndent, pMap, pKey] = pending;
        pending = null;
        if (indent > pIndent) {                        // deeper: `key:` opens a map
          pMap[pKey] = Object.create(null);
          stack.push([indent, pMap[pKey]]);
        }
      }
      while (indent < stack[stack.length - 1][0]) stack.pop();
      if (indent !== stack[stack.length - 1][0]) {
        if (stack.length === 1 && !Object.keys(root).length) throw new Error(`${where}: top-level keys start at column 0`);
        throw new Error(`${where}: inconsistent indentation`);
      }
      const cur = stack[stack.length - 1][1];
      const sep = findColon(body);
      if (sep < 0) throw new Error(`${where}: expected key: value`);
      const key = scalar(body.slice(0, sep), where);
      if (!key) throw new Error(`${where}: empty key`);
      if (key in cur) throw new Error(`${where}: duplicate key ${JSON.stringify(key)}`);
      const value = stripTabs(body.slice(sep + 1));
      cur[key] = value ? scalar(value, where) : "";
      if (!value) pending = [indent, cur, key];
    });
    return root;
  }

  // ------------------------------------------------------------------ themes

  const merge = (base, over) => {
    const out = Object.assign(Object.create(null), base);
    for (const [k, v] of Object.entries(over)) {
      out[k] = v && typeof v === "object" && out[k] && typeof out[k] === "object" ? merge(out[k], v) : v;
    }
    return out;
  };

  async function loadThemeRaw(name, seen = []) {
    if (seen.includes(name)) throw new Error(`theme extends cycle at ${name}`);
    const res = await fetch(`themes/${encodeURIComponent(name)}.yaml`);
    if (!res.ok) throw new Error(`theme ${name}: HTTP ${res.status}`);
    let theme = parseYaml(await res.text(), `${name}.yaml`);
    if (theme.extends) {
      const parent = await loadThemeRaw(theme.extends, [...seen, name]);
      delete theme.extends;
      theme = merge(parent, theme);
    }
    return theme;
  }

  let appliedVars = [];
  function applyTheme(theme) {
    const style = document.documentElement.style;
    appliedVars.forEach((v) => style.removeProperty(v));
    appliedVars = [];
    style.colorScheme = "";
    for (const [section, entries] of Object.entries(theme)) {
      if (!entries || typeof entries !== "object") continue;
      for (const [key, value] of Object.entries(entries)) {
        if (typeof value !== "string") continue;
        const prop = `--${section}-${key.replace(/_/g, "-")}`;
        const css = value.startsWith("$") ? `var(--palette-${value.slice(1)})` : value;
        style.setProperty(prop, css);
        appliedVars.push(prop);
      }
    }
    if (theme.type === "dark" || theme.type === "light") style.colorScheme = theme.type;
    document.documentElement.dataset.theme = theme.name || "";
  }

  async function initThemes() {
    const select = $("#theme");
    let request = 0;                                   // the latest choice wins a load race
    try {
      const res = await fetch("themes/index.yaml");
      if (res.ok) {
        const index = parseYaml(await res.text(), "index.yaml").themes || {};
        select.innerHTML = Object.entries(index)
          .map(([name, label]) => `<option value="${esc(name)}">${esc(label)}</option>`).join("");
      }
    } catch { /* keep the built-in option */ }
    const wanted = new URLSearchParams(location.search).get("theme") || store.get("sigil-theme") || "sigil";
    if ([...select.options].some((o) => o.value === wanted)) select.value = wanted;
    const use = async (name, save) => {
      const id = ++request;
      try {
        const theme = await loadThemeRaw(name);
        if (id !== request) return;
        applyTheme(theme);
        if (save) store.set("sigil-theme", name);     // only a choice made here, not ?theme=
      } catch (err) {
        console.warn(err);
      }
    };
    select.addEventListener("change", () => use(select.value, true));
    await use(select.value, false);
  }

  // ------------------------------------------------------------------ logo

  const GLYPH_KIND = { "[": "service", "{": "data", "<": "event", "(": "actor", "|": "store" };

  function drawLogo() {
    const name = new URLSearchParams(location.search).get("logo") || document.body.dataset.logo;
    const tpl = $(`template[data-logo="${CSS.escape(name)}"]`) || $("template[data-logo]");
    if (!tpl) return;
    const art = tpl.content.textContent;
    // An optional mask (same shape as the art) marks cells drawn in the accent colour.
    const maskTpl = $(`template[data-logo-mask="${CSS.escape(tpl.dataset.logo)}"]`);
    const code = new Array(art.length).fill(" ");
    if (maskTpl) {
      const rows = maskTpl.content.textContent.split("\n");
      let line = 0, col = 0;
      for (let i = 0; i < art.length; i++) {
        if (art[i] === "\n") { line++; col = 0; continue; }
        const c = (rows[line] || "")[col] || " ";
        code[i] = /^[a-z0-9]$/.test(c) ? c : " ";      // it becomes a class name
        col++;
      }
    }
    const re = /([[{<(|])([A-Z])([\]}>)|])|([·◦])|([✦◆◇])|([─~═!?✱]?▶)|([▀-▟]+)|(●)/g;
    const tokens = (text) => {          // unmasked art: colour by what the characters are
      let html = "", last = 0, m;
      re.lastIndex = 0;
      while ((m = re.exec(text))) {
        html += esc(text.slice(last, m.index));
        if (m[1]) {
          const k = GLYPH_KIND[m[1]];
          html += `<span class="g-${k}">${esc(m[1])}</span><span class="letter">${m[2]}</span><span class="g-${k}">${esc(m[3])}</span>`;
        } else if (m[4]) html += `<span class="dot">${m[4]}</span>`;
        else if (m[5]) html += `<span class="star">${m[5]}</span>`;
        else if (m[6]) html += `<span class="arrow">${esc(m[6])}</span>`;
        else if (m[7]) html += `<span class="mark">${m[7]}</span>`;
        else html += `<span class="via">●</span>`;
        last = re.lastIndex;
      }
      return html + esc(text.slice(last));
    };
    // masked cells take their code's colour; the rest go through tokens()
    let html = "";
    for (let i = 0; i < art.length;) {
      let j = i;
      while (j < art.length && code[j] === code[i] && art[j] !== "\n") j++;
      if (j === i) j = i + 1;                          // a newline
      const text = art.slice(i, j);
      html += code[i] === " " || text === "\n" ? tokens(text) : `<span class="k-${code[i]}">${esc(text)}</span>`;
      i = j;
    }
    $("#logo").innerHTML = wrapFallback(html);
    $("#logo").dataset.logo = tpl.dataset.logo;
  }

  // ------------------------------------------------------------------ highlighter
  // Token roles match highlight/sigil.tmTheme; colours come from --syntax-*.

  const RULES = [
    ["comment", /(?<=^|\s)#(?!!).*$/y],
    ["string", /"(?:[^"\\]|\\.)*"/y],
    ["ref", /\$\{[^}]*\}/y],
    ["branch", /\\-(?:\*-?)?(?:\(\d+\)-|\{[^}]*\}-)?(?:->|[>&?$@!=_])?/y],
    ["operator", /<->|\]>\[|->|~>|=>|!>|\?>|\*>|:=|&\?|&|-(?=<)/y],
    ["modifier", /@[A-Za-z_][\w-]*(?:\([^)]*\))?/y],
    ["cardinality", /[×^]\d+(?:@\w+)?/y],
    ["glyph", /[~*]?(?:\[[^\]\s][^\]]*\]|\{[^}\s][^}]*\}|<[A-Za-z?_][^>]*>|(?<!\w)\([^)\s][^)]*\)|\|[^|\s][^|]*\|)/y],
    ["keyword", /\b(?:state|loop|parallel|branch)\b/y],
    ["number", /\b\d+(?:\.\d+)?\b/y],
    ["punct", /[:,/]/y],
    ["tag", /[A-Za-z_][\w.]*/y],
  ];

  function glyphHtml(tok) {
    const lead = tok.match(/^[~*]?/)[0];
    const open = tok[lead.length];
    const close = tok[tok.length - 1];
    const name = tok.slice(lead.length + 1, -1);
    const nameCls = name === "?" ? "t-hole" : "t-name";
    return (lead ? `<span class="t-operator">${esc(lead)}</span>` : "") +
      `<span class="t-glyph">${esc(open)}</span><span class="${nameCls}">${esc(name)}</span>` +
      `<span class="t-glyph">${esc(close)}</span>`;
  }

  function highlight(line) {
    if (/^\s*#!/.test(line)) return `<span class="t-shebang">${esc(line)}</span>`;
    const sec = line.match(/^(\s*)(---)(\s*)(.*?)(\s*)(---)(\s*)$/);
    if (sec) {
      return `${sec[1]}<span class="t-rails">---</span>${sec[3]}<span class="t-section">${esc(sec[4])}</span>` +
        `${sec[5]}<span class="t-rails">---</span>`;
    }
    let out = "", i = 0;
    outer: while (i < line.length) {
      for (const [role, re] of RULES) {
        re.lastIndex = i;
        const m = re.exec(line);
        if (m && m[0]) {
          out += role === "glyph" ? glyphHtml(m[0]) : `<span class="t-${role}">${esc(m[0])}</span>`;
          i += m[0].length;
          continue outer;
        }
      }
      out += esc(line[i]);
      i++;
    }
    return out;
  }

  // ------------------------------------------------------------------ frames

  /** A frame colour as CSS: "#hex", a theme role ("kinds-service") or a tinted
      role derived from one ("tint:", "muted:", "trail:", "faint:" + a role); anything
      else is dropped (it goes into <style>). */
  function roleCss(role) {
    if (typeof role !== "string") return null;
    if (/^#[0-9a-f]{3,8}$/i.test(role)) return role;
    const m = role.match(/^(tint:|muted:|trail:|faint:)?([a-z0-9-]+)$/);
    if (!m) return null;
    const muted = `hsl(from var(--${m[2]}) h calc(s * var(--ui-name-saturation)) l)`;
    if (m[1] === "tint:") return `color-mix(in srgb, var(--${m[2]}) calc(var(--ui-fill) * 100%), var(--palette-bg))`;
    if (m[1] === "muted:") return muted;
    // a sim run's wires: taken before (trail) and never taken (faint), faded toward bg
    if (m[1] === "trail:") return `color-mix(in srgb, var(--${m[2]}) calc(var(--ui-sim-trail) * 100%), var(--palette-bg))`;
    if (m[1] === "faint:") return `color-mix(in srgb, ${muted} calc(var(--ui-sim-faint) * 100%), var(--palette-bg))`;
    return `var(--${m[2]})`;
  }

  function installFrameStyles(styles) {
    const css = styles.map(([fg, bg, bold], i) => {
      const parts = [];
      const fgCss = roleCss(fg), bgCss = roleCss(bg);
      if (fgCss) parts.push(`color:${fgCss}`);
      if (bgCss) parts.push(`background:${bgCss}`);
      if (bold) parts.push("font-weight:700");
      return parts.length ? `.f${i}{${parts.join(";")}}` : "";
    }).join("\n");
    const el = document.createElement("style");
    el.textContent = css;
    document.head.appendChild(el);
  }

  const frameHtml = (rows) => rows.map((row) =>
    row.map(([text, sid]) => `<span class="f${Number(sid)}">${wrapFallback(esc(String(text)))}</span>`).join(""))
    .join("\n");

  // ------------------------------------------------------------------ scene

  function rng(seed) {                                   // mulberry32
    return () => {
      seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const NAMES = ["Api", "Auth", "Cart", "Pay", "Log", "Db", "Queue", "Cache", "Job", "User",
    "Ord", "Bus", "Ship", "Hp", "Xf", "Risk", "Edge", "Feed", "Sync", "Lock", "Tick", "Mesh"];
  const KINDS = [["[", "]", "service"], ["{", "}", "data"], ["<", ">", "event"], ["(", ")", "actor"], ["|", "|", "store"]];
  const LATTICE = "··········[]{}<>()|~*&";

  /** A floating grid of glyph characters: a faint lattice, glyph nodes, and
      circuit wiring between them. Returns HTML. */
  function glyphGrid(cols, rows, seed) {
    const r = rng(seed);
    const grid = Array.from({ length: rows }, () => Array.from({ length: cols }, () => [" ", ""]));
    const set = (x, y, ch, cls, force) => {
      if (y < 0 || y >= rows || x < 0 || x >= cols) return false;
      const c = grid[y][x];
      if (!force && c[1] && c[1] !== "faint") return false;
      grid[y][x] = [ch, cls];
      return true;
    };
    for (let y = 1; y < rows; y += 2) {
      for (let x = 2; x < cols; x += 4) if (r() < 0.55) set(x, y, LATTICE[Math.floor(r() * LATTICE.length)], "faint");
    }
    const nodes = [];
    const want = Math.floor((cols * rows) / 170);
    for (let tries = 0; nodes.length < want && tries < want * 20; tries++) {
      const [open, close, kind] = KINDS[Math.floor(r() * KINDS.length)];
      const label = open + NAMES[Math.floor(r() * NAMES.length)] + close;
      const x = 2 + Math.floor(r() * (cols - label.length - 4));
      const y = 1 + 2 * Math.floor(r() * ((rows - 2) / 2));
      if (nodes.some((n) => Math.abs(n.y - y) < 3 && x < n.x + n.w + 6 && n.x < x + label.length + 6)) continue;
      nodes.push({ x, y, w: label.length, label, kind, delay: (r() * 6).toFixed(2), dur: (4 + r() * 5).toFixed(2) });
    }
    for (const n of nodes) {
      [...n.label].forEach((ch, i) => set(n.x + i, n.y, ch, `node g-${n.kind}`, true));
    }
    // wires: each node to its nearest neighbour to the right, routed right-down/up-right
    for (const a of nodes) {
      const b = nodes.filter((n) => n.x > a.x + a.w + 3)
        .sort((p, q) => Math.hypot(p.x - a.x, (p.y - a.y) * 2) - Math.hypot(q.x - a.x, (q.y - a.y) * 2))[0];
      if (!b || r() < 0.2) continue;
      const x0 = a.x + a.w, x1 = b.x - 1, mid = Math.floor((x0 + x1) / 2);
      const y0 = a.y, y1 = b.y;
      for (let x = x0; x < mid; x++) set(x, y0, "─", "wire");
      if (y0 !== y1) {
        const down = y1 > y0;
        set(mid, y0, down ? "╮" : "╯", "wire");
        for (let y = Math.min(y0, y1) + 1; y < Math.max(y0, y1); y++) set(mid, y, "│", "wire");
        set(mid, y1, down ? "╰" : "╭", "wire");
      } else set(mid, y0, "─", "wire");
      for (let x = mid + 1; x < x1; x++) set(x, y1, "─", "wire");
      set(x1, y1, "▶", "t-operator");
    }
    const nodeAt = new Map(nodes.map((n) => [`${n.x},${n.y}`, n]));     // a node's first cell
    return grid.map((row, y) => {
      let html = "", run = "", cls = null, style = "";
      const flush = () => {
        if (!run) return;
        const text = wrapFallback(esc(run));
        html += cls ? `<span class="${cls}"${style}>${text}</span>` : text;
        run = "";
      };
      row.forEach(([ch, c], x) => {
        const node = nodeAt.get(`${x},${y}`);
        if (c !== cls || node) {
          flush();
          cls = c;
          style = node ? ` style="--delay:-${node.delay}s;--dur:${node.dur}s"` : "";
        }
        run += ch;
      });
      flush();
      return html;
    }).join("\n");
  }

  const GRIDS = [
    { x: "-40vw", y: "-26vh", z: -1500, ry: 24, d: 4.6, cols: 74, rows: 26, seed: 11 },
    { x: "42vw", y: "-30vh", z: -1150, ry: -26, d: 3.8, cols: 64, rows: 22, seed: 23 },
    { x: "-46vw", y: "30vh", z: -820, ry: 30, d: 2.8, cols: 60, rows: 20, seed: 37 },
    { x: "44vw", y: "32vh", z: -620, ry: -22, d: 2.4, cols: 56, rows: 18, seed: 41 },
    { x: "2vw", y: "-46vh", z: -1350, rx: -24, d: 4.2, cols: 90, rows: 16, seed: 53 },
    { x: "-34vw", y: "44vh", z: 260, ry: 16, d: 5.4, cols: 46, rows: 14, seed: 67 },
    { x: "38vw", y: "-6vh", z: 380, ry: -14, d: 6.0, cols: 40, rows: 16, seed: 71 },
  ];
  const VIEWS = {
    tree: { x: "27vw", y: "14vh", z: -40, ry: -16, d: 0.7, label: "view.py --tree" },
    graph: { x: "-27vw", y: "8vh", z: -340, ry: 18, d: 1.2, label: "view.py --payloads" },
  };

  function placePlane(el, p) {
    el.style.setProperty("--x", p.x);
    el.style.setProperty("--y", p.y);
    el.style.setProperty("--z", `${p.z}px`);
    el.style.setProperty("--ry", `${p.ry || 0}deg`);
    el.style.setProperty("--rx", `${p.rx || 0}deg`);
    el.style.setProperty("--d", p.d);
  }

  function buildScene() {
    const stage = $("#stage");
    const small = innerWidth < 700;
    GRIDS.slice(0, small ? 4 : GRIDS.length).forEach((g) => {
      const el = document.createElement("pre");
      el.className = "plane grid";
      el.innerHTML = glyphGrid(g.cols, g.rows, g.seed);
      placePlane(el, g);
      stage.appendChild(el);
    });
    const views = {};
    for (const [name, p] of Object.entries(VIEWS)) {
      const el = document.createElement("pre");
      el.className = `plane view ${name}`;
      el.innerHTML = `<span class="label">${esc(p.label)}</span><div class="frame"></div>`;
      placePlane(el, small ? { ...p, x: name === "tree" ? "8vw" : "-8vw", z: p.z - 300 } : p);
      stage.appendChild(el);
      views[name] = el;
    }
    initTilt(stage);
    initSceneFade($("#scene"));
    return views;
  }

  /** Drift + pointer tilt, eased by the stage's CSS transition (1.8 s, so it
      settles before the next 2 s tick). Off with reduced motion or a hidden tab. */
  function initTilt(stage) {
    let px = 0, py = 0, timer = null;
    const onPointer = (e) => {
      px = e.clientX / innerWidth - 0.5;
      py = e.clientY / innerHeight - 0.5;
    };
    const tilt = () => {
      const t = performance.now() / 1000;
      const ry = px * 5 + Math.sin(t / 9) * 2.5;
      const rx = -py * 4 + Math.cos(t / 11) * 1.5;
      stage.style.transform = `rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg)`;
    };
    const start = () => {
      if (timer || reduceMotion || document.hidden) return;
      addEventListener("pointermove", onPointer, { passive: true });
      tilt();
      timer = setInterval(tilt, 2000);
    };
    const stop = () => {
      clearInterval(timer);
      timer = null;
      removeEventListener("pointermove", onPointer);
    };
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stop();
      else start();
    });
    motionListeners.push((reduce) => {
      if (reduce) {
        stop();
        stage.style.transform = "";
      } else {
        start();
      }
    });
    start();
  }

  /** The background dims as the page scrolls: #scene's own opacity, once per frame. */
  function initSceneFade(scene) {
    let queued = false;
    const fade = () => {
      queued = false;
      const k = Math.min(scrollY / innerHeight, 1);
      scene.style.opacity = (1 - 0.6 * k).toFixed(3);
    };
    addEventListener("scroll", () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(fade);
    }, { passive: true });
    fade();
  }

  // ------------------------------------------------------------------ tabs

  /** ARIA tabs with a roving tabindex: click, ArrowLeft/Right (wrapping), Home
      and End select a tab and call onSelect(tab). mark(tab) only shows a tab as
      selected (for a selection made in code). */
  function initTabs(tablist, onSelect) {
    const tabs = () => $$("[role=tab]", tablist);
    const mark = (tab) => {
      tabs().forEach((t) => {
        const on = t === tab;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
      });
    };
    const choose = (tab, focus) => {
      mark(tab);
      if (focus) tab.focus();
      onSelect(tab);
    };
    tablist.addEventListener("click", (e) => {
      const tab = e.target.closest("[role=tab]");
      if (tab && tablist.contains(tab)) choose(tab, false);
    });
    tablist.addEventListener("keydown", (e) => {
      const list = tabs();
      const i = list.indexOf(e.target);
      if (i < 0) return;
      const to = { ArrowLeft: i - 1, ArrowRight: i + 1, Home: 0, End: list.length - 1 }[e.key];
      if (to === undefined) return;
      e.preventDefault();
      choose(list[(to + list.length) % list.length], true);
    });
    return { mark };
  }

  // ------------------------------------------------------------------ player

  function player(data, views) {
    const code = $("#code");
    const tablist = $("#tabs");
    const playBtn = $("#play");
    const status = { lint: $("#st-lint"), count: $("#st-count"), line: $("#st-line") };
    const st = { ex: 0, line: 0, col: 0, playing: !reduceMotion, timer: null, shown: {} };
    const highlighted = data.examples.map(() => []);   // per example, per line: highlight() output
    const swaps = {};                                  // per view: its pending frame swap
    let rowsShown = 0;                                 // finished rows in #code
    let nowRow = null;                                 // the row being typed

    tablist.innerHTML = data.examples.map((e, i) =>
      `<button type="button" role="tab" id="ex-tab-${i}" data-i="${i}" aria-controls="code" ` +
      `aria-selected="false" tabindex="-1">${esc(e.file)}</button>`).join("");
    const tabs = initTabs(tablist, (tab) => select(Number(tab.dataset.i)));

    const ex = () => data.examples[st.ex];
    const lineHtml = (i) => {
      const cache = highlighted[st.ex];
      if (cache[i] === undefined) cache[i] = highlight(ex().lines[i]);
      return cache[i];
    };

    function showFrame(name, id) {
      const rows = data.frames[id];
      if (!rows || st.shown[name] === id) return;
      st.shown[name] = id;
      const el = views[name];
      const swap = () => {
        $(".frame", el).innerHTML = frameHtml(rows);
        el.classList.remove("swap");
      };
      clearTimeout(swaps[name]);
      if (reduceMotion) {
        swap();
        return;
      }
      el.classList.add("swap");
      swaps[name] = setTimeout(swap, 140);
    }

    function applyStep(lineIdx) {
      let s = null;
      for (const step of ex().steps) if (step.line <= lineIdx) s = step;
      if (!s) return;
      showFrame("tree", s.tree);
      showFrame("graph", s.graph);
      status.lint.textContent = `lint: ${s.lint}`;
      status.lint.className = s.lint === "OK" ? "ok" : "bad";
      status.count.textContent = `${s.nodes} nodes · ${s.edges} edges`;
    }

    // #code holds one .row per line, "\n" between rows. A finished row is
    // highlighted once and appended; only the row being typed is redrawn.
    function addRow(i, parent) {
      const row = document.createElement("span");
      row.className = "row";
      if (i > 0) parent.append("\n");
      parent.append(row);
      return row;
    }

    function fillRow(row, i, html) {
      row.innerHTML = `<span class="ln">${i + 1}</span>${html}`;
    }

    function clearCode() {
      code.textContent = "";
      code.setAttribute("aria-labelledby", `ex-tab-${st.ex}`);
      rowsShown = 0;
      nowRow = null;
    }

    function render() {
      const lines = ex().lines;
      const done = Math.min(st.line, lines.length);
      const before = rowsShown + (nowRow ? 1 : 0);
      if (nowRow && rowsShown < done) {               // the typed row is finished
        nowRow.classList.remove("now");
        fillRow(nowRow, rowsShown, lineHtml(rowsShown));
        nowRow = null;
        rowsShown++;
      }
      if (rowsShown < done) {
        const frag = document.createDocumentFragment();
        for (; rowsShown < done; rowsShown++) fillRow(addRow(rowsShown, frag), rowsShown, lineHtml(rowsShown));
        code.append(frag);
      }
      if (st.line < lines.length) {
        if (!nowRow) {
          nowRow = addRow(st.line, code);
          nowRow.classList.add("now");
        }
        fillRow(nowRow, st.line, highlight(lines[st.line].slice(0, st.col)) + '<span class="caret"></span>');
      }
      if (rowsShown + (nowRow ? 1 : 0) > before) {     // a row was added
        code.scrollTop = code.scrollHeight;
        status.line.textContent = `${ex().file} · line ${Math.min(st.line + 1, lines.length)}/${lines.length}`;
      }
    }

    function select(i, play = st.playing) {
      clearTimeout(st.timer);
      st.ex = i;
      st.line = 0;
      st.col = 0;
      tabs.mark(tablist.children[i]);
      clearCode();
      if (!play) {
        finish(false);
        return;
      }
      render();
      schedule(400);
    }

    function finish(advance = true) {
      clearTimeout(st.timer);
      st.line = ex().lines.length;
      render();
      applyStep(st.line - 1);
      if (advance && st.playing) st.timer = setTimeout(next, 6000);
    }

    const next = () => select((st.ex + 1) % data.examples.length);

    function schedule(ms) {
      clearTimeout(st.timer);
      if (st.playing) st.timer = setTimeout(tick, ms);
    }

    function tick() {
      const lines = ex().lines;
      if (st.line >= lines.length) {
        finish();
        return;
      }
      const line = lines[st.line];
      if (st.col < line.length) {
        // A space is typed together with the character after it, so indents and
        // gaps go by at half the keystrokes; a short pause after whitespace.
        st.col += line[st.col] === " " ? 2 : 1;
        render();
        const ch = line[st.col - 1] || "";
        schedule(/\s/.test(ch) ? 18 : 30 + Math.random() * 40);
        return;
      }
      applyStep(st.line);
      st.line++;
      st.col = 0;
      render();
      if (st.line >= lines.length) {
        finish();
        return;
      }
      schedule(line.trim() ? 380 : 140);
    }

    function setPlaying(on) {
      st.playing = on;
      playBtn.textContent = on ? "pause" : "play";
      playBtn.title = on ? "Pause typing" : "Resume typing";
    }

    playBtn.addEventListener("click", () => {
      setPlaying(!st.playing);
      if (!st.playing) clearTimeout(st.timer);
      else if (st.line >= ex().lines.length) next();
      else schedule(100);
    });
    $("#skip").addEventListener("click", () => finish());
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) clearTimeout(st.timer);
      else if (st.playing) schedule(300);
    });
    motionListeners.push((reduce) => {
      if (!reduce || !st.playing) return;
      setPlaying(false);
      finish(false);
    });
    setPlaying(st.playing);
    select(0);
  }

  // ------------------------------------------------------------------ playground
  // The repo's own Python (copied byte for byte into py/ by build_site.py) run by
  // Pyodide: playground.py asks view.py / lint.py / sim.py for a drawing and packs
  // it the way frames.json is packed, and check.py for the design's findings.
  // Nothing about the notation is decided here.

  const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
  const SHARE = "play=";
  const CHECK_WAIT = 450;          // ms of quiet typing before a check (a draw waits 180)
  const CHECK_BUDGET = 1500;       // ms a check may take before checking waits for the button
  const VIEW_KEYS = "1 2 3 4 t";     // the drawing's view keys, as the terminal viewer's

  // Run speeds in frames a second: the terminal viewer's - / + steps. A run starts
  // at a readable 2/s; a viewer's own choice is remembered (index into the steps).
  const SIM_SPEEDS = [0.25, 0.5, 1, 2, 4, 8, 16, 32];
  const SIM_SPEED = 3;
  const SPEED_KEY = "sigil-pg-speed";
  const speedLabel = (fps) => `${{ 0.25: "¼", 0.5: "½" }[fps] ?? fps}/s`;
  function speedIndex(saved) {
    const i = saved ? Number(saved) : NaN;
    return Number.isInteger(i) && i >= 0 && i < SIM_SPEEDS.length ? i : SIM_SPEED;
  }

  // The findings panel's list items: check.py's findings, then the acknowledged
  // ones (dimmed, with their reason). data-line is the line a click selects.
  function findingsHtml(findings, accepted) {
    const item = (f, cls, tail) =>
      `<li class="${esc(cls)}"><button type="button" data-line="${Number(f.line)}">` +
      `${esc(cls)}:${Number(f.line)}:${esc(f.rule)}</button> ${esc(f.name)}: ${esc(tail)}` +
      (f.why ? `<span class="pg-why">${esc(f.why)}</span>` : "") + "</li>";
    return findings.map((f) => item(f, f.severity, f.message)).join("") +
      accepted.map((f) => item(f, "accepted", f.acknowledged || "")).join("");
  }

  // A run's story under the drawing, worded by view.py (sim.narrate) as the
  // terminal viewer's rows under its footer: `path` and the episode's hops so
  // far by branch (view.py's styled rows, the hop now bold, drawn by
  // `rowsHtml`; without them the text), the STORY_ROWS beats before this one
  // (dim), then this one after `›` — the narration line. Mono reads them all;
  // the classes only rank them.
  const STORY_ROWS = 2;
  function storyHtml(r, rowsHtml) {
    const told = r.story || [];
    const rows = r.path && rowsHtml ? [rowsHtml(r.path)]
      : [`<span class="pg-dim">path   </span>${esc(r.trail || "")}`];
    rows.push(...told.slice(-STORY_ROWS - 1, -1).map((b) => `<span class="pg-dim">  ${esc(b)}</span>`));
    rows.push(`<span class="pg-now">› ${esc(r.say || "")}</span>`);
    return rows.join("\n");
  }

  const b64url = {
    encode(text) {
      let bin = "";
      for (const b of new TextEncoder().encode(text)) bin += String.fromCharCode(b);
      return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    },
    decode(s) {
      const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/"));
      return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
    },
  };

  function sharedText() {
    const h = location.hash.slice(1);
    if (!h.startsWith(SHARE)) return null;
    try { return b64url.decode(h.slice(SHARE.length)); } catch { return null; }
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = src;
      el.onload = resolve;
      el.onerror = () => reject(new Error(`could not load ${src}`));
      document.head.append(el);
    });
  }

  function initPlayground(examples) {
    const root = $("#pg");
    if (!root) return;
    const el = {
      go: $("#pg-go"), msg: $("#pg-msg"), app: $("#pg-app"), example: $("#pg-example"),
      views: [...document.querySelectorAll("#pg-views button[data-view]")], share: $("#pg-share"),
      src: $("#pg-src"), hl: $("#pg-hl"), draw: $("#pg-draw"), legend: $("#pg-legend"),
      story: $("#pg-story"),
      scenario: $("#pg-scenario"), back: $("#pg-back"), play: $("#pg-play"), fwd: $("#pg-fwd"),
      scrub: $("#pg-scrub"), tick: $("#pg-tick"), speed: $("#pg-speed"), lint: $("#pg-lint"),
      count: $("#pg-count"), diags: $("#pg-diags"), log: $("#pg-log"), check: $("#pg-check"),
      findings: $("#pg-findings"), mode: $("#pg-mode"), recheck: $("#pg-recheck"),
    };
    const st = { view: "tree", scenario: "", frame: 0, last: 0, beats: [], playing: false,
      speed: speedIndex(store.get(SPEED_KEY)),
      timer: null, typing: null, styles: 0, api: null, booting: false,
      checkTimer: null, checked: "", checkPaused: false };

    el.speed.innerHTML = SIM_SPEEDS.map((fps, i) =>
      `<option value="${i}">${speedLabel(fps)}</option>`).join("");
    el.speed.value = String(st.speed);

    el.example.innerHTML = examples.map((e, i) =>
      `<option value="${i}">${esc(e.file)}</option>`).join("");

    // frame styles: ids are stable for the session; add the ones not seen yet
    const sheet = document.createElement("style");
    document.head.append(sheet);
    function addStyles(table) {
      let css = "";
      for (; st.styles < table.length; st.styles++) {
        const [fg, bg, bold] = table[st.styles];
        const parts = [];
        const fgCss = roleCss(fg), bgCss = roleCss(bg);
        if (fgCss) parts.push(`color:${fgCss}`);
        if (bgCss) parts.push(`background:${bgCss}`);
        if (bold) parts.push("font-weight:700");
        if (parts.length) css += `.p${st.styles}{${parts.join(";")}}\n`;
      }
      if (css) sheet.append(css);
    }
    const rowsHtml = (rows) => rows.map((row) => row.map(([text, sid]) =>
      `<span class="p${Number(sid)}">${wrapFallback(esc(String(text)))}</span>`).join("")).join("\n");

    function say(text, bad = false) {
      el.msg.textContent = text;
      el.msg.classList.toggle("bad", bad);
    }

    async function boot() {
      if (st.booting || st.api) return;
      st.booting = true;
      el.go.disabled = true;
      root.dataset.state = "loading";
      try {
        say("loading Python (Pyodide)…");
        if (!window.loadPyodide) await loadScript(`${PYODIDE}pyodide.js`);
        const py = await window.loadPyodide({ indexURL: PYODIDE });
        say("loading sigil…");
        const res = await fetch("py/manifest.json");
        if (!res.ok) throw new Error(`py/manifest.json: HTTP ${res.status}`);
        const man = await res.json();
        py.FS.mkdirTree("/sigil/themes");
        const get = async (url) => {
          const r = await fetch(url);
          if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
          return r.text();
        };
        await Promise.all([
          ...man.files.map(async (f) => py.FS.writeFile(`/sigil/${f}`, await get(`py/${f}`))),
          ...man.themes.map(async (f) => py.FS.writeFile(`/sigil/themes/${f}`, await get(`themes/${f}`))),
        ]);
        py.runPython("import sys; sys.path.insert(0, '/sigil')");
        st.api = py.pyimport("playground");
        root.dataset.state = "ready";
        el.app.hidden = false;
        say("");
        const shared = sharedText();
        setText(shared ?? examples[0]?.lines.join("\n") ?? "#!sketch\n[A] -> [B]\n");
        if (shared === null) el.example.value = "0";
        refresh();
      } catch (err) {
        console.error(err);
        root.dataset.state = "idle";
        el.go.disabled = false;
        say(`the playground could not start: ${err.message || err}`, true);
      } finally {
        st.booting = false;
      }
    }

    function call(fn, req) {
      try {
        return JSON.parse(st.api[fn](JSON.stringify(req)));
      } catch (err) {
        const text = String(err.message || err).trim().split("\n").pop();
        return { error: text };
      }
    }

    // the editor: a transparent textarea over its highlighted copy
    function paint() {
      el.hl.innerHTML = el.src.value.split("\n").map(highlight).join("\n") + "\n";
      syncScroll();
    }
    function syncScroll() {
      el.hl.scrollTop = el.src.scrollTop;
      el.hl.scrollLeft = el.src.scrollLeft;
    }
    function setText(text) {
      el.src.value = text.replace(/\n$/, "");
      paint();
    }

    function cols() {
      const probe = document.createElement("span");
      probe.textContent = "0".repeat(20);
      probe.style.visibility = "hidden";
      el.draw.append(probe);
      const ch = probe.getBoundingClientRect().width / 20 || 8;
      probe.remove();
      return Math.max(30, Math.floor((el.draw.clientWidth - 16) / ch));
    }

    const request = () => ({ text: el.src.value, view: st.view, width: cols() });

    function showDrawing(r) {
      addStyles(r.styles);
      el.draw.innerHTML = rowsHtml(r.rows);
      el.legend.innerHTML = rowsHtml(r.legend || []);
    }

    // a fresh draw: lint, counts and the scenario list follow the text
    function refresh() {
      const r = call("draw", request());
      if (r.error) {
        el.lint.textContent = `python: ${r.error}`;
        el.lint.className = "bad";
        return;
      }
      showDrawing(r);
      const errs = r.lint.filter((d) => d.severity === "error").length;
      const warns = r.lint.filter((d) => d.severity === "warn").length;
      el.lint.textContent = `lint: ${errs || warns ? `${errs}E ${warns}W` : "OK"}`;
      el.lint.className = errs || warns ? "bad" : "ok";
      el.count.textContent = `${r.nodes} nodes · ${r.edges} edges`;
      el.diags.innerHTML = r.lint.map((d, i) =>
        `<li class="${esc(d.severity)}"><button type="button" data-i="${i}">` +
        `${esc(d.severity)}:${d.line}:${esc(d.rule)}</button> ${esc(d.message)}</li>`).join("");
      el.diags.onclick = (e) => {
        const b = e.target.closest("button[data-i]");
        if (b) goToLine(r.lint[Number(b.dataset.i)].line);
      };
      scheduleCheck();
      const keep = r.scenarios.some((s) => s.name === st.scenario) ? st.scenario : "";
      el.scenario.innerHTML = `<option value="">— off —</option>` + r.scenarios.map((s) =>
        `<option value="${esc(s.name)}">${esc(s.name)}${s.label ? ` · ${esc(s.label)}` : ""}</option>`).join("");
      el.scenario.value = keep;
      st.scenario = keep;
      if (keep) frame(0);
      else simOff();
    }

    // the findings panel: check.py at k = 1, after the drawing, within CHECK_BUDGET
    const checkRequest = () => ({ text: el.src.value, mode: el.mode.value || null });

    function scheduleCheck() {
      clearTimeout(st.checkTimer);
      if (JSON.stringify(checkRequest()) === st.checked) {
        el.findings.classList.remove("stale");     // back to the text last checked
        return;
      }
      if (st.checkPaused) {
        el.check.textContent = "check: waiting (press check)";
        el.check.className = "";
        return;
      }
      st.checkTimer = setTimeout(runCheck, CHECK_WAIT);
    }

    function runCheck() {
      clearTimeout(st.checkTimer);
      const req = checkRequest();
      const started = performance.now();
      const r = call("check", req);
      const ms = performance.now() - started;
      st.checked = JSON.stringify(req);
      st.checkPaused = ms > CHECK_BUDGET;          // too slow to run on every pause
      el.recheck.hidden = !st.checkPaused;
      showFindings(r, ms);
    }

    function showFindings(r, ms) {
      el.findings.classList.remove("stale");
      if (r.error) {
        el.check.textContent = `check: ${r.error}`;
        el.check.className = "bad";
        el.findings.innerHTML = "";
        return;
      }
      const n = (sev) => r.findings.filter((f) => f.severity === sev).length;
      const [errs, warns, infos] = [n("error"), n("warn"), n("info")];
      const counts = errs || warns || infos ? `${errs}E ${warns}W ${infos}i` : "OK";
      const extra = [r.hidden ? `${r.hidden} hidden` : "",
        r.acknowledged.length ? `${r.acknowledged.length} accepted` : ""].filter(Boolean);
      el.check.textContent = `check (${r.mode}, k=${r.k}): ${counts}` +
        (extra.length ? ` · ${extra.join(" · ")}` : "");
      el.check.className = errs || warns ? "bad" : "ok";
      el.check.title = `${Math.round(ms)} ms`;
      el.findings.innerHTML = findingsHtml(r.findings, r.acknowledged);
    }

    function goToLine(n) {
      const lines = el.src.value.split("\n");
      const k = Math.max(1, Math.min(n || 1, lines.length));
      const start = lines.slice(0, k - 1).reduce((a, l) => a + l.length + 1, 0);
      el.src.focus();
      el.src.setSelectionRange(start, start + lines[k - 1].length);
    }

    function simOff() {
      stop();
      st.frame = st.last = 0;
      el.scrub.max = "0";
      el.scrub.value = "0";
      el.tick.textContent = "";
      el.log.hidden = true;
      el.story.hidden = true;
      root.classList.remove("running");
      [el.back, el.play, el.fwd, el.scrub].forEach((b) => { b.disabled = true; });
      el.draw.setAttribute("aria-keyshortcuts", VIEW_KEYS);
    }

    function frame(k) {
      const r = call("sim", { ...request(), scenario: st.scenario, frame: k });
      if (r.error) {
        el.tick.textContent = r.error;
        stop();
        return;
      }
      showDrawing(r);
      root.classList.add("running");
      [el.back, el.play, el.fwd, el.scrub].forEach((b) => { b.disabled = false; });
      el.draw.setAttribute("aria-keyshortcuts", `${VIEW_KEYS} Space , . < > - +`);
      st.frame = r.frame;
      st.last = r.last;
      st.beats = r.beats || [];
      el.scrub.max = String(r.last);
      el.scrub.value = String(r.frame);
      el.tick.textContent = `t${r.tick}/${r.ticks}` + (r.outcome ? ` · ${r.outcome}` : "");
      el.story.hidden = false;
      el.story.innerHTML = storyHtml(r, rowsHtml);
      el.log.hidden = false;
      el.log.textContent = r.log.join("\n");
      el.log.scrollTop = el.log.scrollHeight;
      if (r.frame >= r.last) stop();
    }

    function stop() {
      clearInterval(st.timer);
      st.timer = null;
      st.playing = false;
      el.play.textContent = "play";
      el.play.title = "Play (space)";
    }
    function play() {
      if (!st.scenario) return;
      if (st.frame >= st.last) frame(0);
      st.playing = true;
      el.play.textContent = "pause";
      el.play.title = "Pause (space)";
      arm();
    }
    function arm() {
      clearInterval(st.timer);
      st.timer = setInterval(() => frame(st.frame + 1), 1000 / SIM_SPEEDS[st.speed]);
    }
    function step(delta) {
      if (!st.scenario) return;
      stop();
      frame(Math.max(0, Math.min(st.last, st.frame + delta)));
    }
    // < >: the previous / next frame where something happens (a beat)
    function stepEvent(dir) {
      if (!st.scenario) return;
      const to = dir > 0 ? st.beats.find((k) => k > st.frame)
        : st.beats.filter((k) => k < st.frame).pop();
      stop();
      frame(to ?? (dir > 0 ? st.last : 0));
    }
    function setSpeed(i) {
      st.speed = Math.max(0, Math.min(i, SIM_SPEEDS.length - 1));
      el.speed.value = String(st.speed);
      store.set(SPEED_KEY, String(st.speed));
      if (st.playing) arm();                       // keep playing, at the new pace
    }

    // the views in the terminal viewer's order: 1 2 3 pick one, t the next
    function setView(v) {
      st.view = v;
      el.views.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === v)));
      if (st.scenario) frame(st.frame);
      else refresh();
    }
    function viewKey(key) {
      const names = el.views.map((b) => b.dataset.view);
      const at = names.indexOf(st.view);
      return key === "t" ? names[(at + 1) % names.length] : names[Number(key) - 1];
    }

    el.go.addEventListener("click", boot);
    el.src.addEventListener("input", () => {
      paint();
      stop();
      el.findings.classList.add("stale");
      clearTimeout(st.typing);
      st.typing = setTimeout(refresh, 180);
    });
    el.findings.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-line]");
      if (b) goToLine(Number(b.dataset.line));
    });
    el.mode.addEventListener("change", runCheck);
    el.recheck.addEventListener("click", runCheck);
    el.src.addEventListener("scroll", syncScroll);
    el.src.addEventListener("keydown", (e) => {
      if (e.key === "Tab" && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();                        // Esc, then Tab, leaves the editor
        if (!document.execCommand("insertText", false, "  ")) {
          const { selectionStart: a, selectionEnd: b, value } = el.src;
          el.src.value = value.slice(0, a) + "  " + value.slice(b);
          el.src.selectionStart = el.src.selectionEnd = a + 2;
          el.src.dispatchEvent(new Event("input"));
        }
      } else if (e.key === "Escape") {
        el.src.blur();
      }
    });
    el.example.addEventListener("change", () => {
      const ex = examples[Number(el.example.value)];
      if (!ex) return;
      setText(ex.lines.join("\n"));
      st.scenario = "";
      refresh();
    });
    el.views.forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
    el.scenario.addEventListener("change", () => {
      st.scenario = el.scenario.value;
      stop();
      if (st.scenario) frame(0);
      else refresh();
    });
    el.play.addEventListener("click", () => (st.playing ? stop() : play()));
    el.back.addEventListener("click", () => step(-1));
    el.fwd.addEventListener("click", () => step(1));
    el.speed.addEventListener("change", () => setSpeed(Number(el.speed.value)));
    // the drawing takes the terminal viewer's run keys while a scenario is on
    // the drawing takes the viewer's view keys (1 2 3, t) at any time
    el.draw.addEventListener("keydown", (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const v = /^[1-9t]$/.test(e.key) ? viewKey(e.key) : undefined;
      if (v) {
        e.preventDefault();
        setView(v);
        return;
      }
      if (!st.scenario) return;
      const act = { " ": () => (st.playing ? stop() : play()), ",": () => step(-1),
        ".": () => step(1), "<": () => stepEvent(-1), ">": () => stepEvent(1), "-": () => setSpeed(st.speed - 1), "+": () => setSpeed(st.speed + 1),
        "=": () => setSpeed(st.speed + 1) }[e.key];
      if (!act) return;
      e.preventDefault();
      act();
    });
    el.scrub.addEventListener("input", () => { stop(); frame(Number(el.scrub.value)); });
    el.share.addEventListener("click", async () => {
      const url = `${location.origin}${location.pathname}#${SHARE}${b64url.encode(el.src.value)}`;
      history.replaceState(null, "", url);
      let ok = true;
      try { await navigator.clipboard.writeText(url); } catch { ok = false; }
      el.share.textContent = ok ? "link copied" : "link in the address bar";
      setTimeout(() => { el.share.textContent = "share"; }, 1800);
    });
    // a run plays only when asked; reduced motion switched on mid-run pauses it
    motionListeners.push((reduce) => { if (reduce && st.playing) stop(); });
    let resizeTimer = null;
    addEventListener("resize", () => {
      if (!st.api) return;
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => (st.scenario ? frame(st.frame) : refresh()), 200);
    });
    simOff();
    if (sharedText() !== null) {
      $("#playground").scrollIntoView();
      boot();
    }
  }

  // ------------------------------------------------------------------ brand
  // The name unpacks on hover / focus: each glyph's letter grows into its word
  // (Sigil → Symbolic Intent Glyph Intermediate Language, see language.md "On
  // the name"). New letters arrive as scrambled glyph characters and settle left
  // to right; leaving runs the same timeline backwards from wherever it is.

  const SCRAMBLE = "[]{}<>()|~*&?!$@#=:/\\";
  const BRAND_STEP = 16;          // ms between successive letters starting
  const BRAND_SETTLE = 170;       // ms a letter scrambles before it settles

  function initBrand() {
    const link = $(".brand");
    const text = $(".brand-text", link);
    const words = (link.dataset.expand || "").split(/\s+/);
    // The compact name: (open, letter, close, kind) per glyph, read from the markup.
    const glyphs = [];
    const kids = [...text.childNodes];
    for (let i = 0; i + 2 < kids.length; i += 3) {
      glyphs.push({ open: kids[i].textContent, letter: kids[i + 1].textContent,
        close: kids[i + 2].textContent, kind: kids[i].className });
    }
    if (glyphs.length !== words.length) return;   // markup and words disagree: keep it static
    let tails = 0;                                  // letters added across all words so far
    glyphs.forEach((g, i) => { g.tail = words[i].slice(1); g.first = tails; tails += g.tail.length; });
    const total = tails * BRAND_STEP + BRAND_SETTLE;

    function render(t) {
      let html = "";
      for (const g of glyphs) {
        html += `<span class="${g.kind}">${esc(g.open)}</span><span class="brand-initial">${esc(g.letter)}</span>`;
        for (let j = 0; j < g.tail.length; j++) {
          const start = (g.first + j) * BRAND_STEP;
          if (t < start) break;
          html += t < start + BRAND_SETTLE
            ? `<span class="brand-scramble ${g.kind}">${esc(SCRAMBLE[Math.floor(Math.random() * SCRAMBLE.length)])}</span>`
            : esc(g.tail[j]);
        }
        html += `<span class="${g.kind}">${esc(g.close)}</span>`;
      }
      text.innerHTML = html;
    }

    let t = 0, target = 0, last = 0, raf = 0;
    function tick(now) {
      const dt = last ? now - last : 16;
      last = now;
      t = target > t ? Math.min(target, t + dt) : Math.max(target, t - dt * 1.6);
      render(t);
      link.classList.toggle("open", t > 0);
      raf = t === target ? 0 : requestAnimationFrame(tick);
    }
    function go(open) {
      target = open ? total : 0;
      if (reduceMotion) {
        t = target;
        render(t);
        link.classList.toggle("open", open);
        return;
      }
      if (!raf) {
        last = 0;
        raf = requestAnimationFrame(tick);
      }
    }
    link.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") go(true); });
    link.addEventListener("pointerleave", () => go(false));
    link.addEventListener("focus", () => { if (link.matches(":focus-visible")) go(true); });
    link.addEventListener("blur", () => go(false));
  }

  // ------------------------------------------------------------------ page bits

  function initFocus() {
    const btn = $("#focus");
    btn.addEventListener("click", () => {
      const on = document.body.classList.toggle("focused");
      btn.setAttribute("aria-pressed", String(on));
    });
  }

  function selectText(node) {
    const range = document.createRange();
    range.selectNodeContents(node);
    const sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  function initInstall() {
    const root = $(".install");
    if (!root) return;
    initTabs($("[role=tablist]", root), (tab) => {
      const pane = tab.getAttribute("aria-controls");
      $$("[role=tabpanel]", root).forEach((p) => { p.hidden = p.id !== pane; });
    });
    $$("pre.copy").forEach((pre) => {
      pre.dataset.copy = pre.textContent.trim();
      const text = pre.firstChild;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy-btn";
      btn.textContent = "copy";
      let timer = null;
      btn.addEventListener("click", async () => {
        clearTimeout(timer);
        try {
          await navigator.clipboard.writeText(pre.dataset.copy);
          btn.textContent = "copied";
        } catch {
          selectText(text);                            // no clipboard access: ready for ctrl+c
          btn.textContent = "selected";
        }
        timer = setTimeout(() => { btn.textContent = "copy"; }, 1400);
      });
      pre.appendChild(btn);
    });
  }

  function initSnippets() {
    $$("code.hl").forEach((el) => { el.innerHTML = highlight(el.textContent); });
    $$("pre.hl-block").forEach((el) => {
      el.innerHTML = el.textContent.split("\n").map(highlight).join("\n");
    });
  }

  async function loadFrames() {
    const res = await fetch("frames.json");
    if (!res.ok) throw new Error(`frames.json: HTTP ${res.status}`);
    const data = await res.json();
    if (!Array.isArray(data.styles) || !Array.isArray(data.frames) ||
        !Array.isArray(data.examples) || !data.examples.length) {
      throw new Error("frames.json: no examples");
    }
    return data;
  }

  /** No frames: say so in the editor, hide the viewer planes, disable the controls. */
  function editorUnavailable(views, err) {
    console.warn("frames.json unavailable", err);
    Object.values(views).forEach((el) => { el.hidden = true; });
    $$("#play, #skip").forEach((b) => { b.disabled = true; });
    $("#tabs").textContent = "";
    $("#code").textContent = "The examples could not be loaded.";
    $$(".editor-status span").forEach((el) => { el.textContent = ""; });
  }

  async function main() {
    drawLogo();
    initBrand();
    initSnippets();
    initFocus();
    initInstall();
    initThemes();
    const views = buildScene();
    let examples = [];
    try {
      const data = await loadFrames();
      examples = data.examples;
      installFrameStyles(data.styles);
      player(data, views);
    } catch (err) {
      editorUnavailable(views, err);
    }
    initPlayground(examples);
  }

  main();
})();
