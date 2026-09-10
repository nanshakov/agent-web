import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: { outDir: "../src/agent_web/ui", emptyOutDir: true },
  server: { proxy: { "/api": { target: "http://127.0.0.1:8765", ws: true } } },
});
