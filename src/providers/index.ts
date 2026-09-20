import type { Provider, StageKind, Tier } from "../types";
import { llmProviders } from "./llm";
import { imageProviders } from "./image";
import { videoProviders } from "./video";
import { ttsProviders } from "./tts";

export const allProviders: Provider[] = [
  ...llmProviders,
  ...imageProviders,
  ...videoProviders,
  ...ttsProviders,
];

const TIER_ORDER: Record<Tier, number> = { free: 0, freemium: 1, paid: 2 };

/** Providers for a stage kind, ordered free -> freemium -> paid. */
export function providersFor(kind: StageKind): Provider[] {
  return allProviders
    .filter((p) => p.kind === kind)
    .sort((a, b) => TIER_ORDER[a.tier] - TIER_ORDER[b.tier]);
}

export function getProvider(id: string): Provider | undefined {
  return allProviders.find((p) => p.id === id);
}

export const TIER_LABEL: Record<Tier, string> = {
  free: "Free",
  freemium: "Freemium",
  paid: "Paid",
};
