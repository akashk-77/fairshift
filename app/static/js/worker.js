const TK = "fs_worker";
const T = {
  en: {conditions:"Working conditions",shift:"Shift",pay:"Payslip",report:"Hazard",feedback:"Feedback",skills:"Skills",code:"Worker code",pin:"PIN",login:"Log in",logout:"Log out",
    checkin:"Check in",checkout:"Check out",scan:"Scan site QR",manual:"Or type site code",gps:"Use my location",working:"You are on shift",off:"You are off shift",
    send:"Send",ph:"Tell us what is unsafe…",anon:"Your name is never saved with this review.",listen:"Read aloud",month:"Month",manager:"Manager",
    speak:"Speak",stop:"Stop",sent:"Sent. Thank you.",none:"Nothing here yet",open:"Open",acknowledged:"Seen",in_progress:"Being fixed",resolved:"Fixed",hello:"Hello",
    myreports:"My reports",download:"Download my passport",since:"Since",hours:"hours"},
  hi: {conditions:"काम की स्थिति",shift:"शिफ्ट",pay:"वेतन पर्ची",report:"खतरा",feedback:"राय",skills:"हुनर",code:"कर्मचारी कोड",pin:"पिन",login:"लॉग इन",logout:"लॉग आउट",
    checkin:"हाज़िरी लगाएं",checkout:"काम खत्म",scan:"साइट QR स्कैन करें",manual:"या साइट कोड लिखें",gps:"मेरी लोकेशन का उपयोग करें",working:"आप ड्यूटी पर हैं",off:"आप ड्यूटी पर नहीं हैं",
    send:"भेजें",ph:"क्या असुरक्षित है, बताएं…",anon:"इस राय के साथ आपका नाम कभी सेव नहीं होता।",listen:"सुनें",month:"महीना",manager:"मैनेजर",
    speak:"बोलें",stop:"रुकें",sent:"भेज दिया। धन्यवाद।",none:"अभी कुछ नहीं",open:"खुला",acknowledged:"देखा गया",in_progress:"ठीक हो रहा है",resolved:"ठीक हो गया",hello:"नमस्ते",
    myreports:"मेरी रिपोर्ट",download:"मेरा पासपोर्ट डाउनलोड करें",since:"से",hours:"घंटे"},
  ta: {conditions:"பணிச்சூழல்",shift:"ஷிஃப்ட்",pay:"சம்பளம்",report:"ஆபத்து",feedback:"கருத்து",skills:"திறன்கள்",code:"ஊழியர் குறியீடு",pin:"பின்",login:"உள்நுழை",logout:"வெளியேறு",
    checkin:"வருகை பதிவு",checkout:"வேலை முடிந்தது",scan:"தளத்தின் QR ஸ்கேன் செய்",manual:"அல்லது தள குறியீட்டை உள்ளிடு",gps:"என் இருப்பிடத்தைப் பயன்படுத்து",working:"நீங்கள் பணியில் இருக்கிறீர்கள்",off:"நீங்கள் பணியில் இல்லை",
    send:"அனுப்பு",ph:"எது பாதுகாப்பற்றது என்று சொல்லுங்கள்…",anon:"இந்த கருத்துடன் உங்கள் பெயர் சேமிக்கப்படாது.",listen:"கேளுங்கள்",month:"மாதம்",manager:"மேலாளர்",
    speak:"பேசுங்கள்",stop:"நிறுத்து",sent:"அனுப்பப்பட்டது. நன்றி.",none:"இன்னும் எதுவும் இல்லை",open:"திறந்தது",acknowledged:"பார்க்கப்பட்டது",in_progress:"சரிசெய்யப்படுகிறது",resolved:"சரிசெய்யப்பட்டது",hello:"வணக்கம்",
    myreports:"என் புகார்கள்",download:"என் பாஸ்போர்ட்டை பதிவிறக்கு",since:"முதல்",hours:"மணி"},
  te: {conditions:"పని పరిస్థితులు",shift:"షిఫ్ట్",pay:"జీతం",report:"ప్రమాదం",feedback:"అభిప్రాయం",skills:"నైపుణ్యాలు",code:"ఉద్యోగి కోడ్",pin:"పిన్",login:"లాగిన్",logout:"లాగ్ అవుట్",
    checkin:"హాజరు వేయండి",checkout:"పని ముగిసింది",scan:"సైట్ QR స్కాన్ చేయండి",manual:"లేదా సైట్ కోడ్ నమోదు చేయండి",gps:"నా లొకేషన్ ఉపయోగించండి",working:"మీరు డ్యూటీలో ఉన్నారు",off:"మీరు డ్యూటీలో లేరు",
    send:"పంపండి",ph:"ఏది సురక్షితం కాదో చెప్పండి…",anon:"ఈ అభిప్రాయంతో మీ పేరు ఎప్పుడూ సేవ్ కాదు.",listen:"వినండి",month:"నెల",manager:"మేనేజర్",
    speak:"మాట్లాడండి",stop:"ఆపండి",sent:"పంపబడింది. ధన్యవాదాలు.",none:"ఇంకా ఏమీ లేదు",open:"తెరిచి ఉంది",acknowledged:"చూశారు",in_progress:"సరిచేస్తున్నారు",resolved:"సరిచేశారు",hello:"నమస్కారం",
    myreports:"నా నివేదికలు",download:"నా పాస్‌పోర్ట్ డౌన్‌లోడ్",since:"నుండి",hours:"గంటలు"},
};
const SPEECH = {en: "en-IN", hi: "hi-IN", ta: "ta-IN", te: "te-IN"};
const TABS = [["shift", "📍"], ["pay", "💰"], ["report", "⚠️"], ["feedback", "⭐"], ["skills", "🎓"]];
let lang = localStorage.getItem("fs_lang") || "en", me = null, view = "shift";
const t = k => (T[lang] || T.en)[k] || T.en[k] || k;
const call = (p, o = {}) => api(p, {...o, tokenKey: TK});

