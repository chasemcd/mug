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
// drives its own frames while a tween runs. Any object with an `id` may tween,
// whether or not it is persistent -- a sprite redrawn whole each frame still moves
// from somewhere to somewhere, and that is the common case for a character.
//
// It reads declared assets: an `image` command names an asset the study declared,
// and the asset table resolves it -- a whole image, or one frame of a sprite
// atlas. A name the table does not hold draws nothing rather than a placeholder,
// so a missing sprite cannot reach a participant unnoticed.

// How small a line of text may be shrunk to fit. Below this nobody can read it,
// so it is better to run past the edge and be seen to be wrong.
const MIN_TEXT = 6;

class Canvas2DRenderer {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.assets = options.assets ?? null;
    this.now = options.now ?? (() => performance.now());
    this.schedule = options.schedule ?? ((fn) => requestAnimationFrame(fn));
    this.objects = new Map();
    this.tweens = new Map();
    // Where each identified object was last told to be. It is kept for **every**
    // object with an id, not only the persistent ones: a chef that is redrawn
    // whole each frame still moves from somewhere to somewhere, and tweening it is
    // the whole difference between walking and teleporting.
    this.places = new Map();
    this.ephemeral = [];
    this.animating = false;
    // The drawing's own units. Everything is drawn in these and the whole picture
    // is scaled onto the canvas at paint time, so a study's `font_size: 14` and a
    // one-unit line are the same part of the picture on any screen. Sizing the
    // drawing by the canvas instead would leave the text on a large screen exactly
    // as many pixels tall as on a small one, and so half the size on it.
    this.logical = options.logical ?? { w: canvas.width, h: canvas.height };
  }

  get width() {
    return this.logical.w;
  }

  get height() {
    return this.logical.h;
  }

  // Draw the same picture on a canvas of a new size. The units do not change: the
  // canvas holds more device pixels, so the picture is larger and no coarser.
  resize(pixelWidth, pixelHeight) {
    if (this.canvas.width === pixelWidth && this.canvas.height === pixelHeight) {
      return;
    }
    this.canvas.width = pixelWidth;
    this.canvas.height = pixelHeight;
    this._paint();
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
      this.places.clear();
    }
    const ephemeral = [];
    for (const command of packet.commands) {
      // Every identified object is tracked, then kept or redrawn. Tweening used to
      // be tied to persistence, so a study that asked a redrawn sprite to move
      // smoothly was ignored and its object jumped a whole square per frame.
      this._track(command);
      if (command.persistent && typeof command.id === "string") {
        this.objects.set(command.id, command);
      } else {
        ephemeral.push(command);
      }
    }
    this.ephemeral = ephemeral;
    this._paint();
  }

  // Note that one object moved, and start its tween when it asked for one.
  //
  // A tween runs from where the object **is on the screen right now**, not from
  // where it was last told to be. Those differ when a second move arrives while
  // the first is still running -- a chef walking two squares in quick succession
  // -- and starting from the stale place would snap it backwards before it went on.
  _track(command) {
    const id = command.id;
    if (typeof id !== "string") return;
    const target = { x: command.x ?? 0, y: command.y ?? 0 };
    const previous = this.places.get(id);
    if (previous === undefined) {
      this.places.set(id, target);
      return;
    }
    if (previous.x === target.x && previous.y === target.y) return;
    const duration = command.tween_duration ?? 0;
    if (duration > 0) {
      const from = this._where(id, previous);
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

  // Where one object is on the screen now: part way through a running tween, or
  // at the last place it was told to be.
  _where(id, previous) {
    const tween = this.tweens.get(id);
    if (tween === undefined) return { x: previous.x, y: previous.y };
    const elapsed = this.now() - tween.startedAt;
    if (elapsed >= tween.duration) return { x: previous.x, y: previous.y };
    const progress = tween.duration === 0 ? 1 : elapsed / tween.duration;
    return {
      x: tween.fromX + (previous.x - tween.fromX) * progress,
      y: tween.fromY + (previous.y - tween.fromY) * progress,
    };
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
    // One transform puts the whole drawing on the canvas, whatever size the canvas
    // is now. Everything below it works in the drawing's own units and knows
    // nothing about the screen.
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
      case "text": {
        // Text is shrunk to what is left of the picture, and never grown. A study
        // says how large its writing is in the units of its own drawing, and a
        // picture small enough for the words not to fit shows them cut off at the
        // edge -- a score that reads "Dishes delivered: 0" and stops. Only the
        // renderer can measure a string, so only the renderer can do this.
        const at = this._x(command, command.x);
        const size = command.font_size ?? 16;
        const face = (points) => `${points}px system-ui, sans-serif`;
        ctx.font = face(size);
        const words = command.text ?? "";
        const room = this.width - at;
        const wide = ctx.measureText(words).width;
        if (wide > room && room > 0) {
          ctx.font = face(Math.max(MIN_TEXT, (size * room) / wide));
        }
        ctx.fillText(words, at, this._y(command, command.y));
        break;
      }
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
