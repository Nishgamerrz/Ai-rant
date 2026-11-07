#!/usr/bin/env node
/**
 * Check that buildHtml() really produces the page it looks like it produces.
 *
 * render_short.mjs is one giant template literal that is served to Chromium and
 * screenshotted frame by frame. Any backtick written *inside* that literal (a
 * comment like "handing over only `.bones`", say) silently ends the literal and
 * turns the following code into JavaScript expressions, so the file still passes
 * `node --check` and then dies at run time with nonsense like
 *
 *     TypeError: WIDTHHEIGHTWIDTHHEIGHTencoded...bones is not a function
 *
 * twenty minutes into a render. This check builds the page for real and asserts
 * it is HTML, not accidental code.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const source = readFileSync(resolve(fileURLToPath(new URL('.', import.meta.url)), 'render_short.mjs'), 'utf8');
const marker = 'return `<!doctype html>';
const start = source.indexOf(marker);
if (start < 0) throw new Error('buildHtml() no longer returns an HTML template');
const literal = source.slice(start + 'return '.length, source.indexOf('`;', start) + 1);

let html;
try {
  // eslint-disable-next-line no-new-func
  html = new Function('WIDTH', 'HEIGHT', 'encoded', `return ${literal}`)(720, 1280, '{"plan":{}}');
} catch (error) {
  throw new Error(`buildHtml() threw while building the page: ${error.message}`);
}

const checks = [
  ['starts with a doctype', html.startsWith('<!doctype html>')],
  ['ends with the closing html tag', html.trimEnd().endsWith('</script></body></html>')],
  ['has exactly one <head>', (html.match(/<head>/g) || []).length === 1],
  ['carries the frame size', html.includes('width:720px') && html.includes('height:1280px')],
  ['carries the caption layer', html.includes('<div id="caption"></div>')],
  ['leaves no unexpanded interpolation', !html.includes('${')],
  ['leaves no stray template delimiter', !html.includes('`')],
];

const failed = checks.filter(([, ok]) => !ok).map(([name]) => name);
if (failed.length) {
  console.error(`buildHtml() produced a broken page: ${failed.join(', ')}`);
  console.error(html.slice(0, 300));
  process.exit(1);
}
console.log(`Page template check passed: ${html.length.toLocaleString()} characters of HTML, `
  + `${checks.length} assertions, no stray backticks or unexpanded values.`);
