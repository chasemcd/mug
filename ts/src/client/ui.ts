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
  manifest?: BrowserManifest | MeshManifest;
  /** Set when this activity is a game and a conversation at once, and where. */
  chat?: { placement?: 'beside' | 'below' | 'drawer' };
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
  wrap.style.marginRight = '1rem';
  const input = document.createElement('input');
  input.type = 'radio';
  input.name = name;
  input.value = value;
  if (required) input.required = true;
  wrap.appendChild(input);
  wrap.append(' ' + value);
  parent.appendChild(wrap);
}

/** Render a form and submit the collected answers through `onAdvance`. */
export function renderForm(
  app: HTMLElement,
  delivery: FormDelivery,
  onAdvance: (answers: JsonValue) => void,
): void {
  const spec = delivery.form;
  app.innerHTML = '';
  const form = document.createElement('form');
  const heading = document.createElement('h2');
  heading.textContent = spec.form_key;
  form.appendChild(heading);

  for (const field of spec.fields) {
    // A choice or a scale is a group of radios, so it is a fieldset with a
    // legend: that is what tells a screen reader which question the options
    // belong to. A free-text field is one control, so its label is tied by id.
    if (field.kind === 'choice' || field.kind === 'likert') {
      const group = document.createElement('fieldset');
      group.style.border = 'none';
      group.style.margin = '0.75rem 0 0.25rem';
      group.style.padding = '0';
      const legend = document.createElement('legend');
      legend.textContent = field.label;
      group.appendChild(legend);
      const values =
        field.kind === 'choice'
          ? (field.options ?? [])
          : Array.from({ length: field.scale ?? 0 }, (_, n) => String(n + 1));
      for (const option of values) {
        addRadio(group, field.field_key, option, field.required);
      }
      form.appendChild(group);
    } else {
      const id = `field-${field.field_key}`;
      const label = document.createElement('label');
      label.textContent = field.label;
      label.htmlFor = id;
      label.style.display = 'block';
      label.style.margin = '0.75rem 0 0.25rem';
      form.appendChild(label);
      const input = document.createElement('input');
      input.type = 'text';
      input.name = field.field_key;
      input.id = id;
      if (field.required) input.required = true;
      form.appendChild(input);
    }
  }

  const submit = document.createElement('button');
  submit.type = 'submit';
  submit.textContent = 'Continue';
  submit.style.display = 'block';
  submit.style.marginTop = '1rem';
  form.appendChild(submit);

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
  app.appendChild(form);
}

