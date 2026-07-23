# `ts/` — the MUG kernel twin and the participant client

Two things live here, both in TypeScript, both zero runtime dependencies:

- **`src/kernel/`** — `@mug/kernel`, the browser-side half of the wire kernel:
  canonicalization (RFC 8785), content digests, identifier encoding, the shared
  scalar formats, and the typed-object envelope. It reproduces the Python
  `mug.kernel` byte for byte.
- **`src/client/`** — the participant client: the `RealtimeCommand` minter
  (`wire.ts`), the `/ws` session with the resume protocol (`session.ts`), the
  canvas renderer (`renderer.ts`), the Pyodide execution slice (`browserGame.ts`),
  the form/content/completion rendering (`ui.ts`), the driver (`client.ts`), and
  the browser entry (`bootstrap.ts`). It is built on `@mug/kernel` and is a
  TypeScript port of the reference JavaScript client under `mug/webclient/`.

The client core keeps every browser dependency behind an injected seam (the
socket, the key-value store, the clock, the random source, the hasher), so it
runs under Node in a test; only `bootstrap.ts` reaches for the real globals.

- Conformance: [`conformance/run.ts`](conformance/run.ts) checks the kernel twin
  against the shared vectors the Python kernel generates under
  `../tests/conformance/vectors/`; [`conformance/client_wire.ts`](conformance/client_wire.ts)
  drives the session with a fake socket and prints the frames it sends, which the
  Python side validates against the real `RealtimeCommand` model.

Use the pinned node (`.nvmrc` = node 20; the toolchain is TypeScript 5.x, which
needs node >= 18):

```bash
nvm use              # or: nvm install
npm ci
npm run build        # tsc -> dist/ (CommonJS: kernel + conformance runners, for node)
npm run build:web    # tsc -> dist-web/ (ES modules: kernel + client, for the browser)
npm run conformance  # run the twin over the shared vectors
npm run check        # type-check the CJS project (kernel + conformance)
npm run check:web    # type-check the web project (kernel + client)
```

Both configs target ES2019, so the output runs on any modern browser and even an
old node — only the build itself needs node 20. Relative imports carry a `.js`
extension, so the ESM web build loads natively in the browser with no bundler; the
CJS `moduleResolution: node` build tolerates the same extension.

The cross-language gate lives on the Python side
(`uv run pytest tests/conformance`); it runs the two conformance runners and
asserts byte-identity. A real participant completing a study in the client is
proven by `tests/e2e_native/test_ts_client_browser.py` (Chromium).

See `scratch/impl/kernel-twin-quickstart.md` for the full walkthrough.
