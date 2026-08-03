/**
 * Form, content, and completion rendering.
 *
 * These render the delivered activity into the app element and, for a form or a
 * content page, collect the answer and hand it to the driver, which submits a
 * `flow.advance`. They touch the DOM directly, so they run only in the browser;
 * the transport and the command minter stay DOM-free and testable without one.
 */

import { JsonValue } from '../kernel/index.js';
import { BrowserManifest } from './browserGame.js';
import { MeshManifest } from './p2pGame.js';
import { PictureAddresses, renderMarkdown } from './markdown.js';
import { ChatAxisFrame, ChatCandidatesFrame } from './session.js';

/** A single form field. */
export interface FormField {
  field_key: string;
  kind: 'likert' | 'choice' | 'text' | 'number' | 'slider' | 'rating';
  label: string;
  required?: boolean;
  options?: string[];
  scale?: number;
}

/** A form activity. */
export interface FormDelivery {
  kind: 'form';
  activity_key: string;
  form: { form_key: string; version: number; fields: FormField[] };
}

/** A content-page activity. */
export interface ContentDelivery {
  kind: 'content';
  activity_key: string;
  content: {
    content_key: string;
    response_required: boolean;
    version: number;
    body: { text?: string };
  };
}

/**
 * An interactive activity: a game, or a conversation the participant holds.
 *
 * The mode names which runtime owns it. `server`, `browser`, and `peer` step an
 * environment; `chat` carries a recorded conversation instead, and the client
 * renders a transcript rather than a canvas.
 */
export interface GameDelivery {
  kind: 'game';
  activity_key: string;
  mode: 'server' | 'browser' | 'peer' | 'chat';
  countdown?: number;
  /** What the participant reads beside the game while they play it. */
  caption?: string;
  /**
   * How large the picture this game draws is, in pixels. A drawing is relative,
   * so it has no size of its own and only the study knows how large it should be.
   * With none said, 600 by 400 stands.
   */
  size?: readonly number[];
  manifest?: BrowserManifest | MeshManifest;
  /** Set when this activity is a game and a conversation at once, and where. */
  chat?: { placement?: 'beside' | 'below' | 'drawer' };
}

/**
 * A conversation activity: the participant talks, and the client renders a transcript.
 *
 * It is its own kind. A conversation used to be delivered as a game with `mode:
 * 'chat'` -- which still arrives, so both are read -- and the recorded activity kind
 * then said the participant played a game.
 */
export interface ChatDelivery {
  kind: 'chat';
  activity_key: string;
  occurrence_key?: string;
}

/**
 * A comparison activity: one question about runs the participant already made.
 *
 * The delivery carries the question alone. The options are this participant's own
 * recorded runs, so the mount that owns the socket sends them once it has resolved
 * and blinded them (`ComparisonOptions`).
 */
export interface ComparisonDelivery {
  kind: 'comparison';
  activity_key: string;
  ask: string;
}

/** One blinded option: an opaque handle and what the run recorded. */
export interface ComparisonOption {
  handle: string;
  /** A run: which round of this visit it was, and what the round recorded. */
  played?: number;
  summary?: { frames: number; reward: number };
  /** A model output: the text the generation produced, and nothing else. */
  text?: string;
}

/** The options frame the comparison mount sends, in the order it committed to. */
export interface ComparisonOptions {
  ask: string;
  options: ComparisonOption[];
}

/** A background announcement to preload the browser runtime during the forms. */
export interface PreloadDelivery {
  kind: 'preload';
  manifest: BrowserManifest | MeshManifest;
}

/** The final activity: the completion code and the optional return link. */
export interface CompleteDelivery {
  kind: 'complete';
  completion_code?: string;
  return_url?: string;
}

/** Any activity the flow delivers. */
export type Delivery =
  | PreloadDelivery
  | FormDelivery
  | ContentDelivery
  | GameDelivery
  | ChatDelivery
  | ComparisonDelivery
  | CompleteDelivery;

/** The collected form answers, keyed by field. */
export type Answers = { [field: string]: string | number };

function addRadio(
  parent: HTMLElement,
  name: string,
  value: string,
  required?: boolean,
): void {
  // The label wraps the input, so clicking the text selects the option and a
  // screen reader reads the option's own name with it.
  const wrap = document.createElement('label');
  const input = document.createElement('input');
  input.type = 'radio';
  input.name = name;
  input.value = value;
  if (required) input.required = true;
  wrap.appendChild(input);
  wrap.append(' ' + value);
  parent.appendChild(wrap);
}

/**
 * One cell of a scale.
 *
 * The whole cell is the hit area, and nothing is chosen at the start: a control
 * that starts in the middle sends the middle when nobody touches it, so the
 * study would record an answer that was never given.
 */
