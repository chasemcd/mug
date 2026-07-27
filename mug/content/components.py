"""The shipped screens, and the accessibility each one actually delivers.

``docs/architecture/quality-attributes.md`` requires that core navigation, forms,
preference controls, replay controls, and chat support keyboard-only and
screen-reader use. ``AccessibilityProfile`` and ``PresentationComponent`` are the
frozen records that say which screen delivers what, and
``ClientManifest.accessibility_profile`` requires a profile key. Nothing declared
either, so the requirement had no place to be true or false.

This module is the declaration, and it is written to be *checkable* rather than
aspirational. Two profiles, and the difference between them is the point:

- **``wcag-aa``** -- keyboard navigable and screen-reader usable. Every screen the
  platform renders as HTML claims it: forms, content, the comparison, and chat. The
  frozen record refuses an ``aa`` profile that does not meet both, so claiming it is
  a commitment the clients are tested against.
- **``wcag-a``** -- keyboard navigable, and **not** screen-reader usable. The game
  canvas claims this one. A canvas is pixels: a screen reader has nothing to read in
  it, and no amount of labelling changes that. A study whose environment must be
  usable without sight needs a text view of its own, which is the study's to write
  and not something this platform can claim on its behalf.

A study's manifest carries the **floor** of the components it uses, not the best of
them. A study with a game is a ``wcag-a`` study however accessible its consent form
is, because a participant who cannot use the game cannot finish it. Reporting the
best would turn the manifest into marketing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from mug.client.types import client_schema
from mug.content.types import (
    AccessibilityProfile,
    GateAnchor,
    GateControl,
    PresentationComponent,
    content_schema,
)
from mug.kernel import Digest, SchemaRef

# The profile keys, ordered from least to most capable. A study reports the floor of
# what it uses, so the order is what makes "floor" mean something.
PROFILE_ORDER: Final[tuple[str, ...]] = ("wcag-a", "wcag-aa", "wcag-aaa")


def _schema(name: str) -> SchemaRef:
    """Return the pinned reference to one API-17 record's frozen schema."""
    return SchemaRef(
        name=name,
        version=0,
        digest=Digest(algorithm="sha-256", hex=content_schema().bundle_digest),
    )


def accessibility_profiles() -> list[AccessibilityProfile]:
    """Return the profiles this platform's own clients are built to.

    ``wcag-aaa`` is not declared, because nothing here delivers it and a profile
    nobody meets is a claim rather than a record.
    """
    return [
        AccessibilityProfile(
            profile_key="wcag-aa",
            wcag_level="aa",
            keyboard_navigable=True,
            screen_reader=True,
        ),
        AccessibilityProfile(
            profile_key="wcag-a",
            wcag_level="a",
            keyboard_navigable=True,
            screen_reader=False,
        ),
    ]


# Which profile each shipped screen delivers. The game is the one exception and the
# reason is structural, not an omission: see the module docstring.
_COMPONENT_PROFILE: Final[dict[str, str]] = {
    "form": "wcag-aa",
    "content": "wcag-aa",
    "comparison": "wcag-aa",
    "chat": "wcag-aa",
    "game": "wcag-a",
    # A game and a conversation on one screen. It delivers the floor of the two,
    # not the better of them: the conversation is screen-reader usable and the
    # canvas beside it is not, and a participant who cannot use the canvas cannot
    # finish the activity. Its keyboard rule is its own -- Tab cycles the panes,
    # Escape returns to the game -- which is why it is a component and not a reuse
    # of the game's.
    "game-chat": "wcag-a",
}


def presentation_components() -> list[PresentationComponent]:
    """Return every screen this platform ships, bound to the profile it delivers."""
    return [
        PresentationComponent(
            component_key=key,
            component_schema=_schema("mug.api-17.presentation-component"),
            accessibility_profile=profile,
        )
        for key, profile in sorted(_COMPONENT_PROFILE.items())
    ]


def gate_controls() -> list[GateControl]:
    """Return the readiness gates this platform's clients surface.

    One gate is shipped: the block a screening study raises when a participant is
    excluded in play (``mug.interactions.monitoring``). It anchors the flow node the
    participant was at, because what is blocked is advancing past it, and it names
    the API-09 op it emits, so the screen a participant sees and the record the
    server writes are the same event described from two sides.
    """
    return [
        GateControl(
            component_key="screening-gate",
            gate_target="advance",
            gate_action="block",
            anchor=GateAnchor(anchor_kind="flow_node", anchor_key="activity"),
            gate_op=SchemaRef(
                name="mug.api-09.gate-op",
                version=0,
                digest=Digest(
                    algorithm="sha-256", hex=client_schema().bundle_digest
                ),
            ),
            accessibility_profile="wcag-aa",
        )
    ]


def component_for(activity_kind: str) -> PresentationComponent:
    """Return the shipped component one activity kind is rendered by."""
    by_key = {one.component_key: one for one in presentation_components()}
    return by_key[activity_kind]


def profile_floor(activity_kinds: Sequence[str]) -> str:
    """Return the least capable profile among the screens a study uses.

    A study is only as usable as its least usable screen, so this reports that one.
    An empty study reports the best profile, which is vacuously true and never
    reached: a study needs at least one activity.
    """
    used = [_COMPONENT_PROFILE[kind] for kind in activity_kinds]
    if not used:
        return PROFILE_ORDER[-1]
    return min(used, key=PROFILE_ORDER.index)


__all__ = [
    "PROFILE_ORDER",
    "accessibility_profiles",
    "component_for",
    "gate_controls",
    "presentation_components",
    "profile_floor",
]
