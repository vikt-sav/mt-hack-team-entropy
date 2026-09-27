window.__BUILD = "v10";

const BASEMAPS = [
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  "https://tiles.openfreemap.org/styles/dark",
];

const FALLBACK_STYLE = {
  version: 8,
  name: "fallback-dark",
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#10161f" } }],
};

const HAS_MAPLIBRE = typeof maplibregl !== "undefined";

let map = null;
let mapReady = false;
let routesLoaded = false;
let lastData = null;
let lastRender = 0;
let lastJson = "";
let fitDone = false;
let mapDisabled = false;
let basemapIdx = 0;
let styleOk = false;
let watchdog = null;
let lastAttempt = Date.now();
const markers = new Map();
const routeLines = new Map();

function projectOntoLine(lat, lon, flat, maxM) {
  let best = -1;
  let bd = Infinity;
  for (let i = 0; i < flat.length; i += 2) {
    const dx = (flat[i] - lon) * 63000;
    const dy = (flat[i + 1] - lat) * 111132;
    const d = dx * dx + dy * dy;
    if (d < bd) {
      bd = d;
      best = i;
    }
  }
  if (Math.sqrt(bd) > maxM) return null;
  return { lat: flat[best + 1], lon: flat[best] };
}

function initMap() {
  if (!HAS_MAPLIBRE) {
    disableMap("библиотека карты не загрузилась");
    return;
  }
  try {
    map = new maplibregl.Map({
      container: "map",
      style: BASEMAPS[0],
      center: [37.6, 55.7],
      zoom: 9.5,
      fadeDuration: 0,
      attributionControl: false,
    });
    map.on("load", onMapReady);
    map.on("error", () => {
      // Ошибка до первой успешной загрузки стиля = подложка недоступна
      // (CDN заблокирован/недоступен) — пробуем следующую в цепочке.
      if (!styleOk) nextBasemap();
    });
    armWatchdog();
  } catch (e) {
    disableMap("Карта не запустилась: " + e);
  }
}

function armWatchdog() {
  clearTimeout(watchdog);
  watchdog = setTimeout(() => {
    if (!styleOk) nextBasemap();
  }, 8000);
}

function nextBasemap() {
  if (!map || mapReady) return;
  const now = Date.now();
  if (now - lastAttempt < 1500) return;
  lastAttempt = now;
  let style = null;
  if (basemapIdx < BASEMAPS.length - 1) {
    basemapIdx += 1;
    style = BASEMAPS[basemapIdx];
  } else if (basemapIdx === BASEMAPS.length - 1) {
    basemapIdx += 1;
    style = FALLBACK_STYLE;
    const hint = document.getElementById("mapHint");
    if (hint) hint.classList.remove("hidden");
  } else {
    return;
  }
  routesLoaded = false;
  try {
    map.setStyle(style);
  } catch (e) {}
  armWatchdog();
}

function onMapReady() {
  styleOk = true;
  clearTimeout(watchdog);
  mapReady = true;
  loadRoutes();
  if (lastData) renderData(lastData);
}

function disableMap(reason) {
  mapDisabled = true;
  const el = document.getElementById("map");
  if (el) el.style.display = "none";
  document.body.classList.add("no-map");
  window.__mapReason = reason;
}

initMap();
if (map) {
  map.on("styledata", () => {
    if (map.isStyleLoaded()) {
      styleOk = true;
      clearTimeout(watchdog);
      if (!routesLoaded) loadRoutes();
    }
  });
}

