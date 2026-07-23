/**
 * The typed-object envelope and the schema reference.
 *
 * A `TypedObject` wraps a data object with the `SchemaRef` that names its schema.
 * It carries a command payload, an accepted receipt result, and a domain-error
 * detail. The data has no domain meaning until a reader resolves the referenced
 * schema and validates the data against it (second-stage validation); the guard
 * here only checks the envelope shape, exactly as the Python `TypedObject` model
 * does at the structural layer.
 */

import { Digest } from './digest.js';
import { isSchemaName, isSha256Hex } from './scalars.js';
import { JsonValue } from './canonical.js';

/** A pinned reference to one schema: name, integer version, and digest. */
export interface SchemaRef {
  name: string;
  version: number;
  digest: Digest;
}

/** A schema reference plus the data it describes. */
export interface TypedObject {
  schema: SchemaRef;
  data: { [key: string]: JsonValue };
}

function isDigest(value: unknown): value is Digest {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const digest = value as { algorithm?: unknown; hex?: unknown };
  return (
    digest.algorithm === 'sha-256' &&
    typeof digest.hex === 'string' &&
    isSha256Hex(digest.hex)
  );
}

function isSafeInteger(value: unknown): value is number {
  return (
    typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= 0 &&
    value <= 9007199254740991
  );
}

/** Report whether a value is a well-formed schema reference. */
export function isSchemaRef(value: unknown): value is SchemaRef {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const ref = value as { name?: unknown; version?: unknown; digest?: unknown };
  return (
    typeof ref.name === 'string' &&
    isSchemaName(ref.name) &&
    isSafeInteger(ref.version) &&
    isDigest(ref.digest)
  );
}

/**
 * Report whether a value is a well-formed typed-object envelope.
 *
 * It checks the envelope shape only -- a valid schema reference and a plain data
 * object of at most 256 members. It does not resolve the schema or validate the
 * data against it; that is the reader's second stage.
 */
export function isTypedObject(value: unknown): value is TypedObject {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const object = value as { schema?: unknown; data?: unknown };
  if (!isSchemaRef(object.schema)) {
    return false;
  }
  if (
    typeof object.data !== 'object' ||
    object.data === null ||
    Array.isArray(object.data)
  ) {
    return false;
  }
  return Object.keys(object.data).length <= 256;
}
