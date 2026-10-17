import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In development, API calls are proxied to the FastAPI backend (uvicorn on :8000).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000", "/mcp": "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist", chunkSizeWarningLimit: 1600 },
});
