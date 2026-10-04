// A terminal in a canvas. The deck renderer builds rows exactly as the Python
// app does - strings with ANSI SGR escapes, fitted to an exact cell width - and
// this module turns those rows into painted cells. Keeping the ANSI string
// model is what lets deck.js be a near line-for-line port of termbeat/app.py.

export const RST = "\x1b[0m";
export const BOLD = "\x1b[1m";
export const NORMAL = "\x1b[22m";

export const fg = (r, g, b) => `\x1b[38;2;${r};${g};${b}m`;
export const bg = (r, g, b) => `\x1b[48;2;${r};${g};${b}m`;

const ANSI_RE = /\x1b\[[0-9;]*[a-zA-Z]/g;

// East Asian Wide/Fullwidth blocks and wide emoji: the cases a live track title
// realistically contains. Ambiguous-width characters count as 1, the Python
// default.
const WIDE_RANGES = [
  [0x1100, 0x115f], [0x231a, 0x231b], [0x2329, 0x232a], [0x23e9, 0x23ec],
  [0x23f0, 0x23f0], [0x23f3, 0x23f3], [0x25fd, 0x25fe], [0x2614, 0x2615],
  [0x2648, 0x2653], [0x267f, 0x267f], [0x2693, 0x2693], [0x26a1, 0x26a1],
  [0x26aa, 0x26ab], [0x26bd, 0x26be], [0x26c4, 0x26c5], [0x26ce, 0x26ce],
  [0x26d4, 0x26d4], [0x26ea, 0x26ea], [0x26f2, 0x26f3], [0x26f5, 0x26f5],
  [0x26fa, 0x26fa], [0x26fd, 0x26fd], [0x2705, 0x2705], [0x270a, 0x270b],
  [0x2728, 0x2728], [0x274c, 0x274c], [0x274e, 0x274e], [0x2753, 0x2755],
  [0x2757, 0x2757], [0x2795, 0x2797], [0x27b0, 0x27b0], [0x27bf, 0x27bf],
  [0x2b1b, 0x2b1c], [0x2b50, 0x2b50], [0x2b55, 0x2b55], [0x2e80, 0x303e],
  [0x3041, 0x33ff], [0x3400, 0x4dbf], [0x4e00, 0x9fff], [0xa000, 0xa4cf],
  [0xa960, 0xa97f], [0xac00, 0xd7a3], [0xf900, 0xfaff], [0xfe10, 0xfe19],
  [0xfe30, 0xfe6f], [0xff00, 0xff60], [0xffe0, 0xffe6], [0x1f004, 0x1f004],
  [0x1f0cf, 0x1f0cf], [0x1f18e, 0x1f18e], [0x1f191, 0x1f19a], [0x1f200, 0x1f2ff],
  [0x1f300, 0x1f64f], [0x1f680, 0x1f6ff], [0x1f7e0, 0x1f7eb], [0x1f90c, 0x1f9ff],
  [0x1fa70, 0x1faff], [0x20000, 0x3fffd],
];

function isWide(cp) {
  if (cp < 0x1100) return false;
  let lo = 0, hi = WIDE_RANGES.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const [a, b] = WIDE_RANGES[mid];
    if (cp < a) hi = mid - 1;
    else if (cp > b) lo = mid + 1;
    else return true;
  }
  return false;
}

function isZeroWidth(cp) {
  return (cp >= 0x0300 && cp <= 0x036f) || (cp >= 0x200b && cp <= 0x200f) ||
         (cp >= 0xfe00 && cp <= 0xfe0f) || (cp >= 0x20d0 && cp <= 0x20ff) ||
         (cp >= 0x1ab0 && cp <= 0x1aff) || (cp >= 0x1dc0 && cp <= 0x1dff) ||
         (cp >= 0xfe20 && cp <= 0xfe2f);
}

export function charWidth(ch) {
  const cp = ch.codePointAt(0);
  if (cp < 0x300) return 1;
  if (isZeroWidth(cp)) return 0;
  return isWide(cp) ? 2 : 1;
}