function addCell(
  parent: HTMLElement,
  name: string,
  value: string,
  required?: boolean,
): void {
  const wrap = document.createElement('label');
  const input = document.createElement('input');
  input.type = 'radio';
  input.name = name;
  input.value = value;
  if (required) input.required = true;
  wrap.appendChild(input);
  wrap.append(value);
  parent.appendChild(wrap);
}

/** A question that must be answered says so where it is asked. */
function needMark(text: string): HTMLElement {
  const mark = document.createElement('span');
  mark.className = 'field__need';
  mark.textContent = text;
  return mark;
}

/** Render a form and submit the collected answers through `onAdvance`. */
export function renderForm(
  app: HTMLElement,
  delivery: FormDelivery,
  onAdvance: (answers: JsonValue) => void,
): void {
  const spec = delivery.form;
  app.innerHTML = '';
  const sheet = document.createElement('div');
  sheet.className = 'sheet';
  const panel = document.createElement('section');
  panel.className = 'panel';
  const head = document.createElement('div');
  head.className = 'panel__head';
  const key = document.createElement('div');
  key.className = 'key';
  key.textContent = 'A few questions';
  head.appendChild(key);
  const heading = document.createElement('h2');
  heading.className = 'panel__ask';
  heading.textContent = spec.form_key;
  head.appendChild(heading);
  panel.appendChild(head);
  const form = document.createElement('form');
  panel.appendChild(form);
  sheet.appendChild(panel);

  for (const field of spec.fields) {
    // A choice or a scale is a group of radios, so it is a fieldset with a
    // legend: that is what tells a screen reader which question the options
    // belong to. A free-text field is one control, so its label is tied by id.
    if (field.kind === 'choice' || field.kind === 'likert') {
      const group = document.createElement('fieldset');
      group.className = 'field';
      const legend = document.createElement('legend');
      legend.className = 'field__label';
      legend.textContent = field.label;
      if (field.required) legend.appendChild(needMark('Needed'));
      group.appendChild(legend);
      if (field.kind === 'likert') {
        const cells = document.createElement('div');
        cells.className = 'cells';
        for (let n = 1; n <= (field.scale ?? 0); n++) {
          addCell(cells, field.field_key, String(n), field.required);
        }
        group.appendChild(cells);
      } else {
        const choices = document.createElement('div');
        choices.className = 'choices';
        for (const option of field.options ?? []) {
          addRadio(choices, field.field_key, option, field.required);
        }
        group.appendChild(choices);
      }
      form.appendChild(group);
    } else {
      const id = `field-${field.field_key}`;
      const wrap = document.createElement('div');
      wrap.className = 'field';
      const label = document.createElement('label');
      label.className = 'field__label';
      label.textContent = field.label;
      label.htmlFor = id;
      if (field.required) label.appendChild(needMark('Needed'));
      wrap.appendChild(label);
      const input = document.createElement('input');
      input.type = 'text';
      input.name = field.field_key;
      input.id = id;
      if (field.required) input.required = true;
      wrap.appendChild(input);
      form.appendChild(wrap);
    }
  }

  const foot = document.createElement('div');
  foot.className = 'panel__foot';
  const submit = document.createElement('button');
  submit.type = 'submit';
  submit.className = 'btn btn--primary';
  submit.textContent = 'Continue';
  foot.appendChild(submit);
  form.appendChild(foot);

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const answers: Answers = {};
    for (const field of spec.fields) {
      const value = new FormData(form).get(field.field_key);
      if (value === null || value === '' || typeof value !== 'string') {
        continue;
      }
      answers[field.field_key] = field.kind === 'likert' ? Number(value) : value;
    }
    onAdvance(answers);
  });
  app.appendChild(sheet);
}

/** Render a content page with a Continue button that advances the flow. */
export function renderContent(
  app: HTMLElement,
  delivery: ContentDelivery,
  onAdvance: (answers: JsonValue) => void,
  assets: PictureAddresses | null = null,
): void {
  app.innerHTML = '';
  const sheet = document.createElement('div');
  sheet.className = 'sheet';
  const page = document.createElement('div');
  page.dataset['testid'] = 'content-page';
  page.className = 'prose';
  // The page is not a landmark, so name the region and let a keyboard reach it:
  // long instructions must be scrollable without a mouse.
  page.tabIndex = 0;
  page.setAttribute('role', 'region');
  page.setAttribute('aria-label', 'Study instructions');
  renderMarkdown(page, delivery.content.body.text ?? '', assets);
  sheet.appendChild(page);
  const actions = document.createElement('div');
  actions.className = 'actions';
  const next = document.createElement('button');
  next.type = 'button';
  next.className = 'btn btn--primary';
  next.textContent = 'Continue';
  next.addEventListener('click', () => onAdvance({}));
  actions.appendChild(next);
  sheet.appendChild(actions);
  app.appendChild(sheet);
}

/** One between-rounds screen, as the mount describes it. */
export interface IntervalFrame {
  type: 'interval';
  markdown?: string;
  round: number;
  of: number;
}

