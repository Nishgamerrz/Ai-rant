#!/usr/bin/env node
/** Headless Three.js renderer: theme-furnished Roblox-style Parts + authentic Roblox avatar OBJ meshes. */
import { createReadStream, existsSync, mkdirSync, readFileSync, statSync } from 'node:fs';
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
  args.preflight = argv.includes('--preflight');
  args.preview = args.preview || '';
  const required = args.preflight ? ['map'] : ['map', 'characters', 'profiles', 'duration', 'output'];
  for (const key of required) {
    if (!args[key]) throw new Error(`Missing --${key.replaceAll('_', '-')}`);
  }
  // Any length is allowed: the workflow lets the user pick an exact moment such
  // as 2:24, or a window the AI ends inside. Keep these bounds in sync with
  // tools/durations.py (MIN_DURATION / MAX_DURATION); tests/test_durations.py
  // fails if they drift.
  const MIN_DURATION = 15;
  const MAX_DURATION = 300;
  // A preflight only draws a single frame, so it has no length of its own: it
  // uses the shortest legal one instead of tripping the bounds check below.
  const stated = args.duration !== undefined && args.duration !== '';
  args.duration = Number(stated ? args.duration : MIN_DURATION);
  if (!args.preflight && !stated) throw new Error('Missing --duration');
  if (!Number.isFinite(args.duration) || args.duration < MIN_DURATION || args.duration > MAX_DURATION) {
    throw new Error(`Duration must be between ${MIN_DURATION} and ${MAX_DURATION} seconds, got ${args.duration}.`);
  }
  args.face_animation = args.face_animation ?? 'auto';
  if (!['auto', 'off', 'always'].includes(args.face_animation)) {
    throw new Error('--face-animation must be auto, always, or off.');
  }
  return args;
}

function safeData(value) {
  return JSON.stringify(value).replaceAll('<', '\\u003c').replaceAll('>', '\\u003e').replaceAll('&', '\\u0026');
}

