import type { Provider, RunContext } from "../types";

// ---------------------------------------------------------------------------
// Video-generation providers. Every option here runs on limited/trial credits
// (there is no reliable no-key free text-to-video API), so this stage is kept
// OUT of the auto-run pipeline — you trigger it per scene when you want motion.
//
// Two modes exist across providers:
//   - text->video : uses the scene's image prompt
//   - image->video: animates the scene's generated still (needs a *remote*
//                   image URL — Pollinations images work; blob: images don't)
// Ordered freemium -> paid.
// ---------------------------------------------------------------------------

function trim(s: string, n = 300) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function sleep(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });
}

/** Poll `step` until it returns {done:true, value}. */
async function poll<T>(
  step: () => Promise<{ done: boolean; value?: T }>,
  opts: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal },
): Promise<T> {
  const intervalMs = opts.intervalMs ?? 4000;
  const timeoutMs = opts.timeoutMs ?? 240000;
  const start = Date.now();
  // eslint-disable-next-line no-constant-condition
  while (true) {
    if (opts.signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const { done, value } = await step();
    if (done) return value as T;
    if (Date.now() - start > timeoutMs) {
      throw new Error("Timed out waiting for the clip (still rendering). Check the provider dashboard, then retry.");
    }
    await sleep(intervalMs, opts.signal);
  }
}

function requireRemoteImage(imageUrl: string | undefined): string {
  if (!imageUrl) {
    throw new Error("This provider animates a still — run Image Generation first so each scene has an image.");
  }
  if (imageUrl.startsWith("blob:") || imageUrl.startsWith("data:")) {
    throw new Error(
      "This provider needs a public image URL. Generate scene images with Pollinations (remote URLs) instead of Hugging Face/Together (local blobs).",
    );
  }
  return imageUrl;
}

const apiKeyField = (placeholder: string) => ({
  key: "apiKey",
  label: "API Key",
  type: "password" as const,
  placeholder,
});

const modeField = {
  key: "mode",
  label: "Mode",
  type: "select" as const,
  options: [
    { value: "text", label: "text → video (uses prompt)" },
    { value: "image", label: "image → video (animates still)" },
  ],
  default: "text",
};

export const videoProviders: Provider[] = [
  {
    id: "fal",
    name: "fal.ai",
    kind: "video",
    tier: "freemium",
    note: "Free signup credits • many models • fast",
    signupUrl: "https://fal.ai/dashboard/keys",
    secrets: [apiKeyField("fal key id:secret")],
    params: [
      {
        key: "model",
        label: "Model",
        type: "text",
        default: "fal-ai/ltx-video",
        placeholder: "fal-ai/…",
        help: "e.g. fal-ai/ltx-video, fal-ai/kling-video/v1/standard/text-to-video, fal-ai/minimax-video",
      },
      modeField,
    ],
    async runVideo(prompt, imageUrl, ctx) {
      const key = ctx.config.apiKey?.trim();
      if (!key) throw new Error("Missing fal.ai key — add it in Settings › API Keys.");
      const model = ctx.config.model?.trim() || "fal-ai/ltx-video";
      const body: any = { prompt };
      if (ctx.config.mode === "image") body.image_url = requireRemoteImage(imageUrl);
      // fal.run is synchronous — it blocks until the result is ready.
      const res = await fetch(`/api/fal/${model}`, {
        method: "POST",
        signal: ctx.signal,
        headers: { "Content-Type": "application/json", Authorization: `Key ${key}` },
        body: JSON.stringify(body),
      });
      const raw = await res.text();
      if (!res.ok) throw new Error(`${res.status} — ${trim(raw)}`);
      const data = JSON.parse(raw);
      const url = data?.video?.url || data?.videos?.[0]?.url || data?.output?.video?.url;
      if (!url) throw new Error(`No video URL in response: ${trim(raw)}`);
      return { url, remote: true };
    },
  },
  {
    id: "replicate",
    name: "Replicate",
    kind: "video",
    tier: "freemium",
    note: "Trial credits • huge model catalog",
    signupUrl: "https://replicate.com/account/api-tokens",
    secrets: [apiKeyField("r8_…")],
    params: [
      {
        key: "model",
        label: "Model (owner/name)",
        type: "text",
        default: "lightricks/ltx-video",
        placeholder: "owner/name",
        help: "e.g. lightricks/ltx-video, minimax/video-01, tencent/hunyuan-video",
      },
    ],
    async runVideo(prompt, _imageUrl, ctx) {
      const key = ctx.config.apiKey?.trim();
      if (!key) throw new Error("Missing Replicate token — add it in Settings › API Keys.");
      const model = ctx.config.model?.trim() || "lightricks/ltx-video";
      const create = await fetch(`/api/replicate/v1/models/${model}/predictions`, {
        method: "POST",
        signal: ctx.signal,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${key}`,
          Prefer: "wait",
        },
        body: JSON.stringify({ input: { prompt } }),
      });
      const raw = await create.text();
      if (!create.ok) throw new Error(`${create.status} — ${trim(raw)}`);
      let pred = JSON.parse(raw);
      if (pred.status !== "succeeded") {
        pred = await poll(
          async () => {
            const r = await fetch(`/api/replicate/v1/predictions/${pred.id}`, {
              signal: ctx.signal,
              headers: { Authorization: `Bearer ${key}` },
            });
            const p = await r.json();
            if (p.status === "succeeded") return { done: true, value: p };
            if (p.status === "failed" || p.status === "canceled")
              throw new Error(`Replicate ${p.status}: ${trim(JSON.stringify(p.error || p))}`);
            return { done: false };
          },
          { signal: ctx.signal },
        );
      }
      const out = pred.output;
      const url = Array.isArray(out) ? out[out.length - 1] : out;
      if (!url) throw new Error("Replicate returned no output URL.");
      return { url, remote: true };
    },
  },
  {
    id: "hf-video",
    name: "Hugging Face (text→video)",
    kind: "video",
    tier: "freemium",
    note: "Free tier with token",
    signupUrl: "https://huggingface.co/settings/tokens",
    secrets: [apiKeyField("hf_…")],
    params: [
      {
        key: "model",
        label: "Model",
        type: "text",
        default: "ali-vilab/text-to-video-ms-1.7b",
        placeholder: "org/model",
        help: "Text-to-video models served by the Inference API. Larger models may cold-start (retry ~20s).",
      },
    ],
    async runVideo(prompt, _imageUrl, ctx) {
      const key = ctx.config.apiKey?.trim();
      if (!key) throw new Error("Missing Hugging Face token — add it in Settings › API Keys.");
      const model = ctx.config.model?.trim() || "ali-vilab/text-to-video-ms-1.7b";
      const res = await fetch(`/api/hf/models/${model}`, {
        method: "POST",
        signal: ctx.signal,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
        body: JSON.stringify({ inputs: prompt }),
      });
      if (!res.ok) {
        const raw = await res.text();
        throw new Error(`${res.status} — ${trim(raw)} (model may be cold-loading; retry shortly)`);
      }
      const blob = await res.blob();
      return { url: URL.createObjectURL(blob), remote: false };
    },
  },
  {
    id: "minimax",
    name: "MiniMax (Hailuo)",
    kind: "video",
    tier: "freemium",
    note: "Free credits • needs Group ID",
    signupUrl: "https://www.minimaxi.chat/user-center/basic-information/interface-key",
    secrets: [
      apiKeyField("MiniMax API key"),
      { key: "groupId", label: "Group ID", type: "text", placeholder: "required to fetch the file" },
    ],
    params: [
      {
        key: "model",
        label: "Model",
        type: "select",
        options: [
          { value: "T2V-01", label: "T2V-01 (text → video)" },
          { value: "I2V-01", label: "I2V-01 (image → video)" },
        ],
        default: "T2V-01",
      },
    ],
    async runVideo(prompt, imageUrl, ctx) {
      const key = ctx.config.apiKey?.trim();
      const groupId = ctx.config.groupId?.trim();
      if (!key) throw new Error("Missing MiniMax key — add it in Settings › API Keys.");
      if (!groupId) throw new Error("MiniMax needs a Group ID (Settings › API Keys) to retrieve the finished file.");
      const model = ctx.config.model || "T2V-01";
      const body: any = { model, prompt };
      if (model.startsWith("I2V")) body.first_frame_image = requireRemoteImage(imageUrl);
      const create = await fetch(`/api/minimax/v1/video_generation`, {
        method: "POST",
        signal: ctx.signal,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
        body: JSON.stringify(body),
      });
      const cr = await create.json();
      const taskId = cr?.task_id;
      if (!taskId) throw new Error(`MiniMax: no task_id (${trim(JSON.stringify(cr))})`);
      const fileId = await poll<string>(
        async () => {
          const r = await fetch(`/api/minimax/v1/query/video_generation?task_id=${taskId}`, {
            signal: ctx.signal,
            headers: { Authorization: `Bearer ${key}` },
          });
          const q = await r.json();
          if (q.status === "Success") return { done: true, value: q.file_id };
          if (q.status === "Fail") throw new Error("MiniMax reported the job failed.");
          return { done: false };
        },
        { signal: ctx.signal },
      );
      const fr = await fetch(`/api/minimax/v1/files/retrieve?file_id=${fileId}&GroupId=${groupId}`, {
        signal: ctx.signal,
        headers: { Authorization: `Bearer ${key}` },
      });
      const fj = await fr.json();
      const url = fj?.file?.download_url;
      if (!url) throw new Error(`MiniMax: no download_url (${trim(JSON.stringify(fj))})`);
      return { url, remote: true };
    },
  },
  {
    id: "luma",
    name: "Luma Dream Machine",
    kind: "video",
    tier: "paid",
    note: "Some free credits • polling",
    signupUrl: "https://lumalabs.ai/dream-machine/api/keys",
    secrets: [apiKeyField("luma-…")],
    params: [
      {
        key: "model",
        label: "Model",
        type: "select",
        options: [
          { value: "ray-flash-2", label: "ray-flash-2 (fast)" },
          { value: "ray-2", label: "ray-2 (quality)" },
        ],
        default: "ray-flash-2",
      },
      modeField,
    ],
    async runVideo(prompt, imageUrl, ctx) {
      const key = ctx.config.apiKey?.trim();
      if (!key) throw new Error("Missing Luma key — add it in Settings › API Keys.");
      const body: any = { prompt, model: ctx.config.model || "ray-flash-2" };
      if (ctx.config.mode === "image") {
        body.keyframes = { frame0: { type: "image", url: requireRemoteImage(imageUrl) } };
      }
      const create = await fetch(`/api/luma/dream-machine/v1/generations`, {
        method: "POST",
        signal: ctx.signal,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}`, accept: "application/json" },
        body: JSON.stringify(body),
      });
      const cr = await create.json();
      const id = cr?.id;
      if (!id) throw new Error(`Luma: no generation id (${trim(JSON.stringify(cr))})`);
      const url = await poll<string>(
        async () => {
          const r = await fetch(`/api/luma/dream-machine/v1/generations/${id}`, {
            signal: ctx.signal,
            headers: { Authorization: `Bearer ${key}`, accept: "application/json" },
          });
          const g = await r.json();
          if (g.state === "completed") return { done: true, value: g?.assets?.video };
          if (g.state === "failed") throw new Error(`Luma failed: ${trim(g.failure_reason || "")}`);
          return { done: false };
        },
        { signal: ctx.signal },
      );
      if (!url) throw new Error("Luma completed but returned no video asset.");
      return { url, remote: true };
    },
  },
  {
    id: "runway",
    name: "Runway (Gen-4)",
    kind: "video",
    tier: "paid",
    note: "Animates a still • polling",
    signupUrl: "https://dev.runwayml.com",
    secrets: [apiKeyField("key_…")],
    params: [
      {
        key: "model",
        label: "Model",
        type: "select",
        options: [
          { value: "gen4_turbo", label: "gen4_turbo" },
          { value: "gen3a_turbo", label: "gen3a_turbo" },
        ],
        default: "gen4_turbo",
      },
      { key: "duration", label: "Seconds", type: "number", default: "5" },
    ],
    async runVideo(prompt, imageUrl, ctx) {
      const key = ctx.config.apiKey?.trim();
      if (!key) throw new Error("Missing Runway key — add it in Settings › API Keys.");
      const promptImage = requireRemoteImage(imageUrl);
      const ratio =
        ctx.inputs.dimensions === "9:16" ? "720:1280" : ctx.inputs.dimensions === "1:1" ? "960:960" : "1280:720";
      const create = await fetch(`/api/runway/v1/image_to_video`, {
        method: "POST",
        signal: ctx.signal,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${key}`,
          "X-Runway-Version": "2024-11-06",
        },
        body: JSON.stringify({
          model: ctx.config.model || "gen4_turbo",
          promptImage,
          promptText: prompt,
          duration: Number(ctx.config.duration || 5),
          ratio,
        }),
      });
      const cr = await create.json();
      const id = cr?.id;
      if (!id) throw new Error(`Runway: no task id (${trim(JSON.stringify(cr))})`);
      const url = await poll<string>(
        async () => {
          const r = await fetch(`/api/runway/v1/tasks/${id}`, {
            signal: ctx.signal,
            headers: { Authorization: `Bearer ${key}`, "X-Runway-Version": "2024-11-06" },
          });
          const t = await r.json();
          if (t.status === "SUCCEEDED") return { done: true, value: t?.output?.[0] };
          if (t.status === "FAILED") throw new Error(`Runway failed: ${trim(t.failure || "")}`);
          return { done: false };
        },
        { signal: ctx.signal },
      );
      return { url, remote: true };
    },
  },
  {
    id: "veo",
    name: "Google Veo (Gemini)",
    kind: "video",
    tier: "paid",
    note: "Veo • uses a Gemini/Vertex key",
    signupUrl: "https://aistudio.google.com/app/apikey",
    secrets: [apiKeyField("AIza…")],
    params: [
      {
        key: "model",
        label: "Model",
        type: "select",
        options: [
          { value: "veo-3.0-generate-preview", label: "veo-3.0-generate-preview" },
          { value: "veo-2.0-generate-001", label: "veo-2.0-generate-001" },
        ],
        default: "veo-3.0-generate-preview",
      },
    ],
    async runVideo(prompt, _imageUrl, ctx) {
      const key = ctx.config.apiKey?.trim();
      if (!key) throw new Error("Missing Google key — add it in Settings › API Keys.");
      const model = ctx.config.model || "veo-3.0-generate-preview";
      const aspect = ctx.inputs.dimensions === "9:16" ? "9:16" : "16:9";
      const start = await fetch(`/api/gemini/v1beta/models/${model}:predictLongRunning?key=${encodeURIComponent(key)}`, {
        method: "POST",
        signal: ctx.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instances: [{ prompt }], parameters: { aspectRatio: aspect } }),
      });
      const sj = await start.json();
      const opName = sj?.name;
      if (!opName) throw new Error(`Veo: no operation name (${trim(JSON.stringify(sj))})`);
      const uri = await poll<string>(
        async () => {
          const r = await fetch(`/api/gemini/v1beta/${opName}?key=${encodeURIComponent(key)}`, { signal: ctx.signal });
          const op = await r.json();
          if (op.error) throw new Error(`Veo error: ${trim(JSON.stringify(op.error))}`);
          if (op.done) {
            const v =
              op?.response?.generateVideoResponse?.generatedSamples?.[0]?.video?.uri ||
              op?.response?.generatedVideos?.[0]?.video?.uri ||
              op?.response?.predictions?.[0]?.video?.uri;
            return { done: true, value: v };
          }
          return { done: false };
        },
        { intervalMs: 8000, timeoutMs: 300000, signal: ctx.signal },
      );
      if (!uri) throw new Error("Veo finished but no video URI was returned.");
      // The download URI needs the API key appended.
      const sep = uri.includes("?") ? "&" : "?";
      return { url: `${uri}${sep}key=${encodeURIComponent(key)}`, remote: true };
    },
  },
];
