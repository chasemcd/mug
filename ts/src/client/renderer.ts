/**
 * The seat renderer: a pure downstream view of the authoritative frame.
 *
 * It consumes a render packet -- a list of backend-neutral surface commands in
 * relative (0..1) coordinates -- and draws it on a canvas. This is the most
 * swappable layer; a production backend can replace the canvas 2D backend behind
 * the `createRenderer` seam without touching the environment or the protocol.
 */

/** A point in relative (0..1) coordinates. */
export type RelativePoint = readonly [number, number];

/** One backend-neutral drawing command in relative coordinates. */
export interface SurfaceCommand {
  op: 'circle' | 'rect' | 'line' | 'polygon' | 'text';
  color?: string;
  alpha?: number;
  depth?: number;
  fill?: boolean;
  x?: number;
  y?: number;
  radius?: number;
  w?: number;
  h?: number;
  points?: readonly RelativePoint[];
  text?: string;
  font_size?: number;
}

/** A render packet: the surface commands for one frame (other fields ignored here). */
export interface RenderPacket {
  commands: readonly SurfaceCommand[];
}

/** Draw a render packet onto a surface. */
export interface Renderer {
  draw(packet: RenderPacket): void;
}

class Canvas2DRenderer implements Renderer {
  private readonly ctx: CanvasRenderingContext2D;

  constructor(private readonly canvas: HTMLCanvasElement) {
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

  // Relative coordinates map onto the canvas; a radius scales by the larger side,
  // so a circle keeps its shape on a non-square canvas.
  private xAt(value: number): number {
    return value * this.width;
  }

  private yAt(value: number): number {
    return value * this.height;
  }

  private rAt(value: number): number {
    return value * Math.max(this.width, this.height);
  }

  draw(packet: RenderPacket): void {
    this.ctx.clearRect(0, 0, this.width, this.height);
    const commands = [...packet.commands].sort(
      (a, b) => (a.depth ?? 0) - (b.depth ?? 0),
    );
    for (const command of commands) {
      this.drawCommand(command);
    }
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
          this.xAt(command.x ?? 0),
          this.yAt(command.y ?? 0),
          this.rAt(command.radius ?? 0),
          0,
          Math.PI * 2,
        );
        if (command.fill) {
          ctx.fill();
        } else {
          ctx.stroke();
        }
        break;
      case 'rect':
        if (command.fill) {
          ctx.fillRect(
            this.xAt(command.x ?? 0),
            this.yAt(command.y ?? 0),
            this.xAt(command.w ?? 0),
            this.yAt(command.h ?? 0),
          );
        } else {
          ctx.strokeRect(
            this.xAt(command.x ?? 0),
            this.yAt(command.y ?? 0),
            this.xAt(command.w ?? 0),
            this.yAt(command.h ?? 0),
          );
        }
        break;
      case 'line':
        this.path(command.points ?? []);
        ctx.stroke();
        break;
      case 'polygon':
        this.path(command.points ?? []);
        ctx.closePath();
        if (command.fill === false) {
          ctx.stroke();
        } else {
          ctx.fill();
        }
        break;
      case 'text':
        ctx.font = (command.font_size ?? 16) + 'px system-ui, sans-serif';
        ctx.fillText(command.text ?? '', this.xAt(command.x ?? 0), this.yAt(command.y ?? 0));
        break;
      default:
        break;
    }
    ctx.globalAlpha = 1;
  }

  private path(points: readonly RelativePoint[]): void {
    const ctx = this.ctx;
    ctx.beginPath();
    points.forEach(([x, y], index) => {
      const px = this.xAt(x);
      const py = this.yAt(y);
      if (index === 0) {
        ctx.moveTo(px, py);
      } else {
        ctx.lineTo(px, py);
      }
    });
  }
}

/** The seam: build a renderer for a canvas. Swap the backend here. */
export function createRenderer(canvas: HTMLCanvasElement): Renderer {
  return new Canvas2DRenderer(canvas);
}
