export function ComingSoon({ title, phase }: { title: string; phase: string }) {
  return (
    <div className="card">
      <h1>{title}</h1>
      <p className="muted">यह हिस्सा {phase} में बनेगा। अभी Phase 1 (बुनियाद) तैयार है।</p>
      <a className="btn" href="#/">← होम</a>
    </div>
  );
}
