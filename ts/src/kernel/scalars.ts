/**
 * Shared scalar formats.
 *
 * These are the small string formats the wire carries -- a schema name, a
 * semantic version, a fixed-width UTC instant, a public handle, a hex digest.
 * Each mirrors the anchored pattern the Python kernel enforces, so the browser
 * validates a value exactly as the server does before it ever reaches the wire.
 */

const SCHEMA_NAME = /^mug(?:\.[a-z][a-z0-9-]*)+$/;

const SEMVER =
  /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;

// A fixed-width RFC 3339 UTC instant: exactly six fractional digits, uppercase Z.
const UTC_INSTANT =
  /^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z$/;

const PUBLIC_HANDLE = /^handle_[A-Za-z0-9_-]{21}[AQgw]$/;

const HEX_256 = /^[0-9a-f]{64}$/;

/** Report whether a string is a well-formed schema name (`mug.<segment>...`). */
export function isSchemaName(value: string): boolean {
  return value.length <= 160 && SCHEMA_NAME.test(value);
}

/** Report whether a string is a well-formed semantic version. */
export function isSemVer(value: string): boolean {
  return value.length <= 128 && SEMVER.test(value);
}

/** Report whether a string is a fixed-width RFC 3339 UTC instant. */
export function isUtcInstant(value: string): boolean {
  return UTC_INSTANT.test(value);
}

/** Report whether a string is a well-formed public handle. */
export function isPublicHandle(value: string): boolean {
  return value.length <= 29 && PUBLIC_HANDLE.test(value);
}

/** Report whether a string is a lowercase 64-character SHA-256 hex digest. */
export function isSha256Hex(value: string): boolean {
  return HEX_256.test(value);
}
