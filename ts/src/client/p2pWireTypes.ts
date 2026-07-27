/** Closed TypeScript shapes for the ephemeral browser P2P control wire. */

import { Digest, SchemaRef } from '../kernel/index.js';

export type PeerRole = 'offerer' | 'answerer';
export type SignalKind = 'offer' | 'answer' | 'candidate' | 'end_of_candidates';
export type SignalAckStatus = 'queued' | 'rejected';
export type SignalErrorCode =
  | 'stale_generation'
  | 'not_a_member'
  | 'unknown_target'
  | 'lease_expired'
  | 'rate_limited'
  | 'payload_too_large'
  | 'invalid_signal'
  | 'room_closed';
export type MeshAbortReason =
  | 'peer_disconnected'
  | 'negotiation_timeout'
  | 'validation_failed'
  | 'stale_connection'
  | 'room_replaced'
  | 'capture_timeout'
  | 'capture_conflict'
  | 'server_unavailable';
export type MeshAbortDisposition = 'repool' | 'resume_flow' | 'terminal';

export interface BootstrapPeer {
  peer_handle: string;
  role: PeerRole;
}

export interface P2PBootstrap {
  schema: SchemaRef;
  room_handle: string;
  negotiation_generation: number;
  local_peer_handle: string;
  capture_owner_handle: string;
  peers: BootstrapPeer[];
  data_channel: {
    label: 'mug-mesh-data';
    ordered: false;
    max_retransmits: 0;
  };
  validation_timeout_ms: number;
  ice_grant_handle: string;
  ice_endpoint: string;
  ice_expires_at: string;
}

export interface P2PSignalDelivery {
  schema: SchemaRef;
  room_handle: string;
  source_peer_handle: string;
  negotiation_generation: number;
  signal_kind: SignalKind;
  payload_json?: string;
}

export interface P2PSignalAck {
  schema: SchemaRef;
  request_id: string;
  status: SignalAckStatus;
  error_code?: SignalErrorCode;
}

export interface P2PMeshStart {
  schema: SchemaRef;
  room_handle: string;
  negotiation_generation: number;
  seed: number;
  start_sequence: number;
  capture_owner_handle: string;
}

export interface P2PMeshAbort {
  schema: SchemaRef;
  room_handle: string;
  negotiation_generation: number;
  reason: MeshAbortReason;
  disposition: MeshAbortDisposition;
}

export interface P2PMeshFinish {
  schema: SchemaRef;
  room_handle: string;
  negotiation_generation: number;
  trajectory_digest: Digest;
  frame_count: number;
  capture_receipt: string;
}

export type P2PInboundFrame =
  | { type: 'p2p_bootstrap'; bootstrap: P2PBootstrap }
  | { type: 'p2p_signal_delivery'; signal: P2PSignalDelivery }
  | { type: 'p2p_signal_ack'; ack: P2PSignalAck }
  | { type: 'p2p_mesh_start'; start: P2PMeshStart }
  | { type: 'p2p_mesh_abort'; abort: P2PMeshAbort }
  | { type: 'p2p_mesh_finish'; finish: P2PMeshFinish };

export interface P2PSignal {
  schema: SchemaRef;
  request_id: string;
  room_handle: string;
  target_peer_handle: string;
  negotiation_generation: number;
  signal_kind: SignalKind;
  payload_json?: string;
}

export interface P2PPeerReady {
  schema: SchemaRef;
  room_handle: string;
  negotiation_generation: number;
  validated_peer_handles: string[];
}

export interface P2PPeerComplete {
  schema: SchemaRef;
  room_handle: string;
  negotiation_generation: number;
  trajectory_digest: Digest;
  frame_count: number;
}

export interface P2PCaptureSubmission extends P2PPeerComplete {
  payload_json: string;
  payload_digest: Digest;
}

export type P2POutboundFrame =
  | { type: 'p2p_signal'; signal: P2PSignal }
  | { type: 'p2p_peer_ready'; ready: P2PPeerReady }
  | { type: 'p2p_peer_complete'; complete: P2PPeerComplete }
  | { type: 'p2p_capture_submission'; submission: P2PCaptureSubmission };
