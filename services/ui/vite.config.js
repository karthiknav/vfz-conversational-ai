import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  server: {
    port: 8080,
    strictPort: true,
  },
  preview: {
    port: 8080,
    strictPort: true,
  },
});
