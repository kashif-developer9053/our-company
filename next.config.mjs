/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false, // Phaser manages its own lifecycle; avoid double-mount in dev
};

export default nextConfig;
