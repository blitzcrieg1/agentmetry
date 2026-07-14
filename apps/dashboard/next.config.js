/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export: `next build` emits a self-contained `out/` the orchestrator
  // serves directly, collapsing Agentmetry to a single process. Dev still runs
  // via `next dev` on :3000 against the orchestrator on :8000.
  output: "export",
  images: { unoptimized: true },
};

module.exports = nextConfig;
