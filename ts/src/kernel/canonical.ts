/**
 * Canonical serialization.
 *
 * Canonical JSON is RFC 8785 (the JSON Canonicalization Scheme). Every digest in
 * the system comes from these bytes. This is the browser-side twin of the Python
 * `mug.kernel.canonical` module; the two produce byte-identical output, which the
 * cross-language conformance vectors prove.
 *
 * The algorithm is the vetted MIT reference canonicalizer (cyberphone / the npm
 * "canonicalize" package): object members sort by their UTF-16 code units, and
 * numbers use the ECMAScript Number-to-String algorithm that RFC 8785 adopts as
 * its number basis. It is ported here with types and the MUG input constraints.
 */

/** A plain JSON value: the only thing the canonicalizer ever serializes. */
export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

/**
 * Return the RFC 8785 canonical JSON string of a plain JSON value.
 *
 * A non-finite number (NaN, +/-Infinity) has no JSON form and throws, exactly as
 * the Python side refuses it. `undefined` inside an array becomes `null`; an
 * `undefined` object member is dropped, matching `JSON.stringify`.
 */
export function canonicalize(value: JsonValue): string {
  if (typeof value === 'number' && !Number.isFinite(value)) {
    throw new Error('cannot canonicalize a non-finite number');
  }
  if (value === null || typeof value !== 'object') {
    // Primitives (including numbers) go through JSON.stringify, whose number
    // formatting is the RFC 8785 number basis.
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    let acc = '';
    for (let i = 0; i < value.length; i++) {
      const element = value[i];
      acc += (i === 0 ? '' : ',') + canonicalize(element === undefined ? null : element);
    }
    return '[' + acc + ']';
  }
  // RFC 8785 orders object members by the UTF-16 code units of their keys, which
  // is exactly the default lexicographic Array.prototype.sort() comparison.
  const keys = Object.keys(value).sort();
  let out = '';
  for (const key of keys) {
    const member = value[key];
    if (member === undefined) {
      continue;
    }
    out += (out.length === 0 ? '' : ',') + JSON.stringify(key) + ':' + canonicalize(member);
  }
  return '{' + out + '}';
}

/** Return the UTF-8 canonical bytes of a plain JSON value. */
export function canonicalBytes(value: JsonValue): Uint8Array {
  return new TextEncoder().encode(canonicalize(value));
}
