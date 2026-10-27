const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
async function api(path, {method = "GET", body, tokenKey} = {}) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  const tk = tokenKey && sessionStorage.getItem(tokenKey);
  if (tk) headers.Authorization = "Bearer " + tk;
  const r = await fetch(path, {method, headers, body: body ? JSON.stringify(body) : undefined});
  if (r.status === 401 && tokenKey && tk) { sessionStorage.removeItem(tokenKey); location.reload(); }
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.blob();
  if (!r.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map(x => x.msg).join("; ") : `Server error (${r.status}). Restart the server or reset the database.`);
  }
  return data;
}
const fmtTime = iso => new Date(iso).toLocaleString([], {day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"});
