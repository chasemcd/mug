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
  ChatMessage,
} from './session.js';

export { ParticipantClient } from './client.js';
export type { ClientConfig, KeyTarget } from './client.js';

export { PeerMesh } from './p2p.js';
export type { PeerMeshConfig, MeshTimer } from './p2p.js';
export { P2PEdge } from './p2pEdge.js';
export { createMeshExecutor, meshRunConfig, preloadMeshRuntime } from './p2pGame.js';
export type {
  MeshDriver,
  MeshExecutorConfig,
  MeshManifest,
  MeshRunResult,
  MeshRuntime,
  MeshSession,
} from './p2pGame.js';
export type {
  P2PControlPort,
  P2PEdgeConfig,
  P2PExecutor,
  P2PMeshHandoff,
} from './p2pEdge.js';
export {
  browserPeerConnectionFactory,
  fetchBrowserPeerConnectionFactory,
} from './p2pRtc.js';
export type {
  IceGrantFetch,
  IceGrantFetchInit,
  IceGrantResponse,
  MeshDataChannel,
  MeshPeerConnection,
  PeerConnectionFactory,
} from './p2pRtc.js';
export {
  captureSubmissionFrame,
  peerCompleteFrame,
  peerReadyFrame,
} from './p2pOutbound.js';
export { isP2PInboundType, parseP2PInboundFrame } from './p2pWire.js';
export type {
  P2PBootstrap,
  P2PInboundFrame,
  P2PMeshAbort,
  P2PMeshFinish,
  P2PMeshStart,
  P2POutboundFrame,
  P2PSignal,
  P2PSignalAck,
  P2PSignalDelivery,
} from './p2pWire.js';

export { createRenderer } from './renderer.js';
export { LoadedAssets, browserDecoder } from './assets.js';
export type { AssetManifest, DeclaredAsset, DecodeAsset } from './assets.js';
export type {
  Renderer,
  RenderPacket,
  SurfaceCommand,
  Point,
  AssetTable,
  AtlasFrame,
  RendererOptions,
} from './renderer.js';

export { preloadBrowserGame, playBrowserEpisode } from './browserGame.js';
export type {
  BrowserManifest,
  BrowserRuntime,
  GameTransition,
  EpisodeBoundary,
  EpisodeRun,
  EpisodeOptions,
} from './browserGame.js';

export { renderChat, renderForm, renderContent, renderComplete } from './ui.js';
export type {
  Delivery,
  FormDelivery,
  ContentDelivery,
  GameDelivery,
  PreloadDelivery,
  CompleteDelivery,
  FormField,
  Answers,
  ChatScreen,
  ChatHandlers,
} from './ui.js';
