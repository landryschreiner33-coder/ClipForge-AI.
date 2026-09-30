import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the UI runs on :5173 and proxies API calls to the Python backend (CLIPFOUNDRY_API: another backend,
// such as the e2e sandbox).
const backend = process.env.CLIPFOUNDRY_API || "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": backend, "/legal": backend } },
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 800 },
});
