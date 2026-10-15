import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// The window's UI. Built to dist/ and loaded from file:// by electron/main.js.
export default defineConfig({
  root: "renderer",
  base: "./",
  plugins: [react(), tailwindcss()],
  build: { outDir: "../dist", emptyOutDir: true },
});
