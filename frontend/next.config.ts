import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