async function loadRoutes() {
  try {
    const res = await fetch("/routes");
    const geo = await res.json();
    const all = geo.features || [];
    const lines = { type: "FeatureCollection", features: all.filter((f) => f.geometry.type === "LineString") };
    const stops = { type: "FeatureCollection", features: all.filter((f) => f.geometry.type === "Point") };
    routeLines.clear();
    for (const f of lines.features) {
      const flat = new Float64Array(f.geometry.coordinates.length * 2);
      f.geometry.coordinates.forEach((c, i) => {
        flat[i * 2] = c[0];
        flat[i * 2 + 1] = c[1];
      });
      routeLines.set(f.properties.tr_id, flat);
    }
    if (!map.getSource("routes")) {
      map.addSource("routes", { type: "geojson", data: lines });
    }
    if (!map.getLayer("routes-line")) {
      map.addLayer({
        id: "routes-line",
        type: "line",
        source: "routes",
        paint: { "line-color": "#3b577a", "line-width": 2.5, "line-opacity": 0.6 },
      });
    }
    if (!map.getSource("stops")) {
      map.addSource("stops", { type: "geojson", data: stops });
    }
    if (!map.getLayer("stops-circle")) {
      map.addLayer({
        id: "stops-halo",
        type: "circle",
        source: "stops",
        paint: { "circle-radius": 5.5, "circle-color": "#0b1017", "circle-opacity": 0.55 },
      });
      map.addLayer({
        id: "stops-circle",
        type: "circle",
        source: "stops",
        paint: {
          "circle-radius": 3.2,
          "circle-color": "#cfd8e3",
          "circle-stroke-color": "#0b1017",
          "circle-stroke-width": 1.2,
        },
      });
      map.on("mouseenter", "stops-circle", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "stops-circle", () => { map.getCanvas().style.cursor = ""; });
      map.on("click", "stops-circle", (e) => {
        const f = e.features && e.features[0];
        if (!f) return;
        const p = f.properties || {};
        const name = p.name && p.name !== "null" ? p.name : null;
        const title = name ? name : `остановка ${p.stop_id}`;
        new maplibregl.Popup({ offset: 10, maxWidth: "260px" })
          .setLngLat(e.lngLat)
          .setHTML(
            `<div class="pp-t">${title}</div>` +
            `<div class="pp-r"><span>ТС</span><b>${p.tr_id}</b></div>` +
            (name ? `<div class="pp-r"><span>Код остановки</span><b>${p.stop_id}</b></div>` : "") +
            `<div class="pp-r"><span>По порядку следования</span><b>${(p.order || 0) + 1}</b></div>`
          )
          .addTo(map);
      });
    }
    routesLoaded = true;
  } catch (e) {}
}

function colorFor(predMin) {
  if (predMin >= 5) return "#e74c3c";
  if (predMin >= 2) return "#e67e22";
  if (predMin >= 0.5) return "#f1c40f";
  return "#2ecc71";
}

function fmtMin(seconds) {
  if (seconds == null) return "—";
  const m = seconds / 60;
  return (m > 0 ? "+" : "") + m.toFixed(1) + " мин";
}

function hhmm(iso) {
  return iso ? new Date(iso).toLocaleTimeString().slice(0, 5) : "—";
}

function bearingBetween(a, b) {
  const p1 = (a.lat * Math.PI) / 180, p2 = (b.lat * Math.PI) / 180;
  const dl = ((b.lon - a.lon) * Math.PI) / 180;
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (Math.atan2(y, x) * 180) / Math.PI;
}

function shortestAngle(from, to) {
  return ((to - from + 540) % 360) - 180;
}

function popupHtml(v) {
  let stuck = "";
  if (v.stuck_street) {
    const dur = v.stuck_s != null ? ` (${Math.round(v.stuck_s / 60)} мин)` : "";
    stuck = `<div class="pp-stuck">участок застревания: ${v.stuck_street}${dur}</div>`;
  }
  return (
    `<div class="pp-t">ТС ${v.tr_id}</div>` +
    `<div class="pp-r"><span>Остановка</span><b>${v.stop_id} · план ${hhmm(v.planned_arrival)}</b></div>` +
    `<div class="pp-r"><span>Факт-отклонение</span><b>${fmtMin(v.est_dev_s)}</b></div>` +
    `<div class="pp-r"><span>Прогноз +${Math.round((v.horizon_s || 720) / 60)} мин</span>` +
    `<b style="color:${colorFor((v.pred_s || 0) / 60)}">${fmtMin(v.pred_s)}</b></div>` +
    (v.speed_last != null ? `<div class="pp-r"><span>Скорость</span><b>${Math.round(v.speed_last)} км/ч</b></div>` : "") +
    stuck +
    `<button class="pp-chat" data-tr="${v.tr_id}">Написать водителю</button>`
  );
}

