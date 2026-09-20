import { STAGES } from "../stages";
import { useStore, setView } from "../store";
import { runAll } from "../engine";
import {
  IconSearch,
  IconScript,
  IconFilm,
  IconImage,
  IconVideo,
  IconMic,
  IconLayers,
  IconSettings,
  IconBolt,
  IconStop,
} from "../icons";
import type { StageStatus } from "../types";

const STAGE_ICON: Record<string, (p: any) => JSX.Element> = {
  research: IconSearch,
  script: IconScript,
  visuals: IconFilm,
  images: IconImage,
  video: IconVideo,
  voiceover: IconMic,
  assemble: IconLayers,
};

export function Sidebar({ running, onRunAll, onStopAll }: { running: boolean; onRunAll: () => void; onStopAll: () => void }) {
  const view = useStore((s) => s.view);
  const runtime = useStore((s) => s.runtime);

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="logo">
          <IconBolt size={19} />
        </div>
        <div>
          <h1>AI YT Studio</h1>
          <div className="sub">agentic video pipeline</div>
        </div>
      </div>

      <div className="rail">
        <div className="rail-label">Pipeline</div>
        {STAGES.map((stage, i) => {
          const Icon = STAGE_ICON[stage.id];
          const status: StageStatus = runtime[stage.id]?.status ?? "idle";
          return (
            <button
              key={stage.id}
              className={"stage-item" + (view === stage.id ? " active" : "")}
              onClick={() => setView(stage.id)}
            >
              <span className="stage-num">{i + 1}</span>
              <span className="stage-meta">
                <span className="stage-title">
                  <Icon size={15} />
                  {stage.title}
                </span>
                <span className="stage-sub">{stage.short}</span>
              </span>
              <span className={"dot " + status} title={status} />
            </button>
          );
        })}
      </div>

      <div className="rail-foot">
        {running ? (
          <button className="btn full danger" onClick={onStopAll}>
            <IconStop size={15} /> Stop
          </button>
        ) : (
          <button className="btn primary full" onClick={onRunAll}>
            <IconBolt size={15} /> Run full pipeline
          </button>
        )}
        <button
          className={"btn ghost full" + (view === "settings" ? " active" : "")}
          style={{ marginTop: 8 }}
          onClick={() => setView("settings")}
        >
          <IconSettings size={15} /> Settings & API keys
        </button>
      </div>
    </aside>
  );
}
