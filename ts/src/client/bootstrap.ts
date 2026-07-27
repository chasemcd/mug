/**
 * The browser entry point.
 *
 * It wires the real browser primitives -- the `WebSocket`, `localStorage`, the
 * clock, the random source, the Web Crypto hasher, and the window key target --
 * into the participant client and starts it. The `index.html` shell loads the
 * compiled form of this module as an ES module, so opening the page runs the
 * study. The client core stays free of these globals, so a test drives it with
 * fakes; only this file reaches for the browser.
 */

import { browserSha256 } from '../kernel/index.js';
import { browserDecoder } from './assets.js';
import { ParticipantClient } from './client.js';
import { fetchBrowserPeerConnectionFactory } from './p2pRtc.js';
import { KeyValueStore, Schedule, Socket, SocketFactory } from './session.js';
import { uuid7, WireEnv } from './wire.js';

function requireElement(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error('the page is missing the #' + id + ' element');
  }
  return element;
}

// Adapt the browser `WebSocket` to the small `Socket` seam the session uses.
const connect: SocketFactory = (url: string): Socket => {
  const websocket = new WebSocket(url);
  return {
    send: (data) => websocket.send(data),
    close: () => websocket.close(),
    onMessage: (handler) =>
      websocket.addEventListener('message', (event) => handler(String(event.data))),
    onOpen: (handler) => websocket.addEventListener('open', () => handler()),
    onClose: (handler) => websocket.addEventListener('close', () => handler()),
    onError: (handler) => websocket.addEventListener('error', () => handler()),
  };
};

const store: KeyValueStore = {
  get: (key) => localStorage.getItem(key),
  set: (key, value) => localStorage.setItem(key, value),
  remove: (key) => localStorage.removeItem(key),
};

const schedule: Schedule = (callback, delayMillis) => {
  setTimeout(callback, delayMillis);
};

function bootstrap(): void {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  const status = requireElement('status');
  const env: WireEnv = {
    now: () => Date.now(),
    randomBytes: (count) => crypto.getRandomValues(new Uint8Array(count)),
    hash: browserSha256,
  };
  const client = new ParticipantClient({
    app: requireElement('app'),
    status,
    keyTarget: window,
    endpoint: {
      wsBase: scheme + '://' + location.host,
      ticket: new URLSearchParams(location.search).get('ticket'),
    },
    connect,
    store,
    schedule,
    env,
    decodeAsset: browserDecoder((url) => fetch(url)),
    p2p: {
      prepareConnections: (mesh) =>
        fetchBrowserPeerConnectionFactory(mesh, (endpoint, init) =>
          fetch(endpoint, init),
        ),
      nextRequestId: () => 'request_' + uuid7(env),
      setTimer: (handler, delayMillis) => window.setTimeout(handler, delayMillis),
      clearTimer: (handle) => {
        if (typeof handle === 'number') {
          window.clearTimeout(handle);
        }
      },
      onError: (message) => {
        status.textContent = 'peer mesh failed: ' + message;
      },
    },
  });
  // The one browser-shaped quality input: how long the page spent in the
  // background. A tab the participant switched away from is not a tab they are
  // playing in, and a study that screens is entitled to be told.
  let hiddenSince: number | null = null;
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      hiddenSince = Date.now();
    } else if (hiddenSince !== null) {
      client.reportHidden(Date.now() - hiddenSince);
      hiddenSince = null;
    }
  });
  client.start();
}

bootstrap();
