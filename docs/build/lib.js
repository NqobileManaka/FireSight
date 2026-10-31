const fs = require("fs");
const path = require("path");
const D = require("docx");
const {
  Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle, AlignmentType,
  ImageRun, HeadingLevel, PageBreak, LevelFormat, VerticalAlign,
} = D;

const W = 9638; // content width (A4, 2 cm margins) in DXA
const FONT = "Arial";
const ROOT = path.join(__dirname, "..", "..");
const sizeOf = require("./sizes.json");

// inline **bold** and `code` parser
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), font: FONT, ...base }));
    const tok = m[0];
    if (tok.startsWith("**")) out.push(new TextRun({ text: tok.slice(2, -2), bold: true, font: FONT, ...base }));
    else out.push(new TextRun({ text: tok.slice(1, -1), font: "Consolas", ...base, size: (base.size || 20) - 1 }));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), font: FONT, ...base }));
  return out;
}

const p = (text, o = {}) => new Paragraph({
  children: runs(text, { size: o.size || 20, color: o.color, italics: o.italics }),
  spacing: { after: o.after ?? 100, before: o.before ?? 0, line: 276 },
  alignment: o.align, keepNext: o.keepNext, indent: o.indent,
});
const HEADINGS = [];
const h1 = (t, brk = true) => (HEADINGS.push({ level: 1, text: t }), new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: brk, children: [new TextRun({ text: t, font: FONT })] }));
const h2 = (t) => (HEADINGS.push({ level: 2, text: t }), new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text: t, font: FONT })] }));
const h3 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun({ text: t, font: FONT })] });
const bullets = (items, ref = "bul") => items.map((t) => new Paragraph({
  numbering: { reference: ref, level: 0 }, children: runs(t, { size: 20 }), spacing: { after: 50, line: 264 },
}));
const numbered = (items, ref) => items.map((t) => new Paragraph({
  numbering: { reference: ref, level: 0 }, children: runs(t, { size: 20 }), spacing: { after: 50, line: 264 },
}));

const border = { style: BorderStyle.SINGLE, size: 4, color: "B7BEC8" };
const borders = { top: border, bottom: border, left: border, right: border };
const STATUS = {
  Pass: "DDF2E3", Partial: "FFF0C7", "Not met": "F8D7D3", "Not executed": "E4E7EC",
  Delivered: "DDF2E3", "Partly delivered": "FFF0C7", "Not delivered": "F8D7D3",
};

function cell(text, w, o = {}) {
  const fill = o.fill || (o.status && STATUS[o.status]) || (o.header ? "1F3A5F" : undefined);
  const lines = Array.isArray(text) ? text : [text];
  return new TableCell({
    width: { size: w, type: WidthType.DXA }, borders,
    shading: fill ? { fill, type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 50, bottom: 50, left: 80, right: 80 }, verticalAlign: VerticalAlign.TOP,
    children: lines.map((t) => new Paragraph({
      spacing: { after: 20, line: 240 }, alignment: o.align,
      children: runs(String(t), { size: o.size || 17, bold: o.header || o.bold, color: o.header ? "FFFFFF" : undefined }),
    })),
  });
}

// widths are relative weights; scaled to W
function table(headers, rows, weights, o = {}) {
  const tot = weights.reduce((a, b) => a + b, 0);
  const ws = weights.map((x) => Math.round((x / tot) * W));
  ws[ws.length - 1] += W - ws.reduce((a, b) => a + b, 0);
  const statusCol = o.statusCol;
  const trs = [];
  if (headers) trs.push(new TableRow({ tableHeader: true, cantSplit: true, children: headers.map((h, i) => cell(h, ws[i], { header: true, size: o.size })) }));
  rows.forEach((r) => trs.push(new TableRow({
    cantSplit: true,
    children: r.map((c, i) => cell(c, ws[i], {
      size: o.size, status: i === statusCol ? (Array.isArray(c) ? c[0] : c).replace(/\*/g, "").split(" (")[0] : undefined,
      bold: o.boldFirst && i === 0,
      fill: o.firstFill && i === 0 ? "EEF2F7" : undefined,
    })),
  })));
  return new Table({ width: { size: W, type: WidthType.DXA }, columnWidths: ws, rows: trs });
}

function note(text, fill = "FFF6DD", edge = "E0A800") {
  const b = { style: BorderStyle.SINGLE, size: 6, color: edge };
  return new Table({
    width: { size: W, type: WidthType.DXA }, columnWidths: [W],
    rows: [new TableRow({ children: [new TableCell({
      width: { size: W, type: WidthType.DXA }, borders: { top: b, bottom: b, right: b, left: { style: BorderStyle.SINGLE, size: 24, color: edge } },
      shading: { fill, type: ShadingType.CLEAR, color: "auto" }, margins: { top: 80, bottom: 80, left: 140, right: 120 },
      children: (Array.isArray(text) ? text : [text]).map((t) => new Paragraph({ spacing: { after: 40, line: 252 }, children: runs(t, { size: 19 }) })),
    })] })],
  });
}

function code(lines) {
  const cb = { style: BorderStyle.SINGLE, size: 4, color: "C9CED6" };
  return new Table({
    width: { size: W, type: WidthType.DXA }, columnWidths: [W],
    rows: [new TableRow({ children: [new TableCell({
      width: { size: W, type: WidthType.DXA }, borders: { top: cb, bottom: cb, left: cb, right: cb },
      shading: { fill: "F4F6F8", type: ShadingType.CLEAR, color: "auto" }, margins: { top: 70, bottom: 70, left: 120, right: 120 },
      children: lines.map((l) => new Paragraph({ spacing: { after: 0, line: 232 }, children: [new TextRun({ text: l === "" ? " " : l, font: "Consolas", size: 16 })] })),
    })] })],
  });
}

let figN = 0;
function fig(file, caption, maxW = 620, maxH = 880, label) {
  const abs = path.isAbsolute(file) ? file : path.join(ROOT, file);
  const [w0, h0] = sizeOf[path.relative(ROOT, abs)];
  const k = Math.min(maxW / w0, maxH / h0);
  const w = Math.round(w0 * k), h = Math.round(h0 * k);
  if (!label || /a$/.test(label)) figN += 1;
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 80, after: 40 }, keepNext: true,
      children: [new ImageRun({ type: "png", data: fs.readFileSync(abs), transformation: { width: w, height: h },
        altText: { title: caption, description: caption, name: path.basename(abs) } })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 160 },
      children: [new TextRun({ text: `${label || "Figure " + figN}. `, bold: true, font: FONT, size: 18 }), new TextRun({ text: caption, font: FONT, size: 18, italics: true })] }),
  ];
}
const spacer = (n = 100) => new Paragraph({ spacing: { after: n }, children: [] });
const pageBreak = () => new Paragraph({ children: [new PageBreak()] });

module.exports = { HEADINGS, D, W, FONT, p, h1, h2, h3, bullets, numbered, table, note, code, fig, spacer, pageBreak, runs, ROOT };
