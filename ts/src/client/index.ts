/**
 * The participant client surface.
 *
 * This barrel re-exports the client core -- the wire minter, the session, the
 * driver, the renderer, and the activity types -- for a test or an embedder. It
 * does not import `bootstrap`, which reaches for the browser globals and starts
 * the client as a side effect; the `index.html` shell loads that module directly.
 */

export {
  buildCommand,
  uuid7,
  idempotencyKey,
  instant,
  base64url,
  DEMO_INTENT,
} from './wire.js';
export type {
  RealtimeCommand,
  CommandFrame,
  InputFrame,
  OutgoingFrame,
  WireEnv,
  NowMillis,
  RandomBytes,
} from './wire.js';

export { ParticipantSession } from './session.js';
export type {
  Socket,
  SocketFactory,
  KeyValueStore,
  Schedule,
  Endpoint,
  HandshakeAck,
  StreamPosition,
  SessionHandlers,
  SessionConfig,
} from './session.js';

export { ParticipantClient } from './client.js';
export type { ClientConfig, KeyTarget } from './client.js';

export { createRenderer } from './renderer.js';
export type { Renderer, RenderPacket, SurfaceCommand, RelativePoint } from './renderer.js';

export { preloadBrowserGame, playBrowserEpisode } from './browserGame.js';
export type {
  BrowserManifest,
  BrowserRuntime,
  GameTransition,
  EpisodeBoundary,
  EpisodeRun,
  EpisodeOptions,
} from './browserGame.js';

export { renderForm, renderContent, renderComplete } from './ui.js';
export type {
  Delivery,
  FormDelivery,
  ContentDelivery,
  GameDelivery,
  PreloadDelivery,
  CompleteDelivery,
  FormField,
  Answers,
} from './ui.js';
