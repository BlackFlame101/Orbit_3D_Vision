const nextConfig = {
  // Keep local builds modest on the same laptop used for reconstruction.
  experimental: {cpus: 1},
  async rewrites() {
    return [{source: '/api/orbit/:path*', destination: 'http://127.0.0.1:8000/:path*'}];
  },
};
export default nextConfig;
