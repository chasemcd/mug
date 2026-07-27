/**
 * Connection quality: measure the round trip and the time the page was hidden.
 *
 * A study that declares a screen asks its clients for two numbers -- how long a
 * frame takes to reach the server and come back, and how long the page has spent
 * in the background. This class measures them and hands them to a sink; it holds
 * no bound, no ladder, and no verdict, because the server owns all three. A client
 * that could decide it had passed would not be a screen.
 *
 * Every dependency is injected: the clock, the random source, and the scheduler.
 * So a test drives a whole measuring session with a fake clock and no browser, and
 * the page visibility -- the one genuinely browser-shaped input -- arrives through
 * `reportHidden`, which the browser bootstrap calls and a test calls directly.
 */

import { NowMillis, RandomBytes } from './wire.js';

/** Run a callback after a delay (the sampling interval). */
export type Schedule = (callback: () => void, delayMillis: number) => void;

/** Where a measurement goes: one ping out, one sample set up. */
export interface QualitySink {
  /** Send one ping frame carrying an opaque token. */
  ping(token: string): void;
  /** Send one measurement frame with the samples in whole microseconds. */
  measurement(samples: Record<string, number>): void;
}

/** The primitives a quality tracker needs, injected. */
export interface QualityEnv {
  now: NowMillis;
  randomBytes: RandomBytes;
  schedule: Schedule;
}

/** The shortest sampling interval the client honours, whatever the server asks. */
const MIN_INTERVAL_MILLIS = 1000;

function token(randomBytes: RandomBytes): string {
  return Array.from(randomBytes(8))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}

/** Measure this connection's quality and report it, on the server's cadence. */
export class ConnectionQuality {
  private readonly pending = new Map<string, number>();
  private rtt: number | null = null;
  private hiddenMillis = 0;
  private generation = 0;
  private running = false;

  constructor(
    private readonly env: QualityEnv,
    private readonly sink: QualitySink,
  ) {}

  /**
   * Begin measuring, on the interval the server asked for.
   *
   * The first sample is taken at once rather than after the first interval, so
   * entry is decided on this connection rather than a minute into it.
   */
  start(everyMillis: number): void {
    this.stop();
    this.running = true;
    const generation = this.generation;
    const interval = Math.max(MIN_INTERVAL_MILLIS, everyMillis);
    const tick = (): void => {
      if (!this.running || generation !== this.generation) {
        return;
      }
      this.measure();
      this.env.schedule(tick, interval);
    };
    tick();
  }

  /** Stop measuring. A stopped tracker sends nothing, however late a pong is. */
  stop(): void {
    this.running = false;
    this.generation += 1;
    this.pending.clear();
  }

  /** Send one ping, so the next pong can be timed. */
  measure(): void {
    const sent = token(this.env.randomBytes);
    this.pending.set(sent, this.env.now());
    this.sink.ping(sent);
  }

  /**
   * Time one round trip and report it.
   *
   * A token this tracker did not send is ignored: an unmatched pong times
   * nothing, and guessing a start would report a measurement nobody made.
   */
  onPong(received: string): void {
    const sentAt = this.pending.get(received);
    if (sentAt === undefined || !this.running) {
      return;
    }
    this.pending.delete(received);
    this.rtt = Math.max(0, Math.round((this.env.now() - sentAt) * 1000));
    this.sink.measurement(this.samples());
    this.hiddenMillis = 0;
  }

  /** Add time the page spent in the background since the last measurement. */
  reportHidden(millis: number): void {
    this.hiddenMillis += Math.max(0, Math.round(millis));
  }

  /** Return the samples measured since the last report, in whole microseconds. */
  samples(): Record<string, number> {
    const found: Record<string, number> = { hidden: this.hiddenMillis * 1000 };
    if (this.rtt !== null) {
      found.rtt = this.rtt;
    }
    return found;
  }
}
