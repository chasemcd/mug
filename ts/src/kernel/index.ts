/**
 * The MUG kernel twin.
 *
 * This is the browser-side half of the wire kernel: canonicalization, content
 * digests, identifier encoding, shared scalar formats, and the typed-object
 * envelope. It reproduces the Python `mug.kernel` byte for byte, which the
 * cross-language conformance vectors prove. It holds only what the browser needs;
 * it carries no server, storage, or domain logic.
 */

export { canonicalize, canonicalBytes } from './canonical.js';
export type { JsonValue } from './canonical.js';

export {
  sha256Hex,
  computeDigest,
  etag,
  bytesToHex,
  browserSha256,
} from './digest.js';
export type { Digest, HashBytes } from './digest.js';

export {
  UUIDV7,
  ID_KIND_REGISTRY,
  ACTIVE_ID_PREFIXES,
  RESERVED_ID_PREFIXES,
  idPattern,
  isRegisteredId,
  isId,
  parseId,
} from './ids.js';
export type { IdKind, ParsedId } from './ids.js';

export {
  isSchemaName,
  isSemVer,
  isUtcInstant,
  isPublicHandle,
  isSha256Hex,
} from './scalars.js';

export { isSchemaRef, isTypedObject } from './typedObject.js';
export type { SchemaRef, TypedObject } from './typedObject.js';
