import { useSyncExternalStore } from "react";
import type {
  AspectRatio,
  ProjectInputs,
  StageRuntimeState,
  StageWiring,
} from "./types";
import { STAGES } from "./stages";
import { providersFor, getProvider } from "./providers";

// ---------------------------------------------------------------------------
// Dependency-free global store with localStorage persistence.
// ---------------------------------------------------------------------------

const LS_KEY = "ai-yt-studio:v1";

export interface AppState {
  inputs: ProjectInputs;
  /** providerId -> { fieldKey: value } (API keys etc.) */
  secrets: Record<string, Record<string, string>>;
  /** stageId -> wiring (provider + params + systemPrompt) */
  wiring: Record<string, StageWiring>;
  /** stageId -> runtime output/status */
  runtime: Record<string, StageRuntimeState>;
  /** which stage panel is open, or "settings" */
  view: string;
}

function defaultParamsFor(providerId: string): Record<string, string> {
  const p = getProvider(providerId);
  const out: Record<string, string> = {};
  p?.params.forEach((f) => {
    if (f.default !== undefined) out[f.key] = f.default;
  });
  return out;
}

function buildDefaults(): AppState {
  const wiring: Record<string, StageWiring> = {};
  const runtime: Record<string, StageRuntimeState> = {};
  for (const stage of STAGES) {
    runtime[stage.id] = { status: "idle" };
    if (stage.kind === "assemble") continue;
    const options = providersFor(stage.kind);
    const first = options[0];
    wiring[stage.id] = {
      providerId: first?.id ?? "",
      params: defaultParamsFor(first?.id ?? ""),
      systemPrompt: stage.defaultSystemPrompt,
    };
  }
  return {
    inputs: {
      topic: "",
      dimensions: "16:9" as AspectRatio,
      duration: "60s",
      audienceType: "General",
      ageGroup: "18-34",
    },
    secrets: {},
    wiring,
    runtime,
    view: STAGES[0].id,
  };
}

function hydrate(): AppState {
  const base = buildDefaults();
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return base;
    const saved = JSON.parse(raw);
    // Merge persisted fields; do NOT restore volatile blob URLs (images/audio).
    return {
      ...base,
      inputs: { ...base.inputs, ...saved.inputs },
      secrets: { ...base.secrets, ...saved.secrets },
      wiring: mergeWiring(base.wiring, saved.wiring),
      runtime: mergeRuntime(base.runtime, saved.runtime),
      view: base.view,
    };
  } catch {
    return base;
  }
}

function mergeWiring(
  base: Record<string, StageWiring>,
  saved: Record<string, StageWiring> | undefined,
): Record<string, StageWiring> {
  if (!saved) return base;
  const out = { ...base };
  for (const id of Object.keys(base)) {
    if (saved[id]) out[id] = { ...base[id], ...saved[id], params: { ...base[id].params, ...saved[id].params } };
  }
  return out;
}

function mergeRuntime(
  base: Record<string, StageRuntimeState>,
  saved: Record<string, StageRuntimeState> | undefined,
): Record<string, StageRuntimeState> {
  if (!saved) return base;
  const out = { ...base };
  for (const id of Object.keys(base)) {
    if (saved[id]) {
      // Restore only durable text/scenes — never volatile blob/object URLs.
      out[id] = {
        status: saved[id].text || saved[id].scenes ? "done" : "idle",
        text: saved[id].text,
        scenes: saved[id].scenes,
      };
    }
  }
  return out;
}

function persist(state: AppState) {
  try {
    const runtimeToSave: Record<string, any> = {};
    for (const [id, rt] of Object.entries(state.runtime)) {
      runtimeToSave[id] = { text: rt.text, scenes: rt.scenes };
    }
    localStorage.setItem(
      LS_KEY,
      JSON.stringify({
        inputs: state.inputs,
        secrets: state.secrets,
        wiring: state.wiring,
        runtime: runtimeToSave,
      }),
    );
  } catch {
    /* ignore quota / private-mode errors */
  }
}

// --- store plumbing --------------------------------------------------------

let state: AppState = hydrate();
const listeners = new Set<() => void>();

function emit() {
  persist(state);
  listeners.forEach((l) => l());
}

export function getState(): AppState {
  return state;
}

export function setState(update: Partial<AppState> | ((s: AppState) => Partial<AppState>)) {
  const patch = typeof update === "function" ? update(state) : update;
  state = { ...state, ...patch };
  emit();
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function useStore<T>(selector: (s: AppState) => T): T {
  return useSyncExternalStore(
    subscribe,
    () => selector(state),
    () => selector(state),
  );
}

// --- typed mutators --------------------------------------------------------

export function setInputs(patch: Partial<ProjectInputs>) {
  setState((s) => ({ inputs: { ...s.inputs, ...patch } }));
}

export function setView(view: string) {
  setState({ view });
}

export function setSecret(providerId: string, key: string, value: string) {
  setState((s) => ({
    secrets: { ...s.secrets, [providerId]: { ...(s.secrets[providerId] || {}), [key]: value } },
  }));
}

export function setStageProvider(stageId: string, providerId: string) {
  setState((s) => ({
    wiring: {
      ...s.wiring,
      [stageId]: { ...s.wiring[stageId], providerId, params: defaultParamsFor(providerId) },
    },
  }));
}

export function setStageParam(stageId: string, key: string, value: string) {
  setState((s) => ({
    wiring: {
      ...s.wiring,
      [stageId]: { ...s.wiring[stageId], params: { ...s.wiring[stageId].params, [key]: value } },
    },
  }));
}

export function setStagePrompt(stageId: string, systemPrompt: string) {
  setState((s) => ({
    wiring: { ...s.wiring, [stageId]: { ...s.wiring[stageId], systemPrompt } },
  }));
}

export function setRuntime(stageId: string, patch: Partial<StageRuntimeState>) {
  setState((s) => ({
    runtime: { ...s.runtime, [stageId]: { ...s.runtime[stageId], ...patch } },
  }));
}

/** Merged config passed to a provider's run function. */
export function stageConfig(stageId: string): Record<string, string> {
  const w = state.wiring[stageId];
  if (!w) return {};
  const secrets = state.secrets[w.providerId] || {};
  return { ...secrets, ...w.params };
}
