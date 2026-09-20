import { useStore, setInputs } from "../store";
import type { AspectRatio } from "../types";

export function InputsBar() {
  const inputs = useStore((s) => s.inputs);
  return (
    <div className="inputs-bar">
      <div className="field grow">
        <label>Topic</label>
        <input
          className="input"
          placeholder="e.g. How compound interest quietly builds wealth"
          value={inputs.topic}
          onChange={(e) => setInputs({ topic: e.target.value })}
        />
      </div>
      <div className="field">
        <label>Dimensions</label>
        <select
          className="select"
          value={inputs.dimensions}
          onChange={(e) => setInputs({ dimensions: e.target.value as AspectRatio })}
        >
          <option value="16:9">16:9 — landscape</option>
          <option value="9:16">9:16 — shorts/reels</option>
          <option value="1:1">1:1 — square</option>
        </select>
      </div>
      <div className="field">
        <label>Duration</label>
        <input
          className="input"
          style={{ width: 92 }}
          value={inputs.duration}
          onChange={(e) => setInputs({ duration: e.target.value })}
        />
      </div>
      <div className="field">
        <label>Audience type</label>
        <input
          className="input"
          style={{ width: 150 }}
          placeholder="Beginners, Investors…"
          value={inputs.audienceType}
          onChange={(e) => setInputs({ audienceType: e.target.value })}
        />
      </div>
      <div className="field">
        <label>Age group</label>
        <input
          className="input"
          style={{ width: 100 }}
          placeholder="18-34"
          value={inputs.ageGroup}
          onChange={(e) => setInputs({ ageGroup: e.target.value })}
        />
      </div>
    </div>
  );
}
