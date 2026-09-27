const base = "http://localhost:8000";

async function testRest() {
  const res = await fetch(base + "/snapshot");
  const j = await res.json();
  console.log("REST /snapshot:", res.status, "vehicles:", (j.vehicles || []).length, "alerts:", (j.alerts || []).length);
}

function testWs() {
  return new Promise((resolve) => {
    const ws = new WebSocket("ws://localhost:8000/ws");
    let count = 0;
    const timer = setTimeout(() => {
      console.log("WS: timeout after 8s, messages:", count);
      ws.close();
      resolve();
    }, 8000);
    ws.onopen = () => console.log("WS: opened");
    ws.onerror = (e) => console.log("WS: error", e.message || e.type);
    ws.onclose = (e) => console.log("WS: closed", e.code, e.reason);
    ws.onmessage = (ev) => {
      count++;
      if (count === 1) {
        const d = JSON.parse(ev.data);
        console.log("WS: first message, vehicles:", (d.vehicles || []).length, "alerts:", (d.alerts || []).length);
      }
      if (count >= 3) {
        clearTimeout(timer);
        console.log("WS: OK, 3 messages received");
        ws.close();
        resolve();
      }
    };
  });
}

(async () => {
  await testRest().catch((e) => console.log("REST failed:", e.message));
  await testWs();
})();
