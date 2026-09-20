import { providersFor, TIER_LABEL } from "../providers";
import { useStore, setSecret } from "../store";
import { FieldEditor } from "./FieldEditor";
import { IconExternal } from "../icons";
import type { StageKind } from "../types";

const KINDS: { kind: StageKind; label: string }[] = [
  { kind: "llm", label: "Text / LLM" },
  { kind: "image", label: "Images" },
  { kind: "video", label: "Video (credit-based)" },
  { kind: "tts", label: "Voice / TTS" },
];

export function Settings() {
  const secrets = useStore((s) => s.secrets);

  return (
    <div className="panel-wrap">
      <div className="panel-head">
        <div>
          <h2>Settings &amp; API keys</h2>
          <div className="desc">
            Add a key once here and it’s available to every stage that uses that provider. Keys are stored only in this
            browser (<code>localStorage</code>) and are sent through a local proxy — never to any third party but the
            provider itself. Pick which provider each stage uses (and its model/prompt) on the stage’s own panel.
          </div>
        </div>
      </div>

      {KINDS.map(({ kind, label }) => (
        <div key={kind}>
          <div className="section-title">{label}</div>
          <div className="settings-grid">
            {providersFor(kind).map((p) => {
              const cfg = secrets[p.id] || {};
              return (
                <div className="provider-card" key={p.id}>
                  <div className="head">
                    <span className={"badge " + p.tier}>{TIER_LABEL[p.tier]}</span>
                    <span className="name">{p.name}</span>
                    {p.note && <span className="pill">{p.note}</span>}
                    <span className="kind">
                      {p.signupUrl && (
                        <a className="link-ext" href={p.signupUrl} target="_blank" rel="noreferrer">
                          Get key <IconExternal size={12} />
                        </a>
                      )}
                    </span>
                  </div>
                  {p.secrets.length === 0 ? (
                    <div className="pill" style={{ display: "inline-block" }}>
                      {p.needsBackend ? "No key — but needs the Phase-2 backend" : "No API key required"}
                    </div>
                  ) : (
                    <div className="fields-row">
                      {p.secrets.map((f) => (
                        <FieldEditor
                          key={f.key}
                          field={f}
                          value={cfg[f.key] ?? ""}
                          onChange={(v) => setSecret(p.id, f.key, v)}
                        />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      <div className="notice" style={{ marginTop: 26 }}>
        <b>Recommended free starting stack:</b> Gemini (text) → Pollinations (images, no key) → Browser Web Speech
        (voice). That gets you a full run with just one free Gemini key. Add ElevenLabs or the Edge-TTS backend later
        for downloadable, higher-quality narration.
      </div>
    </div>
  );
}