function speak(text) {
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text); u.lang = SPEECH[lang]; speechSynthesis.speak(u);
}
const listenBtn = id => "speechSynthesis" in window ? `<button class="btn ghost small" id="${id}">🔊 ${t("listen")}</button>` : "";

function shell(inner) {
  $("#app").innerHTML = `<div class="top"><b>🦺 FairShift</b><span class="row">
    <select id="lang" aria-label="Language">${[["en","English"],["hi","हिन्दी"],["ta","தமிழ்"],["te","తెలుగు"]]
      .map(([c, n]) => `<option value="${c}" ${c === lang ? "selected" : ""}>${n}</option>`).join("")}</select>
    ${me ? `<button class="btn ghost small" id="out" style="color:#fff;border-color:#fff3">${t("logout")}</button>` : ""}</span></div>
    <main class="w">${inner}</main>`;
  $("#lang").onchange = e => { lang = e.target.value; localStorage.setItem("fs_lang", lang); me ? render() : showLogin(); };
  const out = $("#out"); if (out) out.onclick = () => { sessionStorage.removeItem(TK); location.reload(); };
}

function showLogin() {
  shell(`<a class="back" href="/">← FairShift</a><div class="card"><h2>🦺 FairShift</h2><label>${t("code")}</label><input id="code" autocomplete="username" autocapitalize="characters">
    <label>${t("pin")}</label><input id="pin" type="password" inputmode="numeric" autocomplete="current-password">
    <p class="err" id="err" role="alert"></p><button class="btn vest" id="go">${t("login")}</button>
    <p class="muted" id="hint"></p></div>`);
  api("/api/meta").then(m => { if (m.demo) $("#hint").textContent = "Demo: CON01, FAC01, HOS01 or COL01 · PIN 1234"; }).catch(() => {});
  $("#go").onclick = async () => {
    try {
      const r = await api("/api/auth/worker", {method: "POST", body: {code: $("#code").value, pin: $("#pin").value}});
      sessionStorage.setItem(TK, r.token);
      if (!localStorage.getItem("fs_lang")) { lang = r.language; }
      start();
    } catch (e) { $("#err").textContent = e.message; }
  };
}

async function start() { me = await call("/api/me"); render(); }

function render() {
  document.querySelector("nav.tabs")?.remove();
  shell(`<p class="muted">${t("hello")}, <b>${esc(me.name)}</b> · ${esc(me.site)}</p><div id="view"></div>`);
  document.body.insertAdjacentHTML("beforeend", `<nav class="tabs" role="tablist">${TABS.map(([k, i]) =>
    `<button role="tab" aria-selected="${k === view}" data-v="${k}"><span>${i}</span>${t(k)}</button>`).join("")}</nav>`);
  document.querySelectorAll("nav.tabs button").forEach(b => b.onclick = () => { view = b.dataset.v; render(); });
  ({shift: vShift, pay: vPay, report: vReport, feedback: vFeedback, skills: vSkills})[view]($("#view"));
}

