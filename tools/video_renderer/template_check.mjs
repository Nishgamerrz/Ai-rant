#!/usr/bin/env node
/**
 * Check that buildHtml() really produces the page it looks like it produces.
 *
 * render_short.mjs is one giant template literal that is served to Chromium and
 * screenshotted frame by frame. Any backtick written *inside* that literal (a
 * comment like "only `.bones`", say) silently ends the literal and turns the
 * following code into expressions, so the file still passes `node --check` and
 * then dies at run time with nonsense like
 *
 *     TypeError: WIDTHHEIGHT...encoded...bones is not a function
 *
 * after the story, the plan and the model download are already done.
 *
 * This check pulls the real buildHtml() out of the source, runs it with dummy
 * data, and asserts the result is a whole page. It exercises the actual code
 * path, so a stray backtick anywhere in the function shows up here instead of on
 * a runner twenty minutes later.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = resolve(fileURLToPath(new URL('.', import.meta.url)));
const source = readFileSync(resolve(here, 'render_short.mjs'), 'utf8');

/* --- pull the function out by matching braces ------------------------- */
const start = source.indexOf('function buildHtml(');
if (start < 0) throw new Error('buildHtml() is missing from render_short.mjs');
let index = source.indexOf('{', start);
let depth = 0;
let end = -1;
let inLiteral = false;
let inQuote = '';
for (let i = index; i < source.length; i += 1) {
  const char = source[i];
  const previous = source[i - 1];
  if (previous === '\\') continue;
  if (inQuote) {
    if (char === inQuote) inQuote = '';
    continue;
  }
  if (inLiteral) {
    if (char === '`') inLiteral = false;
    continue;
  }
  if (char === '`') { inLiteral = true; continue; }
  if (char === '"' || char === "'") { inQuote = char; continue; }
  if (char === '{') depth += 1;
  if (char === '}') {
    depth -= 1;
    if (depth === 0) { end = i + 1; break; }
  }
}
if (end < 0) throw new Error('could not find the end of buildHtml(); the file is broken');

const body = source.slice(start, end);

/* --- count the backticks the literal is allowed to have --------------- */
const returnAt = body.indexOf('return `');
if (returnAt < 0) throw new Error('buildHtml() no longer returns an HTML template');
const literal = body.slice(returnAt + 'return '.length);
const closing = literal.lastIndexOf('`;');
if (closing < 0) throw new Error('the HTML template is never closed');
const html = literal.slice(0, closing + 1).slice(1, -1); // strip the delimiters
const inner = literal.slice(1, closing);
if (inner.includes('`')) {
  const where = inner.slice(0, inner.indexOf('`')).split('\n').length;
  throw new Error(`a backtick inside the page template ends it early (about line ${where} `
    + 'of the template): use quotes in comments, never `');
}

/* --- run the real function ------------------------------------------- */
// buildHtml() calls safeData(); give the extracted function the real one.
const safeData = (value) => JSON.stringify(value)
  .replaceAll('<', '\\u003c').replaceAll('>', '\\u003e').replaceAll('&', '\\u0026');
const factory = new Function('safeData', 'WIDTH', 'HEIGHT', `${body}\nreturn buildHtml;`);
const page = factory(safeData, 720, 1280)({ plan: { props: [], camera_shots: [] }, profiles: [], duration: 5,
  captions: '', faceAnimation: 'auto' });

const checks = [
  ['starts with a doctype', page.startsWith('<!doctype html>')],
  ['ends with the closing html tag', page.trimEnd().endsWith('</script></body></html>')],
  ['has exactly one <head>', (page.match(/<head>/g) || []).length === 1],
  ['is a whole page, not a fragment', page.length > 20000],
  ['carries the frame size', page.includes('width:720px') && page.includes('height:1280px')],
  ['carries the caption layer', page.includes('<div id="caption"></div>')],
  ['leaves no unexpanded interpolation', !page.includes('${')],
  ['leaves no stray template delimiter', !page.includes('`')],
];

/* --- escapes that the outer template literal silently eats ------------- */
// The page is one big template literal, and a template literal only understands
// a small set of escapes. Anything else loses its backslash without a word, so
// `/\s+/g` (written with one backslash) reached Chromium as `/s+/g` and deleted
// every letter s from every caption. Scan the literal's own source and refuse any
// backslash that is not a real escape: a regex escape must be written doubled.
const TEMPLATE_ESCAPES = new Set(['n', 't', 'r', 'b', 'f', 'v', '0', "'", '"', '\\', '`', '$', '\n']);
const literalStart = body.indexOf('return `') + 'return `'.length;
const templateText = body.slice(literalStart);
const eaten = [];
for (let index = 0; index < templateText.length; index += 1) {
  if (templateText[index] !== '\\') continue;
  const next = templateText[index + 1];
  // \x, \u and line continuations are real escapes; everything else must be doubled.
  if (TEMPLATE_ESCAPES.has(next) || next === 'x' || next === 'u') { index += 1; continue; }
  const line = templateText.slice(0, index).split('\n').length;
  eaten.push(`line ${line}: \\${next} (write \\\\${next} if a regex escape was meant)`);
}
if (eaten.length) {
  console.error('The page template contains escapes a template literal silently eats:');
  for (const item of eaten.slice(0, 10)) console.error(`  ${item}`);
  process.exit(1);
}
checks.push(['every backslash in the page template is a real escape', true]);

const failed = checks.filter(([, ok]) => !ok).map(([name]) => name);
if (failed.length) {
  console.error(`buildHtml() produced a broken page: ${failed.join(', ')}`);
  console.error(page.slice(0, 300));
  process.exit(1);
}
console.log(`Page template check passed: ${page.length.toLocaleString()} characters of HTML, `
  + `${checks.length} assertions, the real buildHtml() executed with dummy data.`);
