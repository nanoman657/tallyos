// Thin fetch wrapper for the TallyOS backend.
const BASE = window.TALLYOS_API || "";

async function request(method, path, body, contentType = "application/json") {
  const raw = typeof body === "string";
  const res = await fetch(BASE + path, {
    method,
    headers: body != null ? { "content-type": contentType } : {},
    body: body == null ? undefined : raw ? body : JSON.stringify(body),
  });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail || res.statusText;
    throw new Error(msg);
  }
  return data;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b ?? {}),
  put: (p, b) => request("PUT", p, b),
  patch: (p, b) => request("PATCH", p, b),
  postText: (p, text, type = "text/csv") => request("POST", p, text, type),
};
