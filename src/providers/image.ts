import type { Provider, RunContext } from "../types";

// ---------------------------------------------------------------------------
// Image providers, ordered free -> paid.
// ---------------------------------------------------------------------------

function trim(s: string, n = 300) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

async function blobToObjectUrl(res: Response): Promise<string> {
  const buf = await res.blob();
  return URL.createObjectURL(buf);
}

const apiKeyField = (placeholder: string) => ({
  key: "apiKey",
  label: "API Key",
  type: "password" as const,
  placeholder,
});

export const imageProviders: Provider[] = [
  {
    id: "pollinations",
    name: "Pollinations.ai",
    kind: "image",
    tier: "free",
    note: "No key needed",
    signupUrl: "https://pollinations.ai",
    secrets: [],
    params: [
      {
        key: "model",
        label: "Model",
        type: "select",
        options: [
          { value: "flux", label: "flux (best quality)" },
          { value: "turbo", label: "turbo (fastest)" },
        ],
        default: "flux",
      },
    ],
    async runImage(prompt, ctx) {
      const { config, width, height } = ctx;
      const model = config.model || "flux";
      const seed = Math.floor(Math.random() * 1_000_000);
      // Direct remote URL — displayable via <img> with no CORS requirement.
      const url =
        `https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}` +
        `?width=${width}&height=${height}&seed=${seed}&nologo=true&model=${model}`;
      return { url, remote: true };
    },
  },
  {
    id: "huggingface",
    name: "Hugging Face (FLUX)",
    kind: "image",
    tier: "freemium",
    note: "Free tier w/ key",
    signupUrl: "https://huggingface.co/settings/tokens",
    secrets: [apiKeyField("hf_…")],
    params: [
      {
        key: "model",
        label: "Model",
        type: "text",
        default: "black-forest-labs/FLUX.1-schnell",
        placeholder: "org/model",
      },
    ],
    async runImage(prompt, ctx) {
      const { config, signal, width, height } = ctx;
      const apiKey = config.apiKey?.trim();
      if (!apiKey) throw new Error("Missing Hugging Face token — add it in Settings › API Keys.");
      const model = config.model?.trim() || "black-forest-labs/FLUX.1-schnell";
      const res = await fetch(`/api/hf/models/${model}`, {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({ inputs: prompt, parameters: { width, height } }),
      });
      if (!res.ok) {
        const raw = await res.text();
        throw new Error(`${res.status} — ${trim(raw)} (model may be cold-loading; retry in ~20s)`);
      }
      return { url: await blobToObjectUrl(res), remote: false };
    },
  },
  {
    id: "together-image",
    name: "Together AI (FLUX)",
    kind: "image",
    tier: "freemium",
    note: "Free FLUX.1-schnell",
    signupUrl: "https://api.together.xyz/settings/api-keys",
    secrets: [apiKeyField("Together key")],
    params: [
      {
        key: "model",
        label: "Model",
        type: "text",
        default: "black-forest-labs/FLUX.1-schnell-Free",
        placeholder: "org/model",
      },
    ],
    async runImage(prompt, ctx) {
      const { config, signal, width, height } = ctx;
      const apiKey = config.apiKey?.trim();
      if (!apiKey) throw new Error("Missing Together key — add it in Settings › API Keys.");
      const res = await fetch("/api/together/v1/images/generations", {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({
          model: config.model?.trim() || "black-forest-labs/FLUX.1-schnell-Free",
          prompt,
          width,
          height,
          n: 1,
          response_format: "b64_json",
        }),
      });
      const raw = await res.text();
      if (!res.ok) throw new Error(`${res.status} — ${trim(raw)}`);
      const data = JSON.parse(raw);
      const b64 = data?.data?.[0]?.b64_json;
      const remoteUrl = data?.data?.[0]?.url;
      if (b64) return { url: `data:image/png;base64,${b64}`, remote: false };
      if (remoteUrl) return { url: remoteUrl, remote: true };
      throw new Error(`No image returned. Response: ${trim(raw)}`);
    },
  },
  {
    id: "stability",
    name: "Stability AI",
    kind: "image",
    tier: "paid",
    signupUrl: "https://platform.stability.ai/account/keys",
    secrets: [apiKeyField("sk-…")],
    params: [
      {
        key: "model",
        label: "Endpoint",
        type: "select",
        options: [
          { value: "core", label: "Stable Image Core" },
          { value: "ultra", label: "Stable Image Ultra" },
        ],
        default: "core",
      },
    ],
    async runImage(prompt, ctx) {
      const { config, signal, inputs } = ctx;
      const apiKey = config.apiKey?.trim();
      if (!apiKey) throw new Error("Missing Stability key — add it in Settings › API Keys.");
      const endpoint = config.model === "ultra" ? "ultra" : "core";
      const form = new FormData();
      form.append("prompt", prompt);
      form.append("output_format", "png");
      form.append("aspect_ratio", inputs.dimensions);
      const res = await fetch(`/api/stability/v2beta/stable-image/generate/${endpoint}`, {
        method: "POST",
        signal,
        headers: { Authorization: `Bearer ${apiKey}`, Accept: "image/*" },
        body: form,
      });
      if (!res.ok) {
        const raw = await res.text();
        throw new Error(`${res.status} — ${trim(raw)}`);
      }
      return { url: await blobToObjectUrl(res), remote: false };
    },
  },
  {
    id: "openai-image",
    name: "OpenAI (gpt-image-1)",
    kind: "image",
    tier: "paid",
    signupUrl: "https://platform.openai.com/api-keys",
    secrets: [apiKeyField("sk-…")],
    params: [
      {
        key: "model",
        label: "Model",
        type: "select",
        options: [
          { value: "gpt-image-1", label: "gpt-image-1" },
          { value: "dall-e-3", label: "dall-e-3" },
        ],
        default: "gpt-image-1",
      },
    ],
    async runImage(prompt, ctx) {
      const { config, signal, inputs } = ctx;
      const apiKey = config.apiKey?.trim();
      if (!apiKey) throw new Error("Missing OpenAI key — add it in Settings › API Keys.");
      const size =
        inputs.dimensions === "9:16" ? "1024x1536" : inputs.dimensions === "1:1" ? "1024x1024" : "1536x1024";
      const res = await fetch("/api/openai/v1/images/generations", {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({ model: config.model || "gpt-image-1", prompt, size, n: 1 }),
      });
      const raw = await res.text();
      if (!res.ok) throw new Error(`${res.status} — ${trim(raw)}`);
      const data = JSON.parse(raw);
      const b64 = data?.data?.[0]?.b64_json;
      const url = data?.data?.[0]?.url;
      if (b64) return { url: `data:image/png;base64,${b64}`, remote: false };
      if (url) return { url, remote: true };
      throw new Error(`No image returned. Response: ${trim(raw)}`);
    },
  },
];
