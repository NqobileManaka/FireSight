"use strict";
const API = "/api/v1";
let token = null, role = null, ws = null, selected = null, spreadTimer = null;
const $ = (id) => document.getElementById(id);
const map = L.map("map", { zoomControl: true }).setView([-25.7461, 28.1881], 11);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap" }).addTo(map);
L.control.scale().addTo(map);
const layers = { drones: {}, incidents: {}, hotspots: L.layerGroup().addTo(map), crew: {}, spread: null };
const icon = (color, txt) => L.divIcon({ className: "", html: `<div style="background:${color};color:#fff;border-radius:50%;width:26px;height:26px;display:flex;align-items:center;justify-content:center;font:700 11px system-ui;border:2px solid #fff">${txt}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] });

async function api(path, opts = {}) {
  const r = await fetch(API + path, { ...opts, headers: { "Content-Type": "application/json", Authorization: "Bearer " + token, ...(opts.headers || {}) } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
}

$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const r = await fetch(API + "/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: $("u").value, password: $("p").value }) });
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || "login failed");
    token = body.token; role = body.role;
    $("who").textContent = `${body.user} (${role})`;
    $("login").style.display = "none";
    start();
  } catch (err) { $("loginErr").textContent = err.message; }
});

function start() {
  connect();
  refreshAll();
  $("simBtn").disabled = !["operator", "admin"].includes(role);
  $("closeBtn").disabled = true;
}

function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?token=${token}`);
  ws.onopen = () => { $("status").textContent = "live"; $("status").style.color = "var(--ok)"; };
  ws.onclose = () => { $("status").textContent = "reconnecting..."; $("status").style.color = "var(--warn)"; setTimeout(connect, 2000); };
  ws.onmessage = (m) => handle(JSON.parse(m.data));
}

async function refreshAll() {
  if (["commander", "operator", "admin"].includes(role)) {
    (await api("/drones")).forEach(upsertDrone);
    (await api("/firefighters")).forEach((f) => f.location && upsertCrew(f._id, f.location.coordinates[1], f.location.coordinates[0]));
  }
  await refreshIncidents();
}

function upsertDrone(d) {
  const [lon, lat] = d.location.coordinates;
  if (!layers.drones[d._id]) layers.drones[d._id] = L.marker([lat, lon], { icon: icon("#2b8cff", d._id.slice(-2)) }).addTo(map).bindTooltip(d._id);
  layers.drones[d._id].setLatLng([lat, lon]);
}
function upsertCrew(id, lat, lon) {
  if (!layers.crew[id]) layers.crew[id] = L.marker([lat, lon], { icon: icon("#3ecf8e", id.slice(-2)) }).addTo(map).bindTooltip(id);
  layers.crew[id].setLatLng([lat, lon]);
}

async function refreshIncidents() {
  const list = await api("/incidents");
  $("incidents").innerHTML = "";
  list.forEach((i) => {
    const [lon, lat] = i.location.coordinates;
    if (!layers.incidents[i._id]) layers.incidents[i._id] = L.marker([lat, lon], { icon: icon("#ff4d4d", "🔥") }).addTo(map).bindTooltip(i._id);
    const el = document.createElement("div");
    el.className = i._id === selected ? "sel" : "";
    el.innerHTML = `<b>${i._id}</b> P${i.priority} <span class="badge b${i.maxSeverity}">${["No fire", "Fire", "Critical"][i.maxSeverity]}</span><br><small>${i.status} · ${i.dispatchStatus || ""} ${i.droneId || ""}</small>`;
    el.onclick = () => select(i._id, lat, lon, i.status);
    $("incidents").appendChild(el);
  });
}

function select(id, lat, lon, status) {
  selected = id;
  map.setView([lat, lon], 17);
  $("closeBtn").disabled = !(["commander", "admin"].includes(role) && status === "open");
  $("reportBox").style.display = "none";
  loadSpread();
  clearInterval(spreadTimer);
  spreadTimer = setInterval(loadSpread, 60000);          // FR-05: refresh every 60 s
  refreshIncidents();
}

