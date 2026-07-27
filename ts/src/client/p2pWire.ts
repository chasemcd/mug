/**
 * These ephemeral frames negotiate and fence a WebRTC mesh. They are not durable study
 * commands: SDP, ICE, and short-lived room handles must never enter the command
 * ledger or participant storage. The parser rejects malformed P2P frames before
 * they reach the RTC state machine.
 */

import { SchemaRef, isUtcInstant } from '../kernel/index.js';
import {
  BootstrapPeer,
  MeshAbortDisposition,
  MeshAbortReason,
  P2PBootstrap,
  P2PInboundFrame,
  P2PMeshFinish,
  P2PSignalAck,
  P2PSignalDelivery,
  PeerRole,
  SignalAckStatus,
  SignalErrorCode,
  SignalKind,
} from './p2pWireTypes.js';
import {
  choice,
  digest,
  exactKeys,
  handle,
  integer,
  P2PWireError,
  record,
  requestId,
  schemaRef,
  text,
} from './p2pWireFields.js';

export {
  P2P_CLIENT_BUNDLE_DIGEST,
  P2PWireError,
} from './p2pWireFields.js';

export type {
  BootstrapPeer,
  MeshAbortDisposition,
  MeshAbortReason,
  P2PBootstrap,
  P2PCaptureSubmission,
  P2PInboundFrame,
  P2PMeshAbort,
  P2PMeshFinish,
  P2PMeshStart,
  P2POutboundFrame,
  P2PPeerComplete,
  P2PPeerReady,
  P2PSignal,
  P2PSignalAck,
  P2PSignalDelivery,
  PeerRole,
  SignalAckStatus,
  SignalErrorCode,
  SignalKind,
} from './p2pWireTypes.js';

