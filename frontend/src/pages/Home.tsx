import { useEffect, useState } from "react";
import { api } from "../api";

const STATUS: Record<string, string> = {
  draft: "शुरुआत", uploaded: "अपलोड हुआ", ingesting: "तैयार हो रहा", ingested: "तैयार", ingest_failed: "अपलोड विफल",
  transcribing: "transcript बन रहा", transcribed: "transcript तैयार", transcribe_failed: "transcript विफल",
  planned: "प्लान तैयार", rendering: "रेंडर हो रहा", done: "पूरा", render_failed: "रेंडर विफल",
};

type Project ={ id: string; kind: "edit" | "create"; title: string; status: string; updated_at: number };

export function Home() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ projects: Project[] }>("/api/projects")
      .then((r) => setProjects(r.projects))
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div>
      <div className="cards">
        <a className="bigcard" href="#/edit">
          <span className="bigicon" aria-hidden>✂</span>
          <strong>वीडियो एडिट करो</strong>
          <span className="muted">अपना वीडियो अपलोड करो, बताओ क्या बदलना है</span>
        </a>
        <a className="bigcard" href="#/create">
          <span className="bigicon" aria-hidden>✦</span>
          <strong>टॉपिक से वीडियो बनाओ</strong>
          <span className="muted">टॉपिक दो, अवतार के साथ वीडियो पाओ</span>
        </a>
      </div>

      <h2 className="section">हाल के प्रोजेक्ट</h2>
      {error && <div className="msg error">{error}</div>}
      {projects === null && !error && <p className="muted">लोड हो रहा है…</p>}
      {projects && projects.length === 0 && <p className="muted">अभी कोई प्रोजेक्ट नहीं है।</p>}
      {projects && projects.length > 0 && (
        <ul className="list">
          {projects.map((p) => (
            <li key={p.id}>
              <span className={"tag " + p.kind}>{p.kind === "edit" ? "एडिट" : "बनाओ"}</span>
              {p.kind === "edit" ? <a className="grow" href={`#/edit/${p.id}`}>{p.title}</a> : <span className="grow">{p.title}</span>}
              <span className="muted small">{STATUS[p.status] || p.status}</span>
              <span className="muted small">{new Date(p.updated_at * 1000).toLocaleDateString("hi-IN")}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