/**
 * Render the screen between rounds of one game activity.
 *
 * It is participant-paced: the server holds the next round until `onContinue`
 * says to go on, because a rest that ends while someone is still reading is not
 * a rest. The Continue button takes focus, so a keyboard reaches it with no Tab.
 */
export function renderInterval(
  app: HTMLElement,
  frame: IntervalFrame,
  onContinue: () => void,
  assets: PictureAddresses | null = null,
): void {
  clearKeepingHead(app);
  // The rest owns everything it puts on the screen, in one element, so it can be
  // told apart from a content page whether or not the study wrote anything to
  // read. It is drawn inside the game's own host, which the next round clears.
  const rest = document.createElement('div');
  rest.dataset['testid'] = 'between-rounds';
  app.appendChild(rest);
  const heading = document.createElement('h2');
  heading.textContent = 'Round ' + frame.round + ' of ' + frame.of;
  rest.appendChild(heading);
  if (frame.markdown) {
    const body = document.createElement('div');
    body.className = 'prose';
    body.tabIndex = 0;
    body.setAttribute('role', 'region');
    body.setAttribute('aria-label', 'Between rounds');
    renderMarkdown(body, frame.markdown, assets);
    rest.appendChild(body);
  }
  const next = document.createElement('button');
  next.textContent = 'Continue';
  next.addEventListener('click', () => onContinue());
  rest.appendChild(next);
  next.focus();
}

/** The two panes of a composed activity, and where the keyboard is. */
export interface Panes {
  /** The pane the game draws into. */
  game: HTMLElement;
  /** The pane the conversation is mounted in. */
  chat: HTMLElement;
  /** Say which pane owns the keyboard, and let go of any key the game held. */
  showFocus(): void;
  /** Move the keyboard on one stop, or back one when `back` is set. */
  cycle(back: boolean): void;
  /** Give the keyboard back to the game. */
  toGame(): void;
  /** Take the canvas as the game pane's focus stop, once it is mounted. */
  useCanvas(canvas: HTMLElement): void;
}

/**
 * Mount the two panes of an activity that is a game and a conversation at once.
 *
 * Each pane is repainted on its own, which is what lets the conversation stay
 * usable while the game pane shows the screen between rounds: the room belongs to
 * the activity, and a rest from the game is not a rest from the person you are
 * playing with.
 *
 * The keyboard belongs to whichever pane has focus, because the arrow keys both
 * steer and move a caret. Tab **cycles** the stops -- canvas, message box, channel
 * tabs -- rather than toggling between two, because a two-way toggle would leave
 * the channel tabs unreachable, and a private channel that needs a mouse is not
 * usable by keyboard. Escape is the fast way back to the game.
 */
/**
 * A pane's head: what it is, and whether the keys are going to it.
 *
 * The badge is the answer beside the thing it is about, so a participant who
 * presses a key and sees nothing move does not have to look elsewhere.
 */
function paneHead(name: string, on: string, off: string): HTMLElement {
  const head = document.createElement('div');
  head.className = 'pane__head';
  const label = document.createElement('span');
  label.className = 'pane__name';
  label.textContent = name;
  const badge = document.createElement('span');
  badge.className = 'pane__badge';
  badge.dataset['on'] = on;
  badge.dataset['off'] = off;
  badge.textContent = off;
  head.appendChild(label);
  head.appendChild(badge);
  return head;
}

/**
 * One turn of a conversation: a name with a mark, and a bubble under it.
 *
 * The two parties are on opposite sides, which is what makes a conversation
 * readable without reading it. The screen never says whether the other party is
 * a person or a model, so the mark carries no meaning beyond "not you".
 */
export function renderTurn(author: string, name: string): HTMLElement {
  const one = document.createElement('div');
  one.className = author === 'you' ? 'turn turn--you' : 'turn turn--them';
  one.dataset['author'] = author;
  const who = document.createElement('div');
  who.className = 'turn__who';
  const mark = document.createElement('span');
  mark.className = 'turn__mark';
  who.appendChild(mark);
  who.append(name);
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  one.appendChild(who);
  one.appendChild(bubble);
  return one;
}

/**
 * Empty one host, and keep the pane head if it has one.
 *
 * A pane's head says what the pane is and where the keys are going. It belongs to
 * the pane and not to the activity inside it, so it survives the activity being
 * drawn again -- the badge used to disappear the first time a canvas mounted.
 */
export function clearKeepingHead(host: HTMLElement): HTMLElement {
  const head = host.querySelector(':scope > .pane__head');
  host.innerHTML = '';
  if (head !== null) {
    host.appendChild(head);
  }
  return host;
}