const INBOUND_TYPES = new Set<string>([
  'p2p_bootstrap',
  'p2p_signal_delivery',
  'p2p_signal_ack',
  'p2p_mesh_start',
  'p2p_mesh_abort',
  'p2p_mesh_finish',
]);
const SIGNAL_KINDS = new Set<string>([
  'offer',
  'answer',
  'candidate',
  'end_of_candidates',
]);
const SIGNAL_ERRORS = new Set<string>([
  'stale_generation',
  'not_a_member',
  'unknown_target',
  'lease_expired',
  'rate_limited',
  'payload_too_large',
  'invalid_signal',
  'room_closed',
]);
const ABORT_REASONS = new Set<string>([
  'peer_disconnected',
  'negotiation_timeout',
  'validation_failed',
  'stale_connection',
  'room_replaced',
  'capture_timeout',
  'capture_conflict',
  'server_unavailable',
]);
const ICE_ENDPOINT =
  /^\/[A-Za-z0-9](?:[A-Za-z0-9._~!$&'()*+,;=:@/-]*[A-Za-z0-9/_~-])?$/;

function signalPayload(value: Record<string, unknown>): {
  signal_kind: SignalKind;
  payload_json?: string;
} {
  const signalKind = choice<SignalKind>(value.signal_kind, 'signal_kind', SIGNAL_KINDS);
  if (signalKind === 'end_of_candidates') {
    if ('payload_json' in value) {
      throw new P2PWireError('end_of_candidates must omit payload_json');
    }
    return { signal_kind: signalKind };
  }
  const payload = text(value.payload_json, 'payload_json');
  const limit = signalKind === 'candidate' ? 4_096 : 65_536;
  if (payload.length > limit) {
    throw new P2PWireError('payload_json exceeds ' + limit + ' characters');
  }
  return { signal_kind: signalKind, payload_json: payload };
}

function bootstrap(value: unknown): P2PBootstrap {
  const parsed = record(value, 'bootstrap');
  exactKeys(parsed, [
    'schema', 'room_handle', 'negotiation_generation', 'local_peer_handle',
    'capture_owner_handle', 'peers', 'data_channel', 'validation_timeout_ms',
    'ice_grant_handle', 'ice_endpoint', 'ice_expires_at',
  ]);
  if (!Array.isArray(parsed.peers) || parsed.peers.length < 1 || parsed.peers.length > 15) {
    throw new P2PWireError('peers must contain between 1 and 15 entries');
  }
  const peers = parsed.peers.map((item): BootstrapPeer => {
    const peer = record(item, 'peer');
    exactKeys(peer, ['peer_handle', 'role']);
    return {
      peer_handle: handle(peer.peer_handle, 'peer_handle'),
      role: choice<PeerRole>(peer.role, 'role', new Set(['offerer', 'answerer'])),
    };
  });
  const local = handle(parsed.local_peer_handle, 'local_peer_handle');
  const handles = peers.map((peer) => peer.peer_handle);
  if (handles.includes(local) || new Set(handles).size !== handles.length) {
    throw new P2PWireError('peer handles must be unique and remote');
  }
  const captureOwner = handle(parsed.capture_owner_handle, 'capture_owner_handle');
  if (captureOwner !== local && !handles.includes(captureOwner)) {
    throw new P2PWireError('capture_owner_handle must name a room participant');
  }
  const room = handle(parsed.room_handle, 'room_handle');
  const iceGrant = handle(parsed.ice_grant_handle, 'ice_grant_handle');
  if (room === iceGrant || [local, ...handles].includes(room) || [local, ...handles].includes(iceGrant)) {
    throw new P2PWireError('room, ICE grant, and participant handles must be distinct');
  }
  const channel = record(parsed.data_channel, 'data_channel');
  exactKeys(channel, ['label', 'ordered', 'max_retransmits']);
  if (
    channel.label !== 'mug-mesh-data' ||
    channel.ordered !== false ||
    channel.max_retransmits !== 0
  ) {
    throw new P2PWireError('data_channel does not match the MUG mesh channel');
  }
  return {
    schema: schemaRef(parsed.schema, 'mug.api-09.p2p-mesh-bootstrap'),
    room_handle: room,
    negotiation_generation: integer(parsed.negotiation_generation, 'generation', 1),
    local_peer_handle: local,
    capture_owner_handle: captureOwner,
    peers,
    data_channel: { label: 'mug-mesh-data', ordered: false, max_retransmits: 0 },
    validation_timeout_ms: timeout(parsed.validation_timeout_ms),
    ice_grant_handle: iceGrant,
    ice_endpoint: iceEndpoint(parsed.ice_endpoint),
    ice_expires_at: instant(parsed.ice_expires_at),
  };
}

function timeout(value: unknown): number {
  const parsed = integer(value, 'validation_timeout_ms', 1_000);
  if (parsed > 60_000) {
    throw new P2PWireError('validation_timeout_ms exceeds 60000');
  }
  return parsed;
}

function iceEndpoint(value: unknown): string {
  const parsed = text(value, 'ice_endpoint');
  if (parsed.length > 256 || !ICE_ENDPOINT.test(parsed)) {
    throw new P2PWireError('ice_endpoint must be a same-origin path');
  }
  return parsed;
}

function instant(value: unknown): string {
  if (typeof value !== 'string' || !isUtcInstant(value)) {
    throw new P2PWireError('ice_expires_at must be a fixed UTC instant');
  }
  return value;
}

function signal(value: unknown): P2PSignalDelivery {
  const parsed = record(value, 'signal');
  exactKeys(
    parsed,
    ['schema', 'room_handle', 'source_peer_handle', 'negotiation_generation', 'signal_kind'],
    ['payload_json'],
  );
  return {
    schema: schemaRef(parsed.schema, 'mug.api-09.p2p-signal-delivery'),
    room_handle: handle(parsed.room_handle, 'room_handle'),
    source_peer_handle: handle(parsed.source_peer_handle, 'source_peer_handle'),
    negotiation_generation: integer(parsed.negotiation_generation, 'generation', 1),
    ...signalPayload(parsed),
  };
}

function ack(value: unknown): P2PSignalAck {
  const parsed = record(value, 'ack');
  exactKeys(parsed, ['schema', 'request_id', 'status'], ['error_code']);
  const status = choice<SignalAckStatus>(parsed.status, 'status', new Set(['queued', 'rejected']));
  const errorCode = parsed.error_code === undefined
    ? undefined
    : choice<SignalErrorCode>(parsed.error_code, 'error_code', SIGNAL_ERRORS);
  if ((status === 'rejected') !== (errorCode !== undefined)) {
    throw new P2PWireError('only a rejected signal ack carries error_code');
  }
  return {
    schema: schemaRef(parsed.schema, 'mug.api-09.p2p-signal-ack'),
    request_id: requestId(parsed.request_id),
    status,
    ...(errorCode === undefined ? {} : { error_code: errorCode }),
  };
}

function roomBoundary(
  value: unknown,
  path: string,
  fields: readonly string[],
  schemaName: string,
): Record<string, unknown> & {
  schema: SchemaRef;
  room_handle: string;
  negotiation_generation: number;
} {
  const parsed = record(value, path);
  exactKeys(parsed, ['schema', 'room_handle', 'negotiation_generation', ...fields]);
  return {
    ...parsed,
    schema: schemaRef(parsed.schema, schemaName),
    room_handle: handle(parsed.room_handle, 'room_handle'),
    negotiation_generation: integer(parsed.negotiation_generation, 'generation', 1),
  };
}

/** Parse one P2P frame, rejecting extra fields and malformed nested values. */
export function parseP2PInboundFrame(value: unknown): P2PInboundFrame {
  const envelope = record(value, 'P2P frame');
  const type = text(envelope.type, 'type');
  if (!INBOUND_TYPES.has(type)) {
    throw new P2PWireError('unknown P2P frame type');
  }
  if (type === 'p2p_bootstrap') {
    exactKeys(envelope, ['type', 'bootstrap']);
    return { type, bootstrap: bootstrap(envelope.bootstrap) };
  }
  if (type === 'p2p_signal_delivery') {
    exactKeys(envelope, ['type', 'signal']);
    return { type, signal: signal(envelope.signal) };
  }
  if (type === 'p2p_signal_ack') {
    exactKeys(envelope, ['type', 'ack']);
    return { type, ack: ack(envelope.ack) };
  }
  if (type === 'p2p_mesh_start') {
    exactKeys(envelope, ['type', 'start']);
    const start = roomBoundary(
      envelope.start, 'start', ['seed', 'start_sequence', 'capture_owner_handle'],
      'mug.api-09.p2p-mesh-start',
    );
    return { type, start: {
      schema: start.schema,
      room_handle: start.room_handle,
      negotiation_generation: start.negotiation_generation,
      seed: integer(start.seed, 'seed'),
      start_sequence: integer(start.start_sequence, 'start_sequence', 1),
      capture_owner_handle: handle(start.capture_owner_handle, 'capture_owner_handle'),
    } };
  }
  if (type === 'p2p_mesh_abort') {
    exactKeys(envelope, ['type', 'abort']);
    const abort = roomBoundary(
      envelope.abort, 'abort', ['reason', 'disposition'], 'mug.api-09.p2p-mesh-abort',
    );
    return { type, abort: {
      schema: abort.schema,
      room_handle: abort.room_handle,
      negotiation_generation: abort.negotiation_generation,
      reason: choice<MeshAbortReason>(abort.reason, 'reason', ABORT_REASONS),
      disposition: choice<MeshAbortDisposition>(
        abort.disposition, 'disposition', new Set(['repool', 'resume_flow', 'terminal']),
      ),
    } };
  }
  if (type === 'p2p_mesh_finish') {
    exactKeys(envelope, ['type', 'finish']);
    const finish = roomBoundary(
      envelope.finish, 'finish', ['trajectory_digest', 'frame_count', 'capture_receipt'],
      'mug.api-09.p2p-mesh-finish',
    );
    return { type, finish: {
      schema: finish.schema,
      room_handle: finish.room_handle,
      negotiation_generation: finish.negotiation_generation,
      trajectory_digest: digest(finish.trajectory_digest, 'trajectory_digest'),
      frame_count: integer(finish.frame_count, 'frame_count'),
      capture_receipt: handle(finish.capture_receipt, 'capture_receipt'),
    } };
  }
  throw new P2PWireError('unreachable P2P frame type');
}

/** Report whether a decoded object claims one of the reserved P2P frame types. */
export function isP2PInboundType(value: unknown): boolean {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }
  const type = (value as Record<string, unknown>).type;
  return typeof type === 'string' && (INBOUND_TYPES.has(type) || type.startsWith('p2p_'));
}
