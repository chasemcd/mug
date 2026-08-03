/**
 * The seat renderer: a pure downstream view of the authoritative frame.
 *
 * It consumes a render packet -- a list of backend-neutral surface commands -- and
 * draws it on a canvas. This is the most swappable layer; a production backend can
 * replace the canvas 2D backend behind the `createRenderer` seam without touching
 * the environment or the protocol.
 *
 * Three things it does that a "draw the list" renderer does not.
 *
 * **It keeps an object model.** A command marked `persistent` with an `id` is an
 * object: it arrives once, is re-drawn every frame after that, is replaced when it
 * changes, and survives frames that do not mention it. A keyframe replaces the whole
 * model, which is how removal travels -- the packet carries no removal list, so a
 * frame that dropped an object is sent whole and whatever is not in it is gone.
 *
 * **It tweens.** Any object with an `id` may tween, whether or not it is
 * persistent -- a sprite redrawn whole each frame still moves from somewhere to
 * somewhere, and that is the common case for a character.
 * An object whose command carries `tween_duration` moves to its new
 * position over that many milliseconds instead of jumping, and the renderer drives
 * its own frames while a tween is running. The environment states the intent; how
 * it is honoured is the client's business.
 *
 * **It reads declared assets.** An `image` command names an asset the study
 * declared, and the asset table resolves it -- a whole image, or one named frame of a
 * sprite atlas. A name the table does not hold draws nothing rather than a
 * placeholder: an environment must not be able to silently render a missing sprite.
 */

/** A point in the command's own coordinate system. */
export type Point = readonly [number, number];

/** One backend-neutral drawing command (see `mug.game.types.SurfaceCommand`). */
export interface SurfaceCommand {
  op: 'circle' | 'rect' | 'ellipse' | 'line' | 'polygon' | 'arc' | 'text' | 'image';
  id?: string | null;
  persistent?: boolean | null;
  /** True (the default) for 0..1 coordinates; false for pixels. */
  relative?: boolean | null;
  depth?: number | null;
  tween_duration?: number | null;
  color?: string;
  alpha?: number;
  fill?: boolean;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  radius?: number;
  rx?: number;
  ry?: number;
  points?: readonly Point[];
  start_angle?: number;
  end_angle?: number;
  angle?: number;
  text?: string;
  font_size?: number;
  image_name?: string;
  /** One frame of a sheet, by the name it was packed under. */
  frame?: string;
}

/** A render packet: the surface commands for one frame. */
export interface RenderPacket {
  commands: readonly SurfaceCommand[];
  keyframe?: boolean;
}

/** One rectangle of a sprite atlas, in the atlas image's own pixels. */
export interface AtlasFrame {
  sx: number;
  sy: number;
  sw: number;
  sh: number;
}

/** Where a declared image and its atlas frames come from. */
export interface AssetTable {
  /** The loaded image for one declared asset name, or null when it has none. */
  image(name: string): CanvasImageSource | null;
  /** One frame of a declared sprite atlas, or null for a whole image. */
  frame?(name: string, packed: string): AtlasFrame | null;
}

/** What the renderer needs from its environment, injected so a test can drive it. */
export interface RendererOptions {
  assets?: AssetTable;
  /** Milliseconds since some fixed origin. Defaults to `performance.now`. */
  now?: () => number;
  /** Ask for another animation frame. Defaults to `requestAnimationFrame`. */
  schedule?: (callback: () => void) => void;
  /**
   * The drawing's own units. Everything is drawn in these and the whole picture
   * is scaled onto the canvas at paint time, so a study's `font_size: 14` and a
   * one-unit line are the same part of the picture on any screen. Sizing the
   * drawing by the canvas instead would leave the text on a large screen exactly
   * as many pixels tall as on a small one, and so half the size on it.
   */
  logical?: { w: number; h: number };
}

/** Draw a render packet onto a surface. */
export interface Renderer {
  draw(packet: RenderPacket): void;
  /**
   * Draw the same picture on a canvas of a new size. The units do not change:
   * the canvas holds more device pixels, so the picture is larger and no coarser.
   */
  resize(pixelWidth: number, pixelHeight: number): void;
}