export function renderPanes(
  app: HTMLElement,
  placement: 'beside' | 'below' | 'drawer',
  onRelease: () => void,
): Panes {
  app.innerHTML = '';
  const frame = document.createElement('div');
  frame.dataset['testid'] = 'composed';
  frame.dataset['placement'] = placement;
  frame.className = 'panes';
  const beside = placement === 'beside' && window.innerWidth >= 760;
  if (!beside) {
    frame.style.gridTemplateColumns = 'minmax(0, 1fr)';
  }

  const game = document.createElement('section');
  game.dataset['testid'] = 'game-pane';
  game.dataset['pane'] = 'game';
  game.className = 'pane';
  game.setAttribute('aria-label', 'The game');
  const chat = document.createElement('section');
  chat.dataset['testid'] = 'chat-pane';
  chat.dataset['pane'] = 'chat';
  chat.className = 'pane';
  chat.setAttribute('aria-label', 'The conversation');
  frame.appendChild(game);
  frame.appendChild(chat);

  // Which pane has the keyboard, said out loud. A participant whose arrow keys
  // stopped working needs to be able to see why, not guess. It is a badge in
  // each pane's head as well, so the answer is beside the thing it is about.
  const where = document.createElement('p');
  where.dataset['testid'] = 'focus-hint';
  where.setAttribute('role', 'status');
  where.setAttribute('aria-live', 'polite');
  where.className = 'hint';
  app.appendChild(frame);
  app.appendChild(where);

  game.appendChild(paneHead('The game', 'Your keys play', 'The game is paused'));
  chat.appendChild(
    paneHead('The conversation', 'Your keys write here', 'Not writing'),
  );

  let canvas: HTMLElement | null = null;
  const stops = (): HTMLElement[] => {
    const input = chat.querySelector('[name=message]');
    const tab = chat.querySelector('[role=tablist] button');
    return [canvas, input as HTMLElement | null, tab as HTMLElement | null].filter(
      (one): one is HTMLElement => one !== null,
    );
  };

  const panes: Panes = {
    game,
    chat,
    showFocus() {
      const inGame = game.contains(document.activeElement);
      const held = inGame ? game : chat;
      for (const pane of [game, chat]) {
        const mine = pane === held;
        pane.classList.toggle('pane--held', mine);
        const badge = pane.querySelector('.pane__badge');
        if (badge instanceof HTMLElement) {
          badge.textContent = mine
            ? (badge.dataset['on'] ?? '')
            : (badge.dataset['off'] ?? '');
        }
      }
      where.textContent = inGame
        ? 'The game has the keyboard. Press Tab to write a message.'
        : 'The conversation has the keyboard. Press Tab or Escape to play.';
      if (!inGame) {
        onRelease();
      }
    },
    cycle(back) {
      const found = stops();
      if (found.length < 2) {
        return;
      }
      const at = found.indexOf(document.activeElement as HTMLElement);
      const step = back ? -1 : 1;
      const next = (at + step + found.length) % found.length;
      found[next]?.focus();
    },
    toGame() {
      canvas?.focus();
    },
    useCanvas(mounted) {
      canvas = mounted;
      mounted.focus();
    },
  };

  frame.addEventListener('focusin', () => panes.showFocus());
  frame.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      panes.toGame();
      return;
    }
    if (event.key !== 'Tab') {
      return;
    }
    event.preventDefault();
    panes.cycle(event.shiftKey);
  });
  return panes;
}

/** What the mounted chat screen offers its driver. */
export interface ChatScreen {
  /** Add one message to the transcript, from the participant or from the seat. */
  append(author: 'you' | 'them', text: string, channel?: string): void;
  /** Name the channels this participant is in; two or more get a tab each. */
  channels(keys: string[], seat?: string): void;
  /** Show, or take away, the placeholder that stands where a reply will be. */
  waiting(on: boolean): void;
  /** Say that a reply is not coming, rather than leave the pane empty. */
  notice(text: string): void;
  /** Ask the participant to choose between the replies this turn wrote. */
  elicit(frame: ChatCandidatesFrame): void;
  /** Take the elicitation off the screen, once the judgement is recorded. */
  settled(): void;
  /** Stop accepting messages, after the participant leaves the conversation. */
  close(): void;
}

/** One axis answer on its way back: which reply it is about, and how much. */
export interface ChatAxisAnswer {
  axis: string;
  option?: string;
  value: number;
}

/** What the chat screen does when the participant acts. */
export interface ChatHandlers {
  onSend(text: string, channel?: string): void;
  onEnd(): void;
  /** The participant chose a reply. The thread goes on from the one they chose. */
  onChoose?(
    handle: string,
    verdict: 'choice' | 'tie' | 'both-bad',
    ratings: ChatAxisAnswer[],
    responseTimeMs: number,
  ): void;
  /** The participant passed. No preference is recorded and the thread goes on. */
  onSkip?(): void;
}

/** Draw one axis: a slider between the two replies, or one scale for each of them.
 *
 * A comparative axis runs from one reply to the other with a midpoint, and the
 * value it sends back names the reply it favours -- never the side of the screen,
 * so a shuffled presentation cannot be read back wrong.
 */
