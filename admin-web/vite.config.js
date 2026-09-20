import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Proxy /api to the backend during local development
    proxy: {
      "/docs": { target: process.env.API_TARGET || "http://localhost:8000" },
      "/redoc": { target: process.env.API_TARGET || "http://localhost:8000" },
      "/openapi.json": { target: process.env.API_TARGET || "http://localhost:8000" },
      "/health": { target: process.env.API_TARGET || "http://localhost:8000" },
      "/api": {
        target: process.env.API_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
