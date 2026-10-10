// Provider keys live ONLY in this browser's localStorage (PRD §6.5). They are sent to our
// backend per request in the X-Provider-Keys header and never stored on the server.

export type ProviderKeys = Record<string, Record<string, string>>;

const LS_KEY = "aiyt2:keys";

export function loadKeys(): ProviderKeys {
  try {
    const raw = localStorage.getItem(LS_KEY);
    const data = raw ? JSON.parse(raw) : {};
    return data && typeof data === "object" ? (data as ProviderKeys) : {};
  } catch {
    return {};
  }
}

export function saveProviderKeys(providerId: string, fields: Record<string, string>): void {
  const all = loadKeys();
  const clean: Record<string, string> = {};
  for (const [k, v] of Object.entries(fields)) if (v.trim()) clean[k] = v.trim();
  if (Object.keys(clean).length) all[providerId] = clean;
  else delete all[providerId];
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(all));
  } catch {
    /* storage full / private mode — nothing else we can do */
  }
}

export function clearAllKeys(): void {
  try {
    localStorage.removeItem(LS_KEY);
  } catch {
    /* ignore */
  }
}

/** base64(JSON) with UTF-8 safety, for the X-Provider-Keys header. */
export function encodeKeysHeader(keys: ProviderKeys): string {
  const json = JSON.stringify(keys);
  const bytes = new TextEncoder().encode(json);
  let bin = "";
  bytes.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin);
}