function renderAlerts(alerts) {
  const el = document.getElementById("alerts");
  el.innerHTML = "";
  if (!alerts.length) {
    el.innerHTML = '<li class="empty">Задержек в горизонте 10–15 мин не прогнозируется</li>';
    return;
  }
  for (const a of alerts.slice(0, 8)) {
    const li = document.createElement("li");
    li.className = "incident";
    li.innerHTML =
      `<div><span class="vid">ТС ${a.tr_id}</span>` +
      `<span class="badge" style="background:${colorFor(a.pred_s / 60)}">${fmtMin(a.pred_s)}</span><br/>` +
      `<span class="route">остановка ${a.stop_id} · план ${hhmm(a.planned_arrival)} · через ${Math.round((a.horizon_s || 0) / 60)} мин</span><br/>` +
      `<span class="cause">причина: ${a.cause || "—"}</span><br/>` +
      (a.stuck_street ? `<span class="stuckline">участок застревания: ${a.stuck_street}${a.stuck_s != null ? " · " + Math.round(a.stuck_s / 60) + " мин" : ""}</span><br/>` : "") +
      `<span class="rec">▶ ${a.recommendation || ""}</span></div>`;
    li.addEventListener("click", () => {
      if (coordOk(a) && map) map.flyTo({ center: [a.lon, a.lat], zoom: 13 });
    });
    el.appendChild(li);
  }
}

function renderList(vehicles) {
  const listEl = document.getElementById("list");
  listEl.innerHTML = "";
  for (const v of vehicles.slice(0, 25)) {
    const li = document.createElement("li");
    li.innerHTML =
      `<div><span class="vid">ТС ${v.tr_id}</span><br/><span class="route">план ${hhmm(v.planned_arrival)} · факт-откл. ${fmtMin(v.est_dev_s)}</span></div>` +
      `<div class="pred" style="color:${colorFor((v.pred_s || 0) / 60)}">${fmtMin(v.pred_s)}</div>`;
    listEl.appendChild(li);
  }
}

function coordOk(v) {
  return typeof v.lat === "number" && typeof v.lon === "number" &&
    isFinite(v.lat) && isFinite(v.lon) &&
    Math.abs(v.lat) <= 90 && Math.abs(v.lon) <= 180;
}

function chatFocused() {
  const a = document.activeElement;
  return !!a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA");
}

function updatePopup(s, v) {
  if (chatFocused()) return;
  const popup = s.marker.getPopup();
  if (popup && popup.isOpen()) popup.setHTML(popupHtml(v));
}

