// Lane A carousel renderer: 02-script.json -> 03-board/NN.png at 1080x1080.
//
// Follows the house style decomposed from @collab.gm.marketshq (templates/
// DcnjhnmFdiS.json): square canvas, graph-paper ground, mint chip label, poster
// caps headline with the punch words in green, greyscale cut-out figure bleeding
// off one edge, and a serif sign-off slide carrying the logo and the disclaimer.
//
// Deterministic and free. A beat with no `figure` renders its brief as a dashed
// placeholder, so the words can be judged in position before anyone spends.
//
//   node pipeline/render_carousel.mjs work/@handle/slug
import { chromium } from "playwright";
import fs from "fs";
import path from "path";

const [, , workDir] = process.argv;
if (!workDir) { console.error("usage: node pipeline/render_carousel.mjs <work_dir>"); process.exit(1); }

const ROOT = process.cwd();
const script = JSON.parse(fs.readFileSync(path.join(workDir, "02-script.json"), "utf8"));
const tok = JSON.parse(fs.readFileSync(path.join(ROOT, "brand/brand.tokens.json"), "utf8"));
const tmpl = fs.readFileSync(path.join(ROOT, "templates/carousel/slide.html"), "utf8");
const outDir = path.join(workDir, "03-board");
fs.mkdirSync(outDir, { recursive: true });

// setContent runs on about:blank, so file:// subresources are blocked — every
// image goes in as a data URI instead.
const MIME = { ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
               ".jpeg": "image/jpeg", ".webp": "image/webp" };
const asDataUri = (p) => {
  if (!p) return null;
  const abs = path.resolve(ROOT, p);
  if (!fs.existsSync(abs)) { console.log(`  !! missing asset: ${p}`); return null; }
  const mime = MIME[path.extname(abs).toLowerCase()] || "application/octet-stream";
  return `data:${mime};base64,${fs.readFileSync(abs).toString("base64")}`;
};

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1080, height: 1080 }, deviceScaleFactor: 1 });
const board = { spec_version: "board/1.1-carousel", slug: script.slug, aspect: "1:1",
                size: "1080x1080", house_style: "collab.gm.marketshq (templates/DcnjhnmFdiS.json)",
                beats: [], gate: { n: 3, question: "Is this the right look?", status: "awaiting" } };

for (const b of script.beats) {
  const slide = b.signoff
    ? { signoff: { ...b.signoff, logo: asDataUri(b.signoff.logo) } }
    : {
        chip: b.chip || null, headline: b.headline, body: b.body, list: b.list || null,
        table: b.table || null, bars: b.bars || null, gloss: b.gloss || null,
        receipt: b.receipt || null, journey: b.journey || null, bignum: b.bignum || null,
        steps: !!b.steps, swipe: b.n === 1,
        figure_side: b.figure_side || "right",
        figure: asDataUri(b.figure),
        figure_brief: b.figure || b.table || b.bars ? null : (b.visual || null),
      };
  const page = await ctx.newPage();
  await page.setContent(
    tmpl.replace("__SLIDE__", JSON.stringify(slide)).replace("__BRAND__", JSON.stringify(tok.brand)),
    { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction("window.__layoutSettled === true", { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(150);
  const file = `${String(b.n).padStart(2, "0")}.png`;
  await page.screenshot({ path: path.join(outDir, file) });
  await page.close();
  board.beats.push({
    beat: b.n, role: b.role, keyframe: file,
    motion_route: b.figure ? "lane_b_cutout" : "lane_a_html",
    est_cost: 0,
    status: b.signoff ? "sign-off" : (b.figure ? "figure placed" : (b.table || b.bars ? "data slide, no figure needed" : "words in place, figure still owed")),
  });
  console.log(`  ${file}  ${String(b.role).padEnd(12)} ${board.beats.at(-1).status}`);
}
board.invoice_inr = board.beats.reduce((s, x) => s + x.est_cost, 0);
fs.writeFileSync(path.join(outDir, "board.json"), JSON.stringify(board, null, 1));
console.log(`-> ${outDir}/board.json  (invoice: Rs ${board.invoice_inr})`);
await browser.close();
