#!/usr/bin/env node
/** Headless Three.js renderer: AI-authored Roblox Parts + authentic Roblox avatar OBJ meshes. */
import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { chromium } from 'playwright';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)));
const ASSET_ROOT = resolve(process.cwd());
const WIDTH = 720;
const HEIGHT = 1280;
const FPS = 30;

function argumentsFromProcess(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (!argv[i].startsWith('--')) continue;
    const key = argv[i].slice(2).replaceAll('-', '_');
    args[key] = argv[i + 1];
    i += 1;
  }
  for (const key of ['map', 'characters', 'profiles', 'captions', 'duration', 'output']) {
    if (!args[key]) throw new Error(`Missing --${key.replaceAll('_', '-')}`);
  }
  args.duration = Number(args.duration);
  if (![30, 45, 60].includes(args.duration)) throw new Error('Duration must be 30, 45, or 60 seconds.');
  return args;
}

function parseSrt(text) {
  const cleaned = text.replace(/^\uFEFF/, '').replaceAll('\r', '');
  const blocks = cleaned.trim().split(/\n\s*\n/);
  const cues = [];
  const time = (stamp) => {
    const match = stamp.match(/^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})$/);
    if (!match) return NaN;
    return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]) + Number(match[4]) / 1000;
  };
  for (const block of blocks) {
    const lines = block.split('\n');
    const timing = (lines[1] || '').match(/(\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[,.]\d{3})/);
    if (!timing) continue;
    const start = time(timing[1]);
    const end = time(timing[2]);
    const caption = lines.slice(2).join(' ').replace(/<[^>]*>/g, '').trim();
    if (Number.isFinite(start) && Number.isFinite(end) && end > start && caption) cues.push({ start, finish: end, text: caption });
  }
  return cues;
}

function safeData(value) {
  return JSON.stringify(value).replaceAll('<', '\\u003c').replaceAll('>', '\\u003e').replaceAll('&', '\\u0026');
}

function contentType(path) {
  return ({ '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.obj': 'text/plain; charset=utf-8', '.mtl': 'text/plain; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' })[extname(path).toLowerCase()] || 'application/octet-stream';
}

