/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/orchestrator/:path*",
        destination: "http://localhost:8000/api/v1/:path*",
      },
    ];
  },
};

module.exports = nextConfig;
