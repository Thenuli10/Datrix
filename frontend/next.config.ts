import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The dev badge would show up in dashboard QA screenshots and be flagged as clutter.
  devIndicators: false,
  // Standalone server output for the Docker image.
  output: "standalone",
};

export default nextConfig;
