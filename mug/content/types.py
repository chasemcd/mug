"""The objects that API-17 owns: content, forms, presentation, and gating.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``content_schema`` loads it for the conformance test.

This family models authored content bodies, form specifications and responses,
shipped presentation components, and the readiness gate control (RP-8). It adds
no runtime; it mints no identity and drives no gate. The gate control only pins
the inert API-09 gate-op bundle that it emits.

These invariants are not expressible in JSON Schema and live here as validators:

- a content body agrees with its source, origin, format, and executable flags;
- a content spec carries an authored body only;
- a form field lists options only for a choice and a scale for a likert;
- a form spec names each field once;
- an aa or aaa profile is keyboard navigable and screen-reader ready;
- a gate control anchors advance to a flow node and join to an interaction.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    Digest,
    SchemaBundle,
    SchemaRef,
    UtcInstant,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import ActivityOccurrenceId, VisitId
from mug.kernel.refs import PositiveSafeInteger

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-17/schemas/v0/content.schema.json"
)


@lru_cache(maxsize=1)
def content_schema() -> SchemaBundle:
    """Return the loaded API-17 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=content_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]
_RepoRelativePath = Annotated[
    str,
    Field(pattern=r"^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*$", max_length=512),
]


class ContentBody(KernelModel):
    """The body of a content item: where it comes from and how it renders."""

    origin: Literal["author", "model", "participant"]
    source: Literal["file", "inline"]
    format: Literal["markdown", "html"]
    executable: bool
    path: _RepoRelativePath | None = None
    text: Annotated[str, Field(max_length=262144)] | None = None
    digest: Digest | None = None

    @model_validator(mode="after")
    def _source_and_safety_agree(self) -> ContentBody:
        if self.source == "file":
            if self.path is None or self.digest is None:
                raise ValueError("a file body must name a path and a digest")
        else:
            if self.text is None:
                raise ValueError("an inline body must carry text")
            if self.path is not None:
                raise ValueError("an inline body must not name a path")
        if self.executable and (self.origin != "author" or self.format != "html"):
            raise ValueError("an executable body must be authored html")
        if self.format == "markdown" and self.executable:
            raise ValueError("a markdown body must not be executable")
        if self.origin != "author" and (self.executable or self.source != "inline"):
            raise ValueError("a non-author body must be inert and inline")
        return self


class ContentSpec(KernelModel):
    """One authored content item, keyed and versioned, with a response flag."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-17.content-spec")
    )
    content_key: _AuthoringKey
    body: ContentBody
    response_required: bool
    version: PositiveSafeInteger

    @model_validator(mode="after")
    def _body_is_authored(self) -> ContentSpec:
        if self.body.origin != "author":
            raise ValueError("a content spec must carry an authored body")
        return self


class FormField(KernelModel):
    """One field in a form: its kind, label, and kind-specific constraints."""

    field_key: _AuthoringKey
    kind: Literal["likert", "choice", "text", "number", "slider", "rating"]
    label: Annotated[str, Field(min_length=1, max_length=1024)]
    required: bool
    options: (
        Annotated[
            list[Annotated[str, Field(min_length=1, max_length=256)]],
            Field(min_length=2, max_length=64),
        ]
        | None
    ) = None
    scale: Annotated[int, Field(ge=2, le=100)] | None = None

    @model_validator(mode="after")
    def _kind_constraints_hold(self) -> FormField:
        if self.kind == "choice":
            if self.options is None:
                raise ValueError("a choice field must list options")
        elif self.options is not None:
            raise ValueError("only a choice field may list options")
        if self.kind == "likert" and self.scale is None:
            raise ValueError("a likert field must name a scale")
        return self


class FormSpec(KernelModel):
    """One form, keyed and versioned, that lists its fields in order."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-17.form-spec")
    )
    form_key: _AuthoringKey
    fields: Annotated[list[FormField], Field(min_length=1, max_length=256)]
    version: PositiveSafeInteger

    @model_validator(mode="after")
    def _field_keys_are_unique(self) -> FormSpec:
        seen: set[str] = set()
        for field in self.fields:
            if field.field_key in seen:
                raise ValueError("a form must name each field once")
            seen.add(field.field_key)
        return self


class FormResponse(KernelModel):
    """One submitted form response, joinable to its visit and occurrence."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-17.form-response")
    )
    form_key: _AuthoringKey
    visit_id: VisitId
    occurrence_id: ActivityOccurrenceId
    answers_digest: Digest
    receipt_required: bool
    submitted_at: UtcInstant


class PresentationComponent(KernelModel):
    """One shipped presentation component with its accessibility profile."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-17.presentation-component")
    )
    component_key: _AuthoringKey
    component_schema: SchemaRef
    accessibility_profile: _AuthoringKey


class GateAnchor(KernelModel):
    """What a gate control gates: an interaction or a flow node, keyed."""

    anchor_kind: Literal["interaction", "flow_node"]
    anchor_key: _AuthoringKey


class GateControl(KernelModel):
    """The readiness control (RP-8) that surfaces a gate and emits a gate-op."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-17.gate-control")
    )
    component_key: _AuthoringKey
    gate_target: Literal["advance", "join"]
    gate_action: Literal["block", "unblock"]
    anchor: GateAnchor
    gate_op: SchemaRef
    accessibility_profile: _AuthoringKey

    @model_validator(mode="after")
    def _anchor_matches_target(self) -> GateControl:
        expected = "flow_node" if self.gate_target == "advance" else "interaction"
        if self.anchor.anchor_kind != expected:
            raise ValueError("a gate control anchor must match its gate target")
        return self


class AccessibilityProfile(KernelModel):
    """One accessibility profile: a WCAG level and its access guarantees."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-17.accessibility-profile")
    )
    profile_key: _AuthoringKey
    wcag_level: Literal["a", "aa", "aaa"]
    keyboard_navigable: bool
    screen_reader: bool

    @model_validator(mode="after")
    def _level_meets_access_floor(self) -> AccessibilityProfile:
        if self.wcag_level in {"aa", "aaa"} and not (
            self.keyboard_navigable and self.screen_reader
        ):
            raise ValueError("an aa or aaa profile must meet the access floor")
        return self
