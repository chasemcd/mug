/** Strict scalar and nested-field parsing shared by P2P inbound records. */

import {
  Digest,
  SchemaRef,
  isPublicHandle,
  isSchemaRef,
  isSha256Hex,
} from '../kernel/index.js';

// The api-09 schema bundle this client will accept a P2P frame under. It is the
// canonical digest of `docs/architecture/phase-0/api-09/schemas/v0/client.schema.json`,
// and it is written here rather than fetched because a peer must be able to refuse a
// frame from a client built against a different contract.
//
// **It moves whenever that bundle moves.** A stale value here refuses every P2P frame
// with "schema must identify ...", which is a working server, a working peer, and a
// mesh that never forms. `tests/unit/client/test_wire_twin_pins.py` fails when this
// and the Python bundle disagree, because nothing else noticed the last time.
export const P2P_CLIENT_BUNDLE_DIGEST =
  '8d3a7245555870295a7546bb3c2bc91e2f94c2fded93b07ae779d1ad885a79b6';
const REQUEST_ID =
  /^request_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export class P2PWireError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'P2PWireError';
  }
}

export function record(value: unknown, path: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new P2PWireError(path + ' must be an object');
  }
  return value as Record<string, unknown>;
}

export function exactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): void {
  const allowed = new Set([...required, ...optional]);
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) {
      throw new P2PWireError('unexpected P2P field ' + key);
    }
  }
  for (const key of required) {
    if (!(key in value)) {
      throw new P2PWireError('missing P2P field ' + key);
    }
  }
}

export function text(value: unknown, path: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new P2PWireError(path + ' must be a non-empty string');
  }
  return value;
}

export function integer(value: unknown, path: string, minimum = 0): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw new P2PWireError(path + ' must be a safe integer >= ' + minimum);
  }
  return value as number;
}

export function handle(value: unknown, path: string): string {
  if (typeof value !== 'string' || !isPublicHandle(value)) {
    throw new P2PWireError(path + ' must be a public handle');
  }
  return value;
}

export function requestId(value: unknown): string {
  if (typeof value !== 'string' || !REQUEST_ID.test(value)) {
    throw new P2PWireError('request_id must be a registered request ID');
  }
  return value;
}

export function choice<T extends string>(
  value: unknown,
  path: string,
  choices: ReadonlySet<string>,
): T {
  const parsed = text(value, path);
  if (!choices.has(parsed)) {
    throw new P2PWireError(path + ' has an unknown value');
  }
  return parsed as T;
}

export function digest(value: unknown, path: string): Digest {
  const parsed = record(value, path);
  exactKeys(parsed, ['algorithm', 'hex']);
  const hex = parsed.hex;
  if (parsed.algorithm !== 'sha-256' || typeof hex !== 'string' || !isSha256Hex(hex)) {
    throw new P2PWireError(path + ' must be a SHA-256 digest');
  }
  return { algorithm: 'sha-256', hex };
}

export function schemaRef(value: unknown, name: string): SchemaRef {
  const parsed = record(value, 'schema');
  exactKeys(parsed, ['name', 'version', 'digest']);
  if (
    !isSchemaRef(parsed) ||
    parsed.name !== name ||
    parsed.version !== 0 ||
    parsed.digest.hex !== P2P_CLIENT_BUNDLE_DIGEST
  ) {
    throw new P2PWireError('schema must identify ' + name + ' version 0');
  }
  return { name, version: 0, digest: digest(parsed.digest, 'schema.digest') };
}
