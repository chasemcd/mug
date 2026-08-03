/**
 * Written material, turned into a page a participant can read.
 *
 * A study writes its instructions, its debrief, and the caption beside its game
 * as markdown. This turns that into elements. It is the twin of
 * `mug/webclient/markdown.js`: both clients show a participant the same page, so
 * both read the same written material the same way.
 *
 * Two rules shape what is supported.
 *
 * **A picture is named, never fetched.** An image is written `![alt](name)`,
 * where `name` is an asset the study declared. The name is resolved against the
 * declared collection, exactly as the renderer resolves a sprite. A name nobody
 * declared draws nothing. Nothing here builds an address, so a study cannot -- by
 * writing a page -- make a participant's browser fetch from anywhere else.
 *
 * **Nothing is executed.** Every element is built by hand and every string goes
 * in as text, so a page is written material and never markup. There is no
 * `innerHTML` in this file, which is what makes that true rather than intended.
 */

/** Where a declared picture is served, by the name the study gave it. */
export interface PictureAddresses {
  url(name: string): string | null;
}

const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^\s*[-*]\s+(.*)$/;
const NUMBERED = /^\s*(\d+)[.)]\s+(.*)$/;
const IMAGE = /!\[([^\]]*)\]\(([^)]+)\)/;
const EMPHASIS = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/;

// A picture may name its own size: `![alt](name =64x64)`. It is the one thing a
// page must be able to say about a picture, because the same sprite serves a
// line-height icon in a sentence and a labelled figure in a legend.
const SIZED = /^(.*?)\s+=(\d+)?x(\d+)?$/;

/** Render markdown into `host`, resolving each picture through `assets`. */
export function renderMarkdown(
  host: HTMLElement,
  text: string,
  assets: PictureAddresses | null = null,
): HTMLElement {
  const lines = String(text ?? '').split('\n');
  let list: HTMLElement | null = null;
  let paragraph: string[] = [];

  const endParagraph = (): void => {
    if (paragraph.length === 0) {
      return;
    }
    const element = document.createElement('p');
    inline(element, paragraph.join(' '), assets);
    host.appendChild(element);
    paragraph = [];
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.trim() === '') {
      endParagraph();
      list = null;
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading !== null) {
      endParagraph();
      list = null;
      const element = document.createElement('h' + String(heading[1]?.length ?? 1));
      inline(element, heading[2] ?? '', assets);
      host.appendChild(element);
      continue;
    }

    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (bullet !== null || numbered !== null) {
      endParagraph();
      const wanted = bullet !== null ? 'ul' : 'ol';
      if (list === null || list.tagName.toLowerCase() !== wanted) {
        list = document.createElement(wanted);
        host.appendChild(list);
      }
      const item = document.createElement('li');
      inline(item, (bullet !== null ? bullet[1] : numbered?.[2]) ?? '', assets);
      list.appendChild(item);
      continue;
    }

    list = null;
    paragraph.push(line.trim());
  }
  endParagraph();
  return host;
}

// One line of text: pictures first, because a picture is the only thing here
// that is not text, and then the emphasis inside what is left.
function inline(
  parent: HTMLElement,
  text: string,
  assets: PictureAddresses | null,
): void {
  let rest = String(text);
  for (;;) {
    const found = IMAGE.exec(rest);
    if (found === null) {
      break;
    }
    emphasise(parent, rest.slice(0, found.index));
    parent.appendChild(picture(found[1] ?? '', found[2] ?? '', assets));
    rest = rest.slice(found.index + found[0].length);
  }
  emphasise(parent, rest);
}

function emphasise(parent: HTMLElement, text: string): void {
  let rest = String(text);
  for (;;) {
    const found = EMPHASIS.exec(rest);
    if (found === null) {
      break;
    }
    if (found.index > 0) {
      parent.append(rest.slice(0, found.index));
    }
    const run = found[1] ?? '';
    const tag = run.startsWith('**') ? 'strong' : run.startsWith('`') ? 'code' : 'em';
    const element = document.createElement(tag);
    element.textContent = run.replace(/^(\*\*|\*|`)|(\*\*|\*|`)$/g, '');
    parent.appendChild(element);
    rest = rest.slice(found.index + run.length);
  }
  if (rest !== '') {
    parent.append(rest);
  }
}

// A declared picture, by the name the study gave it. A name the study did not
// declare leaves the alternative text, so a participant reads what the picture
// was going to say rather than meeting a broken image.
function picture(
  alt: string,
  target: string,
  assets: PictureAddresses | null,
): HTMLElement {
  const sized = SIZED.exec(target);
  const name = (sized !== null ? (sized[1] ?? '') : target).trim();
  const url = assets === null ? null : assets.url(name);
  if (url === null) {
    const missing = document.createElement('span');
    missing.dataset['missingAsset'] = name;
    missing.textContent = alt;
    return missing;
  }
  const image = document.createElement('img');
  image.src = url;
  image.alt = alt;
  image.dataset['asset'] = name;
  image.style.verticalAlign = 'middle';
  image.style.margin = '0 0.25rem';
  image.style.maxWidth = '100%';
  if (sized !== null && sized[2] !== undefined) {
    image.width = Number(sized[2]);
  }
  if (sized !== null && sized[3] !== undefined) {
    image.height = Number(sized[3]);
  } else {
    image.style.height = 'auto';
  }
  return image;
}