interface Tween {
  fromX: number;
  fromY: number;
  startedAt: number;
  duration: number;
}

/**
 * How small a line of text may be shrunk to fit. Below this nobody can read it,
 * so it is better to run past the edge and be seen to be wrong.
 */
const MIN_TEXT = 6;

function defaultNow(): number {
  return typeof performance === 'undefined' ? Date.now() : performance.now();
}

function defaultSchedule(callback: () => void): void {
  if (typeof requestAnimationFrame === 'undefined') {
    setTimeout(callback, 16);
  } else {
    requestAnimationFrame(callback);
  }
}

class Canvas2DRenderer implements Renderer {
  private readonly ctx: CanvasRenderingContext2D;
  private readonly objects = new Map<string, SurfaceCommand>();
  private readonly tweens = new Map<string, Tween>();
  // Where each identified object was last told to be. It is kept for **every**
  // object with an id, not only the persistent ones: a sprite redrawn whole each
  // frame still moves from somewhere to somewhere, and tweening it is the whole
  // difference between walking and teleporting.
  private readonly places = new Map<string, { x: number; y: number }>();
  private ephemeral: readonly SurfaceCommand[] = [];
  private animating = false;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly options: RendererOptions = {},
  ) {
    const ctx = canvas.getContext('2d');
    if (ctx === null) {
      throw new Error('the canvas has no 2d rendering context');
    }
    this.ctx = ctx;
  }

  private get width(): number {
    return this.options.logical?.w ?? this.canvas.width;
  }

  private get height(): number {
    return this.options.logical?.h ?? this.canvas.height;
  }

  resize(pixelWidth: number, pixelHeight: number): void {
    if (this.canvas.width === pixelWidth && this.canvas.height === pixelHeight) {
      return;
    }
    this.canvas.width = pixelWidth;
    this.canvas.height = pixelHeight;
    this.paint();
  }

  private get now(): () => number {
    return this.options.now ?? defaultNow;
  }

  // A relative coordinate maps onto the canvas; a pixel coordinate is already
  // where it wants to be. A radius scales by the larger side, so a circle keeps
  // its shape on a canvas that is not square.
  private xAt(command: SurfaceCommand, value: number): number {
    return command.relative === false ? value : value * this.width;
  }

  private yAt(command: SurfaceCommand, value: number): number {
    return command.relative === false ? value : value * this.height;
  }

  private rAt(command: SurfaceCommand, value: number): number {
    return command.relative === false
      ? value
      : value * Math.max(this.width, this.height);
  }

  draw(packet: RenderPacket): void {
    if (packet.keyframe) {
      // A keyframe is the whole scene, so nothing survives it that is not in it.
      this.objects.clear();
      this.tweens.clear();
      this.places.clear();
    }
    const ephemeral: SurfaceCommand[] = [];
    for (const command of packet.commands) {
      // Every identified object is tracked, then kept or redrawn. Tweening used to
      // be tied to persistence, so a study that asked a redrawn sprite to move
      // smoothly was ignored and its object jumped a whole square per frame.
      this.track(command);
      if (command.persistent && typeof command.id === 'string') {
        this.objects.set(command.id, command);
      } else {
        ephemeral.push(command);
      }
    }
    this.ephemeral = ephemeral;
    this.paint();
  }

  /**
   * Note that one object moved, and start its tween when it asked for one.
   *
   * A tween runs from where the object **is on the screen right now**, not from
   * where it was last told to be. Those differ when a second move arrives while
   * the first is still running -- a character walking two squares in quick
   * succession -- and starting from the stale place would snap it backwards
   * before it went on.
   */
  private track(command: SurfaceCommand): void {
    const id = command.id;
    if (typeof id !== 'string') {
      return;
    }
    const target = { x: command.x ?? 0, y: command.y ?? 0 };
    const previous = this.places.get(id);
    if (previous === undefined) {
      this.places.set(id, target);
      return;
    }
    if (previous.x === target.x && previous.y === target.y) {
      return;
    }
    const duration = command.tween_duration ?? 0;
    if (duration > 0) {
      const from = this.where(id, previous);
      this.tweens.set(id, {
        fromX: from.x,
        fromY: from.y,
        startedAt: this.now(),
        duration,
      });
    } else {
      // A move with no tween is a jump, and it cancels whatever was running.
      this.tweens.delete(id);
    }
    this.places.set(id, target);
  }

  /**
   * Return where one object is on the screen now: part way through a running
   * tween, or at the last place it was told to be.
   */
  private where(
    id: string,
    previous: { x: number; y: number },
  ): { x: number; y: number } {
    const tween = this.tweens.get(id);
    if (tween === undefined) {
      return { x: previous.x, y: previous.y };
    }
    const elapsed = this.now() - tween.startedAt;
    if (elapsed >= tween.duration) {
      return { x: previous.x, y: previous.y };
    }
    const progress = tween.duration === 0 ? 1 : elapsed / tween.duration;
    return {
      x: tween.fromX + (previous.x - tween.fromX) * progress,
      y: tween.fromY + (previous.y - tween.fromY) * progress,
    };
  }

  /** Return where an object is right now, part way through any tween it has. */
  private placed(command: SurfaceCommand): SurfaceCommand {
    const id = command.id;
    if (typeof id !== 'string') {
      return command;
    }
    const tween = this.tweens.get(id);
    if (tween === undefined) {
      return command;
    }
    const elapsed = this.now() - tween.startedAt;
    if (elapsed >= tween.duration) {
      this.tweens.delete(id);
      return command;
    }
    const progress = tween.duration === 0 ? 1 : elapsed / tween.duration;
    return {
      ...command,
      x: tween.fromX + ((command.x ?? 0) - tween.fromX) * progress,
      y: tween.fromY + ((command.y ?? 0) - tween.fromY) * progress,
    };
  }

  private paint(): void {
    // One transform puts the whole drawing on the canvas, whatever size the
    // canvas is now. Everything below it works in the drawing's own units and
    // knows nothing about the screen.
    this.ctx.setTransform(
      this.canvas.width / this.width,
      0,
      0,
      this.canvas.height / this.height,
      0,
      0,
    );
    this.ctx.clearRect(0, 0, this.width, this.height);
    const drawing = [...this.objects.values(), ...this.ephemeral]
      .map((command) => this.placed(command))
      .sort((a, b) => (a.depth ?? 0) - (b.depth ?? 0));
    for (const command of drawing) {
      this.drawCommand(command);
    }
    this.animate();
  }

  /** Keep drawing while a tween is running, and stop the moment none is. */
  private animate(): void {
    if (this.tweens.size === 0 || this.animating) {
      return;
    }
    this.animating = true;
    const schedule = this.options.schedule ?? defaultSchedule;
    schedule(() => {
      this.animating = false;
      if (this.tweens.size > 0) {
        this.paint();
      }
    });
  }

  private drawCommand(command: SurfaceCommand): void {
    const ctx = this.ctx;
    ctx.globalAlpha = command.alpha ?? 1;
    ctx.fillStyle = command.color ?? '#000000';
    ctx.strokeStyle = command.color ?? '#000000';
    ctx.lineWidth = 2;

    switch (command.op) {
      case 'circle':
        ctx.beginPath();
        ctx.arc(
          this.xAt(command, command.x ?? 0),
          this.yAt(command, command.y ?? 0),
          this.rAt(command, command.radius ?? 0),
          0,
          Math.PI * 2,
        );
        this.paintPath(command, true);
        break;
      case 'ellipse':
        ctx.beginPath();
        ctx.ellipse(
          this.xAt(command, command.x ?? 0),
          this.yAt(command, command.y ?? 0),
          this.xAt(command, command.rx ?? 0),
          this.yAt(command, command.ry ?? 0),
          command.angle ?? 0,
          0,
          Math.PI * 2,
        );
        this.paintPath(command, true);
        break;
      case 'arc':
        ctx.beginPath();
        ctx.arc(
          this.xAt(command, command.x ?? 0),
          this.yAt(command, command.y ?? 0),
          this.rAt(command, command.radius ?? 0),
          command.start_angle ?? 0,
          command.end_angle ?? Math.PI * 2,
        );
        // An arc is a stroke unless the drawing asked for a filled wedge, which
        // is a different shape: the fill closes it back through the centre.
        this.paintPath(command, false);
        break;
      case 'rect':
        if (command.fill === false) {
          ctx.strokeRect(
            this.xAt(command, command.x ?? 0),
            this.yAt(command, command.y ?? 0),
            this.xAt(command, command.w ?? 0),
            this.yAt(command, command.h ?? 0),
          );
        } else {
          ctx.fillRect(
            this.xAt(command, command.x ?? 0),
            this.yAt(command, command.y ?? 0),
            this.xAt(command, command.w ?? 0),
            this.yAt(command, command.h ?? 0),
          );
        }
        break;
      case 'line':
        this.path(command, command.points ?? []);
        ctx.stroke();
        break;
      case 'polygon':
        this.path(command, command.points ?? []);
        ctx.closePath();
        this.paintPath(command, true);
        break;
      case 'text': {
        // Text is shrunk to what is left of the picture, and never grown. A study
        // says how large its writing is in the units of its own drawing, and a
        // picture small enough for the words not to fit shows them cut off at the
        // edge -- a score that reads "Dishes delivered: 0" and stops. Only the
        // renderer can measure a string, so only the renderer can do this.
        const at = this.xAt(command, command.x ?? 0);
        const size = command.font_size ?? 16;
        const face = (points: number): string =>
          points + 'px system-ui, sans-serif';
        ctx.font = face(size);
        const words = command.text ?? '';
        const room = this.width - at;
        const wide = ctx.measureText(words).width;
        if (wide > room && room > 0) {
          ctx.font = face(Math.max(MIN_TEXT, (size * room) / wide));
        }
        ctx.fillText(words, at, this.yAt(command, command.y ?? 0));
        break;
      }
      case 'image':
        this.drawImage(command);
        break;
      default:
        break;
    }
    ctx.globalAlpha = 1;
  }

  private paintPath(command: SurfaceCommand, fillByDefault: boolean): void {
    const filled = command.fill ?? fillByDefault;
    if (filled) {
      this.ctx.fill();
    } else {
      this.ctx.stroke();
    }
  }

  private drawImage(command: SurfaceCommand): void {
    const assets = this.options.assets;
    const name = command.image_name;
    if (assets === undefined || typeof name !== 'string') {
      return;
    }
    const image = assets.image(name);
    if (image === null) {
      // A study that declared no such asset renders nothing here. Drawing a
      // placeholder would let a missing sprite reach a participant unnoticed.
      return;
    }
    const ctx = this.ctx;
    const x = this.xAt(command, command.x ?? 0);
    const y = this.yAt(command, command.y ?? 0);
    const w = this.xAt(command, command.w ?? 0);
    const h = this.yAt(command, command.h ?? 0);
    const angle = command.angle ?? 0;
    if (angle !== 0) {
      ctx.save();
      ctx.translate(x + w / 2, y + h / 2);
      ctx.rotate(angle);
      ctx.translate(-(x + w / 2), -(y + h / 2));
    }
    const frame =
      command.frame === undefined || assets.frame === undefined
        ? null
        : assets.frame(name, command.frame);
    if (frame === null) {
      ctx.drawImage(image, x, y, w, h);
    } else {
      ctx.drawImage(image, frame.sx, frame.sy, frame.sw, frame.sh, x, y, w, h);
    }
    if (angle !== 0) {
      ctx.restore();
    }
  }

  private path(command: SurfaceCommand, points: readonly Point[]): void {
    const ctx = this.ctx;
    ctx.beginPath();
    points.forEach(([x, y], index) => {
      const px = this.xAt(command, x);
      const py = this.yAt(command, y);
      if (index === 0) {
        ctx.moveTo(px, py);
      } else {
        ctx.lineTo(px, py);
      }
    });
  }
}

/** The seam: build a renderer for a canvas. Swap the backend here. */
export function createRenderer(
  canvas: HTMLCanvasElement,
  options: RendererOptions = {},
): Renderer {
  return new Canvas2DRenderer(canvas, options);
}
