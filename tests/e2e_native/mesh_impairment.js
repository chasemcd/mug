/**
 * Make a real WebRTC data channel behave like a bad connection.
 *
 * The mesh peers in these tests are real Chromium contexts and the packets
 * really cross `RTCDataChannel`. On one machine that link is perfect, so a
 * browser test over it only ever shows the mesh its easiest case. This script
 * wraps the send side of the channel and delays, reorders, drops, or holds back
 * the packets before they reach the wire.
 *
 * It is installed before any page script, so the client below it uses the
 * standard API and knows nothing about this.
 *
 * Two rules keep it honest:
 *
 * - It touches only the mesh data channel, and only the game packets on it. The
 *   transport validates each channel with a ping and an ack before it hands the
 *   channel over. To impair that traffic is to stop rooms from forming, which
 *   tests the handshake and not the rollback.
 * - It counts what it did. A test that says "the mesh survives packet loss" but
 *   lost nothing is a test of nothing, so the counters below are what a scenario
 *   asserts against.
 *
 * The generator is seeded, so a scenario that fails fails the same way again.
 */
(() => {
  const config = __CONFIG__;

  /** What the shim did to this page's traffic, read back by the test. */
  const counts = {
    sent: 0,
    passed: 0,
    dropped: 0,
    delayed: 0,
    late: 0,
    held: 0,
  };
  window.__mugImpairment = counts;

  /**
   * Every game packet this peer tried to send, before the shim touched it.
   *
   * This is what makes an outside statement of the truth possible in a real
   * browser. The inputs a participant gave are not known in advance -- they come
   * from keys pressed against a live clock -- but each peer says what they were,
   * on the wire, at the moment it played them. So the test can rebuild what the
   * episode *should* have been from what the peers sent, and never from what the
   * mesh later agreed it was.
   *
   * The same text goes to every peer in a tick, so a repeat is dropped here.
   */
  const packets = [];
  window.__mugPackets = packets;
  let lastText = null;

  let state = (config.seed >>> 0) || 1;
  const random = () => {
    // A small linear congruential generator: seeded, and the same in every run.
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };

  // Time zero is the first game packet, not the page load. The peers boot their
  // runtimes at their own speed, so a window measured from load would fall in a
  // different part of the episode on each of them.
  let firstPacketAt = null;
  const held = [];

  const deliver = (channel, data) => {
    if (channel.readyState === 'open') {
      try {
        original.call(channel, data);
      } catch (error) {
        // The channel closed between the delay and the delivery. A lost packet
        // is what this shim is for, so this is not an error here.
      }
    }
  };

  const release = () => {
    for (const [channel, data] of held.splice(0)) {
      deliver(channel, data);
    }
  };

  const original = RTCDataChannel.prototype.send;
  RTCDataChannel.prototype.send = function (data) {
    if (this.label !== config.label || typeof data !== 'string') {
      return original.call(this, data);
    }
    if (data.indexOf('mug_mesh_validation') !== -1) {
      // Handshake traffic, not a game packet.
      return original.call(this, data);
    }

    counts.sent += 1;
    if (data !== lastText && packets.length < 20000) {
      lastText = data;
      packets.push(data);
    }
    const now = performance.now();
    if (firstPacketAt === null) {
      firstPacketAt = now;
    }
    const since = now - firstPacketAt;

    const cut = config.partition_ms;
    if (cut !== null && since >= cut[0] && since < cut[1]) {
      // The peer is away: a closed lid, or a phone that changed network. Nothing
      // leaves, and it all arrives together when the connection comes back.
      counts.held += 1;
      held.push([this, data]);
      if (held.length === 1) {
        window.setTimeout(release, cut[1] - since + config.latency_ms);
      }
      return undefined;
    }

    if (config.loss > 0 && random() < config.loss) {
      counts.dropped += 1;
      return undefined;
    }

    const jitter =
      config.jitter_ms > 0
        ? Math.floor(random() * (2 * config.jitter_ms + 1)) - config.jitter_ms
        : 0;
    const delay = Math.max(0, config.latency_ms + jitter);
    if (delay === 0) {
      counts.passed += 1;
      return original.call(this, data);
    }
    counts.delayed += 1;
    if (delay >= config.late_ms) {
      // Past this point the packet cannot reach the peer in time for the frame
      // it belongs to, so that peer must predict the input and then correct it.
      counts.late += 1;
    }
    window.setTimeout(() => deliver(this, data), delay);
    return undefined;
  };
})();