function renderVehicles(vehicles) {
  if (mapDisabled || !map) return;
  const seen = new Set();
  const now = performance.now();
  const dtWall = lastVehicleRender ? Math.min(Math.max(now - lastVehicleRender, 800), 6000) : 0;
  lastVehicleRender = now;
  for (const v of vehicles) {
    const mlat = typeof v.disp_lat === "number" && isFinite(v.disp_lat) ? v.disp_lat : v.lat;
    const mlon = typeof v.disp_lon === "number" && isFinite(v.disp_lon) ? v.disp_lon : v.lon;
    if (!coordOk({ lat: mlat, lon: mlon })) continue;
    seen.add(v.tr_id);
    const color = colorFor((v.pred_s || 0) / 60);
    let pos = { lat: mlat, lon: mlon };
    // страховка на клиенте: прижимаем маркер к своей линии маршрута (<=600 м)
    const line = routeLines.get(v.tr_id);
    if (line) {
      const proj = projectOntoLine(pos.lat, pos.lon, line, 600);
      if (proj) pos = proj;
    }
    let s = markers.get(v.tr_id);
    try {
      if (!s) {
        const el = document.createElement("div");
        el.className = "veh-marker";
        const rot = document.createElement("div");
        rot.className = "veh-marker-rot";
        rot.innerHTML = arrowSvg(color);
        el.appendChild(rot);
        const marker = new maplibregl.Marker({ element: el })
          .setLngLat([pos.lon, pos.lat])
          .setPopup(
            new maplibregl.Popup({ offset: 14, maxWidth: "280px" }).setHTML(popupHtml(v))
          );
        marker.addTo(map);
        s = {
          marker,
          rot,
          cur: pos,
          from: pos,
          to: pos,
          heading: null,
          fromHeading: null,
          toHeading: null,
          t0: 0,
          dur: 0,
          animating: false,
          speedKmh: null,
          vMps: 0,
          drVx: 0,
          drVy: 0,
          drT0: 0,
          drUntil: 0,
        };
        markers.set(v.tr_id, s);
      }
      s.rot.innerHTML = arrowSvg(color);
      s.speedKmh = typeof v.speed_last === "number" && isFinite(v.speed_last) ? v.speed_last : null;
      let heading = typeof v.heading === "number" && isFinite(v.heading) && v.heading >= 0 && v.heading < 360
        ? v.heading
        : null;
      if (heading == null && s.to && distM(s.to, pos) >= 15) heading = bearingBetween(s.to, pos);
      if (heading == null) heading = s.heading != null ? s.heading : 0;
      const moved = s.to ? distM(s.to, pos) : 0;
      if (s.speedKmh != null && s.speedKmh < 2) {
        // ТС стоит: курс в телеметрии шумит — стрелку на месте не вертим
        heading = s.heading != null ? s.heading : heading;
      } else if (s.heading != null && moved < 80) {
        const dh = Math.abs(shortestAngle(s.heading, heading));
        if (dh > 120) heading = s.heading;   // резкий разворот при малом смещении — шум
      }
      const jump = s.to ? distM(s.to, pos) : 0;
      if (jump > 15000) {
        // телепорт в данных: точку игнорируем, маркер ждёт правдоподобную
        updatePopup(s, v);
        continue;
      }
      if (jump > 2500) {
        // резкий скачок: переносим без анимации, чтобы не "лететь" через карту
        s.from = pos;
        s.to = pos;
        s.cur = pos;
        s.heading = heading;
        s.animating = false;
        s.drUntil = 0;
        s.rot.style.transform = `rotate(${heading}deg)`;
        s.marker.setLngLat([pos.lon, pos.lat]);
        updatePopup(s, v);
        continue;
      }
      if (!dtWall) {
        // первый кадр: ставим сразу, без анимации
        s.from = pos;
        s.to = pos;
        s.cur = pos;
        s.heading = heading;
        s.animating = false;
        s.drUntil = 0;
        s.rot.style.transform = `rotate(${heading}deg)`;
        s.marker.setLngLat([pos.lon, pos.lat]);
        updatePopup(s, v);
        continue;
      }
      const from = s.cur || s.to || pos;
      const legDist = distM(from, pos);
      if (legDist < 4) {
        // достигли цели: стоим до следующего тика (без микро-дрожи)
        s.from = pos;
        s.to = pos;
        s.cur = pos;
        s.heading = heading;
        s.animating = false;
        s.drUntil = 0;
        s.rot.style.transform = `rotate(${heading}deg)`;
        s.marker.setLngLat([pos.lon, pos.lat]);
        updatePopup(s, v);
        continue;
      }
      // Скорость движения по данным (EMA) — переходы между тиками без рывков
      const legV = (legDist / dtWall) * 1000;
      s.vMps = s.vMps ? s.vMps * 0.5 + legV * 0.5 : legV;
      s.vMps = Math.min(Math.max(s.vMps, 2), 250);
      s.from = { lat: from.lat, lon: from.lon };
      s.to = pos;
      s.cur = { lat: from.lat, lon: from.lon };
      s.fromHeading = s.heading != null ? s.heading : heading;
      s.toHeading = heading;
      s.t0 = now;
      s.dur = Math.min(6000, Math.max(400, (legDist / s.vMps) * 1000));
      s.animating = true;
      s.drUntil = 0;
      updatePopup(s, v);
    } catch (e) {}
  }
  for (const [id, s] of markers) {
    if (!seen.has(id)) {
      try {
        s.marker.remove();
      } catch (e) {}
      markers.delete(id);
    }
  }
  if (!fitDone && vehicles.length) {
    const pts = vehicles.filter(coordOk).map((v) => [v.lon, v.lat]);
    if (pts.length) {
      fitDone = true;
      try {
        const bounds = pts.reduce((b, c) => b.extend(c), new maplibregl.LngLatBounds(pts[0], pts[0]));
        map.fitBounds(bounds, { padding: 60, maxZoom: 12 });
      } catch (e) {}
    }
  }
}

function arrowSvg(color) {
  return (
    '<svg width="20" height="20" viewBox="0 0 20 20">' +
    `<path d="M10 2.2 L15.6 16.4 L10 13.2 L4.4 16.4 Z" fill="${color}" ` +
    'stroke="#0b1017" stroke-width="1.6" stroke-linejoin="round"/></svg>'
  );
}

