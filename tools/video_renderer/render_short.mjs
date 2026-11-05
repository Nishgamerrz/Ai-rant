#!/usr/bin/env node
/** Headless Three.js renderer: theme-furnished Roblox-style Parts + authentic Roblox avatar OBJ meshes. */
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
  for (const key of ['map', 'characters', 'profiles', 'duration', 'output']) {
    if (!args[key]) throw new Error(`Missing --${key.replaceAll('_', '-')}`);
  }
  args.duration = Number(args.duration);
  if (![30, 45, 60].includes(args.duration)) throw new Error('Duration must be 30, 45, or 60 seconds.');
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
  </style></head><body><div id="frame">
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
  import { animateAvatarRig, applyRobloxAnimationRig, buildAvatarRig } from '/avatar_rig.mjs';
  import { chooseSafeCamera } from '/scene_camera.mjs';
  const DATA=JSON.parse(document.getElementById('render-data').textContent);
  await RAPIER.init();
  const physicsWorld=new RAPIER.World({x:0,y:-18,z:0});physicsWorld.timestep=1/60;
  const fixedWorldBody=physicsWorld.createRigidBody(RAPIER.RigidBodyDesc.fixed());
  const dynamicPropBodies=new Map();let dynamicPropCount=0,staticPropCount=0;
  physicsWorld.createCollider(RAPIER.ColliderDesc.cuboid(320,1,320).setTranslation(0,-1.08,0).setFriction(.9),fixedWorldBody);
  for(const part of DATA.plan.props||[]){
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
  const dynamicPropInstances=[];
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
      const body=dynamicPropBodies.get(part);if(body)dynamicPropInstances.push({part,body,mesh:instanced,index});
    });
    instanced.instanceMatrix.needsUpdate=true; scene.add(instanced);
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
  function strengthSprite(value){
    const canvas=document.createElement('canvas');canvas.width=256;canvas.height=128;
    const ctx=canvas.getContext('2d');const text=String(Math.max(1,Math.min(999,Math.round(Number(value)||50))));
    ctx.font='bold 92px Arial';ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.lineJoin='round';ctx.lineWidth=10;ctx.strokeStyle='rgba(10,18,28,.92)';ctx.strokeText(text,128,66);
    ctx.fillStyle='#ffe18a';ctx.fillText(text,128,66);
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
    const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:true,depthWrite:false}));
    sprite.scale.set(2.5,1.25,1);return sprite;
  }
  function registerActor(root,point,index,placement,username,strength,rig=null,animationClips=null,animationScale=1){
    const lead=placement?.role==='lead'||index===0;
    const number=strengthSprite(strength);number.position.set(0,7.25,0);root.add(number);
    actors.push({root,username:String(username||''),baseX:Number(point[0]),baseY:Number(point[1]),baseZ:Number(point[2]),
      phase:index*1.73,lead,stride:lead?2.1:1.15,rig,animationClips,animationScale});
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
      scene.add(root);registerActor(root,point,index,place,username,place?.strength);return;
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
    scene.add(pivot);registerActor(pivot,point,index,place,username,place?.strength,avatarRig?.bones||null,animationClips,avatarScale);
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
  }
  window.sceneReady=avatarPromise.then(()=>{
    window.avatarRigSummary={total:actors.length,rigged:actors.filter(actor=>actor.rig).length,nativeAnimations:actors.filter(actor=>actor.rig&&actor.animationClips?.walk).length};
    renderer.compile(scene,camera);return true;
  });
  window.renderAt=async(t)=>{
    for(const actor of actors)animateActor(actor,t);cameraAt(t);
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
  const data={plan,profiles:orderedProfiles,duration:args.duration};
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
    const simulation=await page.evaluate(()=>window.physicsSummary);
    const avatarRigging=await page.evaluate(()=>window.avatarRigSummary);
    console.log(`Rapier simulation ready for ${simulation.dynamicProps} dynamic AI prop(s) and ${simulation.staticProps} static world collider(s); ${orderedProfiles.length} authentic avatar(s) use collision-free scripted paths.`);
    console.log(`Avatar sources: ${orderedProfiles.map(profile => `${profile.username}=${profile.model_source || (profile.thumbnail_ready ? 'official-thumbnail-fallback' : 'unknown')}`).join(', ')}.`);
    console.log(`Automatic avatar limb rigs: ${avatarRigging.rigged}/${avatarRigging.total} mesh(es) skinned to R15-style joints.`);
    console.log(`Native Roblox walk clips retargeted: ${avatarRigging.nativeAnimations}/${avatarRigging.total} avatar(s).`);
    if (avatarRigging.rigged !== avatarRigging.total) {
      throw new Error(`Moving-limb MP4 blocked: only ${avatarRigging.rigged}/${avatarRigging.total} avatars loaded as 3D meshes. A 2D thumbnail cannot animate limbs. Make the username-matched RBXM MeshParts or an authorized Roblox 3D avatar mesh accessible, then rerun; no static-limb MP4 will be packaged.`);
    }
    const frameStartedAt = Date.now();
    ffmpeg=spawn('ffmpeg',['-y','-hide_banner','-loglevel','warning','-f','image2pipe','-vcodec','mjpeg','-framerate',String(FPS),'-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-vf','scale=1440:2560:flags=lanczos','-r',String(FPS),'-t',String(args.duration),'-movflags','+faststart',args.output],{stdio:['pipe','ignore','inherit']});
    const ffmpegExit=once(ffmpeg,'close');
    const totalFrames=args.duration*FPS;
    console.log(`Rendering ${totalFrames} headless 3D frames with Rapier gravity/collisions and ${orderedProfiles.length} genuine Roblox avatar(s) (mesh or account-thumbnail source).`);
    for(let frame=0;frame<totalFrames;frame++){
      const time=frame/FPS;
      await page.evaluate(t=>window.renderAt(t),time);
      const jpeg=await page.screenshot({type:'jpeg',quality:92,timeout:30000});
      await writeFrame(ffmpeg.stdin,jpeg);
      const completed=frame+1;
      if(frame===0||completed%30===0||completed===totalFrames){
        const elapsed=(Date.now()-frameStartedAt)/1000;
        const rate=completed/Math.max(elapsed,0.001);
        const remaining=(totalFrames-completed)/Math.max(rate,0.001);
        console.log(`Rendered ${completed}/${totalFrames} frames (${time.toFixed(1)}s video); elapsed ${elapsed.toFixed(0)}s, estimated ${remaining.toFixed(0)}s remaining.`);
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
