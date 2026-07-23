// The seat renderer. It consumes a render packet -- a list of backend-neutral
// surface commands in relative (0..1) coordinates -- and draws it. This is the
// most swappable layer: a pure downstream view of the authoritative frame. The
// demo ships a canvas 2D backend; a later production backend (pixi) can replace
// it behind this same seam without touching the environment or the protocol.

class Canvas2DRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
  }

  get width() {
    return this.canvas.width;
  }

  get height() {
    return this.canvas.height;
  }

  // Relative coordinates map onto the canvas; a radius scales by the larger side
  // so a circle keeps its shape on a non-square canvas.
  _x(value) {
    return value * this.width;
  }
  _y(value) {
    return value * this.height;
  }
  _r(value) {
    return value * Math.max(this.width, this.height);
  }

  draw(packet) {
    this.ctx.clearRect(0, 0, this.width, this.height);
    const commands = [...packet.commands].sort(
      (a, b) => (a.depth ?? 0) - (b.depth ?? 0),
    );
    for (const command of commands) this._drawCommand(command);
  }

  _drawCommand(command) {
    const ctx = this.ctx;
    ctx.globalAlpha = command.alpha ?? 1;
    ctx.fillStyle = command.color ?? "#000000";
    ctx.strokeStyle = command.color ?? "#000000";
    ctx.lineWidth = 2;

    switch (command.op) {
      case "circle":
        ctx.beginPath();
        ctx.arc(this._x(command.x), this._y(command.y), this._r(command.radius), 0, Math.PI * 2);
        command.fill ? ctx.fill() : ctx.stroke();
        break;
      case "rect":
        if (command.fill) {
          ctx.fillRect(this._x(command.x), this._y(command.y), this._x(command.w), this._y(command.h));
        } else {
          ctx.strokeRect(this._x(command.x), this._y(command.y), this._x(command.w), this._y(command.h));
        }
        break;
      case "line":
        this._path(command.points);
        ctx.stroke();
        break;
      case "polygon":
        this._path(command.points);
        ctx.closePath();
        command.fill === false ? ctx.stroke() : ctx.fill();
        break;
      case "text":
        ctx.font = `${command.font_size ?? 16}px system-ui, sans-serif`;
        ctx.fillText(command.text ?? "", this._x(command.x), this._y(command.y));
        break;
      default:
        break;
    }
    ctx.globalAlpha = 1;
  }

  _path(points) {
    const ctx = this.ctx;
    ctx.beginPath();
    points.forEach(([x, y], index) => {
      const px = this._x(x);
      const py = this._y(y);
      if (index === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
  }
}

// The seam: build a renderer for a canvas. Swap the backend here.
export function createRenderer(canvas) {
  return new Canvas2DRenderer(canvas);
}
