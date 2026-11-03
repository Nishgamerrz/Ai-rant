import assert from 'node:assert/strict';
import RAPIER from '@dimforge/rapier3d-compat';

await RAPIER.init();
const world = new RAPIER.World({ x: 0, y: -18, z: 0 });
world.timestep = 1 / 60;
const fixed = world.createRigidBody(RAPIER.RigidBodyDesc.fixed());
world.createCollider(
  RAPIER.ColliderDesc.cuboid(10, 0.5, 10).setTranslation(0, -0.5, 0).setFriction(0.9),
  fixed,
);
const character = world.createRigidBody(
  RAPIER.RigidBodyDesc.dynamic().setTranslation(0, 4, 0).lockRotations().setCanSleep(false),
);
world.createCollider(RAPIER.ColliderDesc.capsule(1, 0.4).setFriction(0.9), character);
const looseProp = world.createRigidBody(
  RAPIER.RigidBodyDesc.dynamic().setTranslation(3, 4, 0).setCanSleep(false),
);
world.createCollider(RAPIER.ColliderDesc.ball(0.4).setFriction(0.72).setRestitution(0.24), looseProp);
for (let frame = 0; frame < 240; frame += 1) world.step();
const restingHeight = character.translation().y;
const propHeight = looseProp.translation().y;
assert.ok(Math.abs(restingHeight - 1.4) < 0.06, `capsule should settle on the floor, got y=${restingHeight}`);
assert.ok(Math.abs(propHeight - 0.4) < 0.06, `dynamic prop should settle on the floor, got y=${propHeight}`);
console.log(`Rapier smoke test passed; avatar capsule and loose prop settled at y=${restingHeight.toFixed(3)} and y=${propHeight.toFixed(3)}.`);
