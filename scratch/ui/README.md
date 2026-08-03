# The participant interface -- mock-ups

Static pages that propose a look for the participant client. **Nothing here is
wired into the platform.** No file in `mug/` or `ts/` reads them, and no test
covers them. They are made to be argued with, and then thrown away or built.

There are four passes. **`v4/` is the current one, and it is the only complete
set -- start at `v4/index.html`.**

- **This directory is the first pass, and it is the generic one.** Rounded
  panels, soft shadows, one teal accent, and a rectangle that lights up under
  the pointer. It is kept because the layouts and the two findings below are
  still right.
- **`v2/` is the second pass**: two committed directions, `Transcript` and
  `Instrument`, with no card, no shadow, no radius, and nothing that fills under
  the pointer. It went too far: a page of ruled text, where an action was a word
  with a line under it and a participant had to read the screen to find what was
  clickable.
- **`v3/` is between the two.** The bubble, the card, and the filled button come
  back from the first pass. Charter for what somebody said, one accent for
  actions only, no shadow anywhere, and no hover fill come from the second. A
  pointer darkens an edge that is already drawn; it never puts a fill on a shape
  that had none. It covers four screens, not all of them.
- **`v4/` is v3 with an identity, a stronger hand on the judgements, and every
  screen back.** The notch (one square corner on every surface that holds
  something somebody said or made), two faces, and one blue with one amber. A
  judgement is numbered 1 read, 2 compare, 3 choose; a scale is anchored by the
  same badges as the options and writes back in words what was answered.

These documents use ASD-STE100 Simplified Technical English.

## Look at them

Open `index.html`. A file is enough -- there is no build step and no server.

```bash
xdg-open scratch/ui/index.html
```

Each page has switches along the top that are **not part of the design**: light
and dark, the two readings of a thread, which pane holds the keys, and which
screen of the study to show.

## What is here

| File | What it shows |
| --- | --- |
| `index.html` | The contact sheet, the three rules, and what is different from today |
| `01-chat.html` | One conversation: the thread, the wait for a reply, a reply that does not come |
| `02-inline-preference.html` | Two replies were written, and the one that is chosen is the one the conversation goes on with |
| `03-comparison.html` | The comparison activity, for two rounds that were played and for two things that were written |
| `04-study-shell.html` | Instructions, a form, and the last screen |
| `05-game-and-chat.html` | A game and a conversation in two panes |
| `06-shared-room.html` | Several people in one conversation, with channels |
| `mug-ui.css` | The tokens and the components. One file, and it is the proposal |

## The three rules the design keeps

1. **The screen never says whether the other party is a person or a model.**
   Only the study knows that, and only the study may say it. So there is no
   robot icon, no "Assistant", and no brand mark on a reply.
2. **Two things a participant compares must look the same.** The cards are one
   grid with one track rule, and no rule anywhere styles "the first one". A card
   that is wider or brighter is a measurement error, not a style choice.
3. **Every control keeps a visible focus ring.** A game pane and a chat pane are
   changed with the Tab key, so a participant who can not see the focus can not
   play.

## Two things the mock-ups found

- **An axis is a slider that starts in the middle.** It draws a filled bar to
  one side before anybody touches it, so it reads as a small preference for the
  left thing. Worse, a participant who never touches it still sends the middle
  value, and the study records a tie that nobody gave. The mock-ups use a row of
  marks with nothing chosen.
- **Everybody who is not you is "Them", in a room of four as well.** The server
  already sends `author_actor_id` on every message (`mug/participant_chat.py`,
  `_send_chat`); the client reads `author` and throws the identity away. The
  mock-ups give each other party a name and a colour, which says nothing about
  whether the party is a person or a model.

Neither is fixed in the platform. They are findings, not changes.
