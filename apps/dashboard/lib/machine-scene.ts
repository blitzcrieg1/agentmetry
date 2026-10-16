/** Layout and projection for the This machine 3D host. No DOM. */

export type Vec3 = { x: number; y: number; z: number };

export type SceneAgent = {
  name: string;
  state: "covered" | "uncovered" | "absent" | "unknown";
};

export type LaidOut = SceneAgent & { position: Vec3 };

export type Projected = {
  x: number;
  y: number;
  scale: number;
  depth: number;
};

const RING = 1.35;
const CAMERA = 3.4;

export function rotate(point: Vec3, yaw: number, pitch: number): Vec3 {
  const cosY = Math.cos(yaw);
  const sinY = Math.sin(yaw);
  const x1 = point.x * cosY - point.z * sinY;
  const z1 = point.x * sinY + point.z * cosY;
  const cosP = Math.cos(pitch);
  const sinP = Math.sin(pitch);
  return {
    x: x1,
    y: point.y * cosP - z1 * sinP,
    z: point.y * sinP + z1 * cosP,
  };
}

export function project(point: Vec3, width: number, height: number, camera = CAMERA): Projected {
  const depth = point.z + camera;
  const scale = camera / Math.max(0.4, depth);
  const span = Math.min(width, height) * 0.32;
  return {
    x: width / 2 + point.x * span * scale,
    y: height / 2 + point.y * span * scale,
    scale,
    depth,
  };
}

export function layoutAgents(agents: SceneAgent[]): LaidOut[] {
  const n = agents.length;
  if (n === 0) return [];
  return agents.map((agent, index) => {
    const angle = (index / n) * Math.PI * 2 - Math.PI / 2;
    const radius = agent.state === "absent" ? RING * 1.35 : RING;
    const lift = agent.state === "uncovered" ? 0.22 : agent.state === "absent" ? -0.18 : 0;
    return {
      ...agent,
      position: {
        x: Math.cos(angle) * radius,
        y: lift,
        z: Math.sin(angle) * radius,
      },
    };
  });
}

export function hitAgent(
  agents: LaidOut[],
  yaw: number,
  pitch: number,
  width: number,
  height: number,
  pointerX: number,
  pointerY: number,
  threshold = 28,
): string | null {
  let best: { name: string; dist: number; depth: number } | null = null;
  for (const agent of agents) {
    const drawn = project(rotate(agent.position, yaw, pitch), width, height);
    const dx = drawn.x - pointerX;
    const dy = drawn.y - pointerY;
    const dist = Math.hypot(dx, dy);
    const radius = threshold * drawn.scale;
    if (dist > radius) continue;
    if (!best || drawn.depth < best.depth || (drawn.depth === best.depth && dist < best.dist)) {
      best = { name: agent.name, dist, depth: drawn.depth };
    }
  }
  return best?.name ?? null;
}

export function cubeVertices(center: Vec3, size: number): Vec3[] {
  const h = size / 2;
  const corners: Vec3[] = [];
  for (const x of [-h, h]) {
    for (const y of [-h, h]) {
      for (const z of [-h, h]) {
        corners.push({ x: center.x + x, y: center.y + y, z: center.z + z });
      }
    }
  }
  return corners;
}

/** Faces as 4-index groups into cubeVertices order (x,y,z nested). */
export const CUBE_FACES: number[][] = [
  [0, 1, 3, 2],
  [4, 6, 7, 5],
  [0, 4, 5, 1],
  [2, 3, 7, 6],
  [0, 2, 6, 4],
  [1, 5, 7, 3],
];
