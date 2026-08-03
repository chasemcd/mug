/**
 * Map the keys a participant holds to the action their seat takes.
 *
 * This is the browser twin of `resolve_action` in `mug/game/runtime.py`, and the
 * two must agree: a browser run is verified by re-executing it on the server, so
 * a client that read one action where the server read another would make an
 * honest participant's run unverifiable.
 *
 * A chord is a **sequence of keys** held together, and it arrives as one: every
 * key in it must be down. A chord beats a single key, and a longer chord beats a
 * shorter one, so the most specific thing the participant is doing is what the
 * seat does.
 */

/** One chord: the keys that must be held together, and what they mean. */
export interface Chord {
  keys: readonly string[];
  action: number;
}

export function resolveAction(
  pressed: Set<string>,
  bindings: { [key: string]: number },
  defaultAction: number,
  chords: readonly Chord[] = [],
): number {
  let bestSize = 0;
  let best: number | undefined;
  for (const chord of chords) {
    if (chord.keys.every((key) => pressed.has(key)) && chord.keys.length > bestSize) {
      bestSize = chord.keys.length;
      best = chord.action;
    }
  }
  if (best !== undefined) {
    return best;
  }
  for (const key of pressed) {
    if (key in bindings) {
      return bindings[key] as number;
    }
  }
  return defaultAction;
}
