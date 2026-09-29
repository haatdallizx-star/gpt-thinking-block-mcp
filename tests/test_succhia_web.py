import json
import subprocess
import textwrap
import unittest


FAKE_STACK = r"""
const writes = [];
const requests = [];
const listeners = {};
const characteristic = {
  properties: { write: true, writeWithoutResponse: true },
  async writeValueWithResponse(value) { writes.push(Array.from(value)); },
  async writeValueWithoutResponse(value) { writes.push(Array.from(value)); },
};
const service = { async getCharacteristic() { return characteristic; } };
const gatt = {
  connected: false,
  async connect() { this.connected = true; return this; },
  async getPrimaryService() { return service; },
  disconnect() { this.connected = false; if (listeners.gattserverdisconnected) listeners.gattserverdisconnected(); },
};
const device = {
  gatt,
  addEventListener(name, fn) { listeners[name] = fn; },
};
const bluetooth = {
  lastOptions: null,
  async requestDevice(options) { this.lastOptions = options; return device; },
};
async function fakeFetch(url, options = {}) {
  requests.push({url, options});
  if (url.includes('/poll')) {
    return {ok: true, status: 200, async json() {
      return {suck_intensity: 0, vibe_intensity: 0, ems_intensity: 0,
              patterns: {suck: null, vibe: null, ems: null}, updated_at: 1};
    }};
  }
  return {ok: true, status: 200, async json() { return {ok: true}; }};
}
"""


def run_node(body):
    script = textwrap.dedent(
        f"""
        const assert = require('node:assert/strict');
        const {{ createSucchiaController }} = require('./web/succhia-controller.js');
        {FAKE_STACK}
        (async () => {{
          {body}
        }})().catch(error => {{ console.error(error.stack || error); process.exit(1); }});
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        cwd=".",
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout


class SucchiaWebControllerTests(unittest.TestCase):
    def test_connects_sosexy_sends_zero_then_caps_manual_command_with_token(self):
        run_node(
            r"""
            const controller = createSucchiaController({
              bluetooth, fetch: fakeFetch, apiBase: '/succhia-api', apiToken: 'page-token'
            });
            await controller.connect();
            assert.deepEqual(bluetooth.lastOptions.filters, [{namePrefix: 'SOSEXY'}]);
            assert.equal(writes[0][7], 0);
            assert.equal(writes[1][7], 0);

            await controller.setManual('vibe', 99);
            assert.equal(writes.at(-1)[5], 0x01);
            assert.equal(writes.at(-1)[7], 30);
            const setRequest = requests.find(r => r.url.endsWith('/set'));
            assert.equal(setRequest.options.headers['X-Succhia-Token'], 'page-token');
            assert.deepEqual(JSON.parse(setRequest.options.body), {
              vibe_intensity: 30, duration_sec: 30
            });
            assert.deepEqual(controller.snapshot(), {
              connected: true, suck: 0, vibe: 30, patterns: {suck: null, vibe: null}
            });

            await controller.setManual('suck', 999);
            assert.equal(writes.at(-1)[5], 0x07);
            assert.equal(writes.at(-1)[7], 100);
            assert.deepEqual(JSON.parse(requests.at(-1).options.body), {
              suck_intensity: 100, duration_sec: 30
            });
            assert.deepEqual(controller.snapshot(), {
              connected: true, suck: 100, vibe: 30, patterns: {suck: null, vibe: null}
            });
            """
        )

    def test_ems_is_not_a_valid_channel_and_remote_ems_is_ignored(self):
        run_node(
            r"""
            const controller = createSucchiaController({
              bluetooth, fetch: fakeFetch, apiBase: '/succhia-api', apiToken: 'page-token'
            });
            await controller.connect();
            await assert.rejects(() => controller.setManual('ems', 10), /invalid channel/);
            await controller.applyRemote({
              suck_intensity: 0, vibe_intensity: 0, ems_intensity: 30,
              patterns: {suck: null, vibe: null, ems: {type: 'pulse', low: 0, high: 30, period: 1000}},
              updated_at: 2,
            });
            assert.equal(writes.some(frame => frame[5] === 0x03 || frame[5] === 0x04), false);
            """
        )

    def test_disconnect_reports_zero_and_reconnect_starts_with_zero(self):
        run_node(
            r"""
            const controller = createSucchiaController({
              bluetooth, fetch: fakeFetch, apiBase: '/succhia-api', apiToken: 'page-token'
            });
            await controller.connect();
            await controller.setManual('suck', 12);
            const beforeDisconnectWrites = writes.length;
            await controller.handleGattDisconnect();
            assert.deepEqual(controller.snapshot(), {
              connected: false, suck: 0, vibe: 0, patterns: {suck: null, vibe: null}
            });
            assert.ok(requests.some(r => r.url.endsWith('/disconnect')));

            await controller.reconnect();
            assert.equal(writes[beforeDisconnectWrites][7], 0);
            assert.equal(writes[beforeDisconnectWrites + 1][7], 0);
            assert.deepEqual(controller.snapshot(), {
              connected: true, suck: 0, vibe: 0, patterns: {suck: null, vibe: null}
            });
            """
        )

    def test_stop_zeroes_both_channels_before_reporting_state(self):
        run_node(
            r"""
            const controller = createSucchiaController({
              bluetooth, fetch: fakeFetch, apiBase: '/succhia-api', apiToken: 'page-token'
            });
            await controller.connect();
            await controller.setManual('suck', 8);
            await controller.setManual('vibe', 9);
            await controller.stop();
            assert.equal(writes.at(-2)[7], 0);
            assert.equal(writes.at(-1)[7], 0);
            const payload = JSON.parse(requests.at(-1).options.body);
            assert.deepEqual(payload, {suck_intensity: 0, vibe_intensity: 0,
                                       patterns: {suck: null, vibe: null}});
            """
        )

    def test_pattern_engine_uses_remote_spec_and_respects_lease_expiry(self):
        run_node(
            r"""
            let now = 100000;
            const controller = createSucchiaController({
              bluetooth, fetch: fakeFetch, apiBase: '/succhia-api', apiToken: 'page-token',
              now: () => now,
            });
            await controller.connect();
            await controller.applyRemote({
              suck_intensity: 0, vibe_intensity: 0, ems_intensity: 0,
              patterns: {suck: null, vibe: {type: 'pulse', low: 2, high: 20, period: 1000}, ems: null},
              expires_at: 102,
              updated_at: 2,
            });
            await controller.tickPatterns();
            assert.equal(writes.at(-1)[7], 20);
            now = 100750;
            await controller.tickPatterns();
            assert.equal(writes.at(-1)[7], 2);
            now = 102100;
            await controller.tickPatterns();
            assert.equal(writes.at(-1)[7], 0);
            assert.equal(controller.snapshot().vibe, 0);
            """
        )

    def test_html_requires_a_separate_page_token_and_exposes_channel_specific_limits(self):
        from pathlib import Path

        page = Path("web/succhia.html").read_text(encoding="utf-8")
        self.assertIn('id="tokenGate"', page)
        self.assertIn('id="pageToken"', page)
        self.assertIn('src="/gptmcp/succhia-controller.js"', page)
        self.assertIn('id="suckRange" type="range" min="0" max="100"', page)
        self.assertIn('id="vibeRange" type="range" min="0" max="30"', page)
        self.assertNotIn("emsRange", page)


if __name__ == "__main__":
    unittest.main()
