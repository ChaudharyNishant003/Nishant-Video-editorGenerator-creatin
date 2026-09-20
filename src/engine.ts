import { getProvider } from "./providers";
import { STAGES, fillTemplate, parseScenes, dimsToPixels } from "./stages";
import { getState, setRuntime, stageConfig } from "./store";
import type { ProjectInputs, RunContext } from "./types";

// ---------------------------------------------------------------------------
// Runs individual stages and chains the whole pipeline.
// ---------------------------------------------------------------------------

const controllers: Record<string, AbortController> = {};

function inputsSummary(inputs: ProjectInputs): string {
  return (
    `Topic: ${inputs.topic}\n` +
    `Audience type: ${inputs.audienceType}\n` +
    `Age group: ${inputs.ageGroup}\n` +
    `Duration: ${inputs.duration}\n` +
    `Aspect ratio: ${inputs.dimensions}`
  );
}

export function cancelStage(stageId: string) {
  controllers[stageId]?.abort();
}

function makeCtx(stageId: string, signal: AbortSignal): RunContext {
  const { inputs } = getState();
  const { width, height } = dimsToPixels(inputs.dimensions);
  return { config: stageConfig(stageId), inputs, width, height, signal };
}

export async function runStage(stageId: string): Promise<void> {
  const stage = STAGES.find((s) => s.id === stageId);
  if (!stage) return;
  const state = getState();
  const wiring = state.wiring[stageId];
  const provider = getProvider(wiring?.providerId);

  const controller = new AbortController();
  controllers[stageId] = controller;
  setRuntime(stageId, { status: "running", error: undefined, startedAt: Date.now(), finishedAt: undefined });

  try {
    if (!provider) throw new Error("No provider selected. Pick one in this stage's settings.");
    if (provider.needsBackend) {
      throw new Error(`${provider.name} needs the Phase-2 backend running. Pick a browser provider for now.`);
    }
    const ctx = makeCtx(stageId, controller.signal);

    if (stage.kind === "llm") {
      const system = fillTemplate(wiring.systemPrompt || stage.defaultSystemPrompt || "", state.inputs);
      let user: string;
      if (stageId === "research") {
        user = inputsSummary(state.inputs);
      } else if (stageId === "script") {
        user = state.runtime["research"]?.text || inputsSummary(state.inputs);
      } else if (stageId === "visuals") {
        const script = state.runtime["script"]?.text;
        if (!script) throw new Error("Run the Scriptwriter stage first — the Visual Director needs a script.");
        user = script;
      } else {
        user = inputsSummary(state.inputs);
      }
      const res = await provider.runLlm!(system, user, ctx);
      if (stageId === "visuals") {
        const scenes = parseScenes(res.text);
        setRuntime(stageId, { text: res.text, scenes });
      } else {
        setRuntime(stageId, { text: res.text });
      }
    } else if (stage.kind === "image") {
      const scenes = getState().runtime["visuals"]?.scenes;
      if (!scenes || scenes.length === 0) {
        throw new Error("Run the Visual Director first — image generation needs scene prompts.");
      }
      const images: Record<number, string> = { ...(getState().runtime[stageId]?.images || {}) };
      for (const scene of scenes) {
        if (controller.signal.aborted) throw new DOMException("Aborted", "AbortError");
        const res = await provider.runImage!(scene.imagePrompt, ctx);
        images[scene.scene] = res.url;
        setRuntime(stageId, { images: { ...images } });
      }
    } else if (stage.kind === "video") {
      const scenes = getState().runtime["visuals"]?.scenes;
      if (!scenes || scenes.length === 0) {
        throw new Error("Run the Visual Director first — video generation needs scene prompts.");
      }
      const stills = getState().runtime["images"]?.images || {};
      const videos: Record<number, string> = { ...(getState().runtime[stageId]?.videos || {}) };
      for (const scene of scenes) {
        if (controller.signal.aborted) throw new DOMException("Aborted", "AbortError");
        const res = await provider.runVideo!(scene.imagePrompt, stills[scene.scene], ctx);
        videos[scene.scene] = res.url;
        setRuntime(stageId, { videos: { ...videos } });
      }
    } else if (stage.kind === "tts") {
      const script = getState().runtime["script"]?.text;
      if (!script) throw new Error("Run the Scriptwriter first — the voiceover needs a script.");
      const res = await provider.runTts!(script, ctx);
      setRuntime(stageId, { audioUrl: res.url || undefined, audioPlaybackOnly: !!res.playbackOnly });
    }

    setRuntime(stageId, { status: "done", finishedAt: Date.now() });
  } catch (err: any) {
    if (err?.name === "AbortError") {
      setRuntime(stageId, { status: "idle", error: undefined });
    } else {
      setRuntime(stageId, { status: "error", error: err?.message || String(err) });
    }
    throw err;
  } finally {
    delete controllers[stageId];
  }
}

/** Runs the creative pipeline end-to-end, stopping at the first failure. */
export async function runAll(): Promise<void> {
  const order = ["research", "script", "visuals", "images", "voiceover"];
  for (const id of order) {
    try {
      await runStage(id);
    } catch {
      return; // stop the chain; the failing stage already shows its error
    }
  }
}
