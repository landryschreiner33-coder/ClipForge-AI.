import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the UI runs on :5173 and proxies API calls to the Python backend.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 800 },
});
