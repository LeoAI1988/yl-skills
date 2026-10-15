import {bundle} from '@remotion/bundler';
import {selectComposition, renderStill, openBrowser} from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
// fileURLToPath handles spaces, Unicode and Windows paths correctly.
const {fileURLToPath} = await import('node:url');
const project = path.dirname(fileURLToPath(import.meta.url));
const read = name => JSON.parse(fs.readFileSync(path.join(project, name), 'utf8'));
const output = path.join(project, 'layers');
fs.mkdirSync(output); // refuse prior complete/partial renders; prepare another version
const binding = read('binding.json');
const browserExecutable = process.env.YL_SLICE_BROWSER || null;
const serveUrl = await bundle({entryPoint: path.join(project, 'index.tsx'), publicDir: path.join(project, 'public')});
const files = {};
const browser = await openBrowser('chrome', {browserExecutable});
try {
  for (const id of read('layer-list.json')) {
    const composition = await selectComposition({serveUrl, id, puppeteerInstance: browser, timeoutInMilliseconds: 120000});
    const dest = path.join(output, `${id}.png`);
    await renderStill({serveUrl, composition, puppeteerInstance: browser, output: dest, imageFormat: 'png', frame: 0, timeoutInMilliseconds: 120000});
    files[id] = crypto.createHash('sha256').update(fs.readFileSync(dest)).digest('hex');
    console.log(`Rendered ${id}`);
  }
} finally {
  await browser.close({silent: true});
}
fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify({project_sha256: binding.project_sha256, files}, null, 2));
