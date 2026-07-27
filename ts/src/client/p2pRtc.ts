/**
 * The narrow RTC seam used by the P2P mesh.
 *
 * Tests provide an in-process implementation. The browser adapter below is the
 * only place, apart from bootstrap, that translates native WebRTC events.
 */

import { p2pSchema } from './p2pOutbound.js';
import { P2PBootstrap, P2PSignalDelivery } from './p2pWire.js';

export type RtcJsonObject = Record<string, unknown>;

export interface MeshDataChannel {
  readonly label: string;
  readonly ordered: boolean;
  readonly maxRetransmits: number | null;
  readonly readyState: string;
  send(data: string): void;
  close(): void;
  onOpen(handler: () => void): void;
  onMessage(handler: (data: unknown) => void): void;
  onClose(handler: () => void): void;
  onError(handler: () => void): void;
}

export interface MeshPeerConnection {
  readonly connectionState: string;
  createDataChannel(
    label: string,
    options: { ordered: false; maxRetransmits: 0 },
  ): MeshDataChannel;
  createOffer(): Promise<RtcJsonObject>;
  createAnswer(): Promise<RtcJsonObject>;
  setLocalDescription(description: RtcJsonObject): Promise<void>;
  setRemoteDescription(description: RtcJsonObject): Promise<void>;
  addIceCandidate(candidate: RtcJsonObject | null): Promise<void>;
  close(): void;
  onIceCandidate(handler: (candidate: RtcJsonObject | null) => void): void;
  onDataChannel(handler: (channel: MeshDataChannel) => void): void;
  onConnectionStateChange(handler: () => void): void;
}

export interface PeerConnectionFactory {
  (peerHandle: string, bootstrap: P2PBootstrap): MeshPeerConnection;
  release?(): void;
}

export interface IceGrantFetchInit {
  method: 'POST';
  credentials: 'same-origin';
  headers: { 'Content-Type': 'application/json' };
  body: string;
  signal: AbortSignal;
}

export interface IceGrantResponse {
  readonly ok: boolean;
  readonly status: number;
  readonly headers: { get(name: string): string | null };
  json(): Promise<unknown>;
}

export type IceGrantFetch = (
  endpoint: string,
  init: IceGrantFetchInit,
) => Promise<IceGrantResponse>;

/** Decode the already size-checked opaque SDP or ICE JSON object. */
export function parseRtcSignalPayload(
  signal: P2PSignalDelivery,
): RtcJsonObject {
  if (signal.payload_json === undefined) {
    throw new Error(signal.signal_kind + ' signal is missing payload_json');
  }
  const value: unknown = JSON.parse(signal.payload_json);
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('P2P signal payload must be a JSON object');
  }
  return value as RtcJsonObject;
}

function descriptionJson(description: RTCSessionDescriptionInit): RtcJsonObject {
  return {
    type: description.type,
    ...(description.sdp === undefined ? {} : { sdp: description.sdp }),
  };
}

function descriptionInit(value: RtcJsonObject): RTCSessionDescriptionInit {
  const type = value.type;
  if (!['answer', 'offer', 'pranswer', 'rollback'].includes(String(type))) {
    throw new Error('RTC description has an invalid type');
  }
  if (value.sdp !== undefined && typeof value.sdp !== 'string') {
    throw new Error('RTC description has an invalid SDP value');
  }
  return {
    type: type as RTCSdpType,
    ...(value.sdp === undefined ? {} : { sdp: value.sdp }),
  };
}

function candidateInit(value: RtcJsonObject): RTCIceCandidateInit {
  if (typeof value.candidate !== 'string') {
    throw new Error('RTC candidate is missing candidate text');
  }
  const result: RTCIceCandidateInit = { candidate: value.candidate };
  if (value.sdpMid === null || typeof value.sdpMid === 'string') {
    result.sdpMid = value.sdpMid;
  }
  if (value.sdpMLineIndex === null || Number.isInteger(value.sdpMLineIndex)) {
    result.sdpMLineIndex = value.sdpMLineIndex as number | null;
  }
  if (typeof value.usernameFragment === 'string') {
    result.usernameFragment = value.usernameFragment;
  }
  return result;
}

function candidateJson(candidate: RTCIceCandidate): RtcJsonObject {
  const value = candidate.toJSON();
  return {
    candidate: value.candidate,
    ...(value.sdpMid === null ? {} : { sdpMid: value.sdpMid }),
    ...(value.sdpMLineIndex === null ? {} : { sdpMLineIndex: value.sdpMLineIndex }),
    ...(value.usernameFragment === undefined
      ? {}
      : { usernameFragment: value.usernameFragment }),
  };
}

/** Adapt a native browser channel without exposing DOM event types to the core. */
function adaptChannel(channel: RTCDataChannel): MeshDataChannel {
  return {
    get label(): string {
      return channel.label;
    },
    get ordered(): boolean {
      return channel.ordered;
    },
    get maxRetransmits(): number | null {
      return channel.maxRetransmits;
    },
    get readyState(): string {
      return channel.readyState;
    },
    send: (data) => channel.send(data),
    close: () => channel.close(),
    onOpen: (handler) => channel.addEventListener('open', handler),
    onMessage: (handler) =>
      channel.addEventListener('message', (event) => handler(event.data as unknown)),
    onClose: (handler) => channel.addEventListener('close', handler),
    onError: (handler) => channel.addEventListener('error', handler),
  };
}

