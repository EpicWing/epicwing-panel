import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5183,
    strictPort: true,
    // The browser sees only one origin, so the API needs no CORS.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8010",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