export function stripAnsi(s) {
  return s.includes("\x1b") ? s.replace(ANSI_RE, "") : s;
}

export function strWidth(s) {
  s = stripAnsi(s);
  // eslint-disable-next-line no-control-regex
  if (/^[\x00-\x7f]*$/.test(s)) return s.length;
  let w = 0;
  for (const ch of s) w += charWidth(ch);
  return w;
}

/** One entry per terminal cell; a wide glyph is followed by an empty slot. */
export function cellSlots(text) {
  const slots = [];
  for (const ch of text) {
    const w = charWidth(ch);
    if (w === 0) {
      for (let i = slots.length - 1; i >= 0; i--) {
        if (slots[i]) { slots[i] += ch; break; }
      }
      continue;
    }
    slots.push(ch);
    if (w === 2) slots.push("");
  }
  return slots;
}

/** Truncate to at most maxWidth cells, copying escapes whole. Returns [str, width]. */
export function truncateAnsi(s, maxWidth) {
  let out = "";
  let w = 0;
  let inEsc = false;
  for (const ch of s) {
    if (ch === "\x1b") {
      inEsc = true;
      out += ch;
    } else if (inEsc) {
      out += ch;
      if (/[a-zA-Z]/.test(ch)) inEsc = false;
    } else {
      const cw = ch.charCodeAt(0) < 0x80 ? 1 : charWidth(ch);
      if (w + cw > maxWidth) break;
      out += ch;
      w += cw;
    }
  }
  return [out + RST, w];
}

/** Exactly targetWidth visible cells: truncated if long, padded if short. */
export function fitRow(content, targetWidth, bgColor = "", fillChar = " ") {
  let visW = strWidth(content);
  if (visW > targetWidth) [content, visW] = truncateAnsi(content, targetWidth);
  if (visW < targetWidth) return `${content}${bgColor}${fillChar.repeat(targetWidth - visW)}${RST}`;
  return content;
}

export function center(s, width) {
  // Python's str.center: extra space goes to the right when the split is odd
  const total = width - s.length;
  if (total <= 0) return s;
  const left = Math.floor(total / 2) + (total % 2 && width % 2 ? 1 : 0);
  return " ".repeat(left) + s + " ".repeat(total - left);
}

export const pad2 = (n) => String(n).padStart(2, "0");

// ------------------------------------------------------------- ANSI -> cells

const DEFAULT_FG = [204, 214, 230];
const STD16 = {
  30: [0, 0, 0], 31: [205, 49, 49], 32: [13, 188, 121], 33: [229, 229, 16],
  34: [36, 114, 200], 35: [188, 63, 188], 36: [17, 168, 205], 37: [229, 229, 229],
  90: [102, 102, 102], 91: [241, 76, 76], 92: [35, 209, 139], 93: [245, 245, 67],
  94: [59, 142, 234], 95: [214, 112, 214], 96: [41, 184, 219], 97: [255, 255, 255],
};

/**
 * Parse one ANSI row into cells: {ch, fg, bg, bold}. A wide glyph's second
 * cell has ch === "" so the grid stays cell-indexed.
 */
export function parseRow(line, cols) {
  const cells = [];
  let cur = { fg: null, bg: null, bold: false };
  let i = 0;
  while (i < line.length && cells.length < cols) {
    const c = line[i];
    if (c === "\x1b" && line[i + 1] === "[") {
      let j = i + 2;
      while (j < line.length && !/[a-zA-Z]/.test(line[j])) j++;
      const final = line[j];
      if (final === "m") cur = applySgr(cur, line.slice(i + 2, j));
      i = j + 1;
      continue;
    }
    const cp = line.codePointAt(i);
    const ch = String.fromCodePoint(cp);
    i += ch.length;
    const w = charWidth(ch);
    if (w === 0) {
      if (cells.length) cells[cells.length - 1].ch += ch;
      continue;
    }
    cells.push({ ch, fg: cur.fg, bg: cur.bg, bold: cur.bold });
    if (w === 2) cells.push({ ch: "", fg: cur.fg, bg: cur.bg, bold: cur.bold });
  }
  return cells.slice(0, cols);
}