async function vShift(el) {
  const s = await call("/api/shifts/mine?days=7");
  const canScan = "BarcodeDetector" in window;
  el.innerHTML = `<div class="card"><div class="big">${s.on_shift ? "✅" : "⏸️"}</div><h2>${s.on_shift ? t("working") : t("off")}</h2>
    ${s.on_shift ? `<p class="muted">${t("since")} ${fmtTime(s.since)}</p><button class="btn vest" id="co">🏁 ${t("checkout")}</button>` : `
    ${canScan ? `<button class="btn vest" id="scan">📷 ${t("scan")}</button><video id="cam" hidden playsinline muted></video>` : ""}
    <label>${t("manual")}</label><input id="qr" placeholder="FS|…"><button class="btn" id="qrgo">✅ ${t("checkin")}</button>
    <button class="btn ghost" id="gps" style="margin-top:10px">📍 ${t("gps")}</button>`}
    <p class="err" id="msg" role="alert"></p></div>
    <div class="card">${s.shifts.length ? `<table>${s.shifts.map(x => `<tr><td>${fmtTime(x.check_in)}</td><td>${x.hours} ${t("hours")}</td>
      <td>${x.overtime_hours ? `<span class="pill medium">+${x.overtime_hours} OT</span>` : ""}</td></tr>`).join("")}</table>` : t("none")}</div>`;
  const done = p => async () => { try { const r = await p(); speak(r); vShift(el); } catch (e) { $("#msg").textContent = e.message; } };
  const doIn = body => done(async () => { await call("/api/shifts/check-in", {method: "POST", body}); return t("working"); });
  if ($("#co")) $("#co").onclick = done(async () => { const r = await call("/api/shifts/check-out", {method: "POST"}); return `${r.hours} ${t("hours")}`; });
  if ($("#qrgo")) $("#qrgo").onclick = () => doIn({qr: $("#qr").value.trim()})();
  if ($("#gps")) $("#gps").onclick = () => navigator.geolocation.getCurrentPosition(
    p => doIn({lat: p.coords.latitude, lng: p.coords.longitude})(), () => $("#msg").textContent = "Location blocked");
  if ($("#scan")) $("#scan").onclick = async () => {
    try {
      const v = $("#cam"), stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: "environment"}});
      v.hidden = false; v.srcObject = stream; await v.play();
      const det = new BarcodeDetector({formats: ["qr_code"]}); let fin = false;
      const loop = async () => {
        if (fin) return;
        try { const r = await det.detect(v); if (r.length) { fin = true; stream.getTracks().forEach(x => x.stop()); doIn({qr: r[0].rawValue})(); return; } } catch {}
        requestAnimationFrame(loop);
      };
      loop();
    } catch { $("#msg").textContent = "Camera blocked"; }
  };
}

async function vPay(el) {
  const m = new Date().toISOString().slice(0, 7);
  el.innerHTML = `<div class="card"><label>${t("month")}</label><input type="month" id="mon" value="${m}"><div id="slip"></div></div>`;
  const load = async () => {
    const r = await call(`/api/payslip?month=${$("#mon").value}&lang=${lang}`), d = r.data, L = r.labels;
    const rows = [["days_worked", d.days_worked], ["regular_hours", d.regular_hours], ["overtime_hours", d.overtime_hours],
      ["rate", "₹" + d.rate], ["basic_pay", "₹" + d.basic_pay], ["overtime_pay", `₹${d.overtime_pay} (×${r.ot_multiplier})`],
      ["gross", "₹" + d.gross], ["pf", "− ₹" + d.pf], ["esi", "− ₹" + d.esi]];
    $("#slip").innerHTML = `<h2>💰 ${esc(L.title)}</h2><table class="pay">${rows.map(([k, v]) => `<tr><td>${esc(L[k])}</td><td>${esc(v)}</td></tr>`).join("")}
      <tr class="net"><td>${esc(L.net)}</td><td>₹${d.net}</td></tr></table><p>${esc(r.summary)}</p>${listenBtn("say")}`;
    if ($("#say")) $("#say").onclick = async () => {
      speak(r.summary);
      try { const x = await call(`/api/payslip/explain?month=${$("#mon").value}&lang=${lang}`); speak(x.text); } catch {}
    };
  };
  $("#mon").onchange = load; load();
}

