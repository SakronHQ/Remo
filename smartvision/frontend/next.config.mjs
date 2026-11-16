/** @type {import('next').NextConfig} */
const backendHttpUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendHttpUrl}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