function renderAxis(
  axis: ChatAxisFrame,
  order: string[],
  panel: HTMLElement,
): { scope: 'pair' | 'each'; slider: HTMLInputElement | null;
     each: Map<string, HTMLInputElement> } {
  const block = document.createElement('div');
  block.dataset['testid'] = 'chat-axis';
  block.dataset['axis'] = axis.key;
  const label = document.createElement('label');
  label.textContent = axis.ask;
  block.appendChild(label);
  const each = new Map<string, HTMLInputElement>();
  let slider: HTMLInputElement | null = null;
  if (axis.scope === 'each') {
    for (const handle of order) {
      const one = document.createElement('input');
      one.type = 'range';
      one.min = '1';
      one.max = String(axis.points);
      one.value = String(Math.ceil(axis.points / 2));
      one.id = 'axis-' + axis.key + '-' + handle;
      one.dataset['option'] = handle;
      one.setAttribute('aria-label', axis.ask);
      block.appendChild(one);
      each.set(handle, one);
    }
  } else {
    slider = document.createElement('input');
    slider.type = 'range';
    slider.min = String(-axis.points);
    slider.max = String(axis.points);
    slider.step = '1';
    slider.value = '0';
    slider.id = 'axis-' + axis.key;
    slider.setAttribute('aria-label', axis.ask);
    block.appendChild(slider);
  }
  panel.appendChild(block);
  return { scope: axis.scope, slider, each };
}

/**
 * Render the conversation screen: a transcript, a message box, and a way out.
 *
 * The participant's own message is added here when they send it, because the
 * mount does not echo it: it records the message and answers with the reply. The
 * two authors are labelled "You" and "Them" -- the screen never says whether the
 * other party is a person or a model, because only the study knows, and only the
 * study may say.
 */
