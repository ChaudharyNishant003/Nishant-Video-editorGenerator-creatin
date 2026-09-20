// ---------------------------------------------------------------------------
// Core domain types for AI YT Studio.
// ---------------------------------------------------------------------------

export type StageKind = "llm" | "image" | "video" | "tts" | "assemble";

export type Tier = "free" | "freemium" | "paid";

/** A configurable field shown either in the global API-keys panel (secret) or
 *  in per-stage wiring (param, e.g. model/voice). */
export interface Field {
  key: string;
  label: string;
  type: "password" | "text" | "select" | "number";
  placeholder?: string;
  options?: { value: string; label: string }[];
  default?: string;
  help?: string;
}

export interface LlmResult {
  text: string;
}
export interface ImageResult {
  /** Displayable URL (may be a blob: URL or a remote URL). */
  url: string;
  /** True if the URL is a remote provider URL (Pollinations) vs a blob we hold. */
  remote: boolean;
}
export interface VideoResult {
  /** Displayable video URL (blob: or a remote provider URL). */
  url: string;
  remote: boolean;
}
export interface TtsResult {
  /** blob: URL for downloadable audio, or null when the provider only supports
   *  live browser playback (Web Speech). */
  url: string | null;
  /** Provider only plays audio live and cannot hand back a file. */
  playbackOnly?: boolean;
  /** For Web Speech: replay the utterance. */
  play?: () => void;
}

export interface RunContext {
  /** Merged config: provider secrets + stage params. */
  config: Record<string, string>;
  inputs: ProjectInputs;
  /** Convenience: pixel dimensions derived from the aspect ratio input. */
  width: number;
  height: number;
  signal?: AbortSignal;
}

export interface Provider {
  id: string;
  name: string;
  kind: StageKind;
  tier: Tier;
  /** Short note shown under the name, e.g. "No key needed". */
  note?: string;
  /** Where to obtain an API key. */
  signupUrl?: string;
  /** Secrets stored globally per-provider (API keys). */
  secrets: Field[];
  /** Params chosen per-stage (model, voice, etc.). */
  params: Field[];
  /** Marks providers that need the Phase-2 backend (disabled in Phase 1). */
  needsBackend?: boolean;
  runLlm?: (system: string, user: string, ctx: RunContext) => Promise<LlmResult>;
  runImage?: (prompt: string, ctx: RunContext) => Promise<ImageResult>;
  /** imageUrl is the scene's still (for image-to-video); undefined if none. */
  runVideo?: (prompt: string, imageUrl: string | undefined, ctx: RunContext) => Promise<VideoResult>;
  runTts?: (text: string, ctx: RunContext) => Promise<TtsResult>;
}

export type AspectRatio = "16:9" | "9:16" | "1:1";

export interface ProjectInputs {
  topic: string;
  dimensions: AspectRatio;
  duration: string; // e.g. "60s", "3 min"
  audienceType: string; // e.g. "Beginners", "Investors"
  ageGroup: string; // e.g. "18-24"
}

export interface Scene {
  scene: number;
  time: string;
  narration: string;
  onScreenText: string;
  imagePrompt: string;
}

export type StageStatus = "idle" | "running" | "done" | "error";

export interface StageDef {
  id: string;
  title: string;
  kind: StageKind;
  short: string;
  description: string;
  /** Only for llm stages: the default, editable system prompt. */
  defaultSystemPrompt?: string;
}

export interface StageWiring {
  providerId: string;
  params: Record<string, string>;
  systemPrompt?: string;
}

export interface StageRuntimeState {
  status: StageStatus;
  error?: string;
  /** LLM text output. */
  text?: string;
  /** Visual Director parsed scenes. */
  scenes?: Scene[];
  /** Image URLs indexed by scene number. */
  images?: Record<number, string>;
  /** Video clip URLs indexed by scene number. */
  videos?: Record<number, string>;
  /** Voiceover audio blob URL. */
  audioUrl?: string;
  audioPlaybackOnly?: boolean;
  startedAt?: number;
  finishedAt?: number;
}