/**
 * Build the injected factory for a resolved short-lived ICE configuration.
 *
 * Provisioning the credentials is separate from RTC ownership. Callers fetch
 * them through the authenticated grant endpoint, then create one factory shared
 * by all pairwise connections in the room.
 */
export function browserPeerConnectionFactory(
  configuration: RTCConfiguration,
): PeerConnectionFactory {
  return (): MeshPeerConnection => {
    const connection = new RTCPeerConnection(configuration);
    return {
      get connectionState(): string {
        return connection.connectionState;
      },
      createDataChannel: (label, options) =>
        adaptChannel(connection.createDataChannel(label, options)),
      createOffer: async () => descriptionJson(await connection.createOffer()),
      createAnswer: async () => descriptionJson(await connection.createAnswer()),
      setLocalDescription: async (description) =>
        connection.setLocalDescription(descriptionInit(description)),
      setRemoteDescription: async (description) =>
        connection.setRemoteDescription(descriptionInit(description)),
      addIceCandidate: async (candidate) =>
        connection.addIceCandidate(candidate === null ? null : candidateInit(candidate)),
      close: () => connection.close(),
      onIceCandidate: (handler) =>
        connection.addEventListener('icecandidate', (event) =>
          handler(event.candidate === null ? null : candidateJson(event.candidate)),
        ),
      onDataChannel: (handler) =>
        connection.addEventListener('datachannel', (event) =>
          handler(adaptChannel(event.channel)),
        ),
      onConnectionStateChange: (handler) =>
        connection.addEventListener('connectionstatechange', handler),
    };
  };
}

/** Redeem a one-use grant and return a factory that drops credential references. */
export async function fetchBrowserPeerConnectionFactory(
  bootstrap: P2PBootstrap,
  fetchGrant: IceGrantFetch,
): Promise<PeerConnectionFactory> {
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    Math.min(bootstrap.validation_timeout_ms, 10_000),
  );
  let response: IceGrantResponse;
  try {
    response = await fetchGrant(bootstrap.ice_endpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        schema: p2pSchema(bootstrap, 'mug.api-09.p2p-ice-grant-request'),
        ice_grant_handle: bootstrap.ice_grant_handle,
      }),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    throw new Error('ICE grant request failed with status ' + response.status);
  }
  const cacheControl = response.headers.get('Cache-Control') ?? '';
  if (!cacheControl.toLowerCase().split(',').some((value) => value.trim() === 'no-store')) {
    throw new Error('ICE grant response must carry Cache-Control: no-store');
  }
  let configuration: RTCConfiguration | null = parseIceConfiguration(await response.json());
  let remaining = bootstrap.peers.length;
  const release = (): void => {
    if (configuration !== null) {
      configuration.iceServers = [];
      configuration = null;
    }
  };
  const factory: PeerConnectionFactory = (peerHandle, currentBootstrap): MeshPeerConnection => {
    if (
      configuration === null ||
      currentBootstrap.room_handle !== bootstrap.room_handle ||
      currentBootstrap.negotiation_generation !== bootstrap.negotiation_generation
    ) {
      throw new Error('ICE configuration is stale or already consumed');
    }
    let connection: MeshPeerConnection;
    try {
      connection = browserPeerConnectionFactory(configuration)(peerHandle, currentBootstrap);
    } catch (error) {
      release();
      throw error;
    }
    remaining -= 1;
    if (remaining === 0) {
      release();
    }
    return connection;
  };
  factory.release = release;
  return factory;
}

/** An ICE server after parsing, whose urls are always a bounded string list. */
type ParsedIceServer = RTCIceServer & { urls: string[] };

function parseIceConfiguration(value: unknown): RTCConfiguration {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('ICE grant response must be an object');
  }
  const item = value as Record<string, unknown>;
  if (
    Object.keys(item).length !== 2 ||
    !Array.isArray(item.iceServers) ||
    item.iceServers.length > 16 ||
    (item.iceTransportPolicy !== 'all' && item.iceTransportPolicy !== 'relay')
  ) {
    throw new Error('ICE grant response has an invalid shape');
  }
  const iceServers = item.iceServers.map(parseIceServer);
  if (
    item.iceTransportPolicy === 'relay' &&
    !iceServers.some((server) =>
      server.urls.some((url) => url.startsWith('turn:') || url.startsWith('turns:')))
  ) {
    throw new Error('relay-only ICE configuration requires a TURN server');
  }
  return { iceServers, iceTransportPolicy: item.iceTransportPolicy };
}

function parseIceServer(value: unknown): ParsedIceServer {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('ICE server must be an object');
  }
  const item = value as Record<string, unknown>;
  const allowed = new Set(['urls', 'username', 'credential']);
  const hasUsername = item.username !== undefined;
  const hasCredential = item.credential !== undefined;
  if (
    Object.keys(item).some((key) => !allowed.has(key)) ||
    !Array.isArray(item.urls) ||
    item.urls.length === 0 ||
    item.urls.length > 8 ||
    !item.urls.every((url) =>
      typeof url === 'string' && url.length > 0 && url.length <= 2_048) ||
    hasUsername !== hasCredential ||
    (hasUsername && (typeof item.username !== 'string' || item.username.length > 512)) ||
    (hasCredential && (typeof item.credential !== 'string' || item.credential.length > 2_048))
  ) {
    throw new Error('ICE server has an invalid shape');
  }
  return {
    urls: item.urls as string[],
    ...(item.username === undefined ? {} : { username: item.username as string }),
    ...(item.credential === undefined ? {} : { credential: item.credential as string }),
  };
}
