import type { NextConfig } from "next";

// O navegador fala só com o domínio do site: /api/* é repassado ao FastAPI. Assim os cookies de
// sessão ficam no domínio do site (o proxy.ts consegue vê-los) e o CORS deixa de ser necessário.
// Lido no build: na Vercel, BACKEND_URL precisa existir antes do deploy.
const backendUrl = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/:path*` }];
  },
  experimental: {
    agentFeedback: true,
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
