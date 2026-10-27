const TK = "fs_admin";
const call = (p, o = {}) => api(p, {...o, tokenKey: TK});
const SECT = [["all", "All sites"], ["construction", "Construction"], ["factory", "Factory"], ["hospital", "Hospital"], ["education", "College"]];
let sector = "all";

function login() {
  $("#app").innerHTML = `<div class="card" style="max-width:420px;margin:10vh auto;border-top:8px solid var(--denim)"><h1>📊 Employer dashboard</h1>
    <p class="muted">For managers and HR. Workers use <a href="/worker">the worker app</a>.</p>
    <label>Password</label><input id="pw" type="password" autocomplete="current-password"><p class="err" id="err" role="alert"></p>
    <button class="btn vest" id="go">Log in</button></div><p style="text-align:center"><a class="back" href="/">← FairShift home</a> · <a class="back" href="/worker">Worker app</a></p>`;
  $("#go").onclick = async () => {
    try { const r = await api("/api/auth/admin", {method: "POST", body: {password: $("#pw").value}}); sessionStorage.setItem(TK, r.token); dash(); }
    catch (e) { $("#err").textContent = e.message; }
  };
  $("#pw").addEventListener("keydown", e => { if (e.key === "Enter") $("#go").click(); });
}

const pill = l => `<span class="pill ${esc(l)}">${esc(l)}</span>`;

