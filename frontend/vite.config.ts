import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));

// Dev: the v2 UI on :5174 proxies /api and /media to the v2 backend on :8001.
// Production: the FastAPI backend serves frontend/dist itself (single service, same origin).
export default defineConfig({
  root,
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8001", changeOrigin: false },
      "/media": { target: "http://127.0.0.1:8001", changeOrigin: false },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
