/** Builders for generation-fenced client-to-server P2P control frames. */

import { Digest, SchemaRef } from '../kernel/index.js';
import {
  P2PBootstrap,
  P2PCaptureSubmission,
  P2POutboundFrame,
  P2PPeerComplete,
  P2PPeerReady,
  SignalKind,
} from './p2pWireTypes.js';

export type P2POutboundSchemaName =
  | 'mug.api-09.p2p-ice-grant-request'
  | 'mug.api-09.p2p-signal'
  | 'mug.api-09.p2p-peer-ready'
  | 'mug.api-09.p2p-peer-complete'
  | 'mug.api-09.p2p-capture-submission';

/** Derive another record's pinned schema from the authenticated bootstrap. */
export function p2pSchema(
  bootstrap: P2PBootstrap,
  name: P2POutboundSchemaName,
): SchemaRef {
  return { name, version: 0, digest: { ...bootstrap.schema.digest } };
}

/** Encode bounded opaque RTC JSON before it reaches the socket send queue. */
export function signalPayloadJson(
  kind: SignalKind,
  payload: Record<string, unknown> | undefined,
): string | undefined {
  if (payload === undefined) {
    return undefined;
  }
  const encoded = JSON.stringify(payload);
  const characterLimit = kind === 'candidate' ? 4_096 : 65_536;
  if (
    encoded.length > characterLimit ||
    new TextEncoder().encode(encoded).byteLength > 65_536
  ) {
    throw new Error('P2P ' + kind + ' payload exceeds its wire bound');
  }
  return encoded;
}

/** Build the all-links-validated claim sent before the server start barrier. */
export function peerReadyFrame(
  bootstrap: P2PBootstrap,
  peerHandles: readonly string[],
): P2POutboundFrame {
  const ready: P2PPeerReady = {
    schema: p2pSchema(bootstrap, 'mug.api-09.p2p-peer-ready'),
    room_handle: bootstrap.room_handle,
    negotiation_generation: bootstrap.negotiation_generation,
    validated_peer_handles: [...peerHandles].sort(),
  };
  return { type: 'p2p_peer_ready', ready };
}

/** Build one peer's final replica evidence claim. */
export function peerCompleteFrame(
  bootstrap: P2PBootstrap,
  trajectoryDigest: Digest,
  frameCount: number,
): P2POutboundFrame {
  const complete: P2PPeerComplete = {
    schema: p2pSchema(bootstrap, 'mug.api-09.p2p-peer-complete'),
    room_handle: bootstrap.room_handle,
    negotiation_generation: bootstrap.negotiation_generation,
    trajectory_digest: trajectoryDigest,
    frame_count: frameCount,
  };
  return { type: 'p2p_peer_complete', complete };
}

/** Build the designated owner's bounded capture submission. */
export function captureSubmissionFrame(
  bootstrap: P2PBootstrap,
  trajectoryDigest: Digest,
  frameCount: number,
  payloadJson: string,
  payloadDigest: Digest,
): P2POutboundFrame {
  if (payloadJson.length < 1 || payloadJson.length > 1_048_576) {
    throw new Error('P2P capture payload must contain at most 1048576 characters');
  }
  const submission: P2PCaptureSubmission = {
    schema: p2pSchema(bootstrap, 'mug.api-09.p2p-capture-submission'),
    room_handle: bootstrap.room_handle,
    negotiation_generation: bootstrap.negotiation_generation,
    trajectory_digest: trajectoryDigest,
    frame_count: frameCount,
    payload_json: payloadJson,
    payload_digest: payloadDigest,
  };
  return { type: 'p2p_capture_submission', submission };
}