function applySgr(cur, params) {
  const p = params === "" ? [0] : params.split(";").map(Number);
  const next = { ...cur };
  for (let k = 0; k < p.length; k++) {
    const v = p[k];
    if (v === 0) { next.fg = null; next.bg = null; next.bold = false; }
    else if (v === 1) next.bold = true;
    else if (v === 22) next.bold = false;
    else if (v === 39) next.fg = null;
    else if (v === 49) next.bg = null;
    else if ((v === 38 || v === 48) && p[k + 1] === 2) {
      const rgb = [p[k + 2], p[k + 3], p[k + 4]];
      if (v === 38) next.fg = rgb; else next.bg = rgb;
      k += 4;
    } else if (STD16[v]) next.fg = STD16[v];
  }
  return next;
}

// ------------------------------------------------------------- canvas painter

const FONT_STACK = '"JetBrains Mono", "Cascadia Mono", "DejaVu Sans Mono", "Menlo", "Consolas", "Liberation Mono", monospace';

// Block and box characters are drawn as geometry, as terminal emulators do, so
// bars and borders join seamlessly whatever the font's line metrics are.
const LOWER_EIGHTHS = { "▁": 1, "▂": 2, "▃": 3, "▄": 4, "▅": 5, "▆": 6, "▇": 7, "█": 8 };
const BOX = {
  "─": "h", "│": "v", "├": "vr", "┤": "vl", "┬": "hd", "┴": "hu", "┼": "hv",
  "╭": "arc-dr", "╮": "arc-dl", "╰": "arc-ur", "╯": "arc-ul",
  "┌": "dr", "┐": "dl", "└": "ur", "┘": "ul",
};

