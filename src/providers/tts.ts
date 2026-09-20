import type { Provider, RunContext } from "../types";

// ---------------------------------------------------------------------------
// Text-to-speech providers, ordered free -> paid.
// ---------------------------------------------------------------------------

function trim(s: string, n = 300) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

const apiKeyField = (placeholder: string) => ({
  key: "apiKey",
  label: "API Key",
  type: "password" as const,
  placeholder,
});

export const ttsProviders: Provider[] = [
  {
    id: "webspeech",
    name: "Browser Web Speech",
    kind: "tts",
    tier: "free",
    note: "No key • preview only (can't export a file)",
    secrets: [],
    params: [
      // Voice options are populated at runtime from the browser's voice list;
      // the select falls back to a free-text field if none are found.
      { key: "voice", label: "Voice", type: "text", placeholder: "System default", default: "" },
      { key: "rate", label: "Rate", type: "number", default: "1", placeholder: "1" },
    ],
    async runTts(text, ctx) {
      const synth = window.speechSynthesis;
      if (!synth) throw new Error("This browser has no speechSynthesis support.");
      const voiceName = ctx.config.voice?.trim();
      const rate = parseFloat(ctx.config.rate || "1") || 1;
      const speak = () => {
        synth.cancel();
        const u = new SpeechSynthesisUtterance(text);
        u.rate = rate;
        const voices = synth.getVoices();
        const match = voices.find((v) => v.name === voiceName);
        if (match) u.voice = match;
        synth.speak(u);
      };
      speak();
      return { url: null, playbackOnly: true, play: speak };
    },
  },
  {
    id: "edgetts",
    name: "Edge-TTS (Microsoft voices)",
    kind: "tts",
    tier: "free",
    note: "Realistic • needs Phase-2 backend",
    needsBackend: true,
    secrets: [],
    params: [
      { key: "voice", label: "Voice", type: "text", default: "en-US-AriaNeural", placeholder: "en-US-AriaNeural" },
    ],
    async runTts(text, ctx) {
      const res = await fetch("/render/tts", {
        method: "POST",
        signal: ctx.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, voice: ctx.config.voice || "en-US-AriaNeural" }),
      });
      if (!res.ok) {
        throw new Error(
          "Edge-TTS backend not reachable. Start the Phase-2 backend (Python FastAPI) to use this provider.",
        );
      }
      const buf = await res.blob();
      return { url: URL.createObjectURL(buf), playbackOnly: false };
    },
  },
  {
    id: "elevenlabs",
    name: "ElevenLabs",
    kind: "tts",
    tier: "freemium",
    note: "Free monthly quota",
    signupUrl: "https://elevenlabs.io/app/settings/api-keys",
    secrets: [apiKeyField("ElevenLabs key")],
    params: [
      { key: "voiceId", label: "Voice ID", type: "text", default: "21m00Tcm4TlvDq8ikWAM", placeholder: "voice id" },
      {
        key: "model",
        label: "Model",
        type: "select",
        options: [
          { value: "eleven_multilingual_v2", label: "eleven_multilingual_v2" },
          { value: "eleven_flash_v2_5", label: "eleven_flash_v2_5 (fast)" },
        ],
        default: "eleven_multilingual_v2",
      },
    ],
    async runTts(text, ctx) {
      const apiKey = ctx.config.apiKey?.trim();
      if (!apiKey) throw new Error("Missing ElevenLabs key — add it in Settings › API Keys.");
      const voiceId = ctx.config.voiceId?.trim() || "21m00Tcm4TlvDq8ikWAM";
      const res = await fetch(`/api/elevenlabs/v1/text-to-speech/${voiceId}`, {
        method: "POST",
        signal: ctx.signal,
        headers: { "Content-Type": "application/json", "xi-api-key": apiKey, Accept: "audio/mpeg" },
        body: JSON.stringify({ text, model_id: ctx.config.model || "eleven_multilingual_v2" }),
      });
      if (!res.ok) {
        const raw = await res.text();
        throw new Error(`${res.status} — ${trim(raw)}`);
      }
      const buf = await res.blob();
      return { url: URL.createObjectURL(buf), playbackOnly: false };
    },
  },
  {
    id: "openai-tts",
    name: "OpenAI TTS",
    kind: "tts",
    tier: "paid",
    signupUrl: "https://platform.openai.com/api-keys",
    secrets: [apiKeyField("sk-…")],
    params: [
      {
        key: "voice",
        label: "Voice",
        type: "select",
        options: ["alloy", "echo", "fable", "onyx", "nova", "shimmer"].map((v) => ({ value: v, label: v })),
        default: "alloy",
      },
      {
        key: "model",
        label: "Model",
        type: "select",
        options: [
          { value: "gpt-4o-mini-tts", label: "gpt-4o-mini-tts" },
          { value: "tts-1", label: "tts-1" },
          { value: "tts-1-hd", label: "tts-1-hd" },
        ],
        default: "gpt-4o-mini-tts",
      },
    ],
    async runTts(text, ctx) {
      const apiKey = ctx.config.apiKey?.trim();
      if (!apiKey) throw new Error("Missing OpenAI key — add it in Settings › API Keys.");
      const res = await fetch("/api/openai/v1/audio/speech", {
        method: "POST",
        signal: ctx.signal,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({
          model: ctx.config.model || "gpt-4o-mini-tts",
          voice: ctx.config.voice || "alloy",
          input: text,
        }),
      });
      if (!res.ok) {
        const raw = await res.text();
        throw new Error(`${res.status} — ${trim(raw)}`);
      }
      const buf = await res.blob();
      return { url: URL.createObjectURL(buf), playbackOnly: false };
    },
  },
];
