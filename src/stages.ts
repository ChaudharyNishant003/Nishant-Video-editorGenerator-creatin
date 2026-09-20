import type { StageDef, ProjectInputs } from "./types";

// ---------------------------------------------------------------------------
// Pipeline definition. Each stage has a kind (which decides the provider menu)
// and, for LLM stages, an editable default system prompt.
//
// {{topic}}, {{dimensions}}, {{duration}}, {{audienceType}}, {{ageGroup}} are
// substituted from the project inputs before sending.
// ---------------------------------------------------------------------------

export const STAGES: StageDef[] = [
  {
    id: "research",
    title: "Research & Hook",
    kind: "llm",
    short: "Hooks + outline",
    description:
      "Analyzes the audience and age group, then proposes high-retention hooks and a structural outline tuned to the target duration.",
    defaultSystemPrompt:
      `You are an expert YouTube strategist and audience psychologist.\n` +
      `Given the topic, audience type, and age group, reason about what makes THIS demographic keep watching.\n\n` +
      `Output in clean Markdown:\n` +
      `1. **Audience insight** — 2-3 sentences on what this group cares about and their attention triggers.\n` +
      `2. **3 hook options** — each a punchy first line (<= 12 words) with a one-line note on why it works.\n` +
      `3. **Recommended hook** — pick one and say why.\n` +
      `4. **Structural outline** — beat-by-beat sections with rough timestamps that fit a {{duration}} video.\n\n` +
      `Topic: {{topic}}\nAudience type: {{audienceType}}\nAge group: {{ageGroup}}\nDuration: {{duration}}\nFormat/aspect: {{dimensions}}`,
  },
  {
    id: "script",
    title: "Scriptwriter",
    kind: "llm",
    short: "Full spoken script",
    description:
      "Turns the chosen hook and outline into a word-for-word spoken script, paced to the target duration and voiced for the audience.",
    defaultSystemPrompt:
      `You are a world-class short-form scriptwriter.\n` +
      `Using the research/outline provided by the user, write a COMPLETE word-for-word narration script.\n\n` +
      `Rules:\n` +
      `- Open with the recommended hook in the first 3 seconds.\n` +
      `- Tone must fit a {{ageGroup}} {{audienceType}} audience.\n` +
      `- Pace it to be read aloud in about {{duration}} (roughly 150 spoken words per minute).\n` +
      `- Write ONLY the spoken words — no scene directions, no camera notes, no headings.\n` +
      `- Conversational, punchy sentences. End with a clear call-to-action.\n\n` +
      `Topic: {{topic}}`,
  },
  {
    id: "visuals",
    title: "Visual Director",
    kind: "llm",
    short: "Scene-by-scene breakdown",
    description:
      "Breaks the script into scenes and writes a descriptive text-to-image prompt for each, matched to your aspect ratio.",
    defaultSystemPrompt:
      `You are a video director and prompt engineer.\n` +
      `Read the script provided by the user and break it into sequential scenes.\n\n` +
      `Return ONLY a JSON array (no prose, no code fences) where each element is:\n` +
      `{\n` +
      `  "scene": <number starting at 1>,\n` +
      `  "time": "<start-end, e.g. 0:00-0:05>",\n` +
      `  "narration": "<the exact words spoken during this scene>",\n` +
      `  "onScreenText": "<short caption/keyword to overlay, or empty string>",\n` +
      `  "imagePrompt": "<a vivid, self-contained text-to-image prompt; describe style, subject, lighting, composition; end with 'aspect ratio {{dimensions}}'>"\n` +
      `}\n\n` +
      `Make imagePrompts consistent in art style across scenes. Aim for one scene every 4-8 seconds.`,
  },
  {
    id: "images",
    title: "Image Generation",
    kind: "image",
    short: "Render each scene",
    description:
      "Generates an image for every scene using the prompts from the Visual Director, at your chosen aspect ratio.",
  },
  {
    id: "video",
    title: "Video Generation",
    kind: "video",
    short: "Animate scenes (credits)",
    description:
      "Optional motion agent: turns scenes into short video clips (text→video, or image→video that animates each still). Every provider runs on limited trial credits, so this stage is not part of ‘Run full pipeline’ — trigger it per scene when you want motion.",
  },
  {
    id: "voiceover",
    title: "Voiceover",
    kind: "tts",
    short: "Narrate the script",
    description: "Converts the script into narration audio using your selected voice provider.",
  },
  {
    id: "assemble",
    title: "Storyboard / Assemble",
    kind: "assemble",
    short: "Preview + export",
    description:
      "Plays your scenes as a storyboard synced to the voiceover, and exports a real .mp4 (images + Edge-TTS narration + captions) when the Phase-2 render backend is running.",
  },
];

export function fillTemplate(template: string, inputs: ProjectInputs): string {
  return template
    .replaceAll("{{topic}}", inputs.topic || "(topic)")
    .replaceAll("{{dimensions}}", inputs.dimensions)
    .replaceAll("{{duration}}", inputs.duration || "(duration)")
    .replaceAll("{{audienceType}}", inputs.audienceType || "(audience)")
    .replaceAll("{{ageGroup}}", inputs.ageGroup || "(age group)");
}

export function dimsToPixels(dimensions: string): { width: number; height: number } {
  switch (dimensions) {
    case "9:16":
      return { width: 768, height: 1344 };
    case "1:1":
      return { width: 1024, height: 1024 };
    case "16:9":
    default:
      return { width: 1344, height: 768 };
  }
}

/** Robustly pull a JSON array of scenes out of an LLM response. */
export function parseScenes(text: string): import("./types").Scene[] {
  let t = text.trim();
  // Strip code fences if present.
  t = t.replace(/^```(?:json)?/i, "").replace(/```$/i, "").trim();
  const start = t.indexOf("[");
  const end = t.lastIndexOf("]");
  if (start === -1 || end === -1) throw new Error("Could not find a JSON array in the model output.");
  const arr = JSON.parse(t.slice(start, end + 1));
  return arr.map((s: any, i: number) => ({
    scene: Number(s.scene ?? i + 1),
    time: String(s.time ?? ""),
    narration: String(s.narration ?? ""),
    onScreenText: String(s.onScreenText ?? s.on_screen_text ?? ""),
    imagePrompt: String(s.imagePrompt ?? s.image_prompt ?? ""),
  }));
}
