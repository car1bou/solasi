import test from 'node:test';
import assert from 'node:assert/strict';
import {api} from '../src/api.ts';

test('protected request waits for bootstrap and sends the returned token', async () => {
  Object.defineProperty(globalThis, 'location', {value: new URL('http://127.0.0.1:8765/#bootstrap=fixture'), configurable: true});
  Object.defineProperty(globalThis, 'history', {value: {replaceState() {}}, configurable: true});
  let connected = false;
  let protectedToken = '';
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async (input, options) => {
    if (String(input) === '/api/bootstrap') {
      assert.equal(JSON.parse(String(options?.body)).token, 'fixture');
      connected = true;
      return Response.json({csrf_token: 'returned-token'});
    }
    if (!connected) return Response.json({detail: 'not connected'}, {status: 403});
    protectedToken = new Headers(options?.headers).get('X-Session-Token') || '';
    return Response.json([{ready: true}]);
  };
  try {
    const result = await api<{ready:boolean}[]>('/runtime/status');
    assert.equal(result[0].ready, true);
    assert.equal(protectedToken, 'returned-token');
  } finally {
    globalThis.fetch = oldFetch;
  }
});