export function renderChat(
  app: HTMLElement,
  handlers: ChatHandlers,
  composed = false,
): ChatScreen {
  // A pane's head belongs to the pane and not to the activity inside it, so it
  // survives the activity being drawn again.
  const keepHead = app.querySelector(':scope > .pane__head');
  app.innerHTML = '';
  if (keepHead !== null) {
    app.appendChild(keepHead);
  }

  // A standalone conversation owns the screen, so it scrolls the thread and
  // docks what the participant writes at the foot. Inside a pane the pane is
  // already the frame, so the same parts sit in it without a second one.
  const scroll = document.createElement('div');
  scroll.className = composed ? 'pane__body' : 'scroll';
  const thread = document.createElement('div');
  thread.className = composed ? '' : 'thread';
  const scrollDown = (): void => {
    scroll.scrollTop = scroll.scrollHeight;
  };

  const tabs = document.createElement('div');
  tabs.setAttribute('role', 'tablist');
  tabs.dataset['testid'] = 'chat-channels';
  tabs.className = 'channels';
  tabs.hidden = true;
  thread.appendChild(tabs);

  const transcript = document.createElement('div');
  transcript.setAttribute('role', 'log');
  transcript.setAttribute('aria-label', 'Conversation');
  transcript.dataset['testid'] = 'chat-transcript';
  // The transcript keeps a size before anything is said. A pane that collapses
  // to nothing reads as broken rather than empty.
  transcript.className = 'log';
  thread.appendChild(transcript);
  scroll.appendChild(thread);
  app.appendChild(scroll);

  const dock = document.createElement('div');
  dock.className = composed ? 'pane__foot' : 'dock';
  const form = document.createElement('form');
  form.className = 'composer';
  // The box grows to what is written and stops. A held size tells a participant
  // to write one line; an unbounded one pushes the conversation off the screen.
  const input = document.createElement('textarea');
  input.name = 'message';
  input.rows = 1;
  input.autocomplete = 'off';
  input.placeholder = 'Write a message';
  input.setAttribute('aria-label', 'Your message');
  const send = document.createElement('button');
  send.type = 'submit';
  send.className = 'send';
  send.disabled = true;
  send.setAttribute('aria-label', 'Send');
  send.innerHTML =
    '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
    '<path d="M8 13V3.5M8 3.5 3.8 7.7M8 3.5l4.2 4.2" stroke="currentColor" ' +
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  form.appendChild(input);
  form.appendChild(send);
  dock.appendChild(form);

  const grow = (): void => {
    input.style.height = 'auto';
    input.style.height = String(Math.min(input.scrollHeight, 160)) + 'px';
    send.disabled = input.value.trim() === '';
  };
  input.addEventListener('input', grow);
  // Return sends and shift with return breaks the line, which is what a person
  // who has used any other message box expects.
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  // Only a standalone conversation is ended by the participant. A composed
  // activity ends when its rounds end, so leaving the conversation early would
  // leave them playing a game they can no longer talk about.
  const leave = document.createElement('button');
  leave.type = 'button';
  leave.className = 'btn btn--quiet btn--small';
  leave.textContent = 'End the conversation';
  if (!composed) {
    const hint = document.createElement('p');
    hint.className = 'hint';
    hint.textContent = 'Return sends. Shift and return make a new line.';
    dock.appendChild(hint);
    const foot = document.createElement('div');
    foot.className = 'hint';
    foot.appendChild(leave);
    dock.appendChild(foot);
  }
  app.appendChild(dock);
  grow();

  // One channel is shown at a time. A message that belongs to another channel is
  // held rather than dropped, so moving to it shows what was said there.
  const lines = new Map<string, HTMLElement[]>();
  let current: string | null = null;
  // The placeholder that stands where a reply is going to be, or null when the
  // conversation is not waiting for one.
  let pending: HTMLElement | null = null;

  const show = (channel: string): void => {
    current = channel;
    transcript.innerHTML = '';
    for (const line of lines.get(channel) ?? []) {
      transcript.appendChild(line);
    }
    scrollDown();
    for (const tab of Array.from(tabs.children)) {
      tab.setAttribute(
        'aria-selected',
        String((tab as HTMLElement).dataset['channel'] === channel),
      );
    }
  };

  // The open elicitation's panel and its controls, or null when the turn is not
  // asking. Only blinded handles are held: which model wrote which reply is what
  // the screen must not be able to say.
  let asking: {
    panel: HTMLElement;
    order: string[];
    axes: Map<string, { scope: 'pair' | 'each'; slider: HTMLInputElement | null;
      each: Map<string, HTMLInputElement> }>;
    shown: number;
  } | null = null;

  const answers = (): ChatAxisAnswer[] => {
    const written: ChatAxisAnswer[] = [];
    if (asking === null) {
      return written;
    }
    for (const [key, control] of asking.axes) {
      if (control.scope === 'each') {
        for (const [option, input] of control.each) {
          written.push({ axis: key, option, value: Number(input.value) });
        }
        continue;
      }
      const value = Number(control.slider?.value ?? 0);
      const side = value < 0 ? asking.order[0] : asking.order[1];
      if (value === 0 || side === undefined) {
        // The midpoint favours neither reply, and it is the only answer that
        // names none.
        written.push({ axis: key, value: 0 });
      } else {
        written.push({ axis: key, option: side, value: Math.abs(value) });
      }
    }
    return written;
  };

  const screen: ChatScreen = {
    elicit(frame) {
      screen.settled();
      const panel = document.createElement('section');
      panel.dataset['testid'] = 'chat-candidates';
      const ask = document.createElement('h3');
      ask.id = 'chat-candidates-ask';
      ask.textContent = frame.ask;
      panel.appendChild(ask);
      const list = document.createElement('div');
      list.dataset['testid'] = 'chat-candidate-options';
      list.setAttribute('role', 'group');
      list.setAttribute('aria-labelledby', ask.id);
      const order: string[] = [];
      const axes = new Map<
        string,
        { scope: 'pair' | 'each'; slider: HTMLInputElement | null;
          each: Map<string, HTMLInputElement> }
      >();
      const answer = (
        handle: string,
        verdict: 'choice' | 'tie' | 'both-bad',
      ): void => {
        const elapsed = asking === null ? 0 : Date.now() - asking.shown;
        handlers.onChoose?.(handle, verdict, answers(), elapsed);
      };
      for (const option of frame.options) {
        order.push(option.handle);
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset['handle'] = option.handle;
        button.style.display = 'block';
        button.style.margin = '0.5rem 0';
        button.style.whiteSpace = 'pre-wrap';
        button.style.textAlign = 'left';
        button.textContent = option.text;
        button.addEventListener('click', () => answer(option.handle, 'choice'));
        list.appendChild(button);
      }
      panel.appendChild(list);
      for (const axis of frame.axes) {
        axes.set(axis.key, renderAxis(axis, order, panel));
      }
      if (frame.ties) {
        // A tie still resolves to the reply the thread goes on with, and the one
        // they read first is the honest choice for it.
        for (const [verdict, label] of [
          ['tie', 'They are about the same'],
          ['both-bad', 'Both are bad'],
        ] as const) {
          const button = document.createElement('button');
          button.type = 'button';
          button.dataset['verdict'] = verdict;
          button.textContent = label;
          button.addEventListener('click', () => answer(order[0] ?? '', verdict));
          panel.appendChild(button);
        }
      }
      if (frame.skippable) {
        const skip = document.createElement('button');
        skip.type = 'button';
        skip.dataset['testid'] = 'chat-candidate-skip';
        skip.textContent = 'Skip';
        skip.addEventListener('click', () => {
          screen.settled();
          handlers.onSkip?.();
        });
        panel.appendChild(skip);
      }
      app.appendChild(panel);
      asking = { panel, order, axes, shown: Date.now() };
    },
    settled() {
      asking?.panel.remove();
      asking = null;
    },
    channels(keys, seat) {
      current = keys[0] ?? null;
      tabs.innerHTML = '';
      tabs.hidden = keys.length < 2;
      tabs.dataset['seat'] = seat ?? '';
      if (keys.length < 2) {
        return;
      }
      for (const key of keys) {
        const tab = document.createElement('button');
        tab.type = 'button';
        tab.setAttribute('role', 'tab');
        tab.dataset['channel'] = key;
        tab.textContent = key;
        tab.addEventListener('click', () => show(key));
        tabs.appendChild(tab);
      }
      if (current !== null) {
        show(current);
      }
    },
    // What the screen says between a message and its reply. A model on a local
    // runner takes seconds to answer, and a pane that shows nothing at all while
    // it thinks reads as a broken study rather than a slow one.
    waiting(on) {
      if (on) {
        if (pending !== null) {
          return;
        }
        // It is the same bubble the words will arrive in, so nothing on the
        // screen moves when they do.
        pending = renderTurn('them', 'Them');
        pending.dataset['testid'] = 'chat-waiting';
        const dots = document.createElement('span');
        dots.className = 'dots';
        dots.setAttribute('role', 'status');
        dots.setAttribute('aria-label', 'Waiting for a reply');
        dots.innerHTML = '<span></span><span></span><span></span>';
        pending.querySelector('.bubble')?.appendChild(dots);
        transcript.appendChild(pending);
        scrollDown();
        return;
      }
      if (pending !== null) {
        pending.remove();
      }
      pending = null;
    },
    // A reply that is never coming. The mount says so rather than leaving the
    // participant to work it out from an empty pane. It is not a bubble,
    // because nobody said it.
    notice(text) {
      screen.waiting(false);
      const line = document.createElement('div');
      line.className = 'notice';
      line.dataset['testid'] = 'chat-notice';
      line.setAttribute('role', 'status');
      const mark = document.createElement('b');
      mark.setAttribute('aria-hidden', 'true');
      mark.textContent = '!';
      line.appendChild(mark);
      const words = document.createElement('span');
      words.textContent = text;
      line.appendChild(words);
      transcript.appendChild(line);
      scrollDown();
    },
    append(author, text, channel) {
      // The reply has arrived, so what stood in for it goes.
      if (author !== 'you') {
        screen.waiting(false);
      }
      const key = channel ?? current ?? '';
      const line = renderTurn(author, author === 'you' ? 'You' : 'Them');
      line.dataset['channel'] = key;
      line.querySelector('.bubble')?.append(text);
      const held = lines.get(key) ?? [];
      held.push(line);
      lines.set(key, held);
      if (current === null || key === current) {
        transcript.appendChild(line);
        scrollDown();
      }
    },
    close() {
      screen.waiting(false);
      input.disabled = true;
      send.disabled = true;
      leave.disabled = true;
    },
  };

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (text === '') {
      return;
    }
    input.value = '';
    screen.append('you', text, current ?? undefined);
    // Only a conversation that is the whole activity is owed a reply, so only it
    // says one is coming. Beside a game the other party is a **player**: it
    // answers when it is free and it is allowed to say nothing at all, so a
    // "typing" bubble raised by every message is a promise nobody made -- and
    // one the participant then watches for the rest of the round.
    if (!composed) {
      screen.waiting(true);
    }
    handlers.onSend(text, current ?? undefined);
  });
  leave.addEventListener('click', () => {
    screen.close();
    handlers.onEnd();
  });
  return screen;
}

