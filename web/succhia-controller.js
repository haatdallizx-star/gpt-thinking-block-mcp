(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SucchiaBridge = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const MAX_INTENSITY = { suck: 100, vibe: 30 };
  const SERVICE_UUID = "0000ee01-0000-1000-8000-00805f9b34fb";
  const WRITE_UUID = "0000ee03-0000-1000-8000-00805f9b34fb";
  const MOTOR = { vibe: [0x01, 0x02], suck: [0x07, 0x08] };
  const CHANNELS = ["suck", "vibe"];

  function clamp(channel, value) {
    if (!CHANNELS.includes(channel)) throw new TypeError("invalid channel");
    const number = Number(value);
    if (!Number.isFinite(number)) throw new TypeError("invalid intensity");
    return Math.max(0, Math.min(MAX_INTENSITY[channel], Math.round(number)));
  }

  function frame(channel, value) {
    if (!MOTOR[channel]) throw new TypeError("invalid channel");
    const [main, secondary] = MOTOR[channel];
    return new Uint8Array([
      0x01, 0x01, 0x00, 0x02, 0x00, main, 0x11, clamp(channel, value),
      0x00, secondary, 0x11, 0x01,
    ]);
  }

  function createSucchiaController(options) {
    const bluetooth = options.bluetooth;
    const fetchImpl = options.fetch;
    const apiBase = String(options.apiBase || "/succhia-api").replace(/\/$/, "");
    const apiToken = String(options.apiToken || "");
    const now = options.now || (() => Date.now());
    const onState = options.onState || (() => {});
    const onStatus = options.onStatus || (() => {});
    const timers = options.timers || {
      setTimeout: (...args) => setTimeout(...args),
      clearTimeout: id => clearTimeout(id),
      setInterval: (...args) => setInterval(...args),
      clearInterval: id => clearInterval(id),
    };

    if (!bluetooth || typeof bluetooth.requestDevice !== "function") {
      throw new Error("Web Bluetooth unavailable");
    }
    if (typeof fetchImpl !== "function") throw new Error("fetch unavailable");
    if (!apiToken) throw new Error("page token required");

    let device = null;
    let characteristic = null;
    let connected = false;
    let userDisconnect = false;
    let writeQueue = Promise.resolve();
    let pollGeneration = 0;
    let patternTimer = null;
    let watchdogTimer = null;
    let reconnecting = false;
    let expiresAt = null;
    const patternStartedAt = { suck: 0, vibe: 0 };
    const state = {
      suck: 0,
      vibe: 0,
      patterns: { suck: null, vibe: null },
    };

    function emitState() {
      onState(snapshot());
    }

    function snapshot() {
      return {
        connected,
        suck: state.suck,
        vibe: state.vibe,
        patterns: {
          suck: state.patterns.suck ? {...state.patterns.suck} : null,
          vibe: state.patterns.vibe ? {...state.patterns.vibe} : null,
        },
      };
    }

    async function api(path, options = {}) {
      const headers = {...(options.headers || {}), "X-Succhia-Token": apiToken};
      const response = await fetchImpl(apiBase + path, {...options, headers});
      if (!response.ok) {
        let detail = "request failed";
        try { detail = (await response.json()).error || detail; } catch (_) {}
        const error = new Error(detail);
        error.status = response.status;
        throw error;
      }
      return response.json();
    }

    function enqueueWrite(channel, value) {
      const payload = frame(channel, value);
      writeQueue = writeQueue.then(async () => {
        if (!characteristic || !connected) throw new Error("device not connected");
        if (characteristic.properties && characteristic.properties.write) {
          await characteristic.writeValueWithResponse(payload);
        } else {
          await characteristic.writeValueWithoutResponse(payload);
        }
      });
      return writeQueue;
    }

    async function writeZero() {
      state.suck = 0;
      state.vibe = 0;
      state.patterns.suck = null;
      state.patterns.vibe = null;
      expiresAt = null;
      await enqueueWrite("suck", 0);
      await enqueueWrite("vibe", 0);
      emitState();
    }

    async function attachGatt() {
      const server = await device.gatt.connect();
      const service = await server.getPrimaryService(SERVICE_UUID);
      characteristic = await service.getCharacteristic(WRITE_UUID);
      connected = true;
      await writeZero();
      await api("/event?type=connect");
      onStatus("已连接，当前强度为 0");
    }

    async function connect() {
      userDisconnect = false;
      if (!device) {
        device = await bluetooth.requestDevice({
          filters: [{namePrefix: "SOSEXY"}],
          optionalServices: [SERVICE_UUID],
        });
        device.addEventListener("gattserverdisconnected", () => {
          handleGattDisconnect().catch(() => {});
        });
      }
      await attachGatt();
      return snapshot();
    }

    async function reconnect() {
      if (!device) throw new Error("no remembered device");
      if (reconnecting) return snapshot();
      reconnecting = true;
      try {
        await attachGatt();
        return snapshot();
      } finally {
        reconnecting = false;
      }
    }

    async function setManual(channel, value) {
      if (!CHANNELS.includes(channel)) throw new TypeError("invalid channel");
      const safeValue = clamp(channel, value);
      state[channel] = safeValue;
      state.patterns[channel] = null;
      await enqueueWrite(channel, safeValue);
      const payload = {[`${channel}_intensity`]: safeValue};
      if (safeValue > 0) payload.duration_sec = 30;
      await api("/set", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      emitState();
      return snapshot();
    }

    async function stop() {
      if (connected && characteristic) await writeZero();
      else {
        state.suck = 0;
        state.vibe = 0;
        state.patterns.suck = null;
        state.patterns.vibe = null;
        expiresAt = null;
        emitState();
      }
      await api("/set", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          suck_intensity: 0,
          vibe_intensity: 0,
          patterns: {suck: null, vibe: null},
        }),
      });
      onStatus("已全部停止");
      return snapshot();
    }

    async function handleGattDisconnect() {
      connected = false;
      characteristic = null;
      state.suck = 0;
      state.vibe = 0;
      state.patterns.suck = null;
      state.patterns.vibe = null;
      expiresAt = null;
      emitState();
      await api("/disconnect", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: "{}",
      });
      onStatus(userDisconnect ? "已安全断开" : "连接中断，服务器状态已归零");
      return snapshot();
    }

    async function disconnect() {
      userDisconnect = true;
      pollGeneration += 1;
      if (connected && characteristic) {
        try { await stop(); } catch (_) {}
      }
      if (device && device.gatt && device.gatt.connected) device.gatt.disconnect();
      if (connected) await handleGattDisconnect();
      return snapshot();
    }

    function samePattern(a, b) {
      return JSON.stringify(a || null) === JSON.stringify(b || null);
    }

    async function applyRemote(remote) {
      expiresAt = typeof remote.expires_at === "number" ? remote.expires_at : null;
      for (const channel of CHANNELS) {
        const incomingPattern = remote.patterns && remote.patterns[channel] || null;
        if (!samePattern(incomingPattern, state.patterns[channel])) {
          state.patterns[channel] = incomingPattern ? {...incomingPattern} : null;
          patternStartedAt[channel] = now();
        }
        if (!state.patterns[channel]) {
          const value = clamp(channel, remote[`${channel}_intensity`] || 0);
          if (state[channel] !== value) {
            state[channel] = value;
            if (connected) await enqueueWrite(channel, value);
          }
        }
      }
      emitState();
      return snapshot();
    }

    async function tickPatterns() {
      if (!connected) return snapshot();
      const current = now();
      if (expiresAt !== null && current / 1000 >= expiresAt) {
        await writeZero();
        return snapshot();
      }
      for (const channel of CHANNELS) {
        const pattern = state.patterns[channel];
        if (!pattern) continue;
        const period = Math.max(500, Number(pattern.period) || 4000);
        const phase = ((current - patternStartedAt[channel]) % period) / period;
        const low = clamp(channel, pattern.low || 0);
        const high = Math.max(low, clamp(channel, pattern.high || 0));
        let value;
        if (pattern.type === "wave") {
          value = low + (high - low) * (0.5 - 0.5 * Math.cos(2 * Math.PI * phase));
        } else if (pattern.type === "pulse") {
          value = phase < 0.5 ? high : low;
        } else {
          value = low + (high - low) * phase;
        }
        value = clamp(channel, value);
        if (state[channel] !== value) {
          state[channel] = value;
          await enqueueWrite(channel, value);
        }
      }
      emitState();
      return snapshot();
    }

    async function pollLoop(generation) {
      let since = null;
      while (generation === pollGeneration && device) {
        try {
          const query = since === null ? "" : `?wait=20&since=${encodeURIComponent(since)}`;
          const remote = await api("/poll" + query, {cache: "no-store"});
          if (generation !== pollGeneration) return;
          since = remote.updated_at;
          await applyRemote(remote);
        } catch (error) {
          if (generation !== pollGeneration) return;
          onStatus(error.status === 401 ? "控制页令牌无效" : "服务器暂时不可达");
          await new Promise(resolve => timers.setTimeout(resolve, 2000));
        }
      }
    }

    function startPolling() {
      pollGeneration += 1;
      pollLoop(pollGeneration).catch(() => {});
    }

    function startPatternLoop() {
      if (patternTimer) return;
      patternTimer = timers.setInterval(() => tickPatterns().catch(() => {}), 250);
    }

    function startWatchdog() {
      if (watchdogTimer) return;
      watchdogTimer = timers.setInterval(() => {
        if (device && !userDisconnect && !connected && !reconnecting) {
          reconnect().then(startPolling).catch(() => {});
        }
      }, 3000);
    }

    async function status() {
      return api("/status", {cache: "no-store"});
    }

    function destroy() {
      pollGeneration += 1;
      if (patternTimer) timers.clearInterval(patternTimer);
      if (watchdogTimer) timers.clearInterval(watchdogTimer);
      patternTimer = null;
      watchdogTimer = null;
    }

    return {
      connect,
      reconnect,
      disconnect,
      handleGattDisconnect,
      setManual,
      stop,
      applyRemote,
      tickPatterns,
      startPolling,
      startPatternLoop,
      startWatchdog,
      status,
      snapshot,
      destroy,
    };
  }

  return {createSucchiaController, frame, MAX_INTENSITY};
});
