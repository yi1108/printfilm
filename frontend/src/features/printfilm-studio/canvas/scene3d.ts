export type SceneObject = { id: string; name: string; kind: 'person' | 'box'; x: number; y: number; z: number; rotation: number; scale: number; color: string; pose: number }
export type SceneCamera = { yaw: number; pitch: number; distance: number; fov: number; targetY: number }
export type SceneFrame = { time: number; camera: SceneCamera; objects: SceneObject[] }
export type DirectorScene = { version: 1; objects: SceneObject[]; camera: SceneCamera; frames: SceneFrame[]; duration: number; background: string }
type Vec = [number, number, number]
const number = (value: unknown, fallback: number, min: number, max: number) => typeof value === 'number' && Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback
const color = (value: unknown, fallback: string) => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) ? value : fallback
const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' ? value as Record<string, unknown> : {}
const camera = (value: unknown): SceneCamera => { const v = record(value); return { yaw: number(v.yaw, 25, -360, 360), pitch: number(v.pitch, 12, -10, 80), distance: number(v.distance, 7, 1.5, 25), fov: number(v.fov, 45, 15, 100), targetY: number(v.targetY, 1, -2, 5) } }
const objects = (raw: unknown): SceneObject[] => (Array.isArray(raw) ? raw : []).slice(0, 30).map((entry, index) => { const v = record(entry); return { id: String(v.id || `actor-${index}`), name: String(v.name || `物体 ${index + 1}`).slice(0, 80), kind: v.kind === 'box' ? 'box' : 'person', x: number(v.x, 0, -10, 10), y: number(v.y, 0, 0, 10), z: number(v.z, 0, -10, 10), rotation: number(v.rotation, 0, -180, 180), scale: number(v.scale, 1, .2, 4), color: color(v.color, '#b7a0ce'), pose: number(v.pose, 0, -80, 80) } })
export function normalizeScene(raw?: unknown): DirectorScene {
  const v = record(raw), duration = number(v.duration, 5, 1, 30)
  const items = v.objects === undefined ? objects([{ id: 'actor-1', name: '角色 1', x: 0 }]) : objects(v.objects)
  if (new Set(items.map((o) => o.id)).size !== items.length) throw new Error('三维物体 ID 重复')
  return { version: 1, objects: items, camera: camera(v.camera), duration, background: color(v.background, '#e7e8ee'), frames: (Array.isArray(v.frames) ? v.frames : []).slice(0, 60).map((entry) => { const f = record(entry); return { time: number(f.time, 0, 0, duration), camera: camera(f.camera), objects: objects(f.objects) } }).sort((a, b) => a.time - b.time) }
}
export function sceneAtTime(scene: DirectorScene, time: number): DirectorScene {
  if (!scene.frames.length) return scene
  const before = [...scene.frames].reverse().find((f) => f.time <= time) || scene.frames[0]
  const after = scene.frames.find((f) => f.time >= time) || scene.frames[scene.frames.length - 1]
  const t = before === after || before.time === after.time ? 0 : (time - before.time) / (after.time - before.time)
  const mix = (a: number, b: number) => a + (b - a) * t
  const mixedCamera = { ...before.camera }
  for (const key of Object.keys(mixedCamera) as (keyof SceneCamera)[]) mixedCamera[key] = mix(before.camera[key], after.camera[key])
  return { ...scene, camera: mixedCamera, objects: before.objects.map((object) => { const next = after.objects.find((o) => o.id === object.id); if (!next) return object; const copy = { ...object }; for (const key of ['x', 'y', 'z', 'rotation', 'scale', 'pose'] as const) copy[key] = mix(object[key], next[key]); return copy }) }
}
const radians = (value: number) => value * Math.PI / 180
const dot = (a: Vec, b: Vec) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
export function projectPoint(point: Vec, c: SceneCamera, width: number, height: number) {
  const yaw = radians(c.yaw), pitch = radians(c.pitch)
  const eye: Vec = [Math.sin(yaw) * Math.cos(pitch) * c.distance, Math.sin(pitch) * c.distance + c.targetY, Math.cos(yaw) * Math.cos(pitch) * c.distance]
  const forward: Vec = [-Math.sin(yaw) * Math.cos(pitch), -Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch)]
  const right: Vec = [Math.cos(yaw), 0, -Math.sin(yaw)]
  const up: Vec = [-Math.sin(yaw) * Math.sin(pitch), Math.cos(pitch), -Math.cos(yaw) * Math.sin(pitch)]
  const relative: Vec = [point[0] - eye[0], point[1] - eye[1], point[2] - eye[2]]
  const depth = dot(relative, forward)
  if (depth <= .1) return null
  const focal = height / (2 * Math.tan(radians(c.fov) / 2))
  return { x: width / 2 + dot(relative, right) * focal / depth, y: height / 2 - dot(relative, up) * focal / depth, depth }
}

