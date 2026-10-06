import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Dev: the browser talks to the Vite server only (same origin), which forwards
// /api/* to the FastAPI backend. That keeps the refresh cookie first-party; set
// REFRESH_COOKIE_PATH=/api/auth on the backend (see .env.example).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: process.env.API_URL ?? "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["tests/setup.ts"],
    css: false,
  },
});
