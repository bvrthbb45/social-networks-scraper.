import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the browser only talks to the Vite server (one origin). It forwards /api/* to the
// FastAPI backend with the prefix removed, so the httpOnly refresh cookie stays first-party.
// The backend must then set REFRESH_COOKIE_PATH=/api/auth (see .env.example).
const backend = process.env.API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": { target: backend, rewrite: (path) => path.replace(/^\/api/, "") } },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["tests/setup.ts"], css: false },
});
