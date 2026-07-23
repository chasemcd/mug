# The kernel twin: one wire contract, two languages

*For anyone building the browser participant client. The `ts/` workspace holds
`@mug/kernel` -- the browser-side half of the wire kernel. It reproduces the
Python kernel byte for byte, so a value the browser canonicalizes, digests, or
identifies is identical to the one the server produces. You never write a second
canonicalizer.*

> Status: **the kernel twin and the participant client are built.**
> Canonicalization, digest, identifier encoding, the shared scalar formats, and the
> typed-object envelope run today in TypeScript and are proven byte-identical to
> Python by a shared vector set. On top of the twin, `ts/src/client/` is a full
> participant client (forms, content, the server and browser game, completion, and
> the resume protocol); a real participant completes a study in it (Chromium e2e).
> Uploads and chat have no browser front-end in either client yet. See
> [`ts/README.md`](../../ts/README.md) for the client walkthrough.

---

## What the twin gives you

```ts
import {
  canonicalize,       // (value) => RFC 8785 canonical JSON string
  computeDigest,      // (value, hash) => { algorithm, hex }  -- SHA-256 of the canonical bytes
  browserSha256,      // the Web Crypto hasher to pass as `hash` in a browser
  isRegisteredId,     // (id) => is this a well-formed id of an active kind?
  parseId,            // (id) => { kind, uuid } | null
  isTypedObject,      // (value) => is this a well-formed typed-object envelope?
} from '@mug/kernel';

const digest = await computeDigest({ b: 1, a: 2 }, browserSha256);
// -> { algorithm: 'sha-256', hex: '...' }  -- the exact hex the server computes
```

The digest step takes an injected hasher because a browser hashes asynchronously
through Web Crypto. Pass `browserSha256` in the browser; the Node conformance
runner injects its own. Either way the twin canonicalizes the value itself, so
the whole `value -> canonical bytes -> digest` path matches the server.

The twin holds **only what the browser needs**: the wire shapes and their rules.
It carries no server, storage, or domain logic.

---

## Why the two languages cannot drift

The Python kernel is the source of truth. It generates three shared vector sets
under `tests/conformance/vectors/` -- one for canonicalization, one for
identifier encoding, one for the typed-object envelope. Each vector pins the
expected output: the canonical string and its SHA-256, or the identifier verdict
and its parts, or the envelope verdict.

Both languages check themselves against the same files:

- The Python test reproduces every vector from the live kernel.
- The TypeScript runner reproduces every vector from the twin.

Because both read byte-identical vector files, agreeing with the file means
agreeing with each other. A one-byte divergence fails the build.

To refresh the vectors after a deliberate kernel change:

```bash
uv run python -m tests.conformance.generate_vectors
```

The conformance test also asserts the committed files equal a fresh build, so a
stale or hand-edited vector is caught.

---

## Building and checking the workspace

```bash
cd ts
nvm use           # node 20, pinned by .nvmrc (the TypeScript 5.x toolchain needs node >= 18)
npm ci            # installs TypeScript (the only runtime-free dev dependency)
npm run build     # tsc -> dist/
npm run conformance   # runs the twin over the shared vectors
```

The compiled output targets ES2019, so the shipped twin and the conformance
runner run on any modern browser or an old node; only the build needs node 20.

Then the Python side ties the two together:

```bash
uv run pytest tests/conformance
```

That test builds the workspace on demand when `node` is present, runs the TS
runner over the same vectors, and asserts it exits clean. There is no CI in the
repo yet, so this pytest cross-check is the gate; a future CI job runs the two
commands above before the Python suite.

---

## What is deliberately small

The twin is a browser library, not a second server. It has zero runtime
dependencies, targets ES2019 so it runs anywhere a modern browser or an old Node
does, and exposes pure functions and type guards -- no classes, no state, no I/O.
Everything the browser must agree with the server on lives here; nothing else
does.
