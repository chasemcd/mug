/**
 * Load the pictures a study declared, and hand them to the renderer by name.
 *
 * The handshake carries one entry per declared asset: the digest that addresses
 * it, the media type, the address to fetch it from, and the atlas frames when it
 * has any. This module fetches them all, decodes them, and answers the renderer's
 * two questions -- what image is `ball`, and where is frame 2 of `hero`.
 *
 * **Nothing is drawn from a name nobody declared.** An unknown name answers null
 * and the renderer draws nothing, rather than a placeholder that would let a
 * missing sprite reach a participant unnoticed.
 *
 * The decoder is injected, so a test drives the whole table with no browser: the
 * browser passes one that builds an `Image` from a blob, and a test passes one
 * that returns a stand-in.
 */

import { AssetTable, AtlasFrame } from './renderer.js';

/** One declared asset as the handshake describes it. */
export interface DeclaredAsset {
  digest: string;
  media_type: string;
  url: string;
  frames?: readonly AtlasFrame[];
}

/** The declared assets of one study, keyed by the name an environment draws by. */
export type AssetManifest = Record<string, DeclaredAsset>;

/** Turn one fetched asset into something a canvas can draw. */
export type DecodeAsset = (
  asset: DeclaredAsset,
) => Promise<CanvasImageSource | null>;

/** Fetch bytes from an address (the browser passes `fetch`). */
export type FetchAsset = (url: string) => Promise<Response>;

/** The renderer's asset table, plus the loading it needs done first. */
export class LoadedAssets implements AssetTable {
  private readonly images = new Map<string, CanvasImageSource>();
  private readonly frames = new Map<string, readonly AtlasFrame[]>();

  image(name: string): CanvasImageSource | null {
    return this.images.get(name) ?? null;
  }

  frame(name: string, index: number): AtlasFrame | null {
    const sheet = this.frames.get(name);
    if (sheet === undefined || index < 0 || index >= sheet.length) {
      return null;
    }
    return sheet[index] ?? null;
  }

  /** Whether anything at all was loaded, so a caller can skip the table. */
  get empty(): boolean {
    return this.images.size === 0;
  }

  /**
   * Load every declared asset, and keep the ones that arrived.
   *
   * One picture that fails to load does not fail the rest: the study loses that
   * one drawing and the participant keeps their session, which is the better
   * trade in every study where the picture is not the experiment.
   */
  async load(manifest: AssetManifest, decode: DecodeAsset): Promise<void> {
    const names = Object.keys(manifest).sort();
    await Promise.all(
      names.map(async (name) => {
        const declared = manifest[name];
        if (declared === undefined) {
          return;
        }
        if (declared.frames !== undefined && declared.frames.length > 0) {
          this.frames.set(name, declared.frames);
        }
        try {
          const image = await decode(declared);
          if (image !== null) {
            this.images.set(name, image);
          }
        } catch {
          // A picture that will not decode is a picture the study does not draw.
        }
      }),
    );
  }
}

/** Build the browser decoder: fetch the bytes and decode them into an image. */
export function browserDecoder(fetchAsset: FetchAsset): DecodeAsset {
  return async (asset) => {
    const response = await fetchAsset(asset.url);
    if (!response.ok) {
      return null;
    }
    const blob = await response.blob();
    if (typeof createImageBitmap === 'function') {
      return createImageBitmap(blob);
    }
    return await new Promise<CanvasImageSource | null>((resolve) => {
      const element = new Image();
      const address = URL.createObjectURL(blob);
      element.onload = () => resolve(element);
      element.onerror = () => resolve(null);
      element.src = address;
    });
  };
}
