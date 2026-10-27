import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    // /assets занят ассетами историй (их раздаёт Caddy с диска), поэтому бандл — в /static
    assetsDir: "static",
  },
  server: {
    proxy: { "/api": "http://localhost:8000", "/assets": "http://localhost:8000" },
  },
});
