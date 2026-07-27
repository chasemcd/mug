// The seat renderer. It consumes a render packet -- a list of backend-neutral
// surface commands -- and draws it. This is the most swappable layer: a pure
// downstream view of the authoritative frame. The demo ships a canvas 2D backend;
// a later production backend (pixi) can replace it behind this same seam without
// touching the environment or the protocol.
//
// Three things it does that a "draw the list" renderer does not.
//
// It keeps an object model: a command marked `persistent` with an `id` arrives
// once, is re-drawn every frame after that, and is replaced when it changes. A
// keyframe replaces the whole model, which is how removal travels -- the packet
// carries no removal list, so a frame that dropped an object is sent whole and
// whatever is not in it is gone.
//
// It tweens: an object whose command carries `tween_duration` moves to its new
// position over that many milliseconds rather than jumping, and the renderer
// drives its own frames while a tween runs.
//
// It reads declared assets: an `image` command names an asset the study declared,
// and the asset table resolves it -- a whole image, or one frame of a sprite
// atlas. A name the table does not hold draws nothing rather than a placeholder,
// so a missing sprite cannot reach a participant unnoticed.

class Canvas2DRenderer {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.assets = options.assets ?? null;
    this.now = options.now ?? (() => performance.now());
    this.schedule = options.schedule ?? ((fn) => requestAnimationFrame(fn));
    this.objects = new Map();
    this.tweens = new Map();
    this.ephemeral = [];
    this.animating = false;
  }

  get width() {
    return this.canvas.width;
  }

  get height() {
    return this.canvas.height;
  }

  // A relative coordinate maps onto the canvas; a pixel coordinate is already
  // where it wants to be. A radius scales by the larger side, so a circle keeps
  // its shape on a canvas that is not square.
  _x(command, value) {
    return command.relative === false ? value : value * this.width;
  }
  _y(command, value) {
    return command.relative === false ? value : value * this.height;
  }
  _r(command, value) {
    return command.relative === false
      ? value
      : value * Math.max(this.width, this.height);
  }

  draw(packet) {
    if (packet.keyframe) {
      // A keyframe is the whole scene, so nothing survives it that is not in it.
      this.objects.clear();
      this.tweens.clear();
    }
    const ephemeral = [];
    for (const command of packet.commands) {
      if (command.persistent && typeof command.id === "string") {
        this._remember(command.id, command);
      } else {
        ephemeral.push(command);
      }
    }
    this.ephemeral = ephemeral;
    this._paint();
  }

  _remember(id, command) {
    const previous = this.objects.get(id);
    const moved =
      previous !== undefined &&
      (previous.x !== command.x || previous.y !== command.y);
    if (moved && (command.tween_duration ?? 0) > 0) {
      this.tweens.set(id, {
        fromX: previous.x ?? 0,
        fromY: previous.y ?? 0,
        startedAt: this.now(),
        duration: command.tween_duration,
      });
    }
    this.objects.set(id, command);
  }

  // Where an object is right now, part way through any tween it has.
  _placed(command) {
    const tween = this.tweens.get(command.id);
    if (tween === undefined) return command;
    const elapsed = this.now() - tween.startedAt;
    if (elapsed >= tween.duration) {
      this.tweens.delete(command.id);
      return command;
    }
    const progress = tween.duration === 0 ? 1 : elapsed / tween.duration;
    return {
      ...command,
      x: tween.fromX + ((command.x ?? 0) - tween.fromX) * progress,
      y: tween.fromY + ((command.y ?? 0) - tween.fromY) * progress,
    };
  }

  _paint() {
    this.ctx.clearRect(0, 0, this.width, this.height);
    const drawing = [...this.objects.values(), ...this.ephemeral]
      .map((command) => this._placed(command))
      .sort((a, b) => (a.depth ?? 0) - (b.depth ?? 0));
    for (const command of drawing) this._drawCommand(command);
    this._animate();
  }

  // Keep drawing while a tween is running, and stop the moment none is.
  _animate() {
    if (this.tweens.size === 0 || this.animating) return;
    this.animating = true;
    this.schedule(() => {
      this.animating = false;
      if (this.tweens.size > 0) this._paint();
    });
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
        ctx.arc(
          this._x(command, command.x),
          this._y(command, command.y),
          this._r(command, command.radius),
          0,
          Math.PI * 2,
        );
        this._paintPath(command, true);
        break;
      case "ellipse":
        ctx.beginPath();
        ctx.ellipse(
          this._x(command, command.x),
          this._y(command, command.y),
          this._x(command, command.rx),
          this._y(command, command.ry),
          command.angle ?? 0,
          0,
          Math.PI * 2,
        );
        this._paintPath(command, true);
        break;
      case "arc":
        ctx.beginPath();
        ctx.arc(
          this._x(command, command.x),
          this._y(command, command.y),
          this._r(command, command.radius),
          command.start_angle ?? 0,
          command.end_angle ?? Math.PI * 2,
        );
        // An arc is a stroke unless the drawing asked for a filled wedge, which
        // is a different shape: the fill closes it back through the centre.
        this._paintPath(command, false);
        break;
      case "rect":
        if (command.fill === false) {
          ctx.strokeRect(
            this._x(command, command.x),
            this._y(command, command.y),
            this._x(command, command.w),
            this._y(command, command.h),
          );
        } else {
          ctx.fillRect(
            this._x(command, command.x),
            this._y(command, command.y),
            this._x(command, command.w),
            this._y(command, command.h),
          );
        }
        break;
      case "line":
        this._path(command, command.points);
        ctx.stroke();
        break;
      case "polygon":
        this._path(command, command.points);
        ctx.closePath();
        this._paintPath(command, true);
        break;
      case "text":
        ctx.font = `${command.font_size ?? 16}px system-ui, sans-serif`;
        ctx.fillText(
          command.text ?? "",
          this._x(command, command.x),
          this._y(command, command.y),
        );
        break;
      case "image":
        this._drawImage(command);
        break;
      default:
        break;
    }
    ctx.globalAlpha = 1;
  }

  _paintPath(command, fillByDefault) {
    if (command.fill ?? fillByDefault) this.ctx.fill();
    else this.ctx.stroke();
  }

  _drawImage(command) {
    if (this.assets === null || typeof command.image_name !== "string") return;
    const image = this.assets.image(command.image_name);
    // A study that declared no such asset renders nothing here.
    if (!image) return;
    const ctx = this.ctx;
    const x = this._x(command, command.x);
    const y = this._y(command, command.y);
    const w = this._x(command, command.w);
    const h = this._y(command, command.h);
    const angle = command.angle ?? 0;
    if (angle !== 0) {
      ctx.save();
      ctx.translate(x + w / 2, y + h / 2);
      ctx.rotate(angle);
      ctx.translate(-(x + w / 2), -(y + h / 2));
    }
    const frame =
      command.frame === undefined || !this.assets.frame
        ? null
        : this.assets.frame(command.image_name, command.frame);
    if (frame === null) {
      ctx.drawImage(image, x, y, w, h);
    } else {
      ctx.drawImage(image, frame.sx, frame.sy, frame.sw, frame.sh, x, y, w, h);
    }
    if (angle !== 0) ctx.restore();
  }

  _path(command, points) {
    const ctx = this.ctx;
    ctx.beginPath();
    (points ?? []).forEach(([x, y], index) => {
      const px = this._x(command, x);
      const py = this._y(command, y);
      if (index === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
  }
}

// The seam: build a renderer for a canvas. Swap the backend here.
export function createRenderer(canvas, options = {}) {
  return new Canvas2DRenderer(canvas, options);
}
