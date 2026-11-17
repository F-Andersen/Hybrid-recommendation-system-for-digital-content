import type { NextConfig } from "next";

const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: { proxyTimeout: 130_000 },
  // The browser only talks to Next.js; /api/* is forwarded to FastAPI (no CORS, first-party cookies).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};

export default nextConfig;
