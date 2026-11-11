import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, "HOSHI_API_PROXY_TARGET");

  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: env.HOSHI_API_PROXY_TARGET || "http://127.0.0.1:8080",
          changeOrigin: true,
        },
      },
    },
  };
});