/** What the mounted comparison screen offers its driver. */
export interface ComparisonScreen {
  /** Draw the options the mount committed to, in the order it sent them. */
  present(options: ComparisonOptions): void;
  /** Let the participant answer again, after the server refused their answer. */
  reopen(): void;
  /** Stop accepting answers, once one is recorded. */
  close(): void;
}

/**
 * Render the comparison screen: the question, then the options once they arrive.
 *
 * The screen shows what each run recorded and which round of this participant's
 * own visit it was. It never shows the author's label for an option, because that
 * label is the condition the study is measuring; the handle it sends back is
 * opaque and carries no position.
 */
export function renderComparison(
  app: HTMLElement,
  delivery: ComparisonDelivery,
  onChoose: (handle: string) => void,
): ComparisonScreen {
  app.innerHTML = '';
  const sheet = document.createElement('div');
  sheet.className = 'scroll';
  const panel = document.createElement('section');
  panel.className = 'panel';
  const head = document.createElement('div');
  head.className = 'panel__head';
  const key = document.createElement('div');
  key.className = 'key';
  key.textContent = 'A comparison';
  head.appendChild(key);
  const heading = document.createElement('h2');
  heading.className = 'panel__ask';
  heading.textContent = delivery.ask;
  head.appendChild(heading);
  panel.appendChild(head);
  const waiting = document.createElement('p');
  waiting.dataset['testid'] = 'comparison-waiting';
  waiting.className = 'block';
  waiting.textContent = 'Loading what you are being asked about...';
  panel.appendChild(waiting);
  sheet.appendChild(panel);
  app.appendChild(sheet);

  const list = document.createElement('div');
  list.dataset['testid'] = 'comparison-options';
  // The options are a group and the question is its name, so a screen reader
  // announces what is being asked before it reads the first option.
  heading.id = 'comparison-ask';
  list.className = 'pair';
  list.setAttribute('role', 'radiogroup');
  list.setAttribute('aria-labelledby', 'comparison-ask');

  const foot = document.createElement('div');
  foot.className = 'panel__foot';
  // One submit. The choice is made on the option, which is where the
  // participant is already looking; the button says which one it will send.
  const submit = document.createElement('button');
  submit.type = 'button';
  submit.className = 'btn btn--primary';
  submit.dataset['testid'] = 'comparison-submit';
  submit.textContent = 'Pick one above';
  submit.disabled = true;
  foot.appendChild(submit);

  const inputs = (): HTMLInputElement[] =>
    Array.from(list.querySelectorAll('input'));

  const LETTERS = 'ABCDEFGH';

  return {
    present(options) {
      heading.textContent = options.ask;
      waiting.remove();
      list.innerHTML = '';
      options.options.forEach((option, at) => {
        // The option cell is the control. Both cells are one grid with one
        // track rule, they stretch together, and both badges are the same ink,
        // so the layout carries no signal about which is which.
        const cell = document.createElement('label');
        cell.className = 'option option--pick';
        cell.dataset['handle'] = option.handle;
        const input = document.createElement('input');
        input.type = 'radio';
        input.name = 'comparison-choice';
        input.value = option.handle;
        cell.appendChild(input);

        const top = document.createElement('div');
        top.className = 'option__head';
        const badge = document.createElement('span');
        badge.className = 'badge badge--lg';
        badge.textContent = LETTERS[at] ?? String(at + 1);
        top.appendChild(badge);
        const name = document.createElement('span');
        name.className = 'option__name';
        const body = document.createElement('div');
        body.className = 'option__text';
        // An option shows what it recorded: a run shows how long it went and
        // what it earned, a model output shows the text it produced. Neither
        // says which condition it was, which is what the blinding is for.
        if (typeof option.text === 'string') {
          name.textContent = 'Option ' + String(badge.textContent);
          body.textContent = option.text;
        } else {
          const summary = option.summary ?? { frames: 0, reward: 0 };
          name.textContent = 'Round ' + String(option.played ?? 0);
          body.textContent =
            String(summary.frames) + ' frames, score ' + String(summary.reward);
        }
        top.appendChild(name);
        cell.appendChild(top);
        cell.appendChild(body);

        const pick = document.createElement('div');
        pick.className = 'option__pick';
        const dot = document.createElement('span');
        dot.className = 'option__dot';
        dot.setAttribute('aria-hidden', 'true');
        dot.textContent = '✓';
        pick.appendChild(dot);
        const word = document.createElement('span');
        word.textContent = 'Choose this one';
        pick.appendChild(word);
        cell.appendChild(pick);

        input.addEventListener('change', () => {
          submit.disabled = false;
          submit.textContent = 'Send: option ' + String(badge.textContent);
        });
        list.appendChild(cell);
      });
      panel.appendChild(list);
      panel.appendChild(foot);
      submit.addEventListener('click', () => {
        const picked = inputs().find((one) => one.checked);
        if (!picked) return;
        this.close();
        onChoose(picked.value);
      });
    },
    reopen() {
      for (const input of inputs()) {
        input.disabled = false;
      }
      submit.disabled = false;
    },
    close() {
      for (const input of inputs()) {
        input.disabled = true;
      }
      submit.disabled = true;
    },
  };
}

/** Render the completion screen: the code and the optional return link. */
export function renderComplete(app: HTMLElement, delivery: CompleteDelivery): void {
  app.innerHTML = '';
  const done = document.createElement('div');
  done.className = 'sheet done';
  const heading = document.createElement('h1');
  heading.textContent = 'All done. Thank you.';
  done.appendChild(heading);
  if (delivery.completion_code) {
    // The code is what the participant is paid on, so it is the largest thing
    // on the screen and it selects in one press.
    const note = document.createElement('p');
    note.className = 'panel__note';
    note.textContent = 'Copy this code before you close the page.';
    done.appendChild(note);
    const line = document.createElement('p');
    const code = document.createElement('span');
    code.className = 'code';
    code.textContent = delivery.completion_code;
    line.appendChild(code);
    done.appendChild(line);
  }
  if (delivery.return_url) {
    const actions = document.createElement('div');
    actions.className = 'actions';
    actions.style.justifyContent = 'center';
    const link = document.createElement('a');
    link.className = 'btn btn--primary';
    link.href = delivery.return_url;
    link.textContent = 'Return to the study';
    actions.appendChild(link);
    done.appendChild(actions);
  }
  app.appendChild(done);
}
