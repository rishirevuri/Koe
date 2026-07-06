import { defineConfig } from "vite";
import { fileURLToPath, URL } from "node:url";

// Koe is a multi-page app (landing + dashboard + product workspace). Vite only
// builds index.html by default, so the other pages are declared as explicit
// inputs; otherwise they would be missing from the Vercel deployment. Output
// goes to the default "dist" folder, which is what Vercel serves when the root
// directory is set to Frontend.
export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL("./index.html", import.meta.url)),
        dashboard: fileURLToPath(new URL("./dashboard.html", import.meta.url)),
        product: fileURLToPath(new URL("./product.html", import.meta.url)),
      },
    },
  },
});
