"""Authenticated, fail-safe state bridge for the FUNF 啵啵贝 Pro."""

from __future__ import annotations

import copy
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping


CHANNELS = ("suck", "vibe")
ALL_CHANNELS = ("suck", "vibe", "ems")
PATTERN_TYPES = ("wave", "pulse", "climb")


class ValidationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class SucchiaRuntime:
    """Own safe device state and expose small REST/MCP-facing interfaces."""

    def __init__(
        self,
        config_path: str | os.PathLike[str],
        state_path: str | os.PathLike[str],
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.state_path = Path(state_path)
        self.clock = clock or time.time
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self._page_token = self._required_secret(config, "page_token")
        self._mcp_token = self._required_secret(config, "mcp_token")
        legacy_max = int(config.get("max_intensity", 30))
        self.max_intensities = {
            "suck": max(1, min(100, int(config.get("max_suck_intensity", 100)))),
            "vibe": max(1, min(30, int(config.get("max_vibe_intensity", legacy_max)))),
        }
        # Preserve the legacy status field as the vibration cap.
        self.max_intensity = self.max_intensities["vibe"]
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._last_poll = 0.0
        self._bridge_connected = False
        self._events: list[dict[str, Any]] = []
        self._state = self._zero_state()
        # A process restart is a safety boundary: persisted commands are never replayed.
        self._write_locked()

    @staticmethod
    def _required_secret(config: Mapping[str, Any], key: str) -> str:
        value = config.get(key)
        if not isinstance(value, str) or len(value) < 16:
            raise ValueError(f"{key} must be a string of at least 16 characters")
        return value

    def _zero_state(self) -> dict[str, Any]:
        now = float(self.clock())
        return {
            "suck_intensity": 0,
            "suck_mode": 1,
            "vibe_intensity": 0,
            "vibe_mode": 1,
            "ems_intensity": 0,
            "ems_mode": 1,
            "patterns": {"suck": None, "vibe": None, "ems": None},
            "expires_at": None,
            "updated_at": now,
        }

    @staticmethod
    def _json_headers() -> dict[str, str]:
        return {"Content-Type": "application/json", "Cache-Control": "no-store"}

    @staticmethod
    def _header(headers: Mapping[str, Any], name: str) -> str:
        wanted = name.lower()
        for key, value in headers.items():
            if str(key).lower() == wanted:
                return str(value)
        return ""

    def _page_authorized(self, headers: Mapping[str, Any]) -> bool:
        candidate = self._header(headers, "X-Succhia-Token")
        return bool(candidate) and secrets.compare_digest(candidate, self._page_token)

    def mcp_authorized(self, candidate: str | None) -> bool:
        return bool(candidate) and secrets.compare_digest(str(candidate), self._mcp_token)

    def _write_locked(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False), encoding="utf-8")
        tmp.chmod(0o600)
        os.replace(tmp, self.state_path)

    def _notify_locked(self) -> None:
        self._write_locked()
        self._changed.notify_all()

    def _record_locked(self, event: str) -> None:
        self._events.append({"event": event[:120], "at": float(self.clock())})
        del self._events[:-80]

    def _stop_locked(self, event: str) -> None:
        for channel in ALL_CHANNELS:
            self._state[f"{channel}_intensity"] = 0
            self._state["patterns"][channel] = None
        self._state["expires_at"] = None
        self._state["updated_at"] = float(self.clock())
        self._record_locked(event)
        self._notify_locked()

    def _expire_locked(self) -> None:
        expires_at = self._state.get("expires_at")
        if expires_at is not None and float(self.clock()) >= float(expires_at):
            self._stop_locked("lease_expired")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._expire_locked()
            return copy.deepcopy(self._state)

    @staticmethod
    def _number(value: Any, error: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(error)
        return float(value)

    def _intensity(self, channel: str, value: Any) -> int:
        number = self._number(value, "invalid_intensity")
        return max(0, min(self.max_intensities[channel], round(number)))

    def _duration(self, value: Any) -> int:
        if value is None:
            raise ValidationError("duration_required")
        duration = round(self._number(value, "invalid_duration"))
        if not 3 <= duration <= 120:
            raise ValidationError("duration_out_of_range")
        return duration

    def _pattern(self, channel: str, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict) or value.get("type") not in PATTERN_TYPES:
            raise ValidationError("invalid_pattern")
        high = self._intensity(channel, value.get("high", 20))
        low = min(self._intensity(channel, value.get("low", 0)), high)
        period_sec = self._number(value.get("period_sec", 4), "invalid_period")
        if not 0.5 <= period_sec <= 60:
            raise ValidationError("period_out_of_range")
        return {
            "type": value["type"],
            "high": high,
            "low": low,
            "period": round(period_sec * 1000),
        }

    def _apply(self, data: Mapping[str, Any]) -> dict[str, Any]:
        if "ems_intensity" in data or (
            isinstance(data.get("patterns"), dict) and "ems" in data["patterns"]
        ):
            raise ValidationError("ems_locked")

        updates: dict[str, int] = {}
        for channel in CHANNELS:
            key = f"{channel}_intensity"
            if key in data:
                updates[key] = self._intensity(channel, data[key])

        pattern_updates: dict[str, dict[str, Any] | None] = {}
        patterns = data.get("patterns")
        if patterns is not None:
            if not isinstance(patterns, dict):
                raise ValidationError("invalid_pattern")
            unknown = set(patterns) - set(CHANNELS)
            if unknown:
                raise ValidationError("invalid_channel")
            for channel, pattern in patterns.items():
                pattern_updates[channel] = self._pattern(channel, pattern)

        if not updates and not pattern_updates:
            raise ValidationError("nothing_to_set")

        will_be_nonzero = any(value > 0 for value in updates.values()) or any(
            pattern is not None and pattern["high"] > 0
            for pattern in pattern_updates.values()
        )
        duration = self._duration(data.get("duration_sec")) if will_be_nonzero else None

        with self._lock:
            self._expire_locked()
            for key, value in updates.items():
                self._state[key] = value
            for channel, pattern in pattern_updates.items():
                self._state["patterns"][channel] = pattern
                if pattern is not None:
                    self._state[f"{channel}_intensity"] = pattern["low"]
            self._state["ems_intensity"] = 0
            self._state["patterns"]["ems"] = None
            active = any(self._state[f"{ch}_intensity"] > 0 for ch in CHANNELS) or any(
                self._state["patterns"][ch] is not None for ch in CHANNELS
            )
            if active:
                if duration is None:
                    # Partial zero updates do not extend an existing lease.
                    if self._state.get("expires_at") is None:
                        raise ValidationError("duration_required")
                else:
                    self._state["expires_at"] = float(self.clock()) + duration
            else:
                self._state["expires_at"] = None
            self._state["updated_at"] = float(self.clock())
            self._record_locked("set")
            self._notify_locked()
            return copy.deepcopy(self._state)

    def _status(self) -> dict[str, Any]:
        with self._lock:
            self._expire_locked()
            now = float(self.clock())
            age = now - self._last_poll if self._last_poll else None
            return {
                "state": copy.deepcopy(self._state),
                "page_last_poll_sec_ago": round(age, 1) if age is not None else None,
                "page_listening": age is not None and age < 30,
                "bridge_connected": self._bridge_connected,
                "max_intensity": self.max_intensity,
                "max_intensities": dict(self.max_intensities),
            }

    def _unauthorized(self) -> tuple[int, dict[str, str], dict[str, Any]]:
        return 401, self._json_headers(), {"ok": False, "error": "unauthorized"}

    @staticmethod
    def _query_value(query: Mapping[str, Any], key: str, default: Any = None) -> Any:
        value = query.get(key, default)
        if isinstance(value, list):
            return value[0] if value else default
        return value

    def handle_get(
        self,
        path: str,
        query: Mapping[str, Any],
        headers: Mapping[str, Any],
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        if not self._page_authorized(headers):
            return self._unauthorized()
        if path == "/succhia-api/status":
            return 200, self._json_headers(), self._status()
        if path == "/succhia-api/diag":
            with self._lock:
                return 200, self._json_headers(), {"events": copy.deepcopy(self._events)}
        if path == "/succhia-api/event":
            event = str(self._query_value(query, "type", "unknown"))
            with self._lock:
                if event == "connect":
                    self._bridge_connected = True
                self._record_locked(event)
            return 200, self._json_headers(), {"ok": True}
        if path != "/succhia-api/poll":
            return 404, self._json_headers(), {"ok": False, "error": "not_found"}

        try:
            wait = max(0.0, min(25.0, float(self._query_value(query, "wait", 0))))
            since_raw = self._query_value(query, "since")
            since = float(since_raw) if since_raw is not None else None
        except (TypeError, ValueError):
            return 400, self._json_headers(), {"ok": False, "error": "invalid_query"}

        with self._changed:
            self._last_poll = float(self.clock())
            self._bridge_connected = True
            self._expire_locked()
            if wait and since is not None and abs(self._state["updated_at"] - since) < 1e-6:
                self._changed.wait(wait)
                self._expire_locked()
            self._last_poll = float(self.clock())
            return 200, self._json_headers(), copy.deepcopy(self._state)

    def handle_post(
        self,
        path: str,
        query: Mapping[str, Any],
        headers: Mapping[str, Any],
        body: bytes,
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        del query
        if not self._page_authorized(headers):
            return self._unauthorized()
        try:
            data = json.loads(body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, self._json_headers(), {"ok": False, "error": "invalid_json"}
        if not isinstance(data, dict):
            return 400, self._json_headers(), {"ok": False, "error": "invalid_json"}

        if path == "/succhia-api/disconnect":
            with self._lock:
                self._bridge_connected = False
                self._stop_locked("bridge_disconnect")
                state = copy.deepcopy(self._state)
            return 200, self._json_headers(), {"ok": True, "state": state}
        if path != "/succhia-api/set":
            return 404, self._json_headers(), {"ok": False, "error": "not_found"}
        try:
            state = self._apply(data)
        except ValidationError as exc:
            return 400, self._json_headers(), {"ok": False, "error": exc.code}
        return 200, self._json_headers(), {"ok": True, "state": state}

    def mcp_tools(self, authorized: bool) -> list[dict[str, Any]]:
        if not authorized:
            return []
        common = {
            "securitySchemes": [{"type": "noauth"}],
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        }
        return [
            {
                "name": "succhia_set",
                "title": "啵啵贝 · 设置强度",
                "description": "限时设置强度；吮吸上限 100，震动上限 30，微电流已锁定。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "suck": {"type": "integer", "minimum": 0, "maximum": 100},
                        "vibe": {"type": "integer", "minimum": 0, "maximum": 30},
                        "duration_sec": {"type": "integer", "minimum": 3, "maximum": 120},
                    },
                    "required": ["duration_sec"],
                },
                **common,
            },
            {
                "name": "succhia_pattern",
                "title": "啵啵贝 · 限时波形",
                "description": "在吮吸或震动通道运行限时波形；微电流已锁定。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "enum": list(CHANNELS)},
                        "type": {"type": "string", "enum": [*PATTERN_TYPES, "off"]},
                        "low": {"type": "integer", "minimum": 0, "maximum": 100},
                        "high": {"type": "integer", "minimum": 0, "maximum": 100},
                        "period_sec": {"type": "number", "minimum": 0.5, "maximum": 60},
                        "duration_sec": {"type": "integer", "minimum": 3, "maximum": 120},
                    },
                    "required": ["type"],
                },
                **common,
            },
            {
                "name": "succhia_stop",
                "title": "啵啵贝 · 全部停止",
                "description": "立即清除所有强度、波形和租约。",
                "inputSchema": {"type": "object", "properties": {}},
                **common,
            },
            {
                "name": "succhia_status",
                "title": "啵啵贝 · 状态",
                "description": "读取设定状态、租约和安卓桥在线状态。",
                "inputSchema": {"type": "object", "properties": {}},
                "securitySchemes": [{"type": "noauth"}],
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
        ]

    def mcp_call(self, name: str, args: Mapping[str, Any], authorized: bool) -> dict[str, Any]:
        if not authorized:
            return {"ok": False, "error": "unauthorized"}
        try:
            if name == "succhia_stop":
                with self._lock:
                    self._stop_locked("mcp_stop")
                return {"ok": True, "state": self.snapshot()}
            if name == "succhia_status":
                return {"ok": True, **self._status()}
            if name == "succhia_set":
                data: dict[str, Any] = {"duration_sec": args.get("duration_sec")}
                for channel in CHANNELS:
                    if channel in args:
                        data[f"{channel}_intensity"] = args[channel]
                if len(data) == 1:
                    raise ValidationError("nothing_to_set")
                return {"ok": True, "state": self._apply(data)}
            if name == "succhia_pattern":
                pattern_type = args.get("type")
                channel = args.get("channel")
                if pattern_type == "off":
                    if channel is None:
                        with self._lock:
                            self._stop_locked("mcp_pattern_off")
                        return {"ok": True, "state": self.snapshot()}
                    if channel not in CHANNELS:
                        raise ValidationError("invalid_channel")
                    return {
                        "ok": True,
                        "state": self._apply({
                            f"{channel}_intensity": 0,
                            "patterns": {channel: None},
                        }),
                    }
                if channel not in CHANNELS:
                    raise ValidationError("invalid_channel")
                pattern = {
                    "type": pattern_type,
                    "low": args.get("low", 0),
                    "high": args.get("high", 20),
                    "period_sec": args.get("period_sec", 4),
                }
                return {
                    "ok": True,
                    "state": self._apply({
                        "patterns": {channel: pattern},
                        "duration_sec": args.get("duration_sec"),
                    }),
                }
            return {"ok": False, "error": "unknown_tool"}
        except ValidationError as exc:
            return {"ok": False, "error": exc.code}
