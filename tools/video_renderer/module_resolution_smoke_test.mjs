import assert from 'node:assert/strict';
import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const ROOT = fileURLToPath(new URL('.', import.meta.url));
const MODULES = resolve(ROOT, 'node_modules');
const html = `<!doctype html><meta charset="utf-8">
<script type="importmap">{"imports":{"three":"/modules/three/build/three.module.js"}}</script>
<script type="module">
  import * as THREE from '/modules/three/build/three.module.js';
  import { OBJLoader } from '/modules/three/examples/jsm/loaders/OBJLoader.js';
  import { MTLLoader } from '/modules/three/examples/jsm/loaders/MTLLoader.js';
  import { GLTFLoader } from '/modules/three/examples/jsm/loaders/GLTFLoader.js';
  import { FBXLoader } from '/modules/three/examples/jsm/loaders/FBXLoader.js';
  import { ColladaLoader } from '/modules/three/examples/jsm/loaders/ColladaLoader.js';
  import { PLYLoader } from '/modules/three/examples/jsm/loaders/PLYLoader.js';
  import { STLLoader } from '/modules/three/examples/jsm/loaders/STLLoader.js';
  import { TDSLoader } from '/modules/three/examples/jsm/loaders/TDSLoader.js';
  import { chooseSafeCamera } from '/scene_camera.mjs';
  window.moduleResolutionReady = THREE.REVISION === '170' && [OBJLoader,MTLLoader,GLTFLoader,FBXLoader,ColladaLoader,PLYLoader,STLLoader,TDSLoader,chooseSafeCamera].every(Boolean);
</script>`;

const server = createServer((request, response) => {
  const pathname = decodeURIComponent(new URL(request.url, 'http://127.0.0.1').pathname);
  if (pathname === '/') {
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    response.end(html);
    return;
  }
  if (pathname === '/scene_camera.mjs') {
    response.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8' });
    createReadStream(join(ROOT, 'scene_camera.mjs')).pipe(response);
    return;
  }
  if (pathname.startsWith('/modules/')) {
    const file = resolve(MODULES, normalize(pathname.slice('/modules/'.length)));
    if (!file.startsWith(`${MODULES}/`) || !existsSync(file) || !statSync(file).isFile()) {
      response.writeHead(404);
      response.end('Not found');
      return;
    }
    response.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8' });
    createReadStream(file).pipe(response);
    return;
  }
  response.writeHead(404);
  response.end('Not found');
});

await new Promise((resolveReady, reject) => {
  server.once('error', reject);
  server.listen(0, '127.0.0.1', resolveReady);
});
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
try {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/`, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => window.moduleResolutionReady === true, null, { timeout: 15000 });
  assert.deepEqual(pageErrors, [], `browser module errors: ${pageErrors.join('; ')}`);
  console.log('Three.js import-map smoke test passed; OBJLoader and MTLLoader resolve their bare "three" imports.');
} finally {
  await browser.close();
  await new Promise((resolveClose, reject) => server.close((error) => error ? reject(error) : resolveClose()));
}
