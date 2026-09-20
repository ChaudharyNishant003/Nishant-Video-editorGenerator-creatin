import type { Provider, RunContext } from "../types";

// ---------------------------------------------------------------------------
// Text / LLM providers, ordered free -> paid.
// All requests go through the Vite dev proxy (see vite.config.ts) so there are
// no CORS problems and keys stay on localhost.
// ---------------------------------------------------------------------------

const MODEL_HELP = "Model name — edit if a newer/older one is available on your plan.";

async function openaiCompatible(
  endpoint: string,
  ctx: RunContext,
  system: string,
  user: string,
  extraHeaders: Record<string, string> = {},
): Promise<string> {
  const { config, signal } = ctx;
  const apiKey = config.apiKey?.trim();
  if (!apiKey) throw new Error("Missing API key — add it in Settings › API Keys.");
  const model = config.model?.trim();
  const res = await fetch(endpoint, {
    method: "POST",
    signal,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
      ...extraHeaders,
    },
    body: JSON.stringify({
      model,
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
      temperature: 0.85,
    }),
  });
  const raw = await res.text();
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${trim(raw)}`);
  const data = JSON.parse(raw);
  const text = data?.choices?.[0]?.message?.content;
  if (!text) throw new Error(`No text returned. Response: ${trim(raw)}`);
  return text;
}

function trim(s: string, n = 300) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

const modelField = (options: { value: string; label: string }[]) => ({
  key: "model",
  label: "Model",
  type: "select" as const,
  options,
  default: options[0].value,
  help: MODEL_HELP,
});

const apiKeyField = (placeholder: string) => ({
  key: "apiKey",
  label: "API Key",
  type: "password" as const,
  placeholder,
});

export const llmProviders: Provider[] = [
  {
    id: "gemini",
    name: "Google Gemini (AI Studio)",
    kind: "llm",
    tier: "free",
    note: "Generous free tier",
    signupUrl: "https://aistudio.google.com/app/apikey",
    secrets: [apiKeyField("AIza…")],
    params: [
      modelField([
        { value: "gemini-2.0-flash", label: "gemini-2.0-flash (fast, free)" },
        { value: "gemini-2.5-flash", label: "gemini-2.5-flash" },
        { value: "gemini-1.5-flash", label: "gemini-1.5-flash" },
        { value: "gemini-1.5-pro", label: "gemini-1.5-pro" },
      ]),
    ],
    async runLlm(system, user, ctx) {
      const { config, signal } = ctx;
      const key = config.apiKey?.trim();
      if (!key) throw new Error("Missing API key — add it in Settings › API Keys.");
      const model = config.model?.trim() || "gemini-2.0-flash";
      const res = await fetch(
        `/api/gemini/v1beta/models/${model}:generateContent?key=${encodeURIComponent(key)}`,
        {
          method: "POST",
          signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            systemInstruction: { parts: [{ text: system }] },
            contents: [{ role: "user", parts: [{ text: user }] }],
            generationConfig: { temperature: 0.85 },
          }),
        },
      );
      const raw = await res.text();
      if (!res.ok) throw new Error(`${res.status} — ${trim(raw)}`);
      const data = JSON.parse(raw);
      const text = data?.candidates?.[0]?.content?.parts?.map((p: any) => p.text).join("") ?? "";
      if (!text) throw new Error(`No text returned. Response: ${trim(raw)}`);
      return { text };
    },
  },
  {
    id: "groq",
    name: "Groq",
    kind: "llm",
    tier: "free",
    note: "Very fast, free tier",
    signupUrl: "https://console.groq.com/keys",
    secrets: [apiKeyField("gsk_…")],
    params: [
      modelField([
        { value: "llama-3.3-70b-versatile", label: "llama-3.3-70b-versatile" },
        { value: "llama-3.1-8b-instant", label: "llama-3.1-8b-instant (fastest)" },
        { value: "gemma2-9b-it", label: "gemma2-9b-it" },
        { value: "deepseek-r1-distill-llama-70b", label: "deepseek-r1-distill-llama-70b" },
      ]),
    ],
    async runLlm(system, user, ctx) {
      return { text: await openaiCompatible("/api/groq/openai/v1/chat/completions", ctx, system, user) };
    },
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    kind: "llm",
    tier: "freemium",
    note: "Many :free models; also paid",
    signupUrl: "https://openrouter.ai/keys",
    secrets: [apiKeyField("sk-or-…")],
    params: [
      {
        key: "model",
        label: "Model",
        type: "text",
        default: "meta-llama/llama-3.3-70b-instruct:free",
        placeholder: "vendor/model[:free]",
        help: "Browse models at openrouter.ai/models. Append :free for free variants.",
      },
    ],
    async runLlm(system, user, ctx) {
      return {
        text: await openaiCompatible("/api/openrouter/api/v1/chat/completions", ctx, system, user, {
          "HTTP-Referer": "http://localhost:5173",
          "X-Title": "AI YT Studio",
        }),
      };
    },
  },
  {
    id: "deepseek",
    name: "DeepSeek",
    kind: "llm",
    tier: "paid",
    note: "Low cost",
    signupUrl: "https://platform.deepseek.com/api_keys",
    secrets: [apiKeyField("sk-…")],
    params: [
      modelField([
        { value: "deepseek-chat", label: "deepseek-chat" },
        { value: "deepseek-reasoner", label: "deepseek-reasoner" },
      ]),
    ],
    async runLlm(system, user, ctx) {
      return { text: await openaiCompatible("/api/deepseek/chat/completions", ctx, system, user) };
    },
  },
  {
    id: "together",
    name: "Together AI",
    kind: "llm",
    tier: "freemium",
    note: "Free credits on signup",
    signupUrl: "https://api.together.xyz/settings/api-keys",
    secrets: [apiKeyField("Together key")],
    params: [
      {
        key: "model",
        label: "Model",
        type: "text",
        default: "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
        placeholder: "vendor/model",
        help: MODEL_HELP,
      },
    ],
    async runLlm(system, user, ctx) {
      return { text: await openaiCompatible("/api/together/v1/chat/completions", ctx, system, user) };
    },
  },
  {
    id: "openai",
    name: "OpenAI",
    kind: "llm",
    tier: "paid",
    signupUrl: "https://platform.openai.com/api-keys",
    secrets: [apiKeyField("sk-…")],
    params: [
      modelField([
        { value: "gpt-4o-mini", label: "gpt-4o-mini (cheap)" },
        { value: "gpt-4o", label: "gpt-4o" },
        { value: "gpt-4.1-mini", label: "gpt-4.1-mini" },
      ]),
    ],
    async runLlm(system, user, ctx) {
      return { text: await openaiCompatible("/api/openai/v1/chat/completions", ctx, system, user) };
    },
  },
  {
    id: "anthropic",
    name: "Anthropic Claude",
    kind: "llm",
    tier: "paid",
    signupUrl: "https://console.anthropic.com/settings/keys",
    secrets: [apiKeyField("sk-ant-…")],
    params: [
      modelField([
        { value: "claude-3-5-haiku-latest", label: "claude-3-5-haiku (cheap)" },
        { value: "claude-3-5-sonnet-latest", label: "claude-3-5-sonnet" },
      ]),
    ],
    async runLlm(system, user, ctx) {
      const { config, signal } = ctx;
      const apiKey = config.apiKey?.trim();
      if (!apiKey) throw new Error("Missing API key — add it in Settings › API Keys.");
      const res = await fetch("/api/anthropic/v1/messages", {
        method: "POST",
        signal,
        headers: {
          "Content-Type": "application/json",
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
          "anthropic-dangerous-direct-browser-access": "true",
        },
        body: JSON.stringify({
          model: config.model?.trim() || "claude-3-5-haiku-latest",
          max_tokens: 4096,
          system,
          messages: [{ role: "user", content: user }],
        }),
      });
      const raw = await res.text();
      if (!res.ok) throw new Error(`${res.status} — ${trim(raw)}`);
      const data = JSON.parse(raw);
      const text = data?.content?.map((c: any) => c.text).join("") ?? "";
      if (!text) throw new Error(`No text returned. Response: ${trim(raw)}`);
      return { text };
    },
  },
];
