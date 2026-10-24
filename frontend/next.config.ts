import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A second dev stack needs its own build folder, or Next refuses to start beside the first.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  // The browser only ever talks to this origin; Next forwards /api/* to the FastAPI server.
  // That is why there is no CORS configuration anywhere.
  async rewrites() {
    // BACKEND_URL lets a second dev stack (scratch DB, other port) run beside the real one.
    const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
