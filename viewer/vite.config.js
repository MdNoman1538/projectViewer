import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run dev` serves the UI with hot reload and forwards /api to `projectviewer serve` (port 8765).
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  build: { outDir: "dist", chunkSizeWarningLimit: 2000, sourcemap: false },
});
