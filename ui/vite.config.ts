import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy /ws to a running bridge so the app talks to its own origin,
// exactly as it does when the bridge serves it in production.
const bridge = process.env.STYRI_BRIDGE ?? "127.0.0.1:8080";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: `ws://${bridge}`, ws: true },
    },
  },
  build: {
    // Everything ships inside the image; no CDN, no external requests.
    assetsInlineLimit: 0,
    sourcemap: false,
  },
});
