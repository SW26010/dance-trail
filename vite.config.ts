import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: "webui",
  base: "/assets/",
  plugins: [react()],
  build: {
    outDir: "../dance_trail/webui_dist",
    emptyOutDir: true,
    assetsDir: "",
    sourcemap: false,
    rolldownOptions: {
      output: {
        // Python serves an explicit asset allow-list. If Vite starts emitting
        // chunks or CSS, update WEBUI_ASSET_CONTENT_TYPES and its route tests.
        entryFileNames: "app.js",
        assetFileNames: "app.[ext]",
        chunkFileNames: "chunk-[name].js"
      }
    }
  }
});
