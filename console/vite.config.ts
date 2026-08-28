import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The console is a single fixed viewport (1920×1080, no scrolling).
// /api is proxied to the fleet's FastAPI app (SSE included).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.FLEET_API ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
