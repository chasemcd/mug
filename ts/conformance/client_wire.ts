/**
 * The client wire runner.
 *
 * It drives the participant session with a fake socket and deterministic inputs,
 * then prints, as JSON, the connection url, the persisted resume token, and every
 * frame the session sent. The Python side reads this and validates each command
 * against the real `RealtimeCommand` model, so the TypeScript client is proven to
 * emit frames the server accepts -- without a browser.
 *
 * The hash is injected from Node `crypto`, exactly as the kernel conformance
 * runner does. The random source is deterministic, so a run is reproducible; the
 * command ids and idempotency keys still fit their patterns, because the version
 * and variant nibbles and the base64url length force valid shapes.
 */

/// <reference types="node" />

import { createHash } from 'crypto';

import { HashBytes } from '../src/kernel/index.js';
import {
  Endpoint,
  KeyValueStore,
  ParticipantSession,
  Socket,
  SocketFactory,
} from '../src/client/session.js';
import { WireEnv } from '../src/client/wire.js';

const nodeSha256: HashBytes = async (bytes) =>
  createHash('sha256').update(Buffer.from(bytes)).digest('hex');

// A deterministic random source: each call fills bytes from an incrementing seed,
// so successive commands get distinct ids while the run stays reproducible.
function deterministicRandom(): (count: number) => Uint8Array {
  let seed = 1;
  return (count: number): Uint8Array => {
    const bytes = new Uint8Array(count);
    for (let i = 0; i < count; i++) {
      bytes[i] = (seed * 31 + i * 7) & 0xff;
    }
    seed += 1;
    return bytes;
  };
}

// A fake socket that records every frame the session sends and lets the runner
// push server frames back through the message handler.
class FakeSocket implements Socket {
  readonly sent: string[] = [];
  private message: ((data: string) => void) | null = null;

  send(data: string): void {
    this.sent.push(data);
  }
  close(): void {
    // no reconnection in the runner
  }
  onMessage(handler: (data: string) => void): void {
    this.message = handler;
  }
  onOpen(): void {}
  onClose(): void {}
  onError(): void {}

  deliver(frame: unknown): void {
    this.message?.(JSON.stringify(frame));
  }
}

async function main(): Promise<void> {
  const env: WireEnv = {
    now: () => 1_700_000_000_000,
    randomBytes: deterministicRandom(),
    hash: nodeSha256,
  };
  const endpoint: Endpoint = { wsBase: 'ws://test.local', ticket: 'ticket-abc' };

  const socket = new FakeSocket();
  const connect: SocketFactory = () => socket;
  const memory = new Map<string, string>();
  const store: KeyValueStore = {
    get: (key) => memory.get(key) ?? null,
    set: (key, value) => {
      memory.set(key, value);
    },
    remove: (key) => {
      memory.delete(key);
    },
  };

  let url = '';
  // What the session hands the driver for a conversation. The mount pushes one
  // chat frame per message the participant did not write, so a client that
  // dropped or rejected them would show a one-sided transcript.
  const heard: unknown[] = [];
  const session = new ParticipantSession({
    endpoint,
    connect: (built) => {
      url = built;
      return connect(built);
    },
    store,
    schedule: () => {},
    env,
    handlers: {
      onHandshake: () => {},
      onDelivery: () => {},
      onRender: () => {},
      onP2P: () => {},
      onChat: (message) => {
        heard.push(message);
      },
      onComparisonOptions: () => {},
      onComparisonError: () => {},
      onComparisonAck: () => {},
      onError: () => {},
      onClose: () => {},
    },
  });

  session.start();
  // The server opens the session and issues a signed resume token.
  socket.deliver({
    type: 'handshake_ack',
    protocol_version: '0.1.0',
    subject: 'participant_019b6000-0000-7000-8000-0000000000aa',
    resume_cursor: 0,
    resume_token: 'signed-token.mac',
  });

  await session.sendAdvance({ agree: 'yes' });
  await session.sendAdvance({ mood: 4, comment: 'thanks' });
  await session.sendCommand('game.capture', {
    episode: {
      transitions: [
        {
          interaction_id: 'interaction_019b6000-0000-7000-8000-0000000000b1',
          channel_key: 'game.play',
          episode_id: 'episode_019b6000-0000-7000-8000-0000000000c1',
          frame_number: 1,
          action_digest: { algorithm: 'sha-256', hex: 'b'.repeat(64) },
          state_digest: { algorithm: 'sha-256', hex: 'c'.repeat(64) },
          authority: 'browser',
          applied_decisions: [],
          recorded_at: '2026-07-23T12:00:00.000000Z',
        },
      ],
      boundary: {
        episode_id: 'episode_019b6000-0000-7000-8000-0000000000c1',
        interaction_id: 'interaction_019b6000-0000-7000-8000-0000000000b1',
        kind: 'terminal',
        end_frame_exclusive: 1,
        authority: 'browser',
        state_hash: { algorithm: 'sha-256', hex: 'c'.repeat(64) },
      },
    },
    actions: [0, 2, 1],
    generation: 1,
  });
  session.sendInput(['ArrowLeft']);

  // The conversation activity: the seat opens, the participant answers, and the
  // participant then leaves, which is what advances the flow past the chat.
  socket.deliver({
    type: 'chat',
    message_id: 'message_019b6000-0000-7000-8000-0000000000d1',
    author_actor_id: 'actor_019b6000-0000-7000-8000-0000000000d2',
    sequence: 1,
    text: 'Hello. What brings you here today?',
  });
  session.sendChat('I am here for the study.');
  session.sendChatEnd();

  // What the participant carries between activities: the server delivers the
  // namespaces they may read, a page writes one against the revision it read, and
  // a refused write puts back what it replaced.
  socket.deliver({
    type: 'delivery',
    delivery: { kind: 'content', state: { progress: { seen: ['notes'] } } },
  });
  const readBack = session.readState('progress');
  await session.writeState('progress', { seen: ['notes', 'debrief'] });
  const afterWrite = session.stateRevision('progress');
  const refused = socket.sent
    .map((data) => JSON.parse(data) as { command?: { command_id: string } })
    .filter((frame) => frame.command !== undefined)
    .at(-1)?.command?.command_id;
  socket.deliver({
    type: 'error',
    command_id: refused,
    code: 'command.state_conflict',
    category: 'conflict',
    message: 'the namespace moved on to revision 4',
  });
  const afterRefusal = session.stateRevision('progress');
  // Every send goes through the session's one serialized writer, so the frame
  // reaches the socket on a later turn. Wait for the queue to drain before the
  // report reads what was sent.
  await new Promise((resolve) => setImmediate(resolve));

  const report = {
    url,
    stored_resume_token: store.get('mug_resume_token'),
    frames: socket.sent.map((data) => JSON.parse(data)),
    chat_heard: heard,
    state_read_back: readBack,
    state_revision_after_write: afterWrite,
    state_revision_after_refusal: afterRefusal,
  };
  console.log(JSON.stringify(report));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
