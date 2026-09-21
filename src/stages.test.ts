import { describe, it, expect } from "vitest";
import { parseScenes, fillTemplate, dimsToPixels } from "./stages";

describe("parseScenes", () => {
  it("parses a clean JSON array", () => {
    const scenes = parseScenes(
      `[{"scene":1,"time":"0:00","narration":"Hi","onScreenText":"Hi","imagePrompt":"a wave"}]`,
    );
    expect(scenes).toEqual([
      { scene: 1, time: "0:00", narration: "Hi", onScreenText: "Hi", imagePrompt: "a wave" },
    ]);
  });

  it("strips markdown code fences", () => {
    const scenes = parseScenes(
      "```json\n[{\"scene\":1,\"time\":\"0:00\",\"narration\":\"Hi\",\"onScreenText\":\"\",\"imagePrompt\":\"x\"}]\n```",
    );
    expect(scenes).toHaveLength(1);
    expect(scenes[0].scene).toBe(1);
  });

  it("accepts snake_case keys as a fallback", () => {
    const scenes = parseScenes(
      `[{"scene":1,"time":"0:00","narration":"Hi","on_screen_text":"snake","image_prompt":"snake prompt"}]`,
    );
    expect(scenes[0].onScreenText).toBe("snake");
    expect(scenes[0].imagePrompt).toBe("snake prompt");
  });

  it("throws a clear error when no array is present", () => {
    expect(() => parseScenes("Sorry, I can't do that.")).toThrow(
      "Could not find a JSON array in the model output.",
    );
  });

  // Known-fragile case (documented in the handover report): parseScenes() slices
  // between the FIRST "[" and the LAST "]" in the whole response. Trailing prose
  // that itself contains a "]" after the real array breaks the slice.
  it("is fragile to trailing prose containing a stray ']' (documents a known limitation)", () => {
    const withTrailingBracket =
      `[{"scene":1,"time":"0:00","narration":"Hi","onScreenText":"","imagePrompt":"x"}]\n\n` +
      `Note: scenes [1] are just a starting point.`;
    // This currently throws (invalid JSON) rather than parsing the intended array,
    // because the slice runs through the trailing "]". If this test starts failing
    // because parseScenes() got more robust, that's good news — update the assertion.
    expect(() => parseScenes(withTrailingBracket)).toThrow();
  });
});

describe("fillTemplate", () => {
  const inputs = {
    topic: "compound interest",
    dimensions: "16:9" as const,
    duration: "60s",
    audienceType: "beginners",
    ageGroup: "18-24",
  };

  it("substitutes every known placeholder", () => {
    const out = fillTemplate(
      "{{topic}} for {{audienceType}} ({{ageGroup}}), {{duration}}, {{dimensions}}",
      inputs,
    );
    expect(out).toBe("compound interest for beginners (18-24), 60s, 16:9");
  });

  it("falls back to a placeholder label when a field is empty", () => {
    const out = fillTemplate("{{topic}}", { ...inputs, topic: "" });
    expect(out).toBe("(topic)");
  });
});

describe("dimsToPixels", () => {
  it("maps each aspect ratio to its pixel size", () => {
    expect(dimsToPixels("16:9")).toEqual({ width: 1344, height: 768 });
    expect(dimsToPixels("9:16")).toEqual({ width: 768, height: 1344 });
    expect(dimsToPixels("1:1")).toEqual({ width: 1024, height: 1024 });
  });

  it("defaults to 16:9 pixels for an unrecognized value", () => {
    expect(dimsToPixels("unknown")).toEqual({ width: 1344, height: 768 });
  });
});
