import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// All third-party API calls are routed through these dev-server proxies so the
// browser never makes cross-origin requests directly. This eliminates CORS
// problems for providers (Groq, OpenAI, etc.) that don't send CORS headers, and
// keeps the app "browser-only" for Phase 1 — no separate proxy server to run.
//
// The Phase-2 render backend (Edge-TTS + MoviePy) will be proxied under /render.
function proxyTarget(target: string) {
  return {
    target,
    changeOrigin: true,
    secure: true,
    // Strip the /api/<name> prefix before forwarding upstream.
    rewrite: (path: string) => path.replace(/^\/api\/[^/]+/, ""),
  };
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api/gemini": proxyTarget("https://generativelanguage.googleapis.com"),
      "/api/groq": proxyTarget("https://api.groq.com"),
      "/api/openrouter": proxyTarget("https://openrouter.ai"),
      "/api/openai": proxyTarget("https://api.openai.com"),
      "/api/deepseek": proxyTarget("https://api.deepseek.com"),
      "/api/together": proxyTarget("https://api.together.xyz"),
      "/api/anthropic": proxyTarget("https://api.anthropic.com"),
      "/api/hf": proxyTarget("https://api-inference.huggingface.co"),
      "/api/pollinations": proxyTarget("https://image.pollinations.ai"),
      "/api/elevenlabs": proxyTarget("https://api.elevenlabs.io"),
      "/api/stability": proxyTarget("https://api.stability.ai"),
      "/api/gtts": proxyTarget("https://texttospeech.googleapis.com"),
      // Video-generation providers (all credit-based).
      "/api/fal": proxyTarget("https://fal.run"),
      "/api/replicate": proxyTarget("https://api.replicate.com"),
      "/api/luma": proxyTarget("https://api.lumalabs.ai"),
      "/api/runway": proxyTarget("https://api.dev.runwayml.com"),
      "/api/minimax": proxyTarget("https://api.minimaxi.chat"),
      // Phase-2 backend (FastAPI). Harmless if the backend isn't running yet.
      "/render": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