export class CanvasTerm {
  constructor(canvas, ground) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: false });
    this.ground = ground;
    this.cols = 0;
    this.rows = 0;
    this.prev = null;
  }

  /** Pick a font size so the window holds at least minCols x minRows cells. */
  resize(width, height, minCols = 104, minRows = 30) {
    const dpr = window.devicePixelRatio || 1;
    const ctx = this.ctx;
    let size = Math.floor(Math.min(width / (minCols * 0.6), height / (minRows * 1.25)));
    size = Math.max(7, Math.min(28, size));
    ctx.font = `${size}px ${FONT_STACK}`;
    const cw = Math.max(1, ctx.measureText("M").width);
    this.cellW = Math.round(cw * dpr) / dpr;
    this.cellH = Math.round(size * 1.25);
    this.fontSize = size;
    this.cols = Math.floor(width / this.cellW);
    this.rows = Math.floor(height / this.cellH);
    this.canvas.width = Math.floor(width * dpr);
    this.canvas.height = Math.floor(height * dpr);
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.textBaseline = "middle";
    this.offsetX = Math.floor((width - this.cols * this.cellW) / 2);
    this.offsetY = Math.floor((height - this.rows * this.cellH) / 2);
    ctx.fillStyle = rgb(this.ground);
    ctx.fillRect(0, 0, width, height);
    this.prev = null;
  }

  /** Paint rows, repainting only those that changed since the last call. */
  draw(lines) {
    const prev = this.prev;
    for (let r = 0; r < this.rows; r++) {
      const line = r < lines.length ? lines[r] : "";
      if (prev && prev[r] === line) continue;
      this.drawRow(r, parseRow(line, this.cols));
    }
    this.prev = lines.slice(0, this.rows);
    while (this.prev.length < this.rows) this.prev.push("");
  }

  drawRow(r, cells) {
    const ctx = this.ctx;
    const { cellW, cellH } = this;
    const y = this.offsetY + r * cellH;
    ctx.fillStyle = rgb(this.ground);
    ctx.fillRect(this.offsetX, y, this.cols * cellW, cellH);
    for (let c = 0; c < cells.length; c++) {
      const cell = cells[c];
      const x = this.offsetX + c * cellW;
      if (cell.bg) {
        ctx.fillStyle = rgb(cell.bg);
        ctx.fillRect(x, y, Math.ceil(cellW), cellH);
      }
      const ch = cell.ch;
      if (!ch || ch === " ") continue;
      const color = rgb(cell.fg || DEFAULT_FG);
      ctx.fillStyle = color;
      ctx.strokeStyle = color;
      if (this.drawGeometry(ch, x, y)) continue;
      const wide = c + 1 < cells.length && cells[c + 1].ch === "";
      ctx.font = `${cell.bold ? "bold " : ""}${this.fontSize}px ${FONT_STACK}`;
      const maxW = cellW * (wide ? 2 : 1);
      const m = ctx.measureText(ch).width;
      if (m > maxW * 1.05) {
        // a fallback font drew it wider than the grid: squeeze it into place
        ctx.save();
        ctx.translate(x, y + cellH / 2);
        ctx.scale(maxW / m, 1);
        ctx.fillText(ch, 0, 0);
        ctx.restore();
      } else {
        ctx.fillText(ch, x + (maxW - m) / 2, y + cellH / 2);
      }
    }
  }

  drawGeometry(ch, x, y) {
    const ctx = this.ctx;
    const w = Math.ceil(this.cellW);
    const h = this.cellH;
    const eighths = LOWER_EIGHTHS[ch];
    if (eighths) {
      const bh = Math.round((h * eighths) / 8);
      ctx.fillRect(x, y + h - bh, w, bh);
      return true;
    }
    if (ch === "▔") {
      ctx.fillRect(x, y, w, Math.max(1, Math.round(h / 8)));
      return true;
    }
    const kind = BOX[ch];
    if (!kind) return false;
    const lw = Math.max(1, Math.round(this.fontSize / 14));
    const cx = Math.floor(x + this.cellW / 2) - Math.floor(lw / 2);
    const cy = Math.floor(y + h / 2) - Math.floor(lw / 2);
    const left = () => ctx.fillRect(x, cy, cx - x + lw, lw);
    const right = () => ctx.fillRect(cx, cy, x + w - cx, lw);
    const up = () => ctx.fillRect(cx, y, lw, cy - y + lw);
    const down = () => ctx.fillRect(cx, cy, lw, y + h - cy);
    if (kind.startsWith("arc-")) {
      const r = Math.min(this.cellW, h) / 2;
      const ax = cx + lw / 2, ay = cy + lw / 2;
      ctx.lineWidth = lw;
      ctx.beginPath();
      if (kind === "arc-dr") { ctx.moveTo(ax, y + h); ctx.arcTo(ax, ay, x + w, ay, r); ctx.lineTo(x + w, ay); }
      if (kind === "arc-dl") { ctx.moveTo(ax, y + h); ctx.arcTo(ax, ay, x, ay, r); ctx.lineTo(x, ay); }
      if (kind === "arc-ur") { ctx.moveTo(ax, y); ctx.arcTo(ax, ay, x + w, ay, r); ctx.lineTo(x + w, ay); }
      if (kind === "arc-ul") { ctx.moveTo(ax, y); ctx.arcTo(ax, ay, x, ay, r); ctx.lineTo(x, ay); }
      ctx.stroke();
      return true;
    }
    if (kind.includes("h")) { left(); right(); }
    if (kind.includes("v")) { up(); down(); }
    if (kind === "vr" || kind === "dr" || kind === "ur") right();
    if (kind === "vl" || kind === "dl" || kind === "ul") left();
    if (kind === "hd" || kind === "dr" || kind === "dl") down();
    if (kind === "hu" || kind === "ur" || kind === "ul") up();
    return true;
  }
}

export const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;