async function dash() {
  $("#app").innerHTML = `<header><h1>🦺 FairShift</h1>
    <div class="seg" role="group" aria-label="Sector">${SECT.map(([k, n]) => `<button data-s="${k}" aria-pressed="${k === sector}">${n}</button>`).join("")}</div>
    <span class="row"><a class="btn ghost small" href="/worker">Worker app</a><button class="btn ghost small" id="out">Log out</button></span></header>
    <div class="kpis" id="kpis"></div>
    <div class="grid2">
      <section class="card"><h2>Attendance, last 14 days</h2><div id="trend"></div></section>
      <section class="card"><h2>AI insights</h2><div id="ins" class="muted">Loading…</div></section>
      <section class="card"><h2>Fatigue alerts</h2><div class="scroll" id="fat"></div></section>
      <section class="card"><h2>Quit risk</h2><div class="scroll" id="att"></div></section>
      <section class="card"><h2>Safety reports</h2><div class="scroll" id="saf"></div></section>
      <section class="card"><h2>Anonymous manager feedback</h2><div id="fb"></div></section>
      <section class="card"><h2>Site check-in QR</h2><select id="site"></select><div id="qr" style="max-width:220px"></div>
        <p class="muted">Print and post at the gate. Workers scan it to check in.</p></section>
      <section class="card"><h2>Add to a skill passport</h2>
        <input id="sc" placeholder="Worker code e.g. FAC02"><input id="sn" placeholder="Skill or training name">
        <select id="sk"><option>training</option><option>certification</option><option>experience</option></select>
        <input id="si" placeholder="Issuer"><button class="btn small" id="sadd">Add</button> <span id="smsg"></span></section>
    </div>`;
  document.querySelectorAll(".seg button").forEach(b => b.onclick = () => { sector = b.dataset.s; dash(); });
  $("#out").onclick = () => { sessionStorage.removeItem(TK); location.reload(); };
  const q = `?sector=${sector}`;
  const [ov, tr, fat, att, saf, fb, sites] = await Promise.all(["overview", "attendance-trend", "fatigue", "attrition", "safety", "feedback"]
    .map(p => call(`/api/admin/${p}${q}`)).concat(call("/api/admin/sites")));

  const k = (n, l, alert) => `<div class="kpi ${alert ? "alert" : ""}"><b>${n}</b>${l}</div>`;
  $("#kpis").innerHTML = k(ov.workers, "Workers") + k(ov.on_shift_now, "On shift now") + k(ov.attendance_today_pct + "%", "Present today") +
    k(ov.high_fatigue, "High fatigue", ov.high_fatigue) + k(ov.high_attrition, "High quit risk", ov.high_attrition) +
    k(ov.open_safety, "Open safety reports", ov.open_safety) + k(ov.overdue_safety, "Overdue: escalate now", ov.overdue_safety) + k(ov.avg_rating ?? "–", "Manager rating /5");

  $("#trend").innerHTML = `<div class="bars">${tr.map(d => `<div style="height:${Math.max(d.pct, 2)}%" title="${d.date}: ${d.present}/${d.total}"></div>`).join("")}</div>
    <div class="xl">${tr.map(d => `<span>${d.date.slice(8)}</span>`).join("")}</div>`;

  const tbl = (head, rows) => rows.length ? `<table><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr>${rows.join("")}</table>` : "<p class='muted'>Nothing to show.</p>";
  $("#fat").innerHTML = tbl(["Worker", "7-day hrs", "Level", "Why"], fat.filter(x => x.score > 0).slice(0, 8).map(x =>
    `<tr><td>${esc(x.name)}<br><span class="muted">${esc(x.code)}</span></td><td>${x.week_hours}</td><td>${pill(x.level)}</td><td>${x.reasons.map(esc).join("; ")}</td></tr>`));
  $("#att").innerHTML = tbl(["Worker", "Risk", "Why"], att.filter(x => x.score > 0).slice(0, 8).map(x =>
    `<tr><td>${esc(x.name)}<br><span class="muted">${esc(x.code)}</span></td><td>${pill(x.level)} ${x.score}</td><td>${x.reasons.map(esc).join("; ")}</td></tr>`));
  $("#saf").innerHTML = tbl(["Issue", "Severity", "Status"], saf.slice(0, 10).map(r => `<tr><td>${esc(r.summary)}<br><span class="muted">${esc(r.site)} · ${esc(r.worker)}</span></td><td>${pill(r.severity)}${r.overdue ? '<br><span class="pill critical">⏰ overdue</span>' : ""}</td>
    <td><select data-id="${r.id}">${["open", "acknowledged", "in_progress", "resolved"].map(s => `<option ${s === r.status ? "selected" : ""}>${s}</option>`).join("")}</select></td></tr>`));
  document.querySelectorAll("#saf select").forEach(s => s.onchange = async () => {
    await call(`/api/admin/safety/${s.dataset.id}`, {method: "PATCH", body: {status: s.value}}); dash();
  });
  $("#fb").innerHTML = fb.length ? fb.map(m => `<p><b>${esc(m.manager)}</b> · ${esc(m.site)} — ${m.avg_rating}/5 from ${m.reviews} reviews
    ${m.comments.map(c => `<br><span class="muted">“${esc(c)}”</span>`).join("")}</p>`).join("") : "<p class='muted'>Managers appear after 3 reviews, so no one can be identified.</p>";

  const list = sites.filter(s => sector === "all" || s.sector === sector);
  $("#site").innerHTML = list.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
  const showQr = async () => {
    const blob = await call(`/api/admin/sites/${$("#site").value}/qr.svg`);
    const old = $("#qr img");
    if (old) URL.revokeObjectURL(old.src);  // free the previous blob instead of leaking one per change
    $("#qr").innerHTML = `<img alt="Site QR" style="width:100%" src="${URL.createObjectURL(blob)}">`;
  };
  $("#site").onchange = showQr; if (list.length) showQr();
  $("#sadd").onclick = async () => {
    try { await call("/api/admin/skills", {method: "POST", body: {worker_code: $("#sc").value, name: $("#sn").value, kind: $("#sk").value, issuer: $("#si").value || null}});
      $("#smsg").className = "ok"; $("#smsg").textContent = "Added"; } catch (e) { $("#smsg").className = "err"; $("#smsg").textContent = e.message; }
  };
  call(`/api/admin/insights${q}`)
    .then(i => { $("#ins").style.whiteSpace = "pre-wrap"; $("#ins").textContent = i.text + (i.ai ? "" : "\n(Rule-based summary: add a Gemini key for AI insights.)"); })
    .catch(e => { $("#ins").textContent = e.message; });  // never leave "Loading…" hanging on an error
}

sessionStorage.getItem(TK) ? dash().catch(login) : login();
