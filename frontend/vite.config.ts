import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5183,
    strictPort: true,
    // Im Browser gibt es nur eine Origin, deshalb braucht die API kein CORS.
    proxy: { "/api": "http://127.0.0.1:8010" },
  },
});
