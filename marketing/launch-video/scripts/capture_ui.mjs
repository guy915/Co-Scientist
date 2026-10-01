// Captures real product UI from production for the product-led cut.
// Usage: node scripts/capture_ui.mjs  → public/ui/<theme>-<name>.png
import {chromium} from 'playwright';
import {mkdirSync} from 'node:fs';

const BASE = 'https://ai-co-scientist.com';
const RUN = '285b7684-7a8d-4473-9838-3316421713fe';
const SHOTS = [
  {name: 'home', path: '/'},
  {name: 'details', path: `/runs/${RUN}/details`},
  {name: 'learning', path: `/runs/${RUN}/learning`},
  {name: 'overview', path: `/runs/${RUN}/overview`},
  {name: 'ideas', path: `/runs/${RUN}/ideas`},
];

mkdirSync('public/ui', {recursive: true});
const browser = await chromium.launch({executablePath: process.env.CHROME_PATH});
for (const theme of ['light', 'dark']) {
  const ctx = await browser.newContext({
    viewport: {width: 1600, height: 1000},
    deviceScaleFactor: 2,
    colorScheme: theme,
  });
  await ctx.addInitScript(t => localStorage.setItem('cosci-theme', t), theme);
  const page = await ctx.newPage();
  for (const s of SHOTS) {
    await page.goto(BASE + s.path, {waitUntil: 'networkidle'});
    await page.waitForTimeout(2500);
    await page.screenshot({path: `public/ui/${theme}-${s.name}.png`});
    // Full-height variant lets the video scroll through real content.
    await page.screenshot({path: `public/ui/${theme}-${s.name}-full.png`, fullPage: true});
  }
  await ctx.close();
}
await browser.close();
