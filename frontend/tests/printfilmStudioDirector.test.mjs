import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeScene, projectPoint, sceneAtTime } from '../src/features/printfilm-studio/canvas/scene3d.ts'
test('director camera projects its target to the frame center and rejects behind camera', () => {
  const camera = normalizeScene().camera
  const point = projectPoint([0, camera.targetY, 0], camera, 1280, 720)
  assert.ok(Math.abs(point.x - 640) < 0.001 && Math.abs(point.y - 360) < 0.001)
  assert.equal(projectPoint([0, 1, 20], { ...camera, yaw: 0, pitch: 0 }, 1280, 720), null)
})
test('director scene persists and interpolates objects and camera between keyframes', () => {
  const scene = normalizeScene()
  scene.frames = [{ time: 0, camera: { ...scene.camera, yaw: 0 }, objects: scene.objects }, { time: 4, camera: { ...scene.camera, yaw: 80 }, objects: scene.objects.map((o) => ({ ...o, x: 4 })) }]
  const midway = sceneAtTime(normalizeScene(JSON.parse(JSON.stringify(scene))), 2)
  assert.equal(midway.camera.yaw, 40)
  assert.equal(midway.objects[0].x, 2)
  assert.equal(scene.objects[0].x, 0)
})
test('malformed scene numbers and oversized scene inputs are constrained', () => {
  const scene = normalizeScene({ duration: Infinity, camera: { fov: 0 }, objects: Array.from({ length: 80 }, (_, i) => ({ id: String(i), x: NaN })) })
  assert.equal(scene.objects.length, 30)
  assert.equal(scene.camera.fov, 15)
  assert.equal(scene.objects[0].x, 0)
})