function distM(a, b) {
  const dy = (b.lat - a.lat) * 111132;
  const dx = (b.lon - a.lon) * 111320 * Math.cos((a.lat * Math.PI) / 180);
  return Math.hypot(dx, dy);
}

function animateMarkers() {
  requestAnimationFrame(animateMarkers);
  if (!markers.size) return;
  const now = performance.now();
  for (const s of markers.values()) {
    if (s.animating) {
      const k = s.dur > 0 ? Math.min(1, (now - s.t0) / s.dur) : 1;
      const lat = s.from.lat + (s.to.lat - s.from.lat) * k;
      const lon = s.from.lon + (s.to.lon - s.from.lon) * k;
      const heading = s.fromHeading + shortestAngle(s.fromHeading, s.toHeading) * k;
      s.cur = { lat, lon };
      s.heading = heading;
      try {
        s.marker.setLngLat([lon, lat]);
        s.rot.style.transform = `rotate(${heading}deg)`;
      } catch (e) {
        s.animating = false;
      }
      if (k >= 1) {
        s.animating = false;
        // инерционный накат: продолжаем движение с той же скоростью, пока
        // не придёт следующий тик данных (убирает стоп-старт между снапшотами)
        s.drVx = (s.to.lon - s.from.lon) / Math.max(s.dur, 1);
        s.drVy = (s.to.lat - s.from.lat) / Math.max(s.dur, 1);
        s.drT0 = now;
        s.drUntil = now + Math.min(2500, Math.max(s.dur, 600));
      }
    } else if (s.drUntil > now) {
      if (s.speedKmh != null && s.speedKmh < 2) {
        s.drUntil = 0;
        continue;
      }
      const dt = now - (s.drT0 || now);
      const lon = s.to.lon + s.drVx * dt;
      const lat = s.to.lat + s.drVy * dt;
      s.cur = { lat, lon };
      try {
        s.marker.setLngLat([lon, lat]);
      } catch (e) {
        s.drUntil = 0;
      }
    }
  }
}

let lastVehicleRender = 0;
animateMarkers();

/* --- мок-чат диспетчера с водителем --- */

const chatState = { current: null, history: {}, timer: null };
const DRIVER_REPLIES = [
  "Принято, диспетчер.",
  "Понял, выполняю.",
  "Хорошо, сокращаю стоянку.",
  "Вижу затор, объеду по соседней улице.",
  "Еду по графику, отклонений нет.",
];

function chatMsgHtml(m) {
  const t = new Date(m.t).toLocaleTimeString().slice(0, 5);
  return `<div class="msg ${m.who}">${m.text}<time>${t}</time></div>`;
}

function renderChat() {
  const trId = chatState.current;
  const box = document.getElementById("chatMsgs");
  box.innerHTML = (chatState.history[trId] || []).map(chatMsgHtml).join("");
  box.scrollTop = box.scrollHeight;
}

function pushChatMsg(trId, who, text) {
  (chatState.history[trId] = chatState.history[trId] || []).push({ who, text, t: Date.now() });
  if (chatState.current === trId) renderChat();
}

function openChat(trId) {
  chatState.current = trId;
  try {
    if (map) map.closePopup();   // попап под панелью чата всё равно не виден,
  } catch (e) {}                 // а его автоперерисовка крадёт фокус ввода
  document.getElementById("chatTitle").textContent = "Чат с водителем";
  document.getElementById("chatSub").textContent = `ТС ${trId} · канал диспетчера`;
  if (!(chatState.history[trId] || []).length) {
    pushChatMsg(trId, "drv", "Водитель ТС " + trId + " на связи.");
  }
  renderChat();
  document.getElementById("chat").classList.remove("hidden");
  document.getElementById("chatInput").focus();
}

function closeChat() {
  document.getElementById("chat").classList.add("hidden");
  chatState.current = null;
}

document.getElementById("chatClose").addEventListener("click", closeChat);

document.getElementById("chatForm").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const input = document.getElementById("chatInput");
  const text = input.value.trim();
  const trId = chatState.current;
  if (!text || trId == null) return;
  pushChatMsg(trId, "disp", text);
  input.value = "";
  clearTimeout(chatState.timer);
  chatState.timer = setTimeout(() => {
    pushChatMsg(trId, "drv", DRIVER_REPLIES[Math.floor(Math.random() * DRIVER_REPLIES.length)]);
  }, 1200);
});

