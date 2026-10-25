import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A second dev stack needs its own build folder, or Next refuses to start beside the first.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  // Hide the floating Next.js dev-tools button: in screenshots and demos it reads as the site's logo.
  devIndicators: false,
  // The browser only ever talks to this origin; Next forwards /api/* to the FastAPI server.
  // That is why there is no CORS configuration anywhere.
  async rewrites() {
    // BACKEND_URL lets a second dev stack (scratch DB, other port) run beside the real one.
    const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  // The editors live under Create now; old links and bookmarks (with their ?mine=) still land.
  async redirects() {
    return [
      { source: "/algos/editor", destination: "/create/editor", permanent: false },
      { source: "/algos/blocks", destination: "/create/blocks", permanent: false },
    ];
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