function buildHtml(data) {
  const encoded = safeData(data);
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><style>
  *{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#87b9e8;font-family:Arial,Helvetica,sans-serif}
  #frame{position:relative;width:${WIDTH}px;height:${HEIGHT}px}canvas{display:block;width:${WIDTH}px;height:${HEIGHT}px}
  #brand{position:absolute;top:35px;left:5%;width:90%;padding:14px 20px;border-radius:15px;background:rgba(9,20,39,.78);color:#fff;text-align:center;font-size:28px;font-weight:800;letter-spacing:1px;text-shadow:0 2px 4px #000}
  #theme{font-size:15px;font-weight:500;letter-spacing:.2px;color:#eaf4ff;margin-top:4px}
  #caption{position:absolute;left:4%;bottom:92px;width:92%;min-height:112px;padding:18px 22px;border:2px solid rgba(255,255,255,.45);border-radius:18px;background:rgba(4,10,20,.88);color:#fff;text-align:center;font-size:30px;line-height:1.22;font-weight:800;text-shadow:0 2px 5px #000;display:flex;align-items:center;justify-content:center}
  #credit{position:absolute;right:24px;bottom:37px;color:#fff;font-size:15px;text-shadow:0 2px 4px #000}
  </style></head><body><div id="frame"><div id="brand"><span id="title"></span><div id="theme"></div></div><div id="caption"></div><div id="credit">STORY WORLD</div></div>
  <script id="render-data" type="application/json">${encoded}</script><script type="module">
  import * as THREE from '/modules/three/build/three.module.js';
  import { OBJLoader } from '/modules/three/examples/jsm/loaders/OBJLoader.js';
  import { MTLLoader } from '/modules/three/examples/jsm/loaders/MTLLoader.js';
  const DATA=JSON.parse(document.getElementById('render-data').textContent);
  const rgb=(value)=>new THREE.Color(value[0]/255,value[1]/255,value[2]/255);
  const skyColor=rgb(DATA.plan.ambient_color||[180,205,230]).lerp(new THREE.Color(0x93c9f2),.45);
  const scene=new THREE.Scene(); scene.background=skyColor; scene.fog=new THREE.Fog(skyColor,420,1050);
  const renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'high-performance'});
  renderer.setPixelRatio(1); renderer.setSize(${WIDTH},${HEIGHT},false); renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.outputColorSpace=THREE.SRGBColorSpace; renderer.toneMapping=THREE.ACESFilmicToneMapping; renderer.toneMappingExposure=1.08;
  document.getElementById('frame').prepend(renderer.domElement);
  const camera=new THREE.PerspectiveCamera(43,${WIDTH}/${HEIGHT},0.15,1800);
  scene.add(new THREE.HemisphereLight(0xe6f4ff,0x66755a,2.15));
  const sun=new THREE.DirectionalLight(0xfff1d3,3.1); sun.position.set(-160,240,130); sun.castShadow=true; sun.shadow.mapSize.set(1024,1024); sun.shadow.camera.left=-340; sun.shadow.camera.right=340; sun.shadow.camera.top=340; sun.shadow.camera.bottom=-340; scene.add(sun);
  const fill=new THREE.DirectionalLight(0xa8ceff,0.8); fill.position.set(100,100,-140); scene.add(fill);
  const floor=new THREE.Mesh(new THREE.PlaneGeometry(640,640),new THREE.MeshStandardMaterial({color:rgb(DATA.plan.ground_color||[92,160,104]),roughness:0.96}));
  floor.rotation.x=-Math.PI/2; floor.position.y=-0.08; floor.receiveShadow=true; scene.add(floor);
  const foundation=new THREE.Mesh(new THREE.BoxGeometry(640,2,640),new THREE.MeshStandardMaterial({color:rgb(DATA.plan.ground_color||[92,160,104]),roughness:1})); foundation.position.set(0,-1.08,0); foundation.receiveShadow=true; scene.add(foundation);
  const geometry={Block:new THREE.BoxGeometry(1,1,1),Ball:new THREE.SphereGeometry(0.5,16,12),Cylinder:new THREE.CylinderGeometry(0.5,0.5,1,14)};
  const settings={Plastic:[0,.78],SmoothPlastic:[0,.38],Concrete:[0,.93],Grass:[0,1],Slate:[0,.91],Wood:[0,.8],Metal:[.62,.38],Neon:[0,.25],Glass:[.08,.13],Brick:[0,.93],Asphalt:[0,1]};
  const buckets=new Map();
  function addPart(part){
    const shape=['Block','Ball','Cylinder'].includes(part.shape)?part.shape:'Block';
    const mat=['Plastic','SmoothPlastic','Concrete','Grass','Slate','Wood','Metal','Neon','Glass','Brick','Asphalt'].includes(part.material)?part.material:'Plastic';
    const key=shape+'|'+mat;
    if(!buckets.has(key)) buckets.set(key,{shape,mat,parts:[]});
    buckets.get(key).parts.push(part);
  }
  addPart({name:'World Foundation Surface',shape:'Block',material:'Grass',position:[0,-2,0],size:[640,.1,640],color:DATA.plan.ground_color||[92,160,104]});
  const buildingWords=['building','shop','tower','house','school','cafe','store','station','temple','castle','museum','hall','market','hotel','factory','restaurant','library','hospital','arcade','bakery','office','apartment','mansion','workshop','palace','warehouse'];
  const componentWords=['wall','roof','door','window','frame','floor','stair','chimney','foundation','facade','pillar','column'];
  function makeFurnishedShell(p){
    const name=p.name||'Story Building', [x,y,z]=p.position,[sx,sy,sz]=p.size,base=p.color||[130,155,185];
    const t=Math.max(.45,Math.min(1.1,Math.min(sx,sy,sz)*.055)),x0=x-sx/2,x1=x+sx/2,z0=z-sz/2,z1=z+sz/2,y0=y-sy/2,y1=y+sy/2;
    const wallColor=base.map(c=>Math.max(20,Math.round(c*.78))),roofColor=base.map(c=>Math.min(255,Math.round(c*1.12)));
    const slab=(label,at,size,color,material='Brick')=>addPart({name:name+' '+label,shape:'Block',material,position:at,size,color});
    slab('Interior Floor',[x,y0+t/2,z],[sx,t,sz],wallColor,'Concrete');
    slab('Furnished Roof',[x,y1-t/2,z],[sx,t,sz],roofColor,'SmoothPlastic');
    slab('Rear Wall',[x,y,z0+t/2],[sx,sy,t],wallColor);
    slab('Left Wall',[x0+t/2,y,z],[t,sy,sz],wallColor);
    slab('Right Wall',[x1-t/2,y,z],[t,sy,sz],wallColor);
    const windowW=Math.min(Math.max(2,sx*.2),9),windowH=Math.min(Math.max(2,sy*.48),8),windowY=y+sy*.1;
    const doorW=Math.min(Math.max(1.5,sx*.16),4),doorH=Math.min(Math.max(2,sy*.62),8),front=z1+t/2;
    const openings=[
      {kind:'Window Left',cx:x-sx*.27,w:windowW,b:windowY-windowH/2,h:windowY+windowH/2},
      {kind:'Front Door',cx:x,w:doorW,b:y0+t,h:y0+doorH},
      {kind:'Window Right',cx:x+sx*.27,w:windowW,b:windowY-windowH/2,h:windowY+windowH/2}
    ].sort((a,b)=>a.cx-b.cx);
    const spans=[[x0+t,openings[0].cx-openings[0].w/2],...openings.slice(0,-1).map((o,i)=>[o.cx+o.w/2,openings[i+1].cx-openings[i+1].w/2]),[openings.at(-1).cx+openings.at(-1).w/2,x1-t]];
    for(const [left,right] of spans) if(right-left>.12) slab('Front Pier',[ (left+right)/2,(y0+y1)/2,front], [right-left,sy,t],wallColor);
    for(const o of openings){
      if(o.b>y0+t) slab(o.kind+' Sill Wall',[o.cx,(y0+t+o.b)/2,front],[o.w,o.b-(y0+t),t],wallColor);
      if(o.h<y1-t) slab(o.kind+' Header Wall',[o.cx,(o.h+y1-t)/2,front],[o.w,y1-t-o.h,t],wallColor);
      if(o.kind==='Front Door'){
        slab('Wood Entrance Door',[o.cx,(o.b+o.h)/2,front+t/2],[o.w*.9,o.h-o.b,.16],[79,64,48],'Wood');
        slab('Door Handle',[o.cx+o.w*.3,(o.b+o.h)/2,front+t/2+.1],[.13,.32,.08],[244,195,76],'Metal');
      }else{
        slab(o.kind+' Glass Pane',[o.cx,(o.b+o.h)/2,front+t/2],[o.w,o.h-o.b,.1],[145,220,246],'Glass');
        for(const dx of [-o.w/2,o.w/2]) slab(o.kind+' Frame Side',[o.cx+dx,(o.b+o.h)/2,front+t/2+.07],[.16,o.h-o.b+.25,.1],[240,244,248],'SmoothPlastic');
        for(const wy of [o.b,o.h]) slab(o.kind+' Frame Rail',[o.cx,wy,front+t/2+.07],[o.w+.2,.16,.1],[240,244,248],'SmoothPlastic');
      }
    }
    slab('Roof Eave',[x,y1+.35,z],[sx*1.06,.7,sz*1.06],roofColor,'SmoothPlastic');
  }
  for(const p of DATA.plan.props||[]){
    const name=(p.name||'').toLowerCase();
    const core=buildingWords.some(w=>name.includes(w))&&!componentWords.some(w=>name.includes(w))&&p.size[0]>=10&&p.size[1]>=6&&p.size[2]>=8;
    if(core)makeFurnishedShell(p);else addPart(p);
  }
  // Batch ordinary architecture into instanced meshes, so generously furnished AI maps render smoothly.
  const matrix=new THREE.Matrix4(),position=new THREE.Vector3(),scale=new THREE.Vector3(),quaternion=new THREE.Quaternion();
  for(const group of buckets.values()){
    const [metalness,roughness]=settings[group.mat]||[0,.8];
    const material=new THREE.MeshStandardMaterial({color:0xffffff,vertexColors:true,roughness,metalness,transparent:group.mat==='Glass',opacity:group.mat==='Glass'?.48:1,depthWrite:group.mat!=='Glass',emissive:group.mat==='Neon'?0x15202b:0,emissiveIntensity:group.mat==='Neon'?.8:0});
    const instanced=new THREE.InstancedMesh(geometry[group.shape],material,group.parts.length); instanced.castShadow=group.mat!=='Glass'; instanced.receiveShadow=true;
    group.parts.forEach((part,index)=>{
      position.set(Number(part.position[0]),Number(part.position[1]),Number(part.position[2]));
      scale.set(Math.max(.03,Number(part.size[0])),Math.max(.03,Number(part.size[1])),Math.max(.03,Number(part.size[2])));
      quaternion.identity();
      if(part.shape==='Cylinder') quaternion.setFromEuler(new THREE.Euler(0,0,Math.PI/2));
      matrix.compose(position,quaternion,scale); instanced.setMatrixAt(index,matrix); instanced.setColorAt(index,rgb(part.color||[135,165,205]));
    });
    instanced.instanceMatrix.needsUpdate=true; scene.add(instanced);
  }
  // Floor tiles and far green terrain soften the map edge without replacing the AI-authored theme.
  const horizon=new THREE.Mesh(new THREE.PlaneGeometry(2600,2600),new THREE.MeshStandardMaterial({color:0x9ebc82,roughness:1})); horizon.rotation.x=-Math.PI/2; horizon.position.y=-2.25; scene.add(horizon);
  const title=document.getElementById('title'),theme=document.getElementById('theme'),caption=document.getElementById('caption');
  title.textContent=(DATA.plan.name||'STORY WORLD').toUpperCase(); theme.textContent=DATA.plan.theme||'';
  const actors=[];
  function nameSprite(text){
    const canvas=document.createElement('canvas'); canvas.width=512;canvas.height=96;const ctx=canvas.getContext('2d');
    ctx.fillStyle='rgba(8,17,30,.82)';ctx.fillRect(8,8,496,80);ctx.font='bold 38px Arial';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillStyle='#fff';ctx.fillText(text.slice(0,24),256,48,470);
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:false}));sprite.scale.set(7,1.3,1);return sprite;
  }
  const placements=new Map((DATA.plan.character_placements||[]).map(c=>[String(c.username).toLowerCase(),c]));
  async function loadAvatar(profile,index){
    const username=profile.username,place=placements.get(username.toLowerCase());
    const fallback=[[0,0,24],[-4,0,25],[4,0,25],[-7,0,31],[7,0,31],[0,0,36]][index];
    const point=place?.position||fallback; const path='/avatar-assets/'+profile.user_id+'/';
    if(!profile.model_ready){
      const portrait=await new Promise((resolve,reject)=>new THREE.TextureLoader().load(path+'avatar.png',resolve,undefined,reject));
      portrait.colorSpace=THREE.SRGBColorSpace;
      const root=new THREE.Group();root.name='AuthenticRobloxAvatarPortrait_'+username;root.position.set(point[0],point[1],point[2]);
      const image=new THREE.Sprite(new THREE.SpriteMaterial({map:portrait,transparent:true,depthTest:true,depthWrite:false}));image.scale.set(5.4,5.4,1);image.position.y=2.9;root.add(image);
      const label=nameSprite(username);label.position.y=6.3;root.add(label);scene.add(root);actors.push({root,baseY:point[1]});return;
    }
    const [objResponse,mtlResponse]=await Promise.all([fetch(path+'avatar.obj'),fetch(path+'avatar.mtl')]);
    if(!objResponse.ok||!mtlResponse.ok) throw new Error('Missing public Roblox avatar model files for '+username);
    const [objText,mtlText]=await Promise.all([objResponse.text(),mtlResponse.text()]);
    const manager=new THREE.LoadingManager();
    manager.onError=url=>console.warn('Roblox avatar texture failed to load:',url);
    let finishTextures,textureTimer;
    const textureReady=new Promise(resolve=>{finishTextures=()=>{clearTimeout(textureTimer);resolve();};manager.onLoad=finishTextures;textureTimer=setTimeout(finishTextures,30000);});
    const mtlLoader=new MTLLoader(manager);mtlLoader.setResourcePath(location.origin+path);const materials=mtlLoader.parse(mtlText,location.origin+path);
    const hasTextures=Object.values(materials.materialsInfo||{}).some(info=>Object.keys(info).some(key=>key.toLowerCase().startsWith('map_')));
    materials.preload();
    const objLoader=new OBJLoader();objLoader.setMaterials(materials);const model=objLoader.parse(objText);
    if(hasTextures)await textureReady;else finishTextures();
    const bounds=new THREE.Box3().setFromObject(model);const size=bounds.getSize(new THREE.Vector3());
    if(!Number.isFinite(size.y)||size.y<.1) throw new Error('Roblox avatar mesh has invalid bounds for '+username);
    const pivot=new THREE.Group();pivot.name='AuthenticRobloxAvatar_'+username;
    const avatarScale=6.2/size.y;model.scale.setScalar(avatarScale);model.position.set(-((bounds.min.x+bounds.max.x)/2)*avatarScale,-bounds.min.y*avatarScale,-((bounds.min.z+bounds.max.z)/2)*avatarScale);
    model.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true;if(o.material){const ms=Array.isArray(o.material)?o.material:[o.material];for(const m of ms){m.side=THREE.DoubleSide;m.needsUpdate=true;}}}});
    pivot.add(model);pivot.position.set(point[0],point[1],point[2]);
    const label=nameSprite(username);label.position.set(0,7.2,0);pivot.add(label);scene.add(pivot);actors.push({root:pivot,baseY:point[1]});
  }
  const avatarPromise=Promise.all(DATA.profiles.map(loadAvatar));
  const shots=DATA.plan.camera_shots?.length?DATA.plan.camera_shots:[{time:0,position:[0,45,110],target:[0,4,24],transition:'smooth'},{time:DATA.duration,position:[-25,18,50],target:[0,3,24],transition:'smooth'}];
  const cues=DATA.captions;
  function cameraAt(t){
    let index=0;for(let i=0;i<shots.length;i++){if(t>=shots[i].time)index=i;else break;}
    const a=shots[index],b=shots[Math.min(index+1,shots.length-1)];let alpha=0;
    if(b!==a&&b.transition!=='snap'){alpha=Math.max(0,Math.min(1,(t-a.time)/Math.max(.01,b.time-a.time)));alpha=alpha*alpha*(3-2*alpha);}
    const mix=(key)=>new THREE.Vector3(...a[key]).lerp(new THREE.Vector3(...b[key]),alpha);
    const pos=mix('position');pos.y=Math.max(2.5,pos.y);const target=mix('target');camera.position.copy(pos);camera.lookAt(target);camera.updateMatrixWorld(true);
  }
  window.sceneReady=avatarPromise.then(()=>{renderer.compile(scene,camera);return true;});
  window.renderAt=async(t)=>{
    cameraAt(t);for(const actor of actors)actor.root.position.y=actor.baseY+Math.abs(Math.sin(t*2.2))*.035;
    const active=cues.find(c=>t>=c.start&&t<=c.finish);caption.textContent=active?.text||'';
    renderer.render(scene,camera);await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));return true;
  };
  </script></body></html>`;
}

function serveFile(response, path) {
  if (!existsSync(path) || !statSync(path).isFile()) { response.writeHead(404); response.end('Not found'); return; }
  response.writeHead(200, { 'Content-Type': contentType(path), 'Access-Control-Allow-Origin': '*' });
  createReadStream(path).pipe(response);
}

function createStaticServer(html, avatarRoot) {
  return createServer((request, response) => {
    const pathname = decodeURIComponent(new URL(request.url, 'http://127.0.0.1').pathname);
    if (pathname === '/') { response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); response.end(html); return; }
    if (pathname.startsWith('/modules/')) {
      const path = resolve(ROOT, 'node_modules', normalize(pathname.slice('/modules/'.length)));
      if (!path.startsWith(resolve(ROOT, 'node_modules') + '/')) { response.writeHead(403); response.end(); return; }
      serveFile(response, path); return;
    }
    if (pathname.startsWith('/avatar-assets/')) {
      const path = resolve(avatarRoot, normalize(pathname.slice('/avatar-assets/'.length)));
      if (!path.startsWith(avatarRoot + '/')) { response.writeHead(403); response.end(); return; }
      serveFile(response, path); return;
    }
    response.writeHead(404); response.end('Not found');
  });
}

async function writeFrame(stream, png) {
  if (!stream.write(png)) await once(stream, 'drain');
}

async function main() {
  const args=argumentsFromProcess(process.argv.slice(2));
  const plan=JSON.parse(readFileSync(args.map,'utf8'));
  const usernames=JSON.parse(readFileSync(args.characters,'utf8'));
  const profiles=JSON.parse(readFileSync(args.profiles,'utf8'));
  if(!Array.isArray(usernames)||usernames.length===0) throw new Error('Provide at least one actual Roblox username for the lead avatar.');
  if(!Array.isArray(profiles)||profiles.length!==usernames.length) throw new Error('Actual Roblox avatar profiles do not match the username cast.');
  const profileByName=new Map(profiles.map(p=>[p.username.toLowerCase(),p]));
  const orderedProfiles=usernames.map(name=>{const p=profileByName.get(name.toLowerCase());if(!p?.user_id||(!p.model_ready&&!p.thumbnail_ready))throw new Error('Authentic Roblox avatar mesh or thumbnail missing for '+name);return p;});
  const captions=parseSrt(readFileSync(args.captions,'utf8'));
  if(!captions.length) throw new Error('SRT contains no caption cues; refusing to make an uncaptioned MP4.');
  const data={plan,profiles:orderedProfiles,captions,duration:args.duration};
  const server=createStaticServer(buildHtml(data),resolve(ASSET_ROOT,'dist/avatar-assets'));
  await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
  const address=server.address();
  const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=swiftshader']});
  let ffmpeg;
  try{
    const page=await browser.newPage({viewport:{width:WIDTH,height:HEIGHT},deviceScaleFactor:1});
    page.on('console',message=>{if(message.type()==='error')console.error('[browser]',message.text());});
    page.on('pageerror',error=>console.error('[browser page error]',error.message));
    await page.goto(`http://127.0.0.1:${address.port}/`,{waitUntil:'networkidle',timeout:120000});
    await page.waitForFunction(()=>Boolean(window.sceneReady),null,{timeout:120000});
    const ready=await page.evaluate(()=>window.sceneReady);
    if(!ready)throw new Error('3D map and actual Roblox avatars failed to load.');
    ffmpeg=spawn('ffmpeg',['-y','-hide_banner','-loglevel','warning','-f','image2pipe','-vcodec','png','-framerate',String(FPS),'-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-vf','scale=1440:2560:flags=lanczos','-r',String(FPS),'-t',String(args.duration),'-movflags','+faststart',args.output],{stdio:['pipe','ignore','inherit']});
    const ffmpegExit=once(ffmpeg,'close');
    const totalFrames=args.duration*FPS;
    console.log(`Rendering ${totalFrames} headless 3D frames from the furnished AI map and ${orderedProfiles.length} genuine Roblox avatar(s) (mesh or account-thumbnail source).`);
    for(let frame=0;frame<totalFrames;frame++){
      const time=frame/FPS;
      await page.evaluate(t=>window.renderAt(t),time);
      const png=await page.screenshot({type:'png',timeout:30000});
      await writeFrame(ffmpeg.stdin,png);
      if(frame===0||(frame+1)%300===0||frame+1===totalFrames)console.log(`Rendered ${frame+1}/${totalFrames} frames (${time.toFixed(1)}s).`);
    }
    ffmpeg.stdin.end();
    const [code,signal]=await ffmpegExit;
    if(code!==0)throw new Error(`ffmpeg exited with code ${code} (signal ${signal||'none'}).`);
  }finally{
    if(ffmpeg&&!ffmpeg.killed){try{ffmpeg.stdin.destroy();}catch{}}
    await browser.close();
    await new Promise(resolve=>server.close(resolve));
  }
  console.log(`Rendered silent 1440x2560 H.264 video to ${args.output}`);
}

main().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