/** Small deterministic 3D software renderer: perspective projection and depth-sorted faces. */
export function renderScene(canvas: HTMLCanvasElement, scene: DirectorScene) {
  const ctx = canvas.getContext('2d')!, w = canvas.width, h = canvas.height
  ctx.fillStyle = scene.background; ctx.fillRect(0, 0, w, h)
  ctx.lineWidth = 1; ctx.strokeStyle = '#a4a6b066'
  const line = (a: Vec, b: Vec) => { const p = projectPoint(a, scene.camera, w, h), q = projectPoint(b, scene.camera, w, h); if (!p || !q) return; ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke() }
  for (let i = -10; i <= 10; i++) { line([i, 0, -10], [i, 0, 10]); line([-10, 0, i], [10, 0, i]) }
  const polygons: { points: { x: number; y: number; depth: number }[]; color: string; shade: number; depth: number }[] = []
  const box = (object: SceneObject, center: Vec, dimensions: Vec, tilt = 0) => {
    const angle = radians(object.rotation), bend = radians(tilt)
    const points = Array.from({ length: 8 }, (_, i) => {
      const lx = ((i & 1) ? .5 : -.5) * dimensions[0], ly = ((i & 2) ? .5 : -.5) * dimensions[1], lz = ((i & 4) ? .5 : -.5) * dimensions[2]
      const x = (lx + center[0]) * object.scale, y = (ly * Math.cos(bend) - lz * Math.sin(bend) + center[1]) * object.scale, z = (ly * Math.sin(bend) + lz * Math.cos(bend) + center[2]) * object.scale
      return projectPoint([x * Math.cos(angle) + z * Math.sin(angle) + object.x, y + object.y, -x * Math.sin(angle) + z * Math.cos(angle) + object.z], scene.camera, w, h)
    })
    ;[[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]].forEach((face, index) => {
      const facePoints = face.map((i) => points[i]); if (facePoints.some((p) => !p)) return
      const valid = facePoints as { x: number; y: number; depth: number }[]
      polygons.push({ points: valid, color: object.color, shade: [.18, .02, .28, 0, .12, .08][index], depth: valid.reduce((total, p) => total + p.depth, 0) / 4 })
    })
  }
  scene.objects.forEach((object) => {
    if (object.kind === 'box') { box(object, [0, .5, 0], [1, 1, 1]); return }
    box(object, [0, 1.65, 0], [.3, .35, .3])
    box(object, [0, 1.15, 0], [.5, .6, .28])
    box(object, [-.15, .43, 0], [.19, .85, .22], object.pose * .4)
    box(object, [.15, .43, 0], [.19, .85, .22], -object.pose * .4)
    box(object, [-.36, 1.12, 0], [.16, .65, .18], object.pose)
    box(object, [.36, 1.12, 0], [.16, .65, .18], -object.pose)
  })
  polygons.sort((a, b) => b.depth - a.depth).forEach((face) => {
    ctx.beginPath(); face.points.forEach((p, index) => { if (!index) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y) }); ctx.closePath()
    ctx.fillStyle = face.color; ctx.fill(); ctx.fillStyle = `rgba(0,0,0,${face.shade})`; ctx.fill(); ctx.strokeStyle = '#27273522'; ctx.stroke()
  })
}
