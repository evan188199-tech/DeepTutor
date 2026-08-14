import { chromium, devices } from "playwright";
const SHOT = "/Users/xzh/.codex/visualizations/2026/08/13/019ffd89-2f0c-73c3-bcd6-464e414057f9";

async function runTest(label, deviceOpts) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ ...deviceOpts });
  const apiCalls = [];
  page.on("response", (r) => {
    if (r.url().includes("dictionary") || r.url().includes("translate"))
      apiCalls.push(r.status() + " " + r.url().slice(-50));
  });

  // Login
  await page.goto("http://localhost:3782/login", { waitUntil: "networkidle", timeout: 15000 });
  await page.locator('input[type="text"]').first().fill("_codex_test");
  await page.locator('input[type="password"]').first().fill("codextest123");
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(3000);

  // Reader
  await page.goto("http://localhost:3782/immersive-reading?pairing=be0038de1f88", { waitUntil: "networkidle", timeout: 20000 });
  await page.waitForTimeout(3000);

  // Find a full sentence and select it
  const target = await page.evaluate(() => {
    const ps = document.querySelectorAll("p");
    for (const p of ps) {
      const t = p.innerText.trim();
      // Find a sentence (has a period and multiple words)
      if (t.length > 60 && t.length < 300 && /\./.test(t) && /[A-Z]/.test(t)) {
        const rect = p.getBoundingClientRect();
        return { text: t.slice(0, 100), x: rect.x + 30, y: rect.y + rect.height / 2 };
      }
    }
    return null;
  });
  console.log(label, "target:", JSON.stringify(target));

  if (target) {
    // Select the full sentence by selecting a multi-word phrase
    await page.evaluate(() => {
      const ps = document.querySelectorAll("p");
      for (const p of ps) {
        const t = p.innerText.trim();
        if (t.length > 60 && t.length < 300 && /\./.test(t)) {
          const range = document.createRange();
          range.selectNodeContents(p);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
          let el = p;
          for (let i = 0; i < 10 && el; i++) {
            el.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
            el = el.parentElement;
          }
          return true;
        }
      }
    });

    console.log(label, "waiting for translate API...");
    await page.waitForTimeout(15000);
    await page.screenshot({ path: SHOT + "/" + label + "-sentence.png" });

    const data = await page.evaluate(() => {
      const el = document.querySelector('[class*="z-[200]"]');
      if (!el) return { found: false };
      return {
        found: true,
        text: el.innerText.slice(0, 300),
        buttons: Array.from(el.querySelectorAll("button")).map(b => b.innerText.trim()).filter(Boolean),
      };
    });
    console.log(label, "popover:", JSON.stringify(data, null, 2));
  }

  console.log(label, "API:", apiCalls);
  await browser.close();
}

console.log("=== MOBILE SENTENCE TEST ===");
await runTest("mobile-sentence", devices["iPhone 14 Pro"]);

console.log("\nDone.");
