import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxyTarget = env.VITE_DEV_PROXY_TARGET || "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 4173,
      proxy: {
        "/v1": proxyTarget,
        "/health": proxyTarget,
        "/docs": proxyTarget,
        "/api.json": proxyTarget,
      },
    },
    preview: {
      host: "0.0.0.0",
      port: 4173,
    },
  };
});
