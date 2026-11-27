import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const uiRoot = dirname(fileURLToPath(import.meta.url));
const uiNodeModules = resolve(uiRoot, "node_modules");
const repositoryRoot = resolve(uiRoot, "../..");

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      react: resolve(uiNodeModules, "react"),
      "@testing-library": resolve(uiNodeModules, "@testing-library"),
      "react-router-dom": resolve(uiNodeModules, "react-router-dom"),
    },
  },
  test: {
    environment: "jsdom",
    include: ["../../tests/ui/**/*.{test,spec}.{js,jsx,ts,tsx}"],
    setupFiles: ["../../tests/ui/setup.js"],
  },
  server: {
    fs: { allow: [uiRoot, resolve(repositoryRoot, "tests/ui"), resolve(uiRoot, "src")] },
    proxy: {
      "/api": {
        target: process.env.API_PROXY_TARGET || "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});