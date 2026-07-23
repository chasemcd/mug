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

/** A game activity, on the server loop or in the browser through Pyodide. */
export interface GameDelivery {
  kind: 'game';
  activity_key: string;
  mode: 'server' | 'browser';
  countdown?: number;
  manifest?: BrowserManifest;
}

/** A background announcement to preload the browser runtime during the forms. */
export interface PreloadDelivery {
  kind: 'preload';
  manifest: BrowserManifest;
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
  | CompleteDelivery;

/** The collected form answers, keyed by field. */
export type Answers = { [field: string]: string | number };

function addRadio(form: HTMLFormElement, name: string, value: string): void {
  const wrap = document.createElement('label');
  wrap.style.marginRight = '1rem';
  const input = document.createElement('input');
  input.type = 'radio';
  input.name = name;
  input.value = value;
  wrap.appendChild(input);
  wrap.append(' ' + value);
  form.appendChild(wrap);
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
    const label = document.createElement('label');
    label.textContent = field.label;
    label.style.display = 'block';
    label.style.margin = '0.75rem 0 0.25rem';
    form.appendChild(label);

    if (field.kind === 'choice') {
      for (const option of field.options ?? []) {
        addRadio(form, field.field_key, option);
      }
    } else if (field.kind === 'likert') {
      for (let n = 1; n <= (field.scale ?? 0); n++) {
        addRadio(form, field.field_key, String(n));
      }
    } else {
      const input = document.createElement('input');
      input.type = 'text';
      input.name = field.field_key;
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
  app.appendChild(pre);
  const next = document.createElement('button');
  next.textContent = 'Continue';
  next.addEventListener('click', () => onAdvance({}));
  app.appendChild(next);
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
