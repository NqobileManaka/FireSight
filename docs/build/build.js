const fs = require("fs");
const path = require("path");
const L = require("./lib");
const { D, p, FONT, spacer } = L;
const { Document, Packer, Paragraph, TextRun, Header, Footer, PageNumber, AlignmentType, LevelFormat, TableOfContents, StepsBorder } = D;
const { q1, q2 } = require("./q1q2");
const { q3 } = require("./q3");
const { q4 } = require("./q4");
const { q5 } = require("./q5");

const numCfg = (ref) => ({
  reference: ref,
  levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 360 } } } }],
});
const pagesFile = path.join(__dirname, "toc.json");
const pages = fs.existsSync(pagesFile) ? JSON.parse(fs.readFileSync(pagesFile)) : {};
const body = [q1(), q2(), q3(), q4(), q5()].flat(Infinity);
const { PositionalTab, PositionalTabAlignment, PositionalTabRelativeTo, PositionalTabLeader } = D;
const { TabStopType, LeaderType, Tab } = D;
const tocLines = L.HEADINGS.map((h) => new Paragraph({
  spacing: { before: h.level === 1 ? 140 : 0, after: 30 }, indent: { left: h.level === 1 ? 0 : 360 },
  tabStops: [{ type: TabStopType.RIGHT, position: L.W, leader: LeaderType.DOT }],
  children: [
    new TextRun({ text: h.text, font: FONT, size: h.level === 1 ? 21 : 19, bold: h.level === 1 }),
    new TextRun({ children: [new Tab(), String(pages[h.text] || "")], font: FONT, size: h.level === 1 ? 21 : 19, bold: h.level === 1 }),
  ],
}));
const cover = [
  new Paragraph({ spacing: { before: 2400, after: 120 }, children: [new TextRun({ text: "ISJ107V · Integrated Software Project · Assignment 3", font: FONT, size: 22, color: "5B6B7F" })] }),
  new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: "FireSight", font: FONT, size: 84, bold: true, color: "1F3A5F" })] }),
  new Paragraph({ spacing: { after: 400 }, children: [new TextRun({ text: "Project Documentation and UML Design", font: FONT, size: 40, color: "D9622B" })] }),
  new Paragraph({ spacing: { after: 80 }, children: [new TextRun({ text: "An Integrated Drone Command Platform for Municipal Fire and Rescue Services", font: FONT, size: 26 })] }),
  new Paragraph({ spacing: { after: 1200 }, children: [new TextRun({ text: "Emerging technology: AI / Machine Learning (CNN thermal-image analysis)", font: FONT, size: 22, color: "5B6B7F" })] }),
  L.table(null, [
    ["**Student**", "Smangele Manaka"],
    ["**Student number**", "218503322"],
    ["**Module**", "ISJ107V (S2 2026), Assessment weighting 20%, 50 marks"],
    ["**Version / date**", "1.0 · 30 September 2026"],
    ["**Submission**", "Through EC (individual)"],
  ], [28, 72], { boldFirst: true, firstFill: true, size: 20 }),
  new Paragraph({ spacing: { before: 500 }, children: [] }),
  L.note(["**How to read the results.** The system was built as a prototype and tested by simulation. Every number in this document was measured on that prototype. Where a requirement is only partly met, or not met, or was not tested, the document says so."], "EAF2FB", "1F3A5F"),
  new Paragraph({ children: [new D.PageBreak()] }),
  new Paragraph({ spacing: { after: 160 }, children: [new TextRun({ text: "Contents", font: FONT, size: 32, bold: true, color: "1F3A5F" })] }),
  ...tocLines,
];

const doc = new Document({
  creator: "Smangele Manaka", title: "FireSight: Project Documentation and UML Design", description: "ISJ107V Assignment 3",
  features: { updateFields: true },
  styles: {
    default: { document: { run: { font: FONT, size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 34, bold: true, font: FONT, color: "1F3A5F" }, paragraph: { spacing: { before: 0, after: 180 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 26, bold: true, font: FONT, color: "D9622B" }, paragraph: { spacing: { before: 260, after: 110 }, outlineLevel: 1, keepNext: true } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 21, bold: true, font: FONT, color: "1F3A5F" }, paragraph: { spacing: { before: 180, after: 80 }, outlineLevel: 2, keepNext: true } },
    ],
  },
  numbering: { config: [
    { reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] },
    numCfg("steps1"), numCfg("steps2"), numCfg("fut"), numCfg("refs"),
  ] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134, header: 500, footer: 500 } } },
    headers: { default: new Header({ children: [new Paragraph({ border: { bottom: { style: "single", size: 4, color: "B7BEC8", space: 4 } },
      children: [new TextRun({ text: "FireSight · Project Documentation and UML Design · v1.0", font: FONT, size: 16, color: "5B6B7F" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: "218503322 · ISJ107V Assignment 3 · Page ", font: FONT, size: 16, color: "5B6B7F" }), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: "5B6B7F" })] })] }) },
    children: [cover, body].flat(Infinity),
  }],
});
fs.writeFileSync(path.join(__dirname, "headings.json"), JSON.stringify(L.HEADINGS.map((h) => h.text)));
Packer.toBuffer(doc).then((buf) => {
  const out = path.join(__dirname, "..", "FireSight_Assignment3.docx");
  fs.writeFileSync(out, buf);
  console.log("wrote", out, buf.length);
});
