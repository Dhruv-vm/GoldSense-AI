import type { NextConfig } from "next";

const backendOrigin =
  process.env.BACKEND_API_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : "");

const nextConfig: NextConfig = {
  async rewrites() {
    if (!backendOrigin) return [];
    const cleanOrigin = backendOrigin.replace(/\/+$/, "");
    return [
      {
        source: "/api/:path*",
        destination: `${cleanOrigin}/api/:path*`,
      },
      {
        source: "/health",
        destination: `${cleanOrigin}/health`,
      },
    ];
  },
};

export default nextConfig;
