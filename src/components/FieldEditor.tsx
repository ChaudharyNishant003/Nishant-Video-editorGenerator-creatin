import type { Field } from "../types";

// Renders a single provider field (secret or param) as the right control.
export function FieldEditor({
  field,
  value,
  onChange,
}: {
  field: Field;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="field">
      <label>{field.label}</label>
      {field.type === "select" ? (
        <select className="select" value={value ?? field.default ?? ""} onChange={(e) => onChange(e.target.value)}>
          {field.options?.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          className="input"
          type={field.type === "password" ? "password" : field.type === "number" ? "number" : "text"}
          value={value ?? field.default ?? ""}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          autoComplete="off"
        />
      )}
      {field.help && <span className="hint">{field.help}</span>}
    </div>
  );
}
