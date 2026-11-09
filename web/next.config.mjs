/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      // RBX short alias per spec: /rbxshort shows the Roblox short studio
      { source: '/rbxshort', destination: '/rbxshort' },
    ];
  },
  // Vercel needs 0.0.0.0 + preview host allowed
  experimental: {},
};
export default nextConfig;
