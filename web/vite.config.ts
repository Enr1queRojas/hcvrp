import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  // Rutas relativas: la misma compilación sirve en la raíz o bajo un prefijo (/rutas/).
  base: "./",
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
