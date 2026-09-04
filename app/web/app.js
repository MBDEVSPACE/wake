(() => {
  "use strict";

  const PIN_KEY = "zima-wol-pin";
  const POLL_MS = 10000;

  const el = (id) => document.getElementById(id);
  const main = el("main");
  const gate = el("gate");
  const list = el("devices");
  const empty = el("empty");
  const editor = el("editor");

  let devices = [];
  let statuses = {};
  let editingId = null;
  let pollTimer = null;

  const pin = () => sessionStorage.getItem(PIN_KEY) || localStorage.getItem(PIN_KEY) || "";

  async function api(path, options = {}) {
    const headers = Object.assign({}, options.headers);
    if (options.body) headers["Content-Type"] = "application/json";
    const stored = pin();
    if (stored) headers["X-Wol-Pin"] = stored;

    const response = await fetch(path, Object.assign({}, options, { headers }));
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) {
      localStorage.removeItem(PIN_KEY);
      sessionStorage.removeItem(PIN_KEY);
      showGate();
      throw new Error("PIN required");
    }
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
    return payload;
  }

  function toast(message) {
    const node = el("toast");
    node.textContent = message;
    node.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { node.hidden = true; }, 3200);
  }

  // --- rendering ---------------------------------------------------------

  function render() {
    list.textContent = "";
    empty.hidden = devices.length > 0;

    for (const device of devices) {
      const state = statuses[device.id];
      const item = document.createElement("li");
      item.className = "device";

      const info = document.createElement("div");

      const title = document.createElement("h2");
      title.textContent = device.name;
      info.appendChild(title);

      const badge = document.createElement("span");
      badge.className = "state " + (state ? (state.online ? "online" : "offline") : "unknown");
      const dot = document.createElement("span");
      dot.className = "dot";
      badge.appendChild(dot);
      badge.appendChild(document.createTextNode(
        state ? (state.online ? "Online" : "Offline") : "Checking…"
      ));
      info.appendChild(badge);

      const meta = document.createElement("p");
      meta.className = "meta";
      meta.textContent = [device.mac, device.ip].filter(Boolean).join(" · ");
      info.appendChild(meta);

      const edit = document.createElement("button");
      edit.className = "edit";
      edit.type = "button";
      edit.textContent = "Edit";
      edit.addEventListener("click", () => openEditor(device));
      info.appendChild(edit);

      const wake = document.createElement("button");
      wake.className = "wake";
      wake.type = "button";
      wake.textContent = "Wake";
      wake.addEventListener("click", () => sendWake(device, wake));

      item.appendChild(info);
      item.appendChild(wake);
      list.appendChild(item);
    }
  }

  async function sendWake(device, button) {
    button.disabled = true;
    const original = button.textContent;
    button.textContent = "Sending…";
    try {
      await api(`/api/devices/${device.id}/wake`, { method: "POST" });
      button.classList.add("sent");
      button.textContent = "Sent ✓";
      toast(`Magic packet sent to ${device.name}`);
      // Boot takes a moment; check more eagerly for the next half minute.
      for (const delay of [4000, 10000, 20000, 30000]) setTimeout(refreshStatus, delay);
    } catch (error) {
      toast(error.message);
    } finally {
      setTimeout(() => {
        button.disabled = false;
        button.classList.remove("sent");
        button.textContent = original;
      }, 2500);
    }
  }

  // --- data --------------------------------------------------------------

  async function loadDevices() {
    devices = (await api("/api/devices")).devices;
    render();
  }

  async function refreshStatus() {
    if (document.hidden || !devices.length) return;
    try {
      statuses = (await api("/api/status")).statuses;
      render();
    } catch (error) {
      /* transient; the next poll will pick it up */
    }
  }

  function startPolling() {
    clearInterval(pollTimer);
    pollTimer = setInterval(refreshStatus, POLL_MS);
    refreshStatus();
  }

  // --- editor ------------------------------------------------------------

  function openEditor(device) {
    editingId = device ? device.id : null;
    el("editor-title").textContent = device ? "Edit device" : "Add device";
    el("f-name").value = device ? device.name : "";
    el("f-mac").value = device ? device.mac : "";
    el("f-ip").value = device ? device.ip || "" : "";
    el("f-port").value = device && device.port ? device.port : "";
    el("f-broadcast").value = device ? device.broadcast || "" : "";
    el("editor-delete").hidden = !device;
    el("editor-error").hidden = true;
    editor.showModal();
    el("f-name").focus();
  }

  async function saveDevice(event) {
    event.preventDefault();
    const body = JSON.stringify({
      name: el("f-name").value,
      mac: el("f-mac").value,
      ip: el("f-ip").value,
      port: el("f-port").value,
      broadcast: el("f-broadcast").value,
    });
    try {
      if (editingId) {
        await api(`/api/devices/${editingId}`, { method: "PUT", body });
      } else {
        await api("/api/devices", { method: "POST", body });
      }
      editor.close();
      await loadDevices();
      refreshStatus();
    } catch (error) {
      const box = el("editor-error");
      box.textContent = error.message;
      box.hidden = false;
    }
  }

  async function deleteDevice() {
    if (!editingId || !confirm("Remove this device?")) return;
    try {
      await api(`/api/devices/${editingId}`, { method: "DELETE" });
      editor.close();
      delete statuses[editingId];
      await loadDevices();
    } catch (error) {
      toast(error.message);
    }
  }

  // --- session -----------------------------------------------------------

  function showGate() {
    clearInterval(pollTimer);
    main.hidden = true;
    el("add-btn").hidden = true;
    gate.hidden = false;
    el("pin-input").focus();
  }

  async function showApp() {
    gate.hidden = true;
    main.hidden = false;
    el("add-btn").hidden = false;
    await loadDevices();
    startPolling();
    if (!devices.length) openEditor(null);
  }

  async function unlock(event) {
    event.preventDefault();
    const value = el("pin-input").value;
    const response = await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: value }),
    });
    if (!response.ok) {
      el("pin-error").hidden = false;
      return;
    }
    localStorage.setItem(PIN_KEY, value);
    el("pin-error").hidden = true;
    el("pin-input").value = "";
    showApp();
  }

  async function boot() {
    el("add-btn").addEventListener("click", () => openEditor(null));
    el("editor-form").addEventListener("submit", saveDevice);
    el("editor-cancel").addEventListener("click", () => editor.close());
    el("editor-delete").addEventListener("click", deleteDevice);
    el("pin-form").addEventListener("submit", unlock);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && !main.hidden) refreshStatus();
    });

    try {
      const session = await (await fetch("/api/session")).json();
      if (session.pin_required && !pin()) return showGate();
      await showApp();
    } catch (error) {
      if (gate.hidden) toast("Cannot reach the service");
    }
  }

  boot();
})();