document.addEventListener("click", (ev) => {
  const btn = ev.target.closest(".pp-chat");
  if (btn) {
    const trId = parseInt(btn.dataset.tr, 10);
    if (!Number.isNaN(trId)) openChat(trId);
  }
});

function renderData(data) {
  const vehicles = data.vehicles || [];
  renderAlerts(data.alerts || []);
  renderList(vehicles);
  renderVehicles(vehicles);
  const st = data.stats || {};
  const mapInfo = mapDisabled
    ? `карта отключена (${window.__mapReason || ""})`
    : `на карте: ${markers.size}`;
  document.getElementById("status").textContent =
    (data.degraded ? "поток недоступен — последние данные · " : "онлайн · ") +
    `обновлено: ${data.ts ? new Date(data.ts * 1000).toLocaleTimeString() : "—"}` +
    ` · ТС с прогнозом: ${vehicles.length} · ${mapInfo}`;
  document.getElementById("stats").textContent =
    `build ${window.__BUILD} · записей: ${st.records || 0} · бортов: ${st.vehicles || 0} · прогнозов: ${st.predicts || 0}`;
}

function render(data) {
  lastData = data;
  const now = Date.now();
  if (now - lastRender < 800) return;
  lastRender = now;
  const js = JSON.stringify(data.vehicles || []) + "|" + (data.ts || "") + "|" + (data.alerts || []).length;
  if (js === lastJson && markers.size >= 0 && lastJson !== "") {
    return;
  }
  lastJson = js;
  renderData(data);
}

async function pollOnce() {
  try {
    const res = await fetch("/snapshot");
    render(await res.json());
  } catch (e) {
    document.getElementById("status").textContent = "ошибка соединения: " + e;
  }
}

function startPolling() {
  pollOnce();
  setInterval(pollOnce, 4000);
}

function startWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  try {
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (ev) => render(JSON.parse(ev.data));
    ws.onclose = () => startPolling();
    ws.onerror = () => ws.close();
  } catch (e) {
    startPolling();
  }
}

startWs();
setTimeout(() => {
  if (!document.getElementById("status").textContent.includes("онлайн")) startPolling();
}, 4000);

function renderWhatIf() {
  const k = parseInt(document.getElementById("kSlider").value, 10);
  const d = parseInt(document.getElementById("dSlider").value, 10);
  document.getElementById("kVal").textContent = k;
  document.getElementById("dVal").textContent = d + " с";
  fetch("/whatif", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ extra_vehicles: k, dwell_reduction_s: d }),
  })
    .then((r) => r.json())
    .then((data) => {
      const s = data.summary || {};
      document.getElementById("whatifSummary").textContent =
        `Средний прогноз: ${fmtMin(s.mean_base_pred_s)} → ${fmtMin(s.mean_scenario_pred_s)} ` +
        `(улучшение ${fmtMin(s.improvement_s)}) · интервал: ` +
        `${(s.mean_interval_before_s / 60).toFixed(1)} → ${(s.mean_interval_after_s / 60).toFixed(1)} мин`;
      const el = document.getElementById("whatifList");
      el.innerHTML = "";
      for (const v of (data.vehicles || []).slice(0, 8)) {
        const li = document.createElement("li");
        const improved = v.whatif_s < v.pred_s;
        li.innerHTML =
          `<div><span class="vid">ТС ${v.tr_id}</span></div>` +
          `<div class="pred">${fmtMin(v.pred_s)} → <b style="color:${colorFor(v.whatif_s / 60)}">${fmtMin(v.whatif_s)}</b>` +
          `<small>${improved ? "улучшение" : "без изменений"}</small></div>`;
        el.appendChild(li);
      }
    })
    .catch(() => {});
}

let whatifTimer = null;
function scheduleWhatIf() {
  clearTimeout(whatifTimer);
  whatifTimer = setTimeout(renderWhatIf, 400);
}

document.getElementById("kSlider").addEventListener("input", scheduleWhatIf);
document.getElementById("dSlider").addEventListener("input", scheduleWhatIf);
setInterval(scheduleWhatIf, 8000);
