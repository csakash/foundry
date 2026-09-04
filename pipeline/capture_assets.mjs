// High-res evidence captures for the motion layer.
// Usage: node pipeline/capture_assets.mjs assets.json outdir
// assets.json: [{ id, url, selector?, scrollTo?, clipHeight?, wait? }]
import { chromium } from "playwright";
import fs from "fs";
import path from "path";

const [, , specPath, outDir] = process.argv;
const specs = JSON.parse(fs.readFileSync(specPath, "utf8"));
fs.mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 430, height: 932 },     // portrait phone — reads well in 9:16
  deviceScaleFactor: 3,                       // 1290px wide output
  userAgent:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
});

for (const s of specs) {
  const page = await ctx.newPage();
  const out = path.join(outDir, `${s.id}.png`);
  try {
    await page.goto(s.url, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(s.wait ?? 2500);

    // dismiss consent walls
    for (const rx of [/accept all/i, /accept/i, /i agree/i, /allow all/i, /continue/i]) {
      const b = page.locator(`button:has-text("${rx.source.replace(/[\\^$.*+?()[\]{}|]/g, "")}")`).first();
      if (await b.count().catch(() => 0)) {
        await b.click({ timeout: 1500 }).catch(() => {});
        await page.waitForTimeout(600);
        break;
      }
    }
    // strip sticky chrome that would sit over the capture
    await page.evaluate(() => {
      document.querySelectorAll("*").forEach((el) => {
        const p = getComputedStyle(el).position;
        if ((p === "fixed" || p === "sticky") && el.getBoundingClientRect().height < 400) {
          el.style.setProperty("display", "none", "important");
        }
      });
    });

    if (s.selector) {
      const el = page.locator(s.selector).first();
      await el.scrollIntoViewIfNeeded({ timeout: 8000 }).catch(() => {});
      await page.waitForTimeout(500);
    } else if (s.scrollTo) {
      await page.evaluate((y) => window.scrollTo(0, y), s.scrollTo);
      await page.waitForTimeout(500);
    }

    await page.screenshot({
      path: out,
      clip: s.clipHeight
        ? { x: 0, y: 0, width: 430, height: s.clipHeight }
        : undefined,
    });
    console.log(JSON.stringify({ id: s.id, ok: true, out }));
  } catch (e) {
    console.log(JSON.stringify({ id: s.id, ok: false, error: String(e).slice(0, 160) }));
  } finally {
    await page.close();
  }
}
await browser.close();