async function loadSpread() {
  if (!selected || !["commander", "operator", "admin"].includes(role)) return;
  try {
    const f = await api(`/incidents/${selected}/spread`);
    if (layers.spread) map.removeLayer(layers.spread);
    layers.spread = L.geoJSON(f, { style: { color: "#ff9d2b", weight: 2, fillOpacity: 0.18 } }).addTo(map);
    $("spWind").textContent = `${f.properties.weather.windKmh.toFixed(0)} km/h (${f.properties.weather.source})`;
    $("spFwd").textContent = `${f.properties.forwardM} m towards ${f.properties.spreadTowardDeg.toFixed(0)}°`;
    $("spAt").textContent = new Date().toLocaleTimeString();
  } catch (e) { /* no incident data yet */ }
}

function handle(ev) {
  if (ev.type === "telemetry") {
    if (layers.drones[ev.droneId]) layers.drones[ev.droneId].setLatLng([ev.lat, ev.lon]);
    $("tDrone").textContent = ev.droneId; $("tPos").textContent = `${ev.lat.toFixed(5)}, ${ev.lon.toFixed(5)}`;
    $("tAlt").textContent = ev.altitude.toFixed(0) + " m"; $("tBat").textContent = ev.battery + " %"; $("tHead").textContent = ev.heading + "°"; $("tStatus").textContent = ev.status || "-";
  } else if (ev.type === "detection") {
    $("thermal").style.visibility = "visible"; $("thermal").src = "data:image/png;base64," + ev.frameBase64;
    const r = ev.result;
    $("aiClass").innerHTML = `<span class="badge b${r.severity}">${r.classification}</span>`;
    $("aiConf").textContent = (r.confidence * 100).toFixed(1) + " %"; $("aiMs").textContent = r.inferenceMs + " ms"; $("aiHot").textContent = r.hotspots.length;
  } else if (ev.type === "hotspots") {
    layers.hotspots.clearLayers();
    ev.hotspots.forEach((h) => L.circle([h.lat, h.lon], { radius: Math.max(2, Math.sqrt(h.areaM2 / Math.PI)), color: "#ff3b1f", fillOpacity: 0.5 }).addTo(layers.hotspots));
  } else if (ev.type === "alert") {
    $("banner").style.display = "block";
  } else if (ev.type === "location") {
    upsertCrew(ev.firefighterId, ev.lat, ev.lon);
  } else if (ev.type === "message") {
    const d = document.createElement("div"); d.textContent = `[${ev.channel}] ${ev.from}: ${ev.text}`; $("chat").appendChild(d); $("chat").scrollTop = 1e9;
  } else if (ev.type === "incident") {
    if (ev.status === "closed") $("banner").style.display = "none";
    refreshIncidents(); if (ev.status === "closed" && ev.incidentId === selected) showReport();
  }
}

$("simBtn").onclick = async () => {
  const jitter = () => (Math.random() - 0.5) * 0.01;
  const r = await api("/cad/alerts", { method: "POST", body: JSON.stringify({ callId: "CAD-" + Date.now(), priority: 1, lat: -25.7479 + jitter(), lon: 28.2293 + jitter(), description: "Structure fire reported (simulated CAD call)" }) });
  await refreshIncidents(); select(r.incidentId, ...(await api("/incidents/" + r.incidentId)).location.coordinates.slice().reverse(), "open");
};
$("closeBtn").onclick = async () => { await api(`/incidents/${selected}/close`, { method: "POST" }); $("closeBtn").disabled = true; };
$("send").onclick = async () => {
  if (!selected || !$("msg").value) return;
  await api("/messages", { method: "POST", body: JSON.stringify({ incidentId: selected, channel: "command", text: $("msg").value }) });
  $("msg").value = "";
};
async function showReport() {
  try {
    const r = await api(`/incidents/${selected}/report`); const s = r.summary;
    $("reportBox").style.display = "block";
    $("report").textContent = `Report ${r._id}\nIncident ${r.incidentId} (${s.callId})\nDispatch: ${s.dispatchSeconds}s  Duration: ${s.durationSeconds}s\nFrames analysed: ${s.framesAnalysed}\nMax severity: ${["No fire", "Fire", "Critical"][s.maxSeverity]}\nPeak hotspots: ${s.peakHotspots}\nMessages: ${s.messages}\nGenerated in ${r.generationMs} ms`;
  } catch (e) { /* report not available to this role */ }
}
