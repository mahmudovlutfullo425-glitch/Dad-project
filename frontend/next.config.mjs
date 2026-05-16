/** @type {import('next').NextConfig} */
const nextConfig = {
  // `standalone` emits a self-contained `.next/standalone/server.js` that
  // pulls in only the node_modules it actually needs. Final runtime image
  // is ~150 MB instead of dragging the full dev dependency tree.
  output: "standalone",
  reactStrictMode: true,
  // We render no remote images today (everything is text + Tailwind).
  // Keep this empty to satisfy the linter without enabling a remote
  // loader that would surprise reviewers.
  images: { remotePatterns: [] },
};

export default nextConfig;
