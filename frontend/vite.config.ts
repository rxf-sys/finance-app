import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vitest/config";

// Working name of the app; the final name is not decided yet. This is the single
// place to change it: manifest, <title> and the iOS home screen title use it.
const APP_NAME = "Finanzen";
const THEME_COLOR = "#4b3fbf";
// Light `--background` token from src/index.css.
const BACKGROUND_COLOR = "#f7f6f2";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: "app-name-html",
      transformIndexHtml: (html) => html.replaceAll("%APP_NAME%", APP_NAME),
    },
    VitePWA({
      strategies: "generateSW",
      registerType: "autoUpdate",
      // External registerSW.js: the CSP (script-src 'self') forbids inline scripts.
      injectRegister: "script",
      // The Cloudflare Access cookie is needed for the manifest fetch as well.
      useCredentials: true,
      integration: {
        // The plugin adds manifest.webmanifest (and duplicate icon entries) to the
        // precache; the glob already covers the icons and the manifest must stay fresh.
        beforeBuildServiceWorker: (options) => {
          options.workbox.additionalManifestEntries = [];
        },
      },
      manifest: {
        name: APP_NAME,
        short_name: APP_NAME,
        description: "Haushaltsfinanzen: Konten, Verträge, Budgets",
        lang: "de",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: BACKGROUND_COLOR,
        theme_color: THEME_COLOR,
        icons: [
          { src: "pwa-192x192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "pwa-512x512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          {
            src: "pwa-maskable-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // Static assets only. No html: navigations must always hit the network so
        // Cloudflare Access can redirect to its login when the session has expired.
        globPatterns: ["**/*.{js,css,svg,png,woff2}"],
        globIgnores: ["registerSW.js"],
        navigateFallback: null,
        runtimeCaching: [],
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        skipWaiting: true,
        // Web Push handlers (public/push-sw.js) run inside the generated service worker.
        importScripts: ["push-sw.js"],
      },
    }),
  ],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
  test: {
    environment: "node",
  },
});
