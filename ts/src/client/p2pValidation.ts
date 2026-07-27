/** The private ping/ack envelope that proves a negotiated channel is bidirectional. */

export interface ValidationMessage {
  type: 'mug_mesh_validation';
  kind: 'ping' | 'ack';
  room_handle: string;
  negotiation_generation: number;
  nonce: string;
}

export interface ChannelValidation {
  nonce: string | null;
  messages: number;
  pingSeen: boolean;
  acked: boolean;
  complete: boolean;
}

export function channelValidation(): ChannelValidation {
  return { nonce: null, messages: 0, pingSeen: false, acked: false, complete: false };
}

export function validationMessage(
  kind: 'ping' | 'ack',
  roomHandle: string,
  generation: number,
  nonce: string,
): ValidationMessage {
  return {
    type: 'mug_mesh_validation',
    kind,
    room_handle: roomHandle,
    negotiation_generation: generation,
    nonce,
  };
}

export function startChannelValidation(
  state: ChannelValidation,
  room: string,
  generation: number,
  nonce: string,
  send: (data: string) => void,
): void {
  if (state.nonce !== null) {
    return;
  }
  state.nonce = nonce;
  send(JSON.stringify(validationMessage('ping', room, generation, nonce)));
}

export function acceptValidationMessage(
  state: ChannelValidation,
  data: string,
  room: string,
  generation: number,
  send: (data: string) => void,
): 'pending' | 'complete' | 'exceeded' {
  if (state.complete) {
    return 'complete';
  }
  state.messages += 1;
  if (data.length > 1_024 || state.messages > 8) {
    return 'exceeded';
  }
  const message = parseValidationMessage(data);
  if (
    message === null ||
    message.room_handle !== room ||
    message.negotiation_generation !== generation
  ) {
    return 'pending';
  }
  if (message.kind === 'ping') {
    send(JSON.stringify(validationMessage('ack', room, generation, message.nonce)));
    state.pingSeen = true;
  } else if (message.nonce === state.nonce) {
    state.acked = true;
  }
  state.complete = state.pingSeen && state.acked;
  return state.complete ? 'complete' : 'pending';
}

function parseValidationMessage(data: string): ValidationMessage | null {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  const item = value as Record<string, unknown>;
  if (
    Object.keys(item).length !== 5 ||
    item.type !== 'mug_mesh_validation' ||
    (item.kind !== 'ping' && item.kind !== 'ack') ||
    typeof item.room_handle !== 'string' ||
    !Number.isSafeInteger(item.negotiation_generation) ||
    typeof item.nonce !== 'string' ||
    item.nonce.length === 0
  ) {
    return null;
  }
  return {
    type: 'mug_mesh_validation',
    kind: item.kind,
    room_handle: item.room_handle,
    negotiation_generation: item.negotiation_generation as number,
    nonce: item.nonce,
  };
}
