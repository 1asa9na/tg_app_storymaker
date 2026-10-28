import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    assetsDir: "static",
    // Чанк редактора сцен с Monaco весит ~3,7 МБ (900 КБ в gzip) и грузится только на его странице.
    chunkSizeWarningLimit: 4000,
  },
  server: {
    port: 5174,
    proxy: { "/api": "http://localhost:8000", "/assets": "http://localhost:8000" },
  },
});
