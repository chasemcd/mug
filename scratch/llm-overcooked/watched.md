# What watching the study showed

The owner ran the talking-kitchen study and reported three things. All three
reproduce in a real browser (`scratch/llm-overcooked/look.py` style walk, 1440x900).

## 1. Round two draws only the chefs

Measured: round one paints **179,885** opaque pixels, round two **13,403** -- the
two chefs on an empty floor. No counters, no pots, no onion stack, no delivery
square.

Cause: `_Watcher` in `mug/participant.py` holds **one `Surface` for the whole
activity**, minted when the connection sits down. The surface is the delta
protocol's memory of what the client already holds. Round two's first frame is
therefore not a keyframe, so the terrain -- which is `persistent=True`, sent once
and then never again -- is never re-sent. But the client tore its renderer down at
the rest and built a new one, holding nothing.

So the two ends disagree about what the client has. The server is remembering a
canvas that no longer exists.

Fix: a watcher's surface belongs to the **episode**, not the connection. `draw`
resets it when the episode changes, so every round opens with a keyframe.

Why no test caught it: the whole-study browser walk asserts each round paints more
than 500 pixels. Two chefs are 13,403. **A threshold that asks "did anything
draw" cannot tell a kitchen from two chefs standing in an empty room.** The walk
now compares each round against the first.

## 2. The canvas is 600x400 inside a 976x790 pane

The client mounts a fixed 600x400 canvas whatever the study draws and whatever
space it has. Two consequences, both visible:

- the game pane is nearly twice the area of the game in it, with a large empty
  band under the kitchen.
- `cramped_room` is 5 columns by 4 rows drawn into 3:2, so every square is 120x100
  and every sprite is stretched by a fifth.

The surface commands are relative (0..1), so the drawing itself has no proportions
of its own: the shape of the picture is the **study's** to say. So `Game(aspect=)`,
defaulting to today's 3:2, and the client fits the largest box of that shape into
the space it has and refits on resize.

The renderer draws in a fixed logical space and the canvas backing store is set to
the real device pixels, so text and line widths scale with the picture instead of
shrinking as it grows, and the sprites stay crisp.

## 3. A message between rounds is never answered

The seats are fed the message (it reaches the next round's prompt), but nothing
answers it while no round is running, and the client had already drawn a "typing"
bubble. So the participant watches a partner think for the whole rest.

Fix: the table keeps the round that just ended, and a message that arrives between
rounds is answered by it -- one model call per model seat, the reply published to
the room. It is not a decision (no frame is stepped), so it records a model call
and a message and no decision.

And the bubble: a composed activity no longer draws one. A partner in a game is a
player, not an assistant -- it answers when it answers, and it is allowed to say
nothing. A conversation that is the whole activity keeps its bubble, because there
a reply is owed.

## 4. The pane head vanishes at the rest

`renderInterval` clears the game pane with `innerHTML = ""`, which takes the head
("The game" and the keyboard badge) with it. `clear()` exists and keeps the head;
the rest screen was the one place not using it.

## 5. Four more, found by running the suites over the fix

None of these were what the owner reported. All four were already broken and no
run had said so.

- `tests/e2e_native/test_examples_render_browser.py` mounted three of the five
  examples by compiling the activity and then **wrapping the result back into
  `Game(key, ...)`**, which throws the seating away. Those studies mounted nothing
  and the walk went straight from the first page to the last, having played
  nothing, then failed on a `countdown_seconds` that a seated specification does
  not have. `one_game_study` now uses an activity that is already written as one.
- the last of those (the input test) then found the kitchen moving with nobody at
  the keyboard: the status line says how long is left, so it changes every frame.
  The clock is taken off for that one test, which is the only one that reads
  "nothing moved" off the canvas.
- `ts/conformance/p2p.ts` and `p2p_fakes.ts` each wrote out the api-09 client
  bundle digest **again**, and the contract moved under them. Every vector then
  failed as "the schema is wrong" whatever it was really about. Both now read the
  client's own constant, so the copy cannot go stale again.
- `_what_the_partner_said` counted the bubbles and then read them one at a time,
  which reads a transcript that is being written to while it is read. It is one
  call now.

## What shipped

| Fault | Where |
| --- | --- |
| The surface belongs to the episode | `mug/participant.py` `_Watcher.drawn_on` |
| `Game(aspect=)` | `mug/content/study.py`, `mug/participant.py` `_aspect_at` |
| The drawing has its own units, and is fitted | `renderer.js` / `renderer.ts`, `main.js` / `client.ts` |
| A game screen is not a reading column | `app.css` `.sheet--game` |
| The resting round answers | `runtime.py` `answer`, `multiseat_episode.py` `answer`, `participant.py` `answered` / `answering` |
| No promise of a reply beside a game | `main.js` / `ui.ts` composer |
| The pane head survives the rest | `main.js` `renderInterval`, `ui.ts` `clearKeepingHead` |

## Still open

The sprites are drawn with smoothing on, so a kitchen fitted to 800 across is a
45-pixel sprite blurred over 160. Turning smoothing off would make it crisp pixel
art and would make a photographic asset look worse. It is a decision about what
the platform's drawing **is**, not a defect, so it is left for the owner.


## 6. Corrected after the owner watched it again

"The graphics are way too large. We want to keep the same size we were using for
the legacy code. It's also running incredibly slow now."

I had shipped `Game(aspect=)` and fitted the picture to the room it had, so the
kitchen came out 784 by 627 -- a 45-pixel sprite blown up over 157 pixels, and on a
retina screen a backing store of 1568 by 1254 to repaint thirty times a second.

The legacy sized it in **pixels**: `TILE_SIZE * cols` by `TILE_SIZE * rows`, which
is 225 by 180 for `cramped_room`. One sprite pixel, one screen pixel.

So it is `Game(size=(225, 180))` now. The picture is drawn at the size the study
says, and **smaller** in proportion when there is not room for it -- a narrow
window, a pane beside a conversation -- and never larger. `kitchen_size(layout)`
gives the cogrid studies theirs.

Two things that only showed at the smaller size:

- **the status line ran off the edge.** The legacy drew it in an HTML bar above the
  canvas with no bound; the platform draws it on the game's own surface, so it is
  in the record and in a replay -- and so it has to fit. The renderer shrinks a
  line to what is left of the picture and never grows it, because only the renderer
  can measure a string.
- **the wait after continue.** Measured, the blitting was 5 ms in 5 seconds either
  way, so the size was not the whole of "slow". What a participant feels is the
  next round waiting on a resting model call: I had made it wait so a turn could
  not publish into the round that replaced it, but publishing goes to the **room**,
  which belongs to the activity. So it does not wait, and a late answer is a late
  message.