function contentType(path) {
  return ({ '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.obj': 'text/plain; charset=utf-8', '.mtl': 'text/plain; charset=utf-8', '.gltf': 'model/gltf+json', '.glb': 'model/gltf-binary', '.fbx': 'application/octet-stream', '.dae': 'model/vnd.collada+xml', '.3ds': 'application/octet-stream', '.ply': 'application/octet-stream', '.stl': 'application/octet-stream', '.bin': 'application/octet-stream', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' })[extname(path).toLowerCase()] || 'application/octet-stream';
}

function buildHtml(data) {
  const encoded = safeData(data);
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><style>
  *{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#87b9e8;font-family:Arial,Helvetica,sans-serif}
  #frame{position:relative;width:${WIDTH}px;height:${HEIGHT}px}canvas{display:block;width:${WIDTH}px;height:${HEIGHT}px}
  /* On-screen captions, Roblox-shorts style: heavy white text with a black
     outline, centred and sitting a little above the middle of the vertical
     frame. It is drawn inside #frame, so it is captured with the WebGL canvas. */
  #caption{position:absolute;left:50%;top:38%;transform:translate(-50%,-50%) scale(1);
    width:84%;text-align:center;font-family:Arial Black,Arial,Helvetica,sans-serif;font-weight:900;
    font-size:${Math.round(WIDTH * 0.062)}px;line-height:1.14;letter-spacing:.5px;
    text-transform:uppercase;color:#fff;-webkit-text-stroke:${Math.round(WIDTH * 0.008)}px #000;
    paint-order:stroke fill;text-shadow:0 ${Math.round(WIDTH * 0.004)}px ${Math.round(WIDTH * 0.014)}px rgba(0,0,0,.55);
    opacity:0;pointer-events:none;word-wrap:break-word;overflow-wrap:break-word}
  #caption.on{opacity:1}
  </style></head><body><div id="frame">
  <div id="caption"></div>
  <script id="render-data" type="application/json">${encoded}</script><script type="importmap">{"imports":{"three":"/modules/three/build/three.module.js"}}</script><script type="module">
  import * as THREE from '/modules/three/build/three.module.js';
  import RAPIER from '/modules/@dimforge/rapier3d-compat/dist/rapier.mjs';
  import { OBJLoader } from '/modules/three/examples/jsm/loaders/OBJLoader.js';
  import { MTLLoader } from '/modules/three/examples/jsm/loaders/MTLLoader.js';
  import { GLTFLoader } from '/modules/three/examples/jsm/loaders/GLTFLoader.js';
  import { FBXLoader } from '/modules/three/examples/jsm/loaders/FBXLoader.js';
  import { ColladaLoader } from '/modules/three/examples/jsm/loaders/ColladaLoader.js';
  import { PLYLoader } from '/modules/three/examples/jsm/loaders/PLYLoader.js';
  import { STLLoader } from '/modules/three/examples/jsm/loaders/STLLoader.js';
  import { TDSLoader } from '/modules/three/examples/jsm/loaders/TDSLoader.js';
  import { animateAvatarRig, applyRobloxAnimationRig, buildAvatarRig, measureFaceAnchor } from '/avatar_rig.mjs';
  import { chooseFaceCamera, chooseSafeCamera } from '/scene_camera.mjs';
  import { buildShapeGeometry, SHAPE_ROTATIONS } from '/map_shapes.mjs';
  import { createParticleField, isAdditive, sampleParticles } from '/particles.mjs';
  import { applyFaceHeadMotion, blinkSchedule, createFaceRig, defaultFaceTimeline, faceStateAt,
    normalizeExpressionTimeline, parseSrt, speechPulses, syntheticPulses } from '/face_rig.mjs';
  const DATA=JSON.parse(document.getElementById('render-data').textContent);
  await RAPIER.init();
  const physicsWorld=new RAPIER.World({x:0,y:-18,z:0});physicsWorld.timestep=1/60;
  const fixedWorldBody=physicsWorld.createRigidBody(RAPIER.RigidBodyDesc.fixed());
  const dynamicPropBodies=new Map();let dynamicPropCount=0,staticPropCount=0;
  physicsWorld.createCollider(RAPIER.ColliderDesc.cuboid(320,1,320).setTranslation(0,-1.08,0).setFriction(.9),fixedWorldBody);
  const castLaneHazard=(part)=>{
    const [x,y,z]=part.position||[],[sx,sy,sz]=part.size||[];
    if(![x,y,z,sx,sy,sz].every(Number.isFinite))return true;
    if(Math.max(sx,sy,sz)>70)return true;
    const blocks=y-sy/2<7&&y+sy/2>2;
    return blocks&&Math.abs(x)<20&&z>4&&z<54;
  };
  for(const part of DATA.plan.props||[]){
    if(castLaneHazard(part))continue;
    const [x,y,z]=part.position,[sx,sy,sz]=part.size;
    if(part.physics==='dynamic'&&(part.shape==='Block'||part.shape==='Ball')&&Math.max(sx,sy,sz)<=12){
      const body=physicsWorld.createRigidBody(RAPIER.RigidBodyDesc.dynamic().setTranslation(x,y,z)
        .setLinearDamping(.2).setAngularDamping(.35).setCanSleep(false));
      const collider=part.shape==='Ball'
        ? RAPIER.ColliderDesc.ball(Math.max(sx,sy,sz)/2)
        : RAPIER.ColliderDesc.cuboid(Math.max(.03,sx/2),Math.max(.03,sy/2),Math.max(.03,sz/2));
      physicsWorld.createCollider(collider.setFriction(.72).setRestitution(.24),body);
      body.setLinvel({x:((dynamicPropCount%3)-1)*.45,y:.18,z:(dynamicPropCount%2?.4:-.4)},true);
      dynamicPropBodies.set(part,body);dynamicPropCount+=1;
    }else{
      physicsWorld.createCollider(RAPIER.ColliderDesc.cuboid(Math.max(.03,sx/2),Math.max(.03,sy/2),Math.max(.03,sz/2))
        .setTranslation(x,y,z).setFriction(.82).setRestitution(.015),fixedWorldBody);
      staticPropCount+=1;
    }
  }
  window.physicsSummary={dynamicProps:dynamicPropCount,staticProps:staticPropCount};
  // Bright, readable palette guard: a near-black map Part next to the camera
  // used to read as an unexplained black box across the whole frame, so every
  // colour is lifted to a minimum luminance before it reaches the GPU.
  const sanitize=(value,floor=104)=>{
    const c=[0,1,2].map(i=>Math.max(0,Math.min(255,Math.round(Number(value?.[i]??128)))));
    const luminance=.2126*c[0]+.7152*c[1]+.0722*c[2];
    if(luminance>=floor)return c;
    const blend=Math.min(1,(floor-luminance)/Math.max(1,floor));
    const target=[168,180,196];
    return c.map((channel,i)=>Math.round(channel*(1-blend*0.86)+target[i]*(blend*0.86)));
  };
  const rgb=(value)=>new THREE.Color(...sanitize(value).map(v=>v/255));
  const skyColor=rgb(DATA.plan.ambient_color||[186,210,238]).lerp(new THREE.Color(0x9fd0f4),.5);
  const scene=new THREE.Scene(); scene.background=skyColor;
  const renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'high-performance'});
  renderer.setPixelRatio(1); renderer.setSize(${WIDTH},${HEIGHT},false); renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.outputColorSpace=THREE.SRGBColorSpace; renderer.toneMapping=THREE.NoToneMapping;
  document.getElementById('frame').prepend(renderer.domElement);
  const camera=new THREE.PerspectiveCamera(42,${WIDTH}/${HEIGHT},0.4,1600);
  scene.add(new THREE.HemisphereLight(0xf2f9ff,0x9aa88f,2.9));
  scene.add(new THREE.AmbientLight(0xffffff,0.75));
  const sun=new THREE.DirectionalLight(0xfff4dc,2.5); sun.position.set(-150,260,150); sun.castShadow=true; sun.shadow.mapSize.set(2048,2048); sun.shadow.camera.left=-320; sun.shadow.camera.right=320; sun.shadow.camera.top=320; sun.shadow.camera.bottom=-320; sun.shadow.camera.near=10; sun.shadow.camera.far=900; sun.shadow.bias=-0.0006; sun.shadow.normalBias=0.45; scene.add(sun);
  const fill=new THREE.DirectionalLight(0xcfe4ff,1.05); fill.position.set(160,120,-160); scene.add(fill);
  const rim=new THREE.DirectionalLight(0xffffff,0.6); rim.position.set(0,60,220); scene.add(rim);
  const groundRgb=sanitize(DATA.plan.ground_color||[126,182,120],118);
  const floor=new THREE.Mesh(new THREE.PlaneGeometry(760,760),new THREE.MeshStandardMaterial({color:new THREE.Color(...groundRgb.map(v=>v/255)),roughness:0.95}));
  floor.rotation.x=-Math.PI/2; floor.position.y=-0.06; floor.receiveShadow=true; scene.add(floor);
  const foundation=new THREE.Mesh(new THREE.BoxGeometry(760,2.4,760),new THREE.MeshStandardMaterial({color:new THREE.Color(...groundRgb.map(v=>v/255)),roughness:1})); foundation.position.set(0,-1.26,0); foundation.receiveShadow=true; scene.add(foundation);
  // Every shape fits inside one 1x1x1 cube and is scaled by the Part's size, so a
  // single instanced draw call still covers the whole map. The shapes themselves
  // live in map_shapes.mjs, which a Node smoke test builds for real.
  const geometry=buildShapeGeometry();
  const settings={Plastic:[0,.78],SmoothPlastic:[0,.38],Concrete:[0,.93],Grass:[0,1],Slate:[0,.91],Wood:[0,.8],Metal:[.62,.38],Neon:[0,.25],Glass:[.08,.13],Brick:[0,.93],Asphalt:[0,1]};
  const buckets=new Map();
  function addPart(part){
    const shape=geometry[part.shape]?part.shape:'Block';
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
  // Frame audit. A single oversized or dark Part sitting in the camera's working
  // area produced the "black box over the character" artefact. Props are snapped
  // to a 0.25-stud grid and anything that would swallow the shot is dropped or
  // shrunk instead of being rendered as a wall across the lens.
  const GRID=.25, CAST_MIN_Z=6, CAST_MAX_Z=52;
  const snap=(v)=>Math.round(Number(v||0)/GRID)*GRID;
  const groundLevel=0;
  function propIsCameraHazard(p){
    const [x,y,z]=p.position,[sx,sy,sz]=p.size;
    if(![x,y,z,sx,sy,sz].every(Number.isFinite))return true;
    const maxSpan=Math.max(sx,sy,sz);
    if(maxSpan>70)return true;
    const halfH=sy/2;
    const blocksCast=y-halfH<7&&y+halfH>2;
    const nearCast=Math.abs(x)<20&&z>CAST_MIN_Z-2&&z<CAST_MAX_Z+2;
    if(blocksCast&&nearCast)return true;
    return false;
  }
  let droppedProps=0,alignedProps=0;
  const safeProps=[];
  for(const raw of DATA.plan.props||[]){
    if(!Array.isArray(raw?.position)||!Array.isArray(raw?.size)){droppedProps+=1;continue;}
    const size=raw.size.map(v=>Math.max(.5,Math.min(70,Math.abs(Number(v)||.5))));
    const position=[snap(raw.position[0]),Math.max(.5,snap(raw.position[1])),snap(raw.position[2])];
    const p={...raw,position,size,color:sanitize(raw.color||[150,170,196])};
    if(propIsCameraHazard(p)){droppedProps+=1;continue;}
    alignedProps+=1;
    safeProps.push(p);
  }
  DATA.plan.props=safeProps;
  window.mapAudit={alignedParts:alignedProps,droppedHazards:droppedProps};
  for(const p of safeProps){
    const name=(p.name||'').toLowerCase();
    const core=buildingWords.some(w=>name.includes(w))&&!componentWords.some(w=>name.includes(w))&&p.size[0]>=10&&p.size[1]>=6&&p.size[2]>=8;
    if(core)makeFurnishedShell(p);else addPart(p);
  }
  // Cast lane stays completely clear so no wall, roof or prop can cross a face.
  for(let z=CAST_MIN_Z;z<=CAST_MAX_Z;z+=6){
    for(let x=-18;x<=18;x+=6){
      addPart({name:'Plaza Paving Tile',shape:'Block',material:'Concrete',position:[x,.03,z],size:[5.7,.14,5.7],color:[196,202,210]});
    }
  }
  // Batch ordinary architecture into instanced meshes, so generously furnished AI maps render smoothly.
  const matrix=new THREE.Matrix4(),position=new THREE.Vector3(),scale=new THREE.Vector3(),quaternion=new THREE.Quaternion();
  const dynamicPropInstances=[];
  for(const group of buckets.values()){
    const [metalness,roughness]=settings[group.mat]||[0,.8];
    // Per-part colour comes from setColorAt(), which three multiplies into the
    // shader through instanceColor. It must NOT set vertexColors: that defines
    // USE_COLOR, which multiplies vColor by a per-vertex colour attribute these
    // geometries do not have - so every Part in the map rendered pure black.
    // That was the "black boxes all over the world" artefact.
    const material=new THREE.MeshStandardMaterial({color:0xffffff,roughness,metalness,transparent:group.mat==='Glass',opacity:group.mat==='Glass'?.48:1,depthWrite:group.mat!=='Glass',emissive:group.mat==='Neon'?0x15202b:0,emissiveIntensity:group.mat==='Neon'?.8:0});
    const instanced=new THREE.InstancedMesh(geometry[group.shape],material,group.parts.length); instanced.castShadow=group.mat!=='Glass'; instanced.receiveShadow=true;
    group.parts.forEach((part,index)=>{
      position.set(Number(part.position[0]),Number(part.position[1]),Number(part.position[2]));
      scale.set(Math.max(.03,Number(part.size[0])),Math.max(.03,Number(part.size[1])),Math.max(.03,Number(part.size[2])));
      quaternion.identity();
      const spin=SHAPE_ROTATIONS[part.shape];
      if(spin) quaternion.setFromEuler(new THREE.Euler(spin[0],spin[1],spin[2]));
      matrix.compose(position,quaternion,scale); instanced.setMatrixAt(index,matrix); instanced.setColorAt(index,rgb(part.color||[135,165,205]));
      const body=dynamicPropBodies.get(part);if(body)dynamicPropInstances.push({part,body,mesh:instanced,index});
    });
    instanced.instanceMatrix.needsUpdate=true; scene.add(instanced);
    // A vertex-colour material without a colour attribute silently renders
    // black, so the two are checked together rather than trusted.
    if(material.vertexColors&&!geometry[group.shape]?.getAttribute?.('color')){
      throw new Error('Instanced map material asks for vertex colours the geometry does not have; every Part would render black.');
    }
  }
  // LIGHTS. A Part with a light is a lamp: it keeps its own colour and casts a
  // pool of light that the AI can make bigger, brighter or darker by number.
  const lampLights=[];
  for(const p of safeProps){
    const spec=p.light;
    if(!spec)continue;
    const [x,y,z]=p.position;
    const tint=new THREE.Color(...(Array.isArray(spec.color)?spec.color:[255,226,156]).map(v=>Math.max(0,Math.min(255,Number(v)||0))/255));
    const brightness=Math.max(0,Math.min(5,Number(spec.brightness??1.6)));
    const range=Math.max(1,Math.min(60,Number(spec.range??22)));
    // Brightness and range are Roblox units; a point light at 5 studs should read
    // as a bright pool, so intensity scales with both.
    const intensity=brightness*Math.max(6,range*1.15);
    let light;
    if(spec.kind==='Spot'){
      const angle=Math.max(5,Math.min(180,Number(spec.angle??90)));
      light=new THREE.SpotLight(tint,intensity,range*1.3,THREE.MathUtils.degToRad(angle/2),.45,1.6);
      light.position.set(x,y+Math.max(.5,p.size[1]/2),z);
      light.target.position.set(x,y-4,z);
      scene.add(light.target);
    }else{
      light=new THREE.PointLight(tint,intensity,range*1.3,1.7);
      light.position.set(x,y+Math.max(.4,p.size[1]/2),z);
    }
    if(lampLights.length<40) scene.add(light);
    lampLights.push(light);
    // A visible bulb so the source itself is not an invisible nothing.
    const bulb=new THREE.Mesh(new THREE.SphereGeometry(Math.max(.22,Math.min(1.6,Math.max(...p.size)*.07)),10,8),
      new THREE.MeshStandardMaterial({color:tint,emissive:tint,emissiveIntensity:2.2,roughness:.3}));
    bulb.position.copy(light.position); scene.add(bulb);
  }
  window.lightSummary={lights:lampLights.length};

  // PARTICLE EFFECTS. Sparkles, fire, smoke, confetti, rain, snow and the rest of
  // the catalogue. Positions are computed from the render clock, not accumulated
  // frame by frame, so every frame is reproducible and a re-render matches.
  const LOOKS={
    star:{points:[[0,-1],[.35,-.35],[1,0],[.35,.35],[0,1],[-.35,.35],[-1,0],[-.35,-.35]]},
    glow:null, puff:null, bubble:null, square:null, flake:null,
    streak:null, heart:null, petal:null, leaf:null, bolt:null,
  };
  const effectTextures=new Map();
  function effectTexture(look){
    if(effectTextures.has(look))return effectTextures.get(look);
    const size=64,canvas=document.createElement('canvas');
    canvas.width=canvas.height=size;
    const g=canvas.getContext('2d');
    const mid=size/2;
    const radial=(stops)=>{const grd=g.createRadialGradient(mid,mid,0,mid,mid,mid);stops.forEach(s=>grd.addColorStop(s[0],s[1]));return grd;};
    g.fillStyle='rgba(255,255,255,0)';g.fillRect(0,0,size,size);
    if(look==='star'){
      g.fillStyle=radial([[0,'rgba(255,255,255,1)'],[.45,'rgba(255,255,255,.85)'],[1,'rgba(255,255,255,0)']]);
      g.beginPath();g.arc(mid,mid,mid,0,Math.PI*2);g.fill();
      g.fillStyle='rgba(255,255,255,.95)';
      g.beginPath();g.moveTo(mid,2);g.lineTo(mid+6,mid-6);g.lineTo(size-2,mid);g.lineTo(mid+6,mid+6);
      g.lineTo(mid,size-2);g.lineTo(mid-6,mid+6);g.lineTo(2,mid);g.lineTo(mid-6,mid-6);g.closePath();g.fill();
    }else if(look==='glow'){
      g.fillStyle=radial([[0,'rgba(255,255,255,1)'],[.4,'rgba(255,255,255,.55)'],[1,'rgba(255,255,255,0)']]);
      g.beginPath();g.arc(mid,mid,mid,0,Math.PI*2);g.fill();
    }else if(look==='puff'){
      g.fillStyle=radial([[0,'rgba(255,255,255,.85)'],[.55,'rgba(255,255,255,.35)'],[1,'rgba(255,255,255,0)']]);
      g.beginPath();g.arc(mid,mid,mid,0,Math.PI*2);g.fill();
    }else if(look==='bubble'){
      g.strokeStyle='rgba(255,255,255,.9)';g.lineWidth=5;
      g.beginPath();g.arc(mid,mid,mid-6,0,Math.PI*2);g.stroke();
      g.fillStyle='rgba(255,255,255,.28)';g.beginPath();g.arc(mid,mid,mid-6,0,Math.PI*2);g.fill();
      g.fillStyle='rgba(255,255,255,.85)';g.beginPath();g.arc(mid-10,mid-12,6,0,Math.PI*2);g.fill();
    }else if(look==='square'){
      g.fillStyle='rgba(255,255,255,.95)';g.fillRect(mid-20,mid-20,40,40);
    }else if(look==='flake'){
      g.strokeStyle='rgba(255,255,255,.95)';g.lineWidth=5;g.lineCap='round';
      for(let i=0;i<3;i++){const a=i*Math.PI/3;g.beginPath();g.moveTo(mid-Math.cos(a)*mid*.9,mid-Math.sin(a)*mid*.9);g.lineTo(mid+Math.cos(a)*mid*.9,mid+Math.sin(a)*mid*.9);g.stroke();}
    }else if(look==='streak'){
      g.fillStyle=radial([[0,'rgba(255,255,255,.95)'],[1,'rgba(255,255,255,0)']]);
      g.fillRect(mid-5,0,10,size);
    }else if(look==='heart'){
      g.fillStyle='rgba(255,255,255,.95)';g.beginPath();
      g.moveTo(mid,size-10);
      g.bezierCurveTo(2,mid+8,mid-22,6,mid-10,10);g.bezierCurveTo(mid-4,12,mid,mid-8,mid,mid-2);
      g.bezierCurveTo(mid,mid-8,mid+4,12,mid+10,10);g.bezierCurveTo(mid+22,6,size-2,mid+8,mid,size-10);
      g.fill();
    }else if(look==='petal'||look==='leaf'){
      g.fillStyle='rgba(255,255,255,.95)';g.beginPath();
      g.ellipse(mid,mid,mid*.75,mid*.34,Math.PI/5,0,Math.PI*2);g.fill();
    }else if(look==='bolt'){
      g.fillStyle='rgba(255,255,255,.98)';g.beginPath();
      g.moveTo(mid+10,2);g.lineTo(mid-14,mid+4);g.lineTo(mid-2,mid+4);g.lineTo(mid-10,size-2);
      g.lineTo(mid+16,mid-4);g.lineTo(mid+2,mid-4);g.closePath();g.fill();
    }
    const texture=new THREE.CanvasTexture(canvas);
    texture.needsUpdate=true;
    effectTextures.set(look,texture);
    return texture;
  }
  const effectSystems=[];
  for(const p of safeProps){
    const effect=p.effect;
    if(!effect)continue;
    const field=createParticleField(effect,effectSystems.length+1);
    const positions=new Float32Array(field.count*3);
    const geo=new THREE.BufferGeometry();
    geo.setAttribute('position',new THREE.BufferAttribute(positions,3));
    const tint=new THREE.Color(...(Array.isArray(effect.color)?effect.color:[255,199,64]).map(v=>Math.max(0,Math.min(255,Number(v)||0))/255));
    const additive=isAdditive(effect.family);
    const material=new THREE.PointsMaterial({size:Math.max(.08,Number(effect.size)||.4),map:effectTexture(effect.look||'glow'),
      color:tint,transparent:true,opacity:additive?.95:.8,depthWrite:false,sizeAttenuation:true,
      blending:additive?THREE.AdditiveBlending:THREE.NormalBlending});
    const points=new THREE.Points(geo,material);
    points.frustumCulled=false;
    scene.add(points);
    effectSystems.push({points,geo,positions,field,origin:p.position,effect});
  }
  window.effectSummary={systems:effectSystems.length,
    families:[...new Set(effectSystems.map(system=>system.effect.family))]};
  function updateEffects(t){
    for(const system of effectSystems){
      sampleParticles(system.field,system.origin,system.effect,t,system.positions);
      system.geo.attributes.position.needsUpdate=true;
    }
  }
  // Floor tiles and far green terrain soften the map edge without replacing the AI-authored theme.
  const horizon=new THREE.Mesh(new THREE.PlaneGeometry(2600,2600),new THREE.MeshStandardMaterial({color:rgb(DATA.plan.ground_color||[88,166,91]),roughness:1})); horizon.rotation.x=-Math.PI/2; horizon.position.y=-.08; scene.add(horizon);
  const actors=[];
  const placements=new Map((DATA.plan.character_placements||[]).map(c=>[String(c.username).toLowerCase(),c]));
  const mapProps=DATA.plan.props||[];
  const cameraBlockers=mapProps.filter(p=>p.physics!=='dynamic'&&p.size[1]>=2.5);
  function actorPointIsClear(x,z,occupied){
    for(const p of mapProps){
      const [px,py,pz]=p.position,[sx,sy,sz]=p.size;
      if(py-sy/2>8||py+sy/2<.3)continue;
      const dx=Math.max(Math.abs(x-px)-sx/2,0),dz=Math.max(Math.abs(z-pz)-sz/2,0);
      if(dx*dx+dz*dz<4.2*4.2)return false;
    }
    return occupied.every(q=>Math.hypot(x-q[0],z-q[2])>=4.2);
  }
  function resolveActorPoint(point){
    const occupied=actors.map(a=>[a.baseX,a.baseY,a.baseZ]);
    const offsets=[[0,0],[4,0],[-4,0],[0,4],[0,-4],[4,4],[-4,4],[4,-4],[-4,-4],
      [8,0],[-8,0],[0,8],[0,-8],[8,8],[-8,8],[8,-8],[-8,-8],[12,0],[-12,0],[0,12],[0,-12]];
    for(const [dx,dz] of offsets){
      const x=Math.max(-16,Math.min(16,Number(point[0])+dx));
      const z=Math.max(8,Math.min(48,Number(point[2])+dz));
      if(actorPointIsClear(x,z,occupied))return [x,Number(point[1]),z];
    }
    return [Number(point[0]),Number(point[1]),Number(point[2])];
  }
  function bodyTextSprite(value){
    const canvas=document.createElement('canvas');canvas.width=256;canvas.height=96;
    const ctx=canvas.getContext('2d');const text=String(value??'').slice(0,18);
    ctx.font='bold 76px Arial';ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.lineJoin='round';ctx.lineWidth=9;ctx.strokeStyle='rgba(10,18,28,.92)';ctx.strokeText(text,128,50);
    ctx.fillStyle='#ffe18a';ctx.fillText(text,128,50);
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
    const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:true,depthWrite:false}));
    sprite.scale.set(1.8,.68,1);return sprite;
  }
  function addRequestedAvatarEffects(root,bones,effects,frontDirection=[0,0,1]){
    const bonesByPart={head:'Head',torso:'Chest',left_arm:'LeftUpperArm',right_arm:'RightUpperArm',left_leg:'LeftUpperLeg',right_leg:'RightUpperLeg'};
    const frontSign=Number(frontDirection?.[2]??1)>=0?1:-1;
    for(const effect of Array.isArray(effects)?effects:[]){
      const target=bones?.[bonesByPart[effect.attachment]||'Head']||root;
      if(effect.kind==='number'||effect.kind==='text'){
        const label=bodyTextSprite(effect.value);
        label.position.set(0,effect.attachment==='head' ? .38 : .08, target===root?5.4:frontSign*.42);
        target.add(label);
      }else if(['scar','tattoo','birthmark','badge','emblem','symbol'].includes(effect.kind)){
        const color=effect.kind==='scar'||effect.kind==='birthmark'?0x8e3b48:0xf2c45e;
        const mark=new THREE.Mesh(new THREE.CircleGeometry(effect.kind==='scar' ? .18 : .13,16),
          new THREE.MeshBasicMaterial({color,transparent:true,opacity:.9,depthWrite:false,side:THREE.DoubleSide}));
        mark.scale.set(1.25,.34,1);
        mark.position.set(.16,.08,target===root?5.36:frontSign*.36);
        if(frontSign<0)mark.rotation.y=Math.PI;
        mark.rotation.z=-.42;
        target.add(mark);
      }
    }
  }
  // Animated faces. The AI world plan owns the expression timeline, so a cut to a
  // new feeling happens at the exact second the AI chose, and the mouth follows
  // the narration captions the narration step already produced.
  const captions = parseSrt(DATA.captions || '');
  const expressionTimeline = normalizeExpressionTimeline(
    DATA.plan.face_expressions, DATA.duration, DATA.profiles.map(profile => profile.username));
  const fallbackTimeline = expressionTimeline.length
    ? expressionTimeline : defaultFaceTimeline(DATA.duration);
  const faceSpeechPulses = captions.length ? speechPulses(captions) : syntheticPulses(DATA.duration, 11);
  window.facePlanSummary = {
    source: expressionTimeline.length ? 'ai-timeline' : 'generated-fallback',
    expressionSwitches: fallbackTimeline.length,
    captionCues: captions.length,
    mouthPulses: faceSpeechPulses.length,
  };
  function attachAnimatedFace(head,rig,index,frontDirection,mode){
    if(!head||!rig||mode==='off')return null;
    // A face is decoration: if measuring the head fails, the avatar still renders.
    let layout;
    try{layout=measureFaceAnchor(THREE,rig,head,Number(frontDirection?.[2]??1));}
    catch(error){console.warn('Head measurement failed; rendering this avatar without a face:',error.message);return null;}
    const face=createFaceRig(THREE,{headBone:head,width:layout.width,height:layout.height,seed:index*23+7});
    face.mesh.position.copy(layout.anchor);
    if(Number(frontDirection?.[2]??1)<0)face.mesh.rotation.y=Math.PI;
    head.add(face.mesh);
    return face;
  }
  function updateActorFace(actor,t){
    if(!actor.face)return;
    const state=faceStateAt(t,{
      timeline:fallbackTimeline,
      username:actor.username,
      pulses:faceSpeechPulses,
      blinks:actor.blinks,
      seed:actor.face.seed,
      speaking:true,
    });
    actor.face.update(state);
    if(actor.rig)applyFaceHeadMotion(THREE,actor.rig,state);
    actor.faceState=state;
  }
  function registerActor(root,point,index,placement,username,avatarRig=null,animationClips=null,animationScale=1,frontDirection=[0,0,1]){
    const lead=placement?.role==='lead'||index===0;
    // avatarRig is the object buildAvatarRig() returns: the joint map (bones)
    // plus the meshes/skeleton used to measure the head. The body needs joints.
    const bones=avatarRig?.bones&&avatarRig.bones.Head?avatarRig.bones:(avatarRig?.Head?avatarRig:null);
    addRequestedAvatarEffects(root,bones,placement?.visual_effects,frontDirection);
    const face=bones?.Head?attachAnimatedFace(bones.Head,avatarRig,index,frontDirection,DATA.faceAnimation):null;
    actors.push({root,username:String(username||''),baseX:Number(point[0]),baseY:Number(point[1]),baseZ:Number(point[2]),
      phase:index*1.73,lead,stride:lead?2.1:1.15,rig:bones,animationClips,animationScale,face,
      blinks:blinkSchedule(index*31+5,DATA.duration+4,lead?1.15:.9)});
  }
  async function loadAvatar(profile,index){
    const username=profile.username,place=placements.get(username.toLowerCase());
    const fallback=[[0,0,24],[-4,0,25],[4,0,25],[-7,0,31],[7,0,31],[0,0,36]][index];
    const point=resolveActorPoint(place?.position||fallback); const path='/avatar-assets/'+profile.user_id+'/';
    if(!profile.model_ready){
      const portrait=await new Promise((resolve,reject)=>new THREE.TextureLoader().load(path+'avatar.png',resolve,undefined,reject));
      portrait.colorSpace=THREE.SRGBColorSpace;
      const root=new THREE.Group();root.name='AuthenticRobloxAvatarPortrait_'+username;root.position.set(point[0],point[1],point[2]);
      const image=new THREE.Sprite(new THREE.SpriteMaterial({map:portrait,transparent:true,depthTest:true,depthWrite:false}));image.scale.set(5.4,5.4,1);image.position.y=2.9;root.add(image);
      scene.add(root);registerActor(root,point,index,place,username,null,null,1,profile.front_direction);return;
    }
    const modelFile=profile.model_file||'avatar.obj',modelFormat=profile.model_format||'obj';
    const manager=new THREE.LoadingManager();
    let managerSawItems=false;
    manager.onStart=()=>{managerSawItems=true;};
    manager.onError=url=>console.warn('Avatar texture/dependency failed to load:',url);
    let finishTextures,textureTimer;
    const textureReady=new Promise(resolve=>{finishTextures=()=>{clearTimeout(textureTimer);resolve();};manager.onLoad=finishTextures;textureTimer=setTimeout(finishTextures,30000);});
    const modelResponse=await fetch(path+modelFile);
    if(!modelResponse.ok)throw new Error('Missing local avatar model '+modelFile+' for '+username);
    let model,hasTextures=false;
    if(modelFormat==='obj'){
      const mtlResponse=await fetch(path+'avatar.mtl');
      if(!mtlResponse.ok)throw new Error('Missing OBJ material file for '+username);
      const [objText,mtlText]=await Promise.all([modelResponse.text(),mtlResponse.text()]);
      const mtlLoader=new MTLLoader(manager);mtlLoader.setResourcePath(location.origin+path);const materials=mtlLoader.parse(mtlText,location.origin+path);
      hasTextures=Object.values(materials.materialsInfo||{}).some(info=>Object.keys(info).some(key=>key.toLowerCase().startsWith('map_')));
      materials.preload();const objLoader=new OBJLoader();objLoader.setMaterials(materials);model=objLoader.parse(objText);
    }else if(modelFormat==='gltf'||modelFormat==='glb'){
      const data=await modelResponse.arrayBuffer();
      const gltf=await new GLTFLoader(manager).parseAsync(data,location.origin+path);model=gltf.scene;
      hasTextures=true;
    }else if(modelFormat==='fbx'){
      const data=await modelResponse.arrayBuffer();model=new FBXLoader(manager).parse(data,location.origin+path);hasTextures=true;
    }else if(modelFormat==='dae'){
      const text=await modelResponse.text();model=new ColladaLoader(manager).parse(text,location.origin+path).scene;hasTextures=true;
    }else if(modelFormat==='3ds'){
      const data=await modelResponse.arrayBuffer();model=new TDSLoader(manager).parse(data,location.origin+path);hasTextures=true;
    }else if(modelFormat==='ply'||modelFormat==='stl'){
      const data=await modelResponse.arrayBuffer();
      const geometry=modelFormat==='ply'?new PLYLoader().parse(data):new STLLoader().parse(data);
      if(modelFormat==='ply'&&geometry.hasAttribute('color'))geometry.computeVertexNormals();
      const material=new THREE.MeshStandardMaterial({color:0xffffff,vertexColors:modelFormat==='ply'&&geometry.hasAttribute('color'),roughness:.78,metalness:.02,side:THREE.DoubleSide});
      model=new THREE.Group();model.add(new THREE.Mesh(geometry,material));
    }else throw new Error('Unsupported avatar model format '+modelFormat+' for '+username);
    if(hasTextures&&managerSawItems)await textureReady;else finishTextures();
    const bounds=new THREE.Box3().setFromObject(model);const size=bounds.getSize(new THREE.Vector3());
    if(!Number.isFinite(size.y)||size.y<.1) throw new Error('Roblox avatar mesh has invalid bounds for '+username);
    const pivot=new THREE.Group();pivot.name='AuthenticRobloxAvatar_'+username;
    const avatarScale=6.2/size.y;model.scale.setScalar(avatarScale);model.position.set(-((bounds.min.x+bounds.max.x)/2)*avatarScale,-bounds.min.y*avatarScale,-((bounds.min.z+bounds.max.z)/2)*avatarScale);
    model.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true;if(o.material){const ms=Array.isArray(o.material)?o.material:[o.material];for(const m of ms){m.side=THREE.DoubleSide;m.needsUpdate=true;}}}});
    let avatarRig=null;
    try{
      avatarRig=buildAvatarRig(THREE,model);
      pivot.add(avatarRig.root);
      console.log('Automatically skinned '+username+' authentic Roblox mesh to '+avatarRig.skeleton.bones.length+' procedural joints.');
    }catch(error){
      console.warn('Automatic limb rig failed for '+username+'; keeping the authentic mesh with whole-avatar motion:',error.message);
      pivot.add(model);
    }
    const animationClips=profile.rbxm_animation_clips||null;
    if(avatarRig){
      for(const state of ['walk','jump']){
        if(profile.rbxm_animation_ids?.[state]&&!animationClips?.[state])throw new Error('Native Roblox '+state+' keyframes are missing for '+username+'; refusing a procedural substitute.');
        if(animationClips?.[state]){
          const mapped=applyRobloxAnimationRig(THREE,avatarRig.bones,animationClips[state],0,true,avatarScale);
          if(!mapped)throw new Error('Native Roblox '+state+' clip has no R15 Pose channels that map onto '+username+' avatar rig.');
          console.log('Retargeted '+mapped+' native Roblox '+state+' Pose tracks onto '+username+' avatar.');
        }
      }
    }
    pivot.position.set(point[0],point[1],point[2]);
    // Pass the whole rig object: the face needs the meshes and skeleton, the body
    // needs the joints. Handing over only its bones is what crashed measureHeadRegion.
    scene.add(pivot);registerActor(pivot,point,index,place,username,avatarRig,animationClips,avatarScale,profile.front_direction);
  }
  const avatarPromise=Promise.all(DATA.profiles.map(loadAvatar));
  const shots=DATA.plan.camera_shots?.length?DATA.plan.camera_shots:[{time:0,position:[0,38,76],target:[0,3,24],transition:'smooth'},{time:DATA.duration,position:[-14,15,18],target:[0,3,24],transition:'smooth'}];
  function cameraAt(t){
    let index=0;for(let i=0;i<shots.length;i++){if(t>=shots[i].time)index=i;else break;}
    const a=shots[index],b=shots[Math.min(index+1,shots.length-1)];let alpha=0;
    if(b!==a&&b.transition!=='snap'){alpha=Math.max(0,Math.min(1,(t-a.time)/Math.max(.01,b.time-a.time)));alpha=alpha*alpha*(3-2*alpha);}
    const mix=(key)=>new THREE.Vector3(...a[key]).lerp(new THREE.Vector3(...b[key]),alpha);
    const planned=mix('target');
    const actorFor=(shot,shotIndex)=>{
      const focus=String(shot.focus_username||'').toLowerCase();
      if(focus==='world'||focus==='none')return null;
      return actors.find(actor=>actor.username.toLowerCase()===focus)
        ||actors.find(actor=>actor.lead)||actors[shotIndex%Math.max(1,actors.length)];
    };
    const focusPoint=(actor,shot)=>actor
      ?new THREE.Vector3(actor.root.position.x,actor.root.position.y+3.05,actor.root.position.z)
      :new THREE.Vector3(...shot.target);
    const targetA=focusPoint(actorFor(a,index),a);
    const targetB=focusPoint(actorFor(b,Math.min(index+1,shots.length-1)),b);
    const target=targetA.lerp(targetB,alpha).lerp(planned,0.2);
    const desired=mix('position');
    // Roblox story shorts cut to the character's face for the emotional beat.
    // The AI sets framing:"face" on those shots and the camera closes right in.
    const framingA=String(a.framing||a.shot_type||'auto').toLowerCase();
    const framingB=String(b.framing||b.shot_type||'auto').toLowerCase();
    const useFace=alpha>=0.5?['face','close','closeup','close-up'].includes(framingB)
                          :['face','close','closeup','close-up'].includes(framingA);
    const focusActor=alpha>=0.5?actorFor(b,Math.min(index+1,shots.length-1)):actorFor(a,index);
    if(useFace&&focusActor){
      const head=focusActor.rig?.Head
        ? focusActor.rig.Head.getWorldPosition(new THREE.Vector3())
        : new THREE.Vector3(focusActor.root.position.x,focusActor.root.position.y+5.35,focusActor.root.position.z);
      const faceDistance=Math.max(2.0,Math.min(3.4,Number(a.face_distance||b.face_distance||2.45)));
      const faceView=chooseFaceCamera(head.toArray(),desired.toArray(),cameraBlockers,faceDistance);
      camera.position.set(faceView[0],faceView[1],faceView[2]);camera.lookAt(head);camera.updateMatrixWorld(true);
      return;
    }
    const preferred= index===0 ? [23,48] : (index>=shots.length-1 ? [14,28] : [17,36]);
    const safe=chooseSafeCamera(target.toArray(),desired.toArray(),cameraBlockers,preferred[0],preferred[1]);
    camera.position.set(safe[0],safe[1],safe[2]);camera.lookAt(target);camera.updateMatrixWorld(true);
  }
  // Move actors on deterministic, collision-free paths. A dynamic rigidbody used to
  // wedge against generated map Parts and keep moving the rig in place, causing foot
  // sliding and apparent limb stretch. Native Roblox clips still drive every pose.
  function animateActor(actor,t){
    const cycle=t*1.8+actor.phase,progress=Math.max(0,Math.min(1,t/DATA.duration));
    const x=actor.baseX+Math.sin(cycle*.42)*actor.stride;
    const z=actor.baseZ+Math.cos(cycle*.34+actor.phase)*actor.stride*.52;
    const jumpProgress=actor.lead?Math.max(0,Math.min(1,(progress-.88)/.12)):0;
    const jumpHeight=actor.lead?Math.sin(Math.PI*jumpProgress)*3.0:0;
    actor.root.position.set(x,actor.baseY+jumpHeight,z);
    const vx=Math.cos(cycle*.42)*actor.stride*.42*1.8;
    const vz=-Math.sin(cycle*.34+actor.phase)*actor.stride*.34*.52*1.8;
    const nativeClips=actor.animationClips;
    const jumpPose=actor.lead?Math.max(0,Math.sin(Math.PI*jumpProgress)):0;
    if(nativeClips?.walk){
      const jumping=Boolean(actor.lead&&jumpProgress>0&&nativeClips.jump);
      const clip=jumping?nativeClips.jump:nativeClips.walk;
      const clipTime=jumping?jumpProgress*clip.duration:(t*1.15+actor.phase*clip.duration);
      const mapped=applyRobloxAnimationRig(THREE,actor.rig,clip,clipTime,!jumping,actor.animationScale);
      if(!mapped)throw new Error('Native Roblox animation lost all mapped Pose channels during rendering.');
      actor.root.rotation.y=Math.atan2(vx,Math.max(.001,-vz));
      actor.root.rotation.z=0;
    }else{
      actor.root.rotation.y=Math.atan2(vx,Math.max(.001,-vz));
      actor.root.rotation.z=0;
      if(actor.rig)animateAvatarRig(actor.rig,t,actor.phase,jumpPose);
    }
    updateActorFace(actor,t);
    actor.root.updateMatrixWorld(true);
  }
  window.sceneReady=avatarPromise.then(()=>{
    window.avatarRigSummary={total:actors.length,rigged:actors.filter(actor=>actor.rig).length,nativeAnimations:actors.filter(actor=>actor.rig&&actor.animationClips?.walk).length};
    window.faceRigSummary={faces:actors.filter(actor=>actor.face).length,
      expressionSwitches:fallbackTimeline.length,
      expressionSource:expressionTimeline.length?'ai-timeline':'generated-fallback',
      faceShots:(DATA.plan.camera_shots||[]).filter(shot=>['face','close','closeup','close-up'].includes(String(shot.framing||shot.shot_type||'').toLowerCase())).length,
      captions:captions.length};
    renderer.compile(scene,camera);return true;
  });
  // Captions follow the narration's own SRT cues: the line on screen is the line
  // being spoken. A cue pops in slightly small and settles within a tenth of a
  // second, the way story shorts animate their text.
  // Square-pixel probe. A stretched MP4 never has the wrong frame size; it has a
  // projection that is wider in one axis than the other, which happens when the
  // camera aspect and the canvas the browser really drew disagree. Measure it in
  // pixels against the live drawing buffer instead of trusting the constants.
  window.probeProjection=()=>{
    const size=renderer.getDrawingBufferSize(new THREE.Vector2());
    camera.aspect=size.x/size.y;camera.updateProjectionMatrix();camera.updateMatrixWorld(true);
    const forward=new THREE.Vector3(0,0,-1).applyQuaternion(camera.quaternion);
    const right=new THREE.Vector3(1,0,0).applyQuaternion(camera.quaternion);
    const up=new THREE.Vector3(0,1,0).applyQuaternion(camera.quaternion);
    const anchorPoint=camera.position.clone().addScaledVector(forward,12);
    const project=(point)=>{
      const ndc=point.clone().project(camera);
      return {x:(ndc.x*0.5+0.5)*size.x,y:(ndc.y*0.5+0.5)*size.y};
    };
    const centre=project(anchorPoint);
    const across=project(anchorPoint.clone().add(right));
    const tall=project(anchorPoint.clone().add(up));
    const pixelX=Math.abs(across.x-centre.x),pixelY=Math.abs(tall.y-centre.y);
    return {
      canvas:[Math.round(size.x),Math.round(size.y)],
      cameraAspect:Number(camera.aspect.toFixed(4)),
      pixelsPerUnitX:Number(pixelX.toFixed(2)),
      pixelsPerUnitY:Number(pixelY.toFixed(2)),
      stretch:Number((pixelX/Math.max(pixelY,1e-6)).toFixed(4))
    };
  };
  const captionEl=document.getElementById('caption');
  let captionCue=null,captionText='';
  function captionAt(t){
    let active=null;
    for(const cue of captions){if(t>=cue.start&&t<=cue.end){active=cue;break;}}
    if(active!==captionCue){
      captionCue=active;
      const text=active?String(active.text||'').replace(/\s+/g,' ').trim():'';
      if(text!==captionText){
        captionText=text;
        captionEl.textContent=text;
        captionEl.classList.toggle('on',Boolean(text));
      }
    }
    if(!captionCue)return;
    const age=Math.max(0,t-captionCue.start);
    const pop=age>=.12?1:.92+.08*(age/.12);
    captionEl.style.transform='translate(-50%,-50%) scale('+pop.toFixed(3)+')';
  }
  window.renderAt=async(t)=>{
    for(const actor of actors)animateActor(actor,t);cameraAt(t);captionAt(t);updateEffects(t);
    physicsWorld.step();physicsWorld.step();
    for(const item of dynamicPropInstances){
      const p=item.body.translation(),r=item.body.rotation(),size=item.part.size;
      position.set(p.x,p.y,p.z);scale.set(Math.max(.03,size[0]),Math.max(.03,size[1]),Math.max(.03,size[2]));
      quaternion.set(r.x,r.y,r.z,r.w);matrix.compose(position,quaternion,scale);
      item.mesh.setMatrixAt(item.index,matrix);item.mesh.instanceMatrix.needsUpdate=true;
    }
    renderer.render(scene,camera);await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));return true;
  };
  </script></body></html>`;
}

// The page is one enormous template literal. A stray backtick inside it ends the
// literal early and turns the rest of the page into an expression, which used to
// surface as "WIDTHHEIGHT...bones is not a function" *after* the world, the story
// and the model download were already finished. Fail here instead, in the first
// second of the render, with a message that says what to look for.
function checkedHtml(data) {
  let html;
  try {
    html = buildHtml(data);
  } catch (error) {
    throw new Error('buildHtml() could not build the page (' + error.message + '). '
      + 'A backtick inside the HTML template (usually in a comment) ends it early; '
      + 'run npm run test:page-template to find it.');
  }
  if (!html.startsWith('<!doctype html>')) {
    throw new Error('buildHtml() did not return a page (it starts with '
      + JSON.stringify(html.slice(0, 40)) + '); a backtick probably ended the '
      + 'HTML template early. Run npm run test:page-template.');
  }
  return html;
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
    if (pathname === '/avatar_rig.mjs') { serveFile(response, join(ROOT, 'avatar_rig.mjs')); return; }
    if (pathname === '/scene_camera.mjs') { serveFile(response, join(ROOT, 'scene_camera.mjs')); return; }
    if (pathname === '/map_shapes.mjs') { serveFile(response, join(ROOT, 'map_shapes.mjs')); return; }
    if (pathname === '/particles.mjs') { serveFile(response, join(ROOT, 'particles.mjs')); return; }
    if (pathname === '/face_rig.mjs') { serveFile(response, join(ROOT, 'face_rig.mjs')); return; }
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

// Measure the pixels that actually go into the MP4, not the WebGL drawing buffer.
//
// Reading a WebGL canvas back from a separate JavaScript task returns an empty
// buffer once the compositor has cleared it, which made a perfectly bright frame
// measure as 100% black. These are the exact JPEG bytes that are piped to ffmpeg,
// decoded with the same ffmpeg that encodes them and downsampled to 180x320, so
// the audit describes the shipped picture.
const PROBE_WIDTH = 180;
const PROBE_HEIGHT = 320;
async function measureJpeg(jpeg) {
  const probe = spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-f', 'image2pipe',
    '-vcodec', 'mjpeg', '-i', 'pipe:0', '-vf', `scale=${PROBE_WIDTH}:${PROBE_HEIGHT}`,
    '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'], { stdio: ['pipe', 'pipe', 'inherit'] });
  const chunks = [];
  probe.stdout.on('data', chunk => chunks.push(chunk));
  const exit = once(probe, 'close');
  probe.stdin.end(jpeg);
  const [code] = await exit;
  const raw = Buffer.concat(chunks);
  const expected = PROBE_WIDTH * PROBE_HEIGHT * 3;
  if (code !== 0 || raw.length < expected) {
    throw new Error(`could not measure a rendered frame: ffmpeg exited ${code} with ${raw.length}/${expected} bytes`);
  }
  let sum = 0, black = 0, bright = 0, colourful = 0, centreDark = 0, centreCount = 0;
  const pixels = PROBE_WIDTH * PROBE_HEIGHT;
  const centreColumn = PROBE_WIDTH / 2;
  for (let i = 0, pixel = 0; i < expected; i += 3, pixel += 1) {
    const r = raw[i], g = raw[i + 1], b = raw[i + 2];
    const l = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    sum += l;
    if (l < 26) black += 1;
    if (l > 232) bright += 1;
    if (Math.max(r, g, b) - Math.min(r, g, b) > 42) colourful += 1;
    if (Math.abs((pixel % PROBE_WIDTH) - centreColumn) <= 45) {
      centreCount += 1;
      if (l < 26) centreDark += 1;
    }
  }
  return {
    meanLuminance: Number((sum / pixels).toFixed(1)),
    blackFraction: Number((black / pixels).toFixed(3)),
    brightFraction: Number((bright / pixels).toFixed(3)),
    colourFraction: Number((colourful / pixels).toFixed(3)),
    centreBlackFraction: Number((centreDark / Math.max(1, centreCount)).toFixed(3))
  };
}

// Prove the whole render path works - the page template, Chromium, WebGL, Three.js,
// Rapier, the physics step and the screenshot - before the workflow spends an hour
// planning a world. Every historical failure of this renderer (a stray backtick in
// the template, a missing module, a GPU-less browser) shows up here in seconds.
//
// This runs unattended on a fresh runner, so it reports *why* it failed rather than
// a bare stack: the stage that broke (start, page load, scene, frame), every browser
// message, and every request that failed.
const BASE_ARGS = ['--no-sandbox', '--disable-dev-shm-usage', '--enable-webgl',
  '--ignore-gpu-blocklist'];

// Headless Chromium draws WebGL through SwiftShader, and the flag that selects it
// differs between releases: some images only accept ANGLE, some only plain
// SwiftShader, and a few need no flag at all. Trying them in order turns a dead
// run into a one-second retry.
const GL_CONFIGS = [
  ['--use-gl=angle', '--use-angle=swiftshader'],
  ['--use-gl=swiftshader'],
  ['--use-gl=angle', '--use-angle=swiftshader-webgl'],
  [],
];

async function launchBrowser() {
  const problems = [];
  for (const extra of GL_CONFIGS) {
    try {
      const browser = await chromium.launch({ headless: true, args: [...BASE_ARGS, ...extra] });
      const label = extra.length ? extra.join(' ') : 'default GL';
      console.log(`Chromium started with ${label}.`);
      return browser;
    } catch (error) {
      problems.push(`${extra.join(' ') || 'default'}: ${String(error.message).split('\n')[0]}`);
    }
  }
  let where = '';
  try {
    const path = chromium.executablePath();
    where = ` The browser it wanted is ${path} (${existsSync(path) ? 'present' : 'MISSING'}).`;
  } catch { /* older playwright builds have no executablePath() */ }
  throw new Error('Chromium could not start with any WebGL setting. '
    + 'Run "npx playwright install --with-deps chromium" in tools/video_renderer.'
    + where + ` Tried: ${problems.join(' | ')}`);
}

async function preflight(plan) {
  const data = { plan, profiles: [], duration: 15, captions: '', faceAnimation: 'off' };
  let stage = 'build the page';
  let html;
  try {
    html = checkedHtml(data);
  } catch (error) {
    throw new Error(`preflight could not ${stage}: ${error.message}`);
  }
  const server = createStaticServer(html, resolve(ASSET_ROOT, 'dist/avatar-assets'));
  await new Promise((ok, fail) => { server.once('error', fail); server.listen(0, '127.0.0.1', ok); });
  const address = server.address();
  const messages = [];
  let browser;
  try {
    stage = 'start Chromium';
    browser = await launchBrowser();
    const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1 });
    const pageErrors = [];
    page.on('pageerror', error => { pageErrors.push(error.message); messages.push(`[pageerror] ${error.message}`); });
    page.on('console', message => messages.push(`[${message.type()}] ${message.text()}`));
    page.on('requestfailed', request => messages.push(`[request failed] ${request.url()} ${request.failure()?.errorText || ''}`));

    stage = 'load the page';
    await page.goto(`http://127.0.0.1:${address.port}/`, { waitUntil: 'networkidle', timeout: 120000 });

    stage = 'build the 3D scene';
    const ready = await Promise.race([
      page.evaluate(() => window.sceneReady),
      new Promise((_, fail) => setTimeout(() => fail(new Error('the scene never became ready (60s)')), 60000)),
    ]).catch(error => { throw new Error(`the scene failed to build: ${error.message}`); });
    if (!ready) throw new Error('the scene reported itself ready but returned nothing');

    stage = 'draw one frame';
    await page.evaluate(() => window.renderAt(0.1));
    const shot = await page.screenshot({ type: 'jpeg', quality: 80, timeout: 30000 });

    stage = 'check the frame';
    if (pageErrors.length) throw new Error('the page threw: ' + pageErrors.slice(0, 3).join(' | '));
    if (shot.length < 4096) throw new Error(`the rendered frame is only ${shot.length} bytes; the scene is blank`);
    // Catch a stretching or black world at the start of the run, not after it.
    stage = 'measure the picture';
    const health = { projection: await page.evaluate(() => window.probeProjection()), ...await measureJpeg(shot) };
    // The runner turns this into an annotation, so the numbers survive even when
    // the raw job log cannot be opened.
    console.log(`::notice title=Render preflight picture::${health.projection.canvas[0]}x${health.projection.canvas[1]} canvas, `
      + `stretch ${health.projection.stretch}, mean luminance ${health.meanLuminance}/255, `
      + `${(health.blackFraction * 100).toFixed(1)}% near-black, ${(health.colourFraction * 100).toFixed(1)}% colourful.`);
    console.log(`Render preflight picture: ${health.projection.canvas[0]}x${health.projection.canvas[1]} canvas, `
      + `stretch ${health.projection.stretch}, mean luminance ${health.meanLuminance}/255, `
      + `${(health.blackFraction * 100).toFixed(1)}% near-black, ${(health.colourFraction * 100).toFixed(1)}% colourful.`);
    if (health.projection.canvas[0] !== WIDTH || health.projection.canvas[1] !== HEIGHT) {
      throw new Error(`the browser drew a ${health.projection.canvas[0]}x${health.projection.canvas[1]} canvas instead of ${WIDTH}x${HEIGHT}, so the picture would be rescaled and stretched`);
    }
    if (Math.abs(health.projection.stretch - 1) > 0.02) {
      throw new Error(`the picture is stretched (ratio ${health.projection.stretch}); the camera aspect does not match the canvas`);
    }
    if (health.blackFraction > 0.55) {
      throw new Error(`the frame is ${(health.blackFraction * 100).toFixed(0)}% pure black; a material is missing its colour`);
    }
    if (health.colourFraction < 0.05) {
      throw new Error(`the frame is colourless (${(health.colourFraction * 100).toFixed(1)}% coloured pixels)`);
    }
    const props = await page.evaluate(() => (window.physicsSummary || {}).staticProps || 0);
    console.log(`Render preflight passed: page built, WebGL scene ready, ${props} collider(s), `
      + `frame captured (${shot.length.toLocaleString()} bytes).`);
    if (messages.length) {
      console.log(`Browser messages during preflight (${messages.length}, not fatal):`);
      for (const line of messages.slice(0, 10)) console.log('  ' + line);
    }
  } catch (error) {
    console.error(`Render preflight failed while trying to ${stage}: ${error.message}`);
    if (messages.length) {
      console.error('What the browser said:');
      for (const line of messages.slice(0, 25)) console.error('  ' + line);
    }
    throw new Error(`preflight failed at "${stage}": ${error.message}`);
  } finally {
    if (browser) await browser.close().catch(() => {});
    await new Promise(resolve => server.close(resolve));
  }
}

