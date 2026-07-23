/**
 * Content digests over canonical bytes.
 *
 * A digest is the SHA-256 of a value's RFC 8785 canonical bytes, shaped as the
 * structured `{ algorithm, hex }` the wire uses. SHA-256 itself is universal, so
 * once the canonical bytes match the Python side (the conformance vectors prove
 * this) the digest matches too.
 *
 * The hash step is injected. A caller passes a `HashBytes` that hashes UTF-8
 * bytes to a lowercase hex string. `browserSha256` is the browser default; it
 * uses the Web Crypto `crypto.subtle.digest`, which is asynchronous, so every
 * digest helper here returns a promise.
 */

import { canonicalBytes, JsonValue } from './canonical.js';

/** A content digest as the wire carries it. */
export interface Digest {
  algorithm: 'sha-256';
  hex: string;
}

/** Hash UTF-8 bytes to a lowercase SHA-256 hex string. */
export type HashBytes = (bytes: Uint8Array) => Promise<string>;

/** Return the lowercase SHA-256 hex of a value's canonical bytes. */
export async function sha256Hex(value: JsonValue, hash: HashBytes): Promise<string> {
  return hash(canonicalBytes(value));
}

/** Return the structured `Digest` of a value's canonical bytes. */
export async function computeDigest(value: JsonValue, hash: HashBytes): Promise<Digest> {
  return { algorithm: 'sha-256', hex: await sha256Hex(value, hash) };
}

/** Return the `sha256:<hex>` entity tag of a value's canonical bytes. */
export async function etag(value: JsonValue, hash: HashBytes): Promise<string> {
  return 'sha256:' + (await sha256Hex(value, hash));
}

/** Render raw hash bytes as a lowercase hex string. */
export function bytesToHex(bytes: Uint8Array): string {
  let hex = '';
  for (const byte of bytes) {
    hex += byte.toString(16).padStart(2, '0');
  }
  return hex;
}

/**
 * The browser default hasher: SHA-256 over Web Crypto.
 *
 * It runs in any browser and in a Web Worker. Node before 15 has no
 * `crypto.subtle`, so the Node conformance runner injects its own hasher instead.
 */
export const browserSha256: HashBytes = async (bytes: Uint8Array): Promise<string> => {
  // Copy into a fresh ArrayBuffer-backed view: a `Uint8Array` may be backed by a
  // `SharedArrayBuffer`, which Web Crypto's `BufferSource` does not accept.
  const buffer = new Uint8Array(bytes);
  const digest = await crypto.subtle.digest('SHA-256', buffer);
  return bytesToHex(new Uint8Array(digest));
};
