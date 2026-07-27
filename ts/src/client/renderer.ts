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
 * **It tweens.** An object whose command carries `tween_duration` moves to its new
 * position over that many milliseconds instead of jumping, and the renderer drives
 * its own frames while a tween is running. The environment states the intent; how
 * it is honoured is the client's business.
 *
 * **It reads declared assets.** An `image` command names an asset the study
 * declared, and the asset table resolves it -- a whole image, or one frame of a
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
  frame?: number;
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
  frame?(name: string, index: number): AtlasFrame | null;
}

/** What the renderer needs from its environment, injected so a test can drive it. */
export interface RendererOptions {
  assets?: AssetTable;
  /** Milliseconds since some fixed origin. Defaults to `performance.now`. */
  now?: () => number;
  /** Ask for another animation frame. Defaults to `requestAnimationFrame`. */
  schedule?: (callback: () => void) => void;
}

/** Draw a render packet onto a surface. */
export interface Renderer {
  draw(packet: RenderPacket): void;
}

interface Tween {
  fromX: number;
  fromY: number;
  startedAt: number;
  duration: number;
}

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
    return this.canvas.width;
  }

  private get height(): number {
    return this.canvas.height;
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
    }
    const ephemeral: SurfaceCommand[] = [];
    for (const command of packet.commands) {
      if (command.persistent && typeof command.id === 'string') {
        this.remember(command.id, command);
      } else {
        ephemeral.push(command);
      }
    }
    this.ephemeral = ephemeral;
    this.paint();
  }

  private remember(id: string, command: SurfaceCommand): void {
    const previous = this.objects.get(id);
    const moved =
      previous !== undefined && (previous.x !== command.x || previous.y !== command.y);
    if (moved && (command.tween_duration ?? 0) > 0) {
      this.tweens.set(id, {
        fromX: previous?.x ?? 0,
        fromY: previous?.y ?? 0,
        startedAt: this.now(),
        duration: command.tween_duration ?? 0,
      });
    }
    this.objects.set(id, command);
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
      case 'text':
        ctx.font = (command.font_size ?? 16) + 'px system-ui, sans-serif';
        ctx.fillText(
          command.text ?? '',
          this.xAt(command, command.x ?? 0),
          this.yAt(command, command.y ?? 0),
        );
        break;
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
