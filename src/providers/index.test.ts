import { describe, it, expect } from "vitest";
import { allProviders, providersFor, getProvider } from "./index";

describe("providersFor", () => {
  it("returns only providers of the requested kind", () => {
    for (const p of providersFor("tts")) expect(p.kind).toBe("tts");
    for (const p of providersFor("llm")) expect(p.kind).toBe("llm");
  });

  it("sorts free before freemium before paid", () => {
    const tierIndex = { free: 0, freemium: 1, paid: 2 } as const;
    const tts = providersFor("tts");
    for (let i = 1; i < tts.length; i++) {
      expect(tierIndex[tts[i].tier]).toBeGreaterThanOrEqual(tierIndex[tts[i - 1].tier]);
    }
  });

  it("includes the Google Cloud TTS provider in the freemium tier", () => {
    const gtts = providersFor("tts").find((p) => p.id === "google-tts");
    expect(gtts).toBeDefined();
    expect(gtts?.tier).toBe("freemium");
  });
});

describe("getProvider", () => {
  it("finds a known provider by id", () => {
    expect(getProvider("gemini")?.name).toBe("Google Gemini (AI Studio)");
  });

  it("returns undefined for an unknown id", () => {
    expect(getProvider("does-not-exist")).toBeUndefined();
  });
});

describe("allProviders", () => {
  it("has no duplicate ids", () => {
    const ids = allProviders.map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("gives every provider a runner matching its kind", () => {
    for (const p of allProviders) {
      if (p.kind === "llm") expect(p.runLlm).toBeTypeOf("function");
      if (p.kind === "image") expect(p.runImage).toBeTypeOf("function");
      if (p.kind === "video") expect(p.runVideo).toBeTypeOf("function");
      if (p.kind === "tts") expect(p.runTts).toBeTypeOf("function");
    }
  });
});
