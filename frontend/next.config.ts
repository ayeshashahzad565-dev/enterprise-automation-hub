import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces a self-contained `.next/standalone` server (a minimal
  // `server.js` plus only the node_modules actually traced as used),
  // required for the lean, multi-stage production image
  // (frontend/Dockerfile) — this is additive: `next dev`/`next start`
  // (without Docker) behave exactly as before.
  output: "standalone",
};

export default nextConfig;
