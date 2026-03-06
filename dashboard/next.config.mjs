/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const gateway =
      process.env.GATEWAY_INTERNAL_URL ||
      process.env.NEXT_PUBLIC_GATEWAY_URL ||
      "http://gateway-service:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${gateway}/:path*`,
      },
    ];
  },
};

export default nextConfig;
