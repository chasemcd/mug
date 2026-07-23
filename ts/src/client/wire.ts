/**
 * The realtime wire types and the command minter.
 *
 * The participant client speaks the native realtime protocol at `/ws`. It never
 * builds the server-side `WireCommandEnvelope`; it sends a `RealtimeCommand` (an
 * addressed, idempotent command header) plus a free-form payload, and the server
 * translates that into a domain command. This module holds the frame shapes both
 * directions and the minter that builds a well-formed `RealtimeCommand`.
 *
 * The minter derives the command header from `@mug/kernel`: the `payload_digest`
 * is the real SHA-256 of the payload's canonical bytes (the kernel twin), so the
 * client digests a value exactly as the server would. The clock, the random
 * source, and the hasher are injected, so a test drives the minter with fixed
 * inputs and the browser passes the real `Date`, `crypto`, and Web Crypto hasher.
 */

import { computeDigest, Digest, HashBytes, JsonValue, SchemaRef } from '../kernel/index.js';

/** Return the current time as milliseconds since the Unix epoch. */
export type NowMillis = () => number;

/** Return `count` cryptographically random bytes. */
export type RandomBytes = (count: number) => Uint8Array;

/** The injected primitives the command minter needs. */
export interface WireEnv {
  now: NowMillis;
  randomBytes: RandomBytes;
  hash: HashBytes;
}

/** A realtime command header, as the wire carries it (see `mug.client.types`). */
export interface RealtimeCommand {
  command_id: string;
  channel_key: string;
  intent_schema: SchemaRef;
  payload_digest: Digest;
  idempotency_key: string;
  submitted_at: string;
}

/** A command frame: the header and its payload. */
export interface CommandFrame {
  type: 'command';
  command: RealtimeCommand;
  payload: JsonValue;
}

/** A keyboard input frame for the server stepping loop. */
export interface InputFrame {
  type: 'input';
  keys: string[];
}

/** Any frame the client sends to the server. */
export type OutgoingFrame = CommandFrame | InputFrame;

// The demo intent schema. The server reads the payload directly for the flow and
// capture channels, so it never resolves this reference; the client sends a
// well-formed placeholder, matching the reference JavaScript client.
const DEMO_INTENT_DIGEST: Digest = { algorithm: 'sha-256', hex: 'a'.repeat(64) };
export const DEMO_INTENT: SchemaRef = {
  name: 'mug.demo.intent',
  version: 0,
  digest: DEMO_INTENT_DIGEST,
};

/**
 * Mint a UUID version 7: a 48-bit millisecond timestamp, the version and variant
 * nibbles, and random bytes for the rest. This matches the reference client and
 * the server's own version-7 minting, so the value passes the `command_` id rule.
 */
export function uuid7(env: WireEnv): string {
  const bytes = env.randomBytes(16);
  const ms = env.now();
  for (let i = 0; i < 6; i++) {
    bytes[5 - i] = Math.floor(ms / 2 ** (8 * i)) & 0xff;
  }
  bytes[6] = 0x70 | (bytes[6]! & 0x0f);
  bytes[8] = 0x80 | (bytes[8]! & 0x3f);
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
  return (
    hex.slice(0, 8) +
    '-' +
    hex.slice(8, 12) +
    '-' +
    hex.slice(12, 16) +
    '-' +
    hex.slice(16, 20) +
    '-' +
    hex.slice(20)
  );
}

/** Encode bytes as unpadded base64url. */
export function base64url(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/**
 * Mint an idempotency key: `idem_` and 16 random bytes as base64url. Sixteen
 * bytes render as 22 base64url characters whose last character is one of
 * `A Q g w`, so the value fits the `idem_...` pattern the kernel enforces.
 */
export function idempotencyKey(env: WireEnv): string {
  return 'idem_' + base64url(env.randomBytes(16));
}

/**
 * Render the current time as a UTC instant with six fractional digits. The
 * millisecond stamp is padded with three trailing zeros to reach microseconds,
 * which is the precision the wire instant carries.
 */
export function instant(env: WireEnv): string {
  return new Date(env.now()).toISOString().replace('Z', '000Z');
}

/**
 * Build a command frame for a channel and payload. The `payload_digest` is the
 * real digest of the payload, computed through the kernel twin, so the header
 * binds to exactly the bytes the payload canonicalizes to.
 */
export async function buildCommand(
  env: WireEnv,
  channelKey: string,
  payload: JsonValue,
): Promise<CommandFrame> {
  const command: RealtimeCommand = {
    command_id: 'command_' + uuid7(env),
    channel_key: channelKey,
    intent_schema: DEMO_INTENT,
    payload_digest: await computeDigest(payload, env.hash),
    idempotency_key: idempotencyKey(env),
    submitted_at: instant(env),
  };
  return { type: 'command', command, payload };
}
