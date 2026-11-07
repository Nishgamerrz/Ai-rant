// Checks the on-screen caption layer without a browser.
//
// Run #66-style runs render their frames by screenshotting #frame, so the caption
// has to live in the page, not in an ffmpeg filter. This test pulls the caption
// code out of render_short.mjs, runs it against a tiny fake DOM, and asserts that
// the spoken line appears at the cue's time, sits a little above the middle, and
// pops in the way story shorts animate their text.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./render_short.mjs', import.meta.url), 'utf8');

// --- the stylesheet must place the caption, not the viewport -------------------
const style = source.slice(source.indexOf('#caption{'), source.indexOf('#caption.on'));
assert.ok(style.length > 20, 'the caption stylesheet is missing');
const top = /top:(\d+(?:\.\d+)?)%/.exec(style);
assert.ok(top, 'the caption has no vertical position');
const topPercent = Number(top[1]);
assert.ok(topPercent >= 20 && topPercent <= 40,
  `captions must sit a little above the middle, got ${topPercent}% from the top`);
assert.ok(/position:absolute/.test(style), 'the caption must be absolutely positioned inside #frame');
assert.ok(/#caption\.on\{opacity:1\}/.test(source), 'captions never become visible');
assert.ok(/text-transform:uppercase/.test(style), 'story-short captions are uppercase');
assert.ok(/-webkit-text-stroke/.test(style), 'captions need a readable outline');
assert.ok(/font-weight:900/.test(style), 'captions need a heavy weight');
assert.ok(/<div id="caption"><\/div>/.test(source), 'the caption element is not in the page');

// --- the per-frame logic ------------------------------------------------------
const start = source.indexOf("const captionEl=document.getElementById('caption');");
const end = source.indexOf('window.renderAt=async(t)=>{');
assert.ok(start > 0 && end > start, 'caption logic not found');
const logic = source.slice(start, end);

class FakeElement {
  constructor() {
    this.textContent = '';
    this.style = {};
    this.classes = new Set();
    this.classList = {
      toggle: (name, on) => { if (on) this.classes.add(name); else this.classes.delete(name); },
    };
  }
}

const element = new FakeElement();
const captions = [
  { start: 1.0, end: 2.5, text: 'Maya counted the coins twice.' },
  { start: 2.5, end: 4.0, text: 'The bus left without her.' },
];
const document = { getElementById: (id) => { assert.equal(id, 'caption'); return element; } };
const factory = new Function('document', 'captions', `${logic}\nreturn captionAt;`);
const captionAt = factory(document, captions);

captionAt(0.5);
assert.equal(element.textContent, '', 'nothing may show before the first cue');
assert.equal(element.classes.has('on'), false);

captionAt(1.0);
assert.equal(element.textContent, 'Maya counted the coins twice.');
assert.equal(element.classes.has('on'), true, 'the cue must become visible');
assert.match(element.style.transform, /scale\(0\.92/, 'a new cue pops in slightly small');
assert.match(element.style.transform, /translate\(-50%,-50%\)/, 'the caption stays centred');

captionAt(1.2);
assert.match(element.style.transform, /scale\(1\.000\)/, 'the pop settles within 0.12s');

captionAt(2.6);
assert.equal(element.textContent, 'The bus left without her.', 'the caption follows the narration');

captionAt(5.0);
assert.equal(element.classes.has('on'), false, 'the caption hides when nothing is spoken');

// The rendered frame must call it every frame, before the screenshot.
const renderAt = source.slice(source.indexOf('window.renderAt=async(t)=>{'),
  source.indexOf('renderer.render(scene,camera)', source.indexOf('window.renderAt=async(t)=>{')));
assert.ok(/captionAt\(t\)/.test(renderAt), 'renderAt must update the caption for every frame');

console.log(`On-screen caption check passed: ${topPercent}% from the top, uppercase outlined, `
  + `${captions.length} cues followed, pop-in and hide both verified.`);
