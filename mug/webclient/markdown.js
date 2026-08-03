// Written material, turned into a page a participant can read.
//
// A study writes its instructions, its debrief, and the caption beside its game
// as markdown. This turns that into elements. It exists because the client used
// to put the text in a <pre>: an instruction page that said "**W** picks up" was
// shown with the stars in it, and a page that wanted to show the participant
// which chef was theirs could not.
//
// Two rules shape what is supported.
//
// **A picture is named, never fetched.** An image is written `![alt](name)`,
// where `name` is an asset the study declared. The name is resolved against the
// declared collection, exactly as the renderer resolves a sprite. A name nobody
// declared draws nothing. Nothing here builds a URL, so a study cannot -- by
// writing a page -- make a participant's browser fetch from anywhere else.
//
// **Nothing is executed.** Every element is built by hand and every string goes
// in as text, so a page is written material and never markup. There is no
// innerHTML in this file, which is what makes that true rather than intended.

const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^\s*[-*]\s+(.*)$/;
const NUMBERED = /^\s*(\d+)[.)]\s+(.*)$/;
const IMAGE = /!\[([^\]]*)\]\(([^)]+)\)/;
// A run of `**bold**`, `*italic*`, or `` `code` ``, whichever starts first.
const EMPHASIS = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/;

// How wide a picture is drawn unless the study says. A key or a chef is a small
// thing beside a line of text, and a page of instructions that opened with a
// full-width chef would say the chef was the subject.
const IMAGE_HEIGHT = "auto";

// A picture may name its own size: `![alt](name =64x64)`. It is the one thing a
// page must be able to say about a picture, because the same sprite sheet serves
// a 16-pixel tile and a 130-pixel diagram of the arrow keys.
const SIZED = /^(.*?)\s+=(\d+)?x(\d+)?$/;

/**
 * Render markdown into `host`, resolving each picture through `assets`.
 *
 * `assets.url(name)` answers the address a declared picture is served at, or
 * null. Passing no asset table shows a page with no pictures in it, which is
 * what a study with no declared assets has.
 */
export function renderMarkdown(host, text, assets = null) {
  const lines = String(text ?? "").split("\n");
  let list = null;
  let paragraph = [];

  const endParagraph = () => {
    if (paragraph.length === 0) return;
    const element = document.createElement("p");
    inline(element, paragraph.join(" "), assets);
    host.appendChild(element);
    paragraph = [];
  };
  const endList = () => {
    list = null;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.trim() === "") {
      endParagraph();
      endList();
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      endParagraph();
      endList();
      const element = document.createElement(`h${heading[1].length}`);
      inline(element, heading[2], assets);
      host.appendChild(element);
      continue;
    }

    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (bullet || numbered) {
      endParagraph();
      const wanted = bullet ? "ul" : "ol";
      if (list === null || list.tagName.toLowerCase() !== wanted) {
        list = document.createElement(wanted);
        host.appendChild(list);
      }
      const item = document.createElement("li");
      inline(item, (bullet ? bullet[1] : numbered[2]), assets);
      list.appendChild(item);
      continue;
    }

    endList();
    paragraph.push(line.trim());
  }
  endParagraph();
  return host;
}

// One line of text: pictures first, because a picture is the only thing here that
// is not text, and then the emphasis inside what is left.
function inline(parent, text, assets) {
  let rest = String(text);
  for (;;) {
    const found = IMAGE.exec(rest);
    if (!found) break;
    emphasise(parent, rest.slice(0, found.index));
    parent.appendChild(picture(found[1], found[2], assets));
    rest = rest.slice(found.index + found[0].length);
  }
  emphasise(parent, rest);
}

function emphasise(parent, text) {
  let rest = String(text);
  for (;;) {
    const found = EMPHASIS.exec(rest);
    if (!found) break;
    if (found.index > 0) parent.append(rest.slice(0, found.index));
    const run = found[1];
    const element = document.createElement(
      run.startsWith("**") ? "strong" : run.startsWith("`") ? "code" : "em",
    );
    element.textContent = run.replace(/^(\*\*|\*|`)|(\*\*|\*|`)$/g, "");
    parent.appendChild(element);
    rest = rest.slice(found.index + run.length);
  }
  if (rest) parent.append(rest);
}

// A declared picture, by the name the study gave it. A name the study did not
// declare leaves the alternative text, so a participant reads what the picture
// was going to say rather than meeting a broken image.
function picture(alt, target, assets) {
  const sized = SIZED.exec(target);
  const name = (sized ? sized[1] : target).trim();
  const url = assets && typeof assets.url === "function" ? assets.url(name) : null;
  if (!url) {
    const missing = document.createElement("span");
    missing.dataset.missingAsset = name;
    missing.textContent = alt;
    return missing;
  }
  const image = document.createElement("img");
  image.src = url;
  image.alt = alt;
  image.dataset.asset = name;
  image.style.verticalAlign = "middle";
  image.style.margin = "0 0.25rem";
  image.style.maxWidth = "100%";
  if (sized && sized[2]) image.width = Number(sized[2]);
  if (sized && sized[3]) image.height = Number(sized[3]);
  else image.style.height = IMAGE_HEIGHT;
  return image;
}