async function main() {
  const args=argumentsFromProcess(process.argv.slice(2));
  const plan=JSON.parse(readFileSync(args.map,'utf8'));
  if(args.preflight){ await preflight(plan); return; }
  const usernames=JSON.parse(readFileSync(args.characters,'utf8'));
  const profiles=JSON.parse(readFileSync(args.profiles,'utf8'));
  if(!Array.isArray(usernames)||usernames.length===0) throw new Error('Provide at least one actual Roblox username for the lead avatar.');
  if(!Array.isArray(profiles)||profiles.length!==usernames.length) throw new Error('Actual Roblox avatar profiles do not match the username cast.');
  const profileByName=new Map(profiles.map(p=>[p.username.toLowerCase(),p]));
  const orderedProfiles=usernames.map(name=>{
    const p=profileByName.get(name.toLowerCase());
    if(!p?.user_id)throw new Error('Roblox avatar profile missing for '+name);
    if(!p.model_ready)throw new Error(`Moving-limb MP4 requires a local or authorized 3D avatar mesh for ${name}; only a 2D thumbnail fallback is available.`);
    if(p.rbxm_animation_ids){
      const missing=['walk','jump'].filter(state=>p.rbxm_animation_ids[state]&&!p.rbxm_animation_clips?.[state]);
      if(missing.length)throw new Error(`Native Roblox ${missing.join('/')} animation keyframes for ${name} could not be loaded (${missing.map(state=>p.rbxm_animation_errors?.[state]||'missing clip data').join('; ')}); refusing to substitute procedural limb motion.`);
    }
    return p;
  });
  // Caption timings drive the mouth so lip movement lands on the spoken words.
  const captionCues = args.captions && existsSync(args.captions)
    ? readFileSync(args.captions, 'utf8') : '';
  const data={plan,profiles:orderedProfiles,duration:args.duration,
    captions:captionCues,faceAnimation:args.face_animation};
  const server=createStaticServer(checkedHtml(data),resolve(ASSET_ROOT,'dist/avatar-assets'));
  await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
  const address=server.address();
  const browser=await launchBrowser();
  let ffmpeg;
  try{
    const page=await browser.newPage({viewport:{width:WIDTH,height:HEIGHT},deviceScaleFactor:1});
    page.on('console',message=>{if(message.type()==='error')console.error('[browser]',message.text());});
    page.on('pageerror',error=>console.error('[browser page error]',error.message));
    await page.goto(`http://127.0.0.1:${address.port}/`,{waitUntil:'networkidle',timeout:120000});
    await page.waitForFunction(()=>Boolean(window.sceneReady),null,{timeout:120000});
    const ready=await page.evaluate(()=>window.sceneReady);
    if(!ready)throw new Error('3D map and actual Roblox avatars failed to load.');
    const simulation=await page.evaluate(()=>window.physicsSummary);
    const avatarRigging=await page.evaluate(()=>window.avatarRigSummary);
    // Fail before a single frame is encoded if the picture itself is distorted.
    const projection=await page.evaluate(()=>window.probeProjection());
    console.log(`Projection probe: canvas ${projection.canvas[0]}x${projection.canvas[1]}, camera aspect ${projection.cameraAspect}, `
      + `${projection.pixelsPerUnitX}px across vs ${projection.pixelsPerUnitY}px tall per world unit (stretch ${projection.stretch}).`);
    if(projection.canvas[0]!==WIDTH||projection.canvas[1]!==HEIGHT){
      throw new Error(`The renderer drew a ${projection.canvas[0]}x${projection.canvas[1]} frame instead of ${WIDTH}x${HEIGHT}; the MP4 would be scaled off-ratio and look stretched.`);
    }
    if(Math.abs(projection.stretch-1)>0.02){
      throw new Error(`The picture is stretched: one world unit covers ${projection.pixelsPerUnitX}px horizontally but ${projection.pixelsPerUnitY}px vertically (ratio ${projection.stretch}, expected 1). The camera aspect has drifted away from the canvas size.`);
    }
    const faces=await page.evaluate(()=>window.faceRigSummary);
    console.log(`Animated faces: ${faces.faces}/${avatarRigging.total} avatar(s), ${faces.expressionSwitches} AI-scheduled expression switch(es) (${faces.expressionSource}), ${faces.faceShots} face close-up shot(s), ${faces.captions} caption cue(s) driving mouth movement.`);
    console.log(`Rapier simulation ready for ${simulation.dynamicProps} dynamic AI prop(s) and ${simulation.staticProps} static world collider(s); ${orderedProfiles.length} authentic avatar(s) use collision-free scripted paths.`);
    console.log(`Avatar sources: ${orderedProfiles.map(profile => `${profile.username}=${profile.model_source || (profile.thumbnail_ready ? 'official-thumbnail-fallback' : 'unknown')}`).join(', ')}.`);
    console.log(`Automatic avatar limb rigs: ${avatarRigging.rigged}/${avatarRigging.total} mesh(es) skinned to R15-style joints.`);
    console.log(`Native Roblox walk clips retargeted: ${avatarRigging.nativeAnimations}/${avatarRigging.total} avatar(s).`);
    if (args.face_animation !== 'off' && faces.faces !== avatarRigging.total) {
      throw new Error(`Face animation blocked: only ${faces.faces}/${avatarRigging.total} avatars received an animated face.`);
    }
    if (avatarRigging.rigged !== avatarRigging.total) {
      throw new Error(`Moving-limb MP4 blocked: only ${avatarRigging.rigged}/${avatarRigging.total} avatars loaded as 3D meshes. A 2D thumbnail cannot animate limbs. Make the username-matched RBXM MeshParts or an authorized Roblox 3D avatar mesh accessible, then rerun; no static-limb MP4 will be packaged.`);
    }
    const frameStartedAt = Date.now();
    ffmpeg=spawn('ffmpeg',['-y','-hide_banner','-loglevel','warning','-f','image2pipe','-vcodec','mjpeg','-framerate',String(FPS),'-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-vf','scale=1440:2560:flags=lanczos,setsar=1','-r',String(FPS),'-t',String(args.duration),'-movflags','+faststart',args.output],{stdio:['pipe','ignore','inherit']});
    const ffmpegExit=once(ffmpeg,'close');
    const totalFrames=args.duration*FPS;
    console.log(`Rendering ${totalFrames} headless 3D frames with Rapier gravity/collisions and ${orderedProfiles.length} genuine Roblox avatar(s) (mesh or account-thumbnail source).`);
    // Still previews: a handful of frames written as PNG next to the video, so
    // the look of a run can be checked in seconds instead of downloading and
    // watching a hundred-megabyte MP4. They are also the frames the colour audit
    // measures, so a black or blown-out world is caught during the render.
    const previewDir = args.preview ? resolve(args.preview) : '';
    if (previewDir) mkdirSync(previewDir, { recursive: true });
    const previewTimes = new Set([0, Math.round(args.duration * 0.12), Math.round(args.duration * 0.3),
      Math.round(args.duration * 0.5), Math.round(args.duration * 0.7), Math.round(args.duration * 0.9),
      Math.round(args.duration) - 1].filter(value => value >= 0 && value < args.duration));
    const previewFrame = new Map([...previewTimes].map((second, index) => [second * FPS, index + 1]));
    const measured = [];
    for(let frame=0;frame<totalFrames;frame++){
      const time=frame/FPS;
      await page.evaluate(t=>window.renderAt(t),time);
      const jpeg=await page.screenshot({type:'jpeg',quality:92,timeout:30000});
      await writeFrame(ffmpeg.stdin,jpeg);
      if(previewFrame.has(frame)||frame%Math.round(FPS*15)===0){
        const stats=await measureJpeg(jpeg);
        const shotProjection=await page.evaluate(()=>window.probeProjection());
        if(Math.abs(shotProjection.stretch-1)>0.02){
          throw new Error(`Shot at t=${time.toFixed(1)}s is stretched: ${shotProjection.pixelsPerUnitX}px across vs ${shotProjection.pixelsPerUnitY}px tall per world unit (ratio ${shotProjection.stretch}, expected 1).`);
        }
        measured.push({time:Number(time.toFixed(1)),...stats});
        if(previewDir&&previewFrame.has(frame)){
          const label=String(Math.round(time)).padStart(3,'0');
          await page.screenshot({path:join(previewDir,`frame_${previewFrame.get(frame)}_t${label}s.png`),type:'png',timeout:30000});
        }
      }
      const completed=frame+1;
      if(frame===0||completed%30===0||completed===totalFrames){
        const elapsed=(Date.now()-frameStartedAt)/1000;
        const rate=completed/Math.max(elapsed,0.001);
        const remaining=(totalFrames-completed)/Math.max(rate,0.001);
        console.log(`Rendered ${completed}/${totalFrames} frames (${time.toFixed(1)}s video); elapsed ${elapsed.toFixed(0)}s, estimated ${remaining.toFixed(0)}s remaining.`);
      }
    }
    if(measured.length){
      const mean=(key)=>measured.reduce((total,item)=>total+item[key],0)/measured.length;
      const worst=measured.reduce((low,item)=>item.blackFraction>low.blackFraction?item:low,measured[0]);
      console.log(`Frame audit over ${measured.length} sampled frame(s): mean luminance ${mean('meanLuminance').toFixed(0)}/255, `
        + `${(mean('blackFraction')*100).toFixed(1)}% near-black, ${(mean('colourFraction')*100).toFixed(1)}% colourful, `
        + `darkest sample t=${worst.time}s at ${(worst.blackFraction*100).toFixed(1)}% black.`);
      if(previewDir) console.log(`Wrote ${Math.min(measured.length,previewFrame.size)} still preview(s) to ${previewDir}`);
      // A world of black silhouettes is a bug, not a style: stop before shipping it.
      const blackFrames=measured.filter(item=>item.blackFraction>0.55);
      if(blackFrames.length&&blackFrames.length>=Math.ceil(measured.length*0.6)){
        throw new Error(`The world renders black: ${blackFrames.length}/${measured.length} sampled frames are more than 55% pure black `
          + `(worst t=${worst.time}s at ${(worst.blackFraction*100).toFixed(0)}%). A material is missing its colour - `
          + 'check that instanced parts use instanceColor and not vertex colors.');
      }
      if(mean('colourFraction')<0.05){
        throw new Error(`The world renders colourless: only ${(mean('colourFraction')*100).toFixed(1)}% of the frame carries any colour.`);
      }
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
