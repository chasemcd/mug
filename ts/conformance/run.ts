/**
 * The kernel-twin conformance runner.
 *
 * It reads the shared vector sets that the Python kernel generated and asserts
 * the TypeScript twin reproduces every field: the canonical string and its
 * SHA-256, the identifier verdict and its parts, and the typed-object verdict. A
 * mismatch prints a diff and exits non-zero, so continuous integration fails the
 * build when the two languages diverge by a single byte.
 *
 * SHA-256 is injected. Node before 15 has no `crypto.subtle`, so the runner wraps
 * the Node `crypto` hash; a browser uses `browserSha256` instead. Either way the
 * twin canonicalizes the value itself, so this proves the whole
 * value -> canonical bytes -> digest path, not the hash alone.
 */

/// <reference types="node" />

import { createHash } from 'crypto';
import { readFileSync } from 'fs';
import * as path from 'path';

import {
  canonicalize,
  computeDigest,
  HashBytes,
  isRegisteredId,
  isTypedObject,
  parseId,
  sha256Hex,
} from '../src/kernel/index.js';

const nodeSha256: HashBytes = async (bytes) =>
  createHash('sha256').update(Buffer.from(bytes)).digest('hex');

interface Failure {
  set: string;
  vector: string;
  field: string;
  expected: unknown;
  actual: unknown;
}

function readSet(dir: string, name: string): { vectors: any[] } {
  return JSON.parse(readFileSync(path.join(dir, name + '.json'), 'utf-8'));
}

function record(
  failures: Failure[],
  set: string,
  vector: string,
  field: string,
  expected: unknown,
  actual: unknown,
): void {
  if (expected !== actual) {
    failures.push({ set, vector, field, expected, actual });
  }
}

async function checkCanonicalization(dir: string, failures: Failure[]): Promise<void> {
  for (const vector of readSet(dir, 'canonicalization').vectors) {
    record(failures, 'canonicalization', vector.name, 'canonical', vector.canonical, canonicalize(vector.value));
    record(failures, 'canonicalization', vector.name, 'sha256', vector.sha256, await sha256Hex(vector.value, nodeSha256));
  }
}

function checkIds(dir: string, failures: Failure[]): void {
  for (const vector of readSet(dir, 'ids').vectors) {
    record(failures, 'ids', vector.name, 'registered', vector.registered, isRegisteredId(vector.id));
    const parsed = parseId(vector.id);
    record(failures, 'ids', vector.name, 'kind', vector.kind, parsed === null ? null : parsed.kind);
    record(failures, 'ids', vector.name, 'uuid', vector.uuid, parsed === null ? null : parsed.uuid);
  }
}

async function checkTypedObject(dir: string, failures: Failure[]): Promise<void> {
  for (const vector of readSet(dir, 'typed-object').vectors) {
    record(failures, 'typed-object', vector.name, 'valid', vector.valid, isTypedObject(vector.value));
    if (vector.valid) {
      record(failures, 'typed-object', vector.name, 'canonical', vector.canonical, canonicalize(vector.value));
      const digest = await computeDigest(vector.value, nodeSha256);
      record(failures, 'typed-object', vector.name, 'sha256', vector.sha256, digest.hex);
    }
  }
}

async function main(): Promise<void> {
  const dir =
    process.argv[2] !== undefined
      ? process.argv[2]
      : path.resolve(__dirname, '..', '..', '..', 'tests', 'conformance', 'vectors');
  const failures: Failure[] = [];
  await checkCanonicalization(dir, failures);
  checkIds(dir, failures);
  await checkTypedObject(dir, failures);

  const total =
    readSet(dir, 'canonicalization').vectors.length +
    readSet(dir, 'ids').vectors.length +
    readSet(dir, 'typed-object').vectors.length;

  if (failures.length === 0) {
    console.log('kernel twin conformance: ' + total + ' vector(s) OK');
    return;
  }
  console.error('kernel twin conformance: ' + failures.length + ' mismatch(es):');
  for (const failure of failures) {
    console.error(
      '  [' + failure.set + '/' + failure.vector + '] ' + failure.field +
        ': expected ' + JSON.stringify(failure.expected) +
        ' got ' + JSON.stringify(failure.actual),
    );
  }
  process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