let rec = null;
async function vReport(el) {
  const canRec = !!(navigator.mediaDevices && window.MediaRecorder);
  el.innerHTML = `<div class="card"><textarea id="txt" rows="4" maxlength="1500" placeholder="${esc(t("ph"))}"></textarea>
    ${canRec ? `<button class="btn ghost" id="mic">🎙️ ${t("speak")}</button>` : ""}
    <button class="btn vest" id="snd" style="margin-top:10px">📤 ${t("send")}</button><p class="err" id="msg" role="alert"></p></div>
    <h2>${t("myreports")}</h2><div id="mine"></div>`;
  const refresh = async () => {
    const rows = await call("/api/safety/mine");
    $("#mine").innerHTML = rows.length ? rows.map(r => `<div class="card"><div class="row"><span class="pill ${r.severity}">${esc(r.severity)}</span>
      <span class="pill ${r.status === "resolved" ? "resolved" : ""}">${t(r.status)}</span></div><p>${esc(r.summary)}</p>${r.admin_note ? `<p class="muted">💬 ${esc(r.admin_note)}</p>` : ""}</div>`).join("") : `<p class="muted">${t("none")}</p>`;
  };
  const after = r => { $("#msg").className = "ok"; $("#msg").textContent = t("sent"); speak(t("sent")); $("#txt").value = ""; refresh(); };
  $("#snd").onclick = async () => {
    try { after(await call("/api/safety", {method: "POST", body: {description: $("#txt").value, lang}})); }
    catch (e) { $("#msg").className = "err"; $("#msg").textContent = e.message; }
  };
  if ($("#mic")) $("#mic").onclick = async () => {
    const b = $("#mic");
    if (rec) { rec.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true}), chunks = [];
      rec = new MediaRecorder(stream); b.classList.add("rec"); b.textContent = "⏹️ " + t("stop");
      rec.ondataavailable = e => chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach(x => x.stop()); const r = rec; rec = null; b.classList.remove("rec"); b.textContent = "🎙️ " + t("speak");
        const blob = new Blob(chunks, {type: r.mimeType}), fr = new FileReader();
        fr.onload = async () => {
          try { after(await call("/api/safety/voice", {method: "POST", body: {audio_b64: fr.result.split(",")[1], mime: (r.mimeType || "audio/webm").split(";")[0], lang}})); }
          catch (e) { $("#msg").className = "err"; $("#msg").textContent = e.message; }
        };
        fr.readAsDataURL(blob);
      };
      rec.start(); setTimeout(() => rec && rec.state === "recording" && rec.stop(), 30000);
    } catch { $("#msg").textContent = "Microphone blocked"; }
  };
  refresh();
}

function vFeedback(el) {
  let rating = 0;
  el.innerHTML = `<div class="card"><p>🔒 ${t("anon")}</p><label>${t("manager")}</label>
    <select id="mgr"><option value="">🏭 ${t("conditions")}</option>${me.managers.map(m => `<option value="${m.id}">${esc(m.name)}</option>`).join("")}</select>
    <div class="stars" id="st">${[1, 2, 3, 4, 5].map(n => `<button data-n="${n}" aria-label="${n}">⭐</button>`).join("")}</div>
    <textarea id="cm" rows="3" maxlength="600"></textarea><button class="btn vest" id="go">📤 ${t("send")}</button><p class="err" id="msg" role="alert"></p></div>`;
  document.querySelectorAll("#st button").forEach(b => b.onclick = () => {
    rating = +b.dataset.n; document.querySelectorAll("#st button").forEach(x => x.classList.toggle("on", +x.dataset.n <= rating));
  });
  $("#go").onclick = async () => {
    try {
      if (!rating) throw new Error("⭐ 1–5");
      await call("/api/feedback", {method: "POST", body: {manager_id: $("#mgr").value ? +$("#mgr").value : null, rating, comment: $("#cm").value}});
      $("#msg").className = "ok"; $("#msg").textContent = t("sent"); speak(t("sent")); $("#cm").value = "";
    } catch (e) { $("#msg").className = "err"; $("#msg").textContent = e.message; }
  };
}

async function vSkills(el) {
  const p = await call("/api/passport");
  el.innerHTML = `<div class="card"><h2>🎓 ${esc(p.name)}</h2><p class="muted">${esc(p.job_title)} · ${esc(p.employer_site)}<br>✔ ${p.verified_shifts} shifts</p>
    ${p.skills.length ? `<table>${p.skills.map(s => `<tr><td><b>${esc(s.name)}</b><br><span class="muted">${esc(s.issuer || "")}</span></td><td><span class="pill">${esc(s.kind)}</span></td><td>${esc(s.issued_on || "")}</td></tr>`).join("")}</table>` : t("none")}
    <button class="btn ghost" id="dl" style="margin-top:12px">⬇️ ${t("download")}</button></div>`;
  $("#dl").onclick = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(p, null, 2)], {type: "application/json"}));
    a.download = `skill-passport-${p.code}.json`; a.click();
  };
}

if ("serviceWorker" in navigator) { /* intentionally none: keep the app stateless and tiny */ }
sessionStorage.getItem(TK) ? start().catch(showLogin) : showLogin();
