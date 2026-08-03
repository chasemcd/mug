"""Walk a whole study in a real browser, the way a participant walks it.

Every other browser test here plays **one activity**: a study of one page, one
shortened game, and one page. That proves the renderer and proves nothing about a
study. A shipped study is a consent form, instructions, a game at its own speed,
rounds with a rest between them, a survey, and a debrief -- and the faults that
matter live in the joins: a form that will not submit, a round that never advances
to the next, a survey delivered before the game finished, a canvas that painted the
first round and not the second.

So this drives a study **as it ships**, with nothing shortened and nothing replaced,
and reports what the participant met on the way. Each activity is answered by what
it is, which is how a participant answers it:

- a **form** gets every required field filled and is submitted;
- a **page** is read and continued past;
- a **game** is played, with the canvas read while it runs, until it hands over.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from example_server import ink
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

# How long one activity may take before the walk gives up on it. A round of a real
# study is measured in tens of seconds, so this is generous on purpose: a test that
# timed out at the shipped length would only be provable by shortening the study,
# which is the thing being avoided.
ACTIVITY_TIMEOUT_MS = 120_000

# How often the canvas is read while a game runs. It is read throughout rather than
# twice, because a game that painted once and stopped and a game that kept moving
# are the same picture at the start.
LOOK_EVERY_MS = 150


@dataclass
class Played:
    """What one game activity looked like while it was on the screen."""

    key: str
    readings: int = 0
    first_painted: int = 0
    most_painted: int = 0
    pictures: int = 0
    # How much of the canvas was painted, at the most. It is a **fraction**, so it
    # says the same thing about a picture whatever size the canvas is -- and a
    # count of painted pixels does not. A round drawn with everything that is
    # drawn once held back covers a fraction of what the round before it covered,
    # and still beats any threshold set for "did anything draw at all".
    covered: float = 0.0
    # What the participant wrote to their partner while they played, and what came
    # back. A composed activity is a game **and** a conversation, so a walk that
    # only read the canvas would say nothing about half of it.
    said: list[str] = field(default_factory=list)
    heard: list[str] = field(default_factory=list)

    @property
    def moved(self) -> bool:
        """Say whether the picture changed while the participant watched it."""
        return self.pictures > 1


@dataclass
class Walked:
    """What one participant met on the way through a study."""

    finished: bool = False
    activities: list[str] = field(default_factory=list)
    games: list[Played] = field(default_factory=list)
    forms: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    rests: list[str] = field(default_factory=list)

    def game(self, key: str) -> Played:
        """Return what one game activity showed, by its key."""
        found = [one for one in self.games if one.key == key]
        assert found, f"no game activity {key!r} was played; met {self.activities}"
        return found[0]


def walk_the_whole_study(
    page: Page, address: str, *, screens: int = 40, say: Sequence[str] = ()
) -> Walked:
    """Open a study and answer every activity until the participant is finished.

    ``screens`` bounds the walk so a study that loops forever fails here rather than
    hanging. It is a backstop, not a length: the walk ends when the study does.

    ``say`` is what the participant writes to their partner, one line per round of a
    game that carries a conversation. A study with no conversation ignores it.
    """
    page.goto(address)
    page.wait_for_selector("text=connected", timeout=15_000)
    walked = Walked()
    lines = list(say)
    for _ in range(screens):
        met = _one_screen(page, walked, lines)
        if met is None:
            break
    walked.finished = bool(page.locator(".done").count())
    return walked


def _one_screen(page: Page, walked: Walked, say: list[str]) -> str | None:
    """Answer whichever activity is on the screen, and return what it was."""
    kind = _what_is_showing(page)
    if kind is None:
        return None
    walked.activities.append(kind)
    if kind == "game":
        walked.games.append(_play_the_game(page, say.pop(0) if say else None))
    elif kind == "form":
        walked.forms.append(_answer_the_form(page))
    elif kind == "interval":
        walked.rests.append(_take_the_rest(page))
    else:
        walked.pages.append(_read_the_page(page))
    return kind


def _what_is_showing(page: Page) -> str | None:
    """Return which kind of activity is on the screen, or nothing when it is over.

    The end of a study is a **screen**, not the absence of one: the client shows a
    completion panel with the participant's code on it. So it is recognised rather
    than waited out, which is the difference between a walk that ends when the study
    does and one that always pays the timeout. A study that ends any other way still
    ends the walk, after the timeout, and the activities met say where it stopped.
    """
    for _ in range(int(ACTIVITY_TIMEOUT_MS / 200)):
        showing = _showing(page)
        if showing is not None:
            return showing
        if page.locator(".done").count():
            return None
        page.wait_for_timeout(200)
    return None


def _read_the_page(page: Page) -> str:
    """Read what a content page says, then continue past it."""
    said = page.locator("[data-testid='content-page']").inner_text()
    page.get_by_role("button", name="Continue").click()
    _wait_for_the_screen_to_change(page, "page")
    return said.strip().splitlines()[0] if said.strip() else ""


def _take_the_rest(page: Page) -> str:
    """Read the rest between two rounds, then ask for the next one.

    It is answered exactly as a participant answers it. The server is holding the
    next round open, so nothing happens at all until this is clicked -- which is why
    a walk that treated it as an ordinary page waited for a round that never came.
    """
    said = page.locator("[data-testid='between-rounds']").inner_text()
    page.get_by_role("button", name="Continue").click()
    _wait_for_the_screen_to_change(page, "interval")
    return said.strip().splitlines()[0] if said.strip() else ""


def _answer_the_form(page: Page) -> str:
    """Fill in every field a form asks for, then submit it.

    A required radio group gets its **first** option and a scale its lowest cell.
    Which answer is given does not matter; that the platform accepted a real one,
    recorded it, and moved on does. An optional text field is left empty on purpose,
    because a study that refused to advance without an optional answer is a study
    nobody could finish.
    """
    form = page.locator("form:not(.composer)").first
    heading = page.locator("h1, h2").first.inner_text()
    for group in form.locator("fieldset").all():
        # The **label** is clicked, not the input inside it. That is what a
        # participant does, and the client wraps each input in its own label on
        # purpose, so the text is part of the hit area.
        options = group.locator("label")
        if options.count():
            options.first.click()
    for text in form.locator("input[type=text]").all():
        if text.get_attribute("required") is not None:
            text.fill("written by a test")
    form.get_by_role("button", name="Continue").click()
    _wait_for_the_screen_to_change(page, "form")
    return heading.strip()


def _play_the_game(page: Page, say: str | None = None) -> Played:
    """Play one game to its end, reading the canvas for as long as it is up.

    Keys are pressed throughout. A study whose environment only moves when somebody
    plays would otherwise be watched standing still, and the one trajectory where a
    contention fault is invisible is the one nobody touched.
    """
    key = _the_activity_key(page)
    played = Played(key=key)
    canvas = page.locator("canvas")
    canvas.focus()
    pictures: set[int] = set()
    spoke = False
    for turn in range(int(ACTIVITY_TIMEOUT_MS / LOOK_EVERY_MS)):
        # Read while the round is **on**. Reading after it would read a screen the
        # activity has already handed over -- the panes are gone by then, and the
        # walk would report a partner that said nothing.
        played.heard = _what_the_partner_said(page) or played.heard
        if say is not None and not spoke and turn > 2:
            # Said a moment in rather than at once, so the round is really under
            # way: a message that arrived before the first frame would prove
            # nothing about talking **while** playing.
            spoke = _say_to_the_partner(page, say, played)
        read = ink(page)
        if read is None:
            break
        if read["painted"]:
            played.readings += 1
            if not played.first_painted:
                played.first_painted = read["painted"]
            played.most_painted = max(played.most_painted, read["painted"])
            if read.get("pixels"):
                played.covered = max(
                    played.covered, read["painted"] / read["pixels"]
                )
            pictures.add(read["signature"])
        _press(page, turn)
        page.wait_for_timeout(LOOK_EVERY_MS)
    played.pictures = len(pictures)
    return played


def _say_to_the_partner(page: Page, said: str, played: Played) -> bool:
    """Write one message to the partner, without stopping playing.

    It answers whether it wrote, so a round with no conversation beside it is not
    retried on every frame. Focus is given back to the canvas afterwards: the two
    panes share one keyboard, and a walk that left it in the message box would play
    the rest of the round pressing arrow keys into a text field.
    """
    box = page.get_by_label("Your message")
    if not box.count():
        return True
    box.fill(said)
    page.keyboard.press("Enter")
    played.said.append(said)
    page.locator("canvas").focus()
    return True


def _what_the_partner_said(page: Page) -> list[str]:
    """Return every message the participant was shown that they did not write.

    It is read in **one** call. Counting the bubbles and then reading them one at a
    time reads a transcript that is being written to while it is read: a message
    that arrives between the count and the read moves the rest, and the reader waits
    on an element that is no longer there.
    """
    read = page.evaluate(
        "() => [...document.querySelectorAll('[data-author=them] .bubble')]"
        ".map((one) => one.innerText.trim())"
    )
    return [str(one) for one in read]


# The keys a participant presses. They are the four arrows and the two the kitchen
# uses, pressed in turn: what a study binds is its own business, and an unbound key
# is read as no key rather than refused.
_KEYS = ("ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown", "w", "q")


def _press(page: Page, turn: int) -> None:
    """Hold one key for a moment, as somebody playing would."""
    key = _KEYS[turn % len(_KEYS)]
    try:
        page.keyboard.down(key)
        page.wait_for_timeout(40)
        page.keyboard.up(key)
    except PlaywrightTimeout:  # pragma: no cover - the game ended mid-press
        return


def _the_activity_key(page: Page) -> str:
    """Return the activity key the client is showing, for the report."""
    read = page.evaluate(
        "() => document.querySelector('[data-activity]')?.dataset.activity ?? ''"
    )
    return str(read or "game")


def _wait_for_the_screen_to_change(page: Page, was: str) -> None:
    """Wait until the screen is no longer the activity just answered."""
    for _ in range(int(ACTIVITY_TIMEOUT_MS / 100)):
        if _showing(page) != was or page.locator(".done").count():
            return
        page.wait_for_timeout(100)


def _showing(page: Page) -> str | None:
    """Return what is on the screen right now, without waiting for it.

    The order is the whole of this function, and two of the four places it could be
    got wrong have been:

    - the rest between two rounds is asked about **before** a content page, because
      it is a page with a continue button on it too. It is its own kind because it
      is its own thing: the server holds the next round until the participant says
      to go on, so a walk that did not answer it would wait for a round that was
      never coming.
    - a form is asked about **last of the real ones**, and the conversation's own
      message box is not one. A composed activity carries a chat pane whose
      composer is a ``<form>``, and it stays on the screen through the rest between
      rounds -- because a rest from the game is not a rest from the person you are
      playing with. A walk that counted any form as a survey read that composer as
      one, went looking for a Continue button inside it, and reported a study that
      hangs after its first round. The study was fine.
    """
    if page.locator("[data-testid='between-rounds']").count():
        return "interval"
    if page.locator("canvas").count():
        return "game"
    if page.locator("form:not(.composer)").count():
        return "form"
    if page.get_by_role("button", name="Continue").count():
        return "page"
    return None


def recorded(store: Any) -> dict[str, int]:
    """Return how many of each kind of record the walk left behind.

    A study that drew a picture and recorded nothing has not run, so what the walk
    proves is checked against the store rather than against the screen alone.
    """
    counts: dict[str, int] = {}
    for aggregate_id, _ in store.scan_aggregates():
        kind = str(aggregate_id).split("_", 1)[0]
        counts[kind] = counts.get(kind, 0) + 1
    return counts


__all__ = ["Played", "Walked", "recorded", "walk_the_whole_study"]
