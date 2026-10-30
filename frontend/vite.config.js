import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api, /admin and Django's /static go to the Django server on port 8000
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/admin": "http://127.0.0.1:8000",
      "/static": "http://127.0.0.1:8000",
    },
  },
});