/** Render a content page with a Continue button that advances the flow. */
export function renderContent(
  app: HTMLElement,
  delivery: ContentDelivery,
  onAdvance: (answers: JsonValue) => void,
): void {
  app.innerHTML = '';
  const pre = document.createElement('pre');
  pre.textContent = delivery.content.body.text ?? '';
  pre.style.whiteSpace = 'pre-wrap';
  // A <pre> is not a landmark, so name the region and let a keyboard reach it:
  // long instructions must be scrollable without a mouse.
  pre.tabIndex = 0;
  pre.setAttribute('role', 'region');
  pre.setAttribute('aria-label', 'Study instructions');
  app.appendChild(pre);
  const next = document.createElement('button');
  next.textContent = 'Continue';
  next.addEventListener('click', () => onAdvance({}));
  app.appendChild(next);
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
): void {
  app.innerHTML = '';
  const heading = document.createElement('h2');
  heading.textContent = 'Round ' + frame.round + ' of ' + frame.of;
  app.appendChild(heading);
  if (frame.markdown) {
    const body = document.createElement('pre');
    body.textContent = frame.markdown;
    body.style.whiteSpace = 'pre-wrap';
    body.tabIndex = 0;
    body.setAttribute('role', 'region');
    body.setAttribute('aria-label', 'Between rounds');
    app.appendChild(body);
  }
  const next = document.createElement('button');
  next.textContent = 'Continue';
  next.addEventListener('click', () => onContinue());
  app.appendChild(next);
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
export function renderPanes(
  app: HTMLElement,
  placement: 'beside' | 'below' | 'drawer',
  onRelease: () => void,
): Panes {
  app.innerHTML = '';
  const frame = document.createElement('div');
  frame.dataset['testid'] = 'composed';
  frame.dataset['placement'] = placement;
  frame.style.display = 'flex';
  frame.style.gap = '1rem';
  frame.style.alignItems = 'flex-start';
  const beside = placement === 'beside' && window.innerWidth >= 760;
  frame.style.flexDirection = beside ? 'row' : 'column';

  const game = document.createElement('div');
  game.dataset['testid'] = 'game-pane';
  game.style.flex = '0 1 auto';
  const chat = document.createElement('div');
  chat.dataset['testid'] = 'chat-pane';
  chat.style.flex = beside ? '1 1 18rem' : '1 1 auto';
  chat.style.minWidth = '0';
  chat.style.width = beside ? 'auto' : '100%';
  frame.appendChild(game);
  frame.appendChild(chat);

  // Which pane has the keyboard, said out loud. A participant whose arrow keys
  // stopped working needs to be able to see why, not guess.
  const where = document.createElement('p');
  where.dataset['testid'] = 'focus-hint';
  where.setAttribute('role', 'status');
  where.setAttribute('aria-live', 'polite');
  where.style.margin = '0.5rem 0 0';
  where.style.fontSize = '0.85rem';
  app.appendChild(frame);
  app.appendChild(where);

  let canvas: HTMLElement | null = null;
  const stops = (): HTMLElement[] => {
    const input = chat.querySelector('input[name=message]');
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
        pane.style.outline =
          pane === held ? '2px solid #2b6cb0' : '2px solid transparent';
        pane.style.outlineOffset = '4px';
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
  app.innerHTML = '';
  const tabs = document.createElement('div');
  tabs.setAttribute('role', 'tablist');
  tabs.dataset['testid'] = 'chat-channels';
  tabs.style.margin = '0 0 0.5rem';
  app.appendChild(tabs);

  const transcript = document.createElement('div');
  transcript.setAttribute('role', 'log');
  transcript.dataset['testid'] = 'chat-transcript';
  transcript.style.margin = '0 0 1rem';
  // The rail keeps its size before anything is said. A transcript that
  // collapses to nothing reads as a broken pane rather than an empty one.
  transcript.style.minHeight = '8rem';
  transcript.style.maxHeight = '20rem';
  transcript.style.overflowY = 'auto';
  app.appendChild(transcript);

  const form = document.createElement('form');
  const input = document.createElement('input');
  input.type = 'text';
  input.name = 'message';
  input.autocomplete = 'off';
  input.setAttribute('aria-label', 'Your message');
  input.style.width = '70%';
  const send = document.createElement('button');
  send.type = 'submit';
  send.textContent = 'Send';
  form.appendChild(input);
  form.appendChild(send);
  app.appendChild(form);

  // Only a standalone conversation is ended by the participant. A composed
  // activity ends when its rounds end, so leaving the conversation early would
  // leave them playing a game they can no longer talk about.
  const leave = document.createElement('button');
  leave.type = 'button';
  leave.textContent = 'End the conversation';
  leave.style.marginTop = '1rem';
  if (!composed) {
    app.appendChild(leave);
  }

  // One channel is shown at a time. A message that belongs to another channel is
  // held rather than dropped, so moving to it shows what was said there.
  const lines = new Map<string, HTMLElement[]>();
  let current: string | null = null;

  const show = (channel: string): void => {
    current = channel;
    transcript.innerHTML = '';
    for (const line of lines.get(channel) ?? []) {
      transcript.appendChild(line);
    }
    transcript.scrollTop = transcript.scrollHeight;
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
        tab.style.marginRight = '0.5rem';
        tab.addEventListener('click', () => show(key));
        tabs.appendChild(tab);
      }
      if (current !== null) {
        show(current);
      }
    },
    append(author, text, channel) {
      const key = channel ?? current ?? '';
      const line = document.createElement('p');
      line.dataset['author'] = author;
      line.dataset['channel'] = key;
      line.style.margin = '0.25rem 0';
      const who = document.createElement('strong');
      who.textContent = author === 'you' ? 'You: ' : 'Them: ';
      line.appendChild(who);
      line.append(text);
      const held = lines.get(key) ?? [];
      held.push(line);
      lines.set(key, held);
      if (current === null || key === current) {
        transcript.appendChild(line);
        transcript.scrollTop = transcript.scrollHeight;
      }
    },
    close() {
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
  const heading = document.createElement('h2');
  heading.textContent = delivery.ask;
  app.appendChild(heading);
  const waiting = document.createElement('p');
  waiting.dataset['testid'] = 'comparison-waiting';
  waiting.textContent = 'Loading what you are being asked about...';
  app.appendChild(waiting);

  const list = document.createElement('div');
  list.dataset['testid'] = 'comparison-options';
  // The options are a group and the question is its name, so a screen reader
  // announces what is being asked before it reads the first option.
  heading.id = 'comparison-ask';
  list.setAttribute('role', 'group');
  list.setAttribute('aria-labelledby', 'comparison-ask');

  const buttons = (): HTMLButtonElement[] =>
    Array.from(list.querySelectorAll('button'));

  return {
    present(options) {
      heading.textContent = options.ask;
      waiting.remove();
      list.innerHTML = '';
      for (const option of options.options) {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset['handle'] = option.handle;
        button.style.display = 'block';
        button.style.margin = '0.5rem 0';
        // An option shows what it recorded: a run shows how long it went and
        // what it earned, a model output shows the text it produced. Neither
        // says which condition it was, which is what the blinding is for.
        if (typeof option.text === 'string') {
          button.textContent = option.text;
          button.style.whiteSpace = 'pre-wrap';
          button.style.textAlign = 'left';
          button.style.maxWidth = '40rem';
        } else {
          const summary = option.summary ?? { frames: 0, reward: 0 };
          button.textContent =
            'Round ' + String(option.played ?? 0) + ' -- ' +
            String(summary.frames) + ' frames, score ' +
            String(summary.reward);
        }
        button.addEventListener('click', () => {
          this.close();
          onChoose(option.handle);
        });
        list.appendChild(button);
      }
      app.appendChild(list);
    },
    reopen() {
      for (const button of buttons()) {
        button.disabled = false;
      }
    },
    close() {
      for (const button of buttons()) {
        button.disabled = true;
      }
    },
  };
}

/** Render the completion screen: the code and the optional return link. */
export function renderComplete(app: HTMLElement, delivery: CompleteDelivery): void {
  app.innerHTML = '<h2>All done. Thank you.</h2>';
  if (delivery.completion_code) {
    const code = document.createElement('p');
    code.textContent = 'Completion code: ' + delivery.completion_code;
    app.appendChild(code);
  }
  if (delivery.return_url) {
    const link = document.createElement('a');
    link.href = delivery.return_url;
    link.textContent = 'Return to the study';
    app.appendChild(link);
  }
}
