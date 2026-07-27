"""The durable output tape: keep a model generation as three distinct artifacts.

``mug.providers.tape`` states the seam and gives the in-process implementation. It
holds one verbatim output per digest, which is enough to replay a decision in the
same process and not enough to *compare* one: a preference candidate must name an
artifact a reader can open later, from another process, with the provider offline.

This module is the durable implementation. It writes each completed output into the
content-addressed object store in three forms, because the three answer different
questions and carry different privacy:

- **raw** -- exactly what the provider returned. It is the evidence that the call
  happened as recorded, and it is vendor-shaped, so it is the strictest of the
  three.
- **normalized** -- the same generation with the vendor out of it: the text and
  the parts, in one shape whatever produced them. This is what a study analyzes,
  and what makes a candidate reference independent of the provider that filled it.
- **visible** -- the text a participant reads, and nothing else. A comparison
  screen sends this form, so no provider name, model name, or vendor field can
  reach a browser through it.

The provider and the model identity are in none of the three. They stay in the
private provenance the generation records beside them (``mug.agents.generation``),
so a blinded comparison and a full audit read the same evidence and see different
parts of it.

The artifact identifiers are *derived*, not minted: one output digest and one form
always give one artifact identifier. So the tape needs no index of its own -- a
reader that holds the digest holds the address -- and re-recording the same output
overwrites identical bytes rather than growing a second copy. The derivation is
injected, so this module holds no secret and no entropy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from mug.kernel import ArtifactRef, DataHandlingRef, Digest
from mug.providers.tape import Output
from mug.storage import (
    ArtifactStore,
    StorageError,
    json_bytes,
    read_jsonl,
    stage_artifact,
)

# The three forms one generation is kept in. The order is the order they narrow:
# everything the provider said, the same generation without the vendor, then the
# text alone.
GenerationForm = Literal["raw", "normalized", "visible"]
GENERATION_FORMS: Final[tuple[GenerationForm, ...]] = ("raw", "normalized", "visible")

# What each form may be shown to. The raw provider response is vendor-shaped and
# may carry more than the text, so it is the strictest; the visible form is what a
# participant is shown, so it is public by construction.
_HANDLING: Final[dict[GenerationForm, DataHandlingRef]] = {
    "raw": DataHandlingRef(privacy_labels=["research", "sensitive"]),
    "normalized": DataHandlingRef(privacy_labels=["research"]),
    "visible": DataHandlingRef(privacy_labels=["public"]),
}

_JSON: Final[str] = "application/json"

# Turn one raw provider output into the provider-independent generation, and into
# the text a participant reads. A study replaces either when its provider answers
# in a shape the defaults do not read.
Normalize = Callable[[Output], dict[str, Any]]
RenderVisible = Callable[[Output], str]


@dataclass(frozen=True)
class GenerationForms:
    """The three references one recorded generation is addressed by.

    They are distinct artifacts, not three views of one: a candidate names the form
    it is a candidate of, and a comparison screen sends only ``visible``.
    """

    raw: ArtifactRef
    normalized: ArtifactRef
    visible: ArtifactRef

    def of(self, form: GenerationForm) -> ArtifactRef:
        """Return the reference for one named form."""
        by_form: dict[GenerationForm, ArtifactRef] = {
            "raw": self.raw,
            "normalized": self.normalized,
            "visible": self.visible,
        }
        return by_form[form]


def normalize_output(output: Output) -> dict[str, Any]:
    """Read one provider output as the provider-independent generation.

    The default reads a ``text`` field, a list of ``parts``, and a plain string, which
    is the shape the shipped adapters answer in. Anything else is carried whole under
    ``value`` rather than dropped, so a study that has not written its own normalizer
    still records a generation it can read. The provider is named nowhere here.
    """
    if isinstance(output, str):
        return {"text": output, "parts": [output]}
    if isinstance(output, dict):
        body: dict[str, Any] = dict(output)  # pyright: ignore[reportUnknownArgumentType]
        text = body.get("text")
        parts = body.get("parts")
        if isinstance(text, str):
            return {
                "text": text,
                "parts": list(parts) if isinstance(parts, list) else [text],  # pyright: ignore[reportUnknownArgumentType]
            }
    return {"text": "", "parts": [], "value": output}


def render_visible(output: Output) -> str:
    """Read one provider output as the text a participant is shown.

    Only text reaches a participant. An output the default cannot read renders as
    nothing rather than as its vendor shape, because a comparison that leaks the
    shape of one provider's answer is no longer blinded.
    """
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        text: Any = cast("dict[str, Any]", output).get("text")
        if isinstance(text, str):
            return text
    return ""


class ArtifactOutputTape:
    """A durable ``OutputTape`` that keeps each output as three stored artifacts.

    ``put`` and ``get`` are the seam ``mug.providers.tape`` states, so a provider
    takes this tape wherever it takes the in-memory one and replays an output across
    a restart instead of within one process. ``stage`` is the same write, returning
    the three references the caller records; a generation names them so a later
    reader opens the form it is allowed to read.

    The tape is given its derivation, its upload identifiers, and its clock, so it
    holds no entropy of its own and one output always lands at one address.
    """

    def __init__(
        self,
        artifacts: ArtifactStore,
        *,
        artifact_id_for: Callable[[str], str],
        new_upload_id: Callable[[], str],
        now: Callable[[], str],
        normalize: Normalize | None = None,
        render: RenderVisible | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._artifact_id_for = artifact_id_for
        self._new_upload_id = new_upload_id
        self._now = now
        self._normalize = normalize or normalize_output
        self._render = render or render_visible

    def artifact_id(self, digest: Digest, form: GenerationForm) -> str:
        """Return the one artifact identifier this output digest and form give."""
        return self._artifact_id_for(f"model-output:{form}:{digest.hex}")

    async def stage(self, digest: Digest, output: Output) -> GenerationForms:
        """Write one completed output in all three forms and return their references.

        The bytes of each form are canonical, so re-recording the same output writes
        the same bytes to the same address: a retry after a crash costs one overwrite
        and no second artifact.
        """
        bodies: dict[GenerationForm, Any] = {
            "raw": output,
            "normalized": self._normalize(output),
            "visible": {"text": self._render(output)},
        }
        staged: dict[GenerationForm, ArtifactRef] = {}
        for form in GENERATION_FORMS:
            staged[form] = await self._stage_one(digest, form, bodies[form])
        return GenerationForms(
            raw=staged["raw"],
            normalized=staged["normalized"],
            visible=staged["visible"],
        )

    async def put(self, digest: Digest, output: Output) -> None:
        """Record one completed output, as the ``OutputTape`` seam states."""
        await self.stage(digest, output)

    async def get(self, digest: Digest) -> Output | None:
        """Return the verbatim output recorded for a digest, or None for none.

        A partial tape answers None rather than raising, so a replay that finds no
        stored output degrades to the recorded-by-digest behavior (the seam's rule).
        """
        try:
            data = await self._artifacts.read_artifact(self.artifact_id(digest, "raw"))
        except StorageError:
            return None
        return read_jsonl(data)[0]["output"]

    async def _stage_one(
        self, digest: Digest, form: GenerationForm, body: Any
    ) -> ArtifactRef:
        """Stage one form of one output at its derived address."""
        artifact_id = self.artifact_id(digest, form)
        return await stage_artifact(
            self._artifacts,
            data=_form_bytes(form, body),
            media_type=_JSON,
            new_artifact_id=lambda: artifact_id,
            new_upload_id=self._new_upload_id,
            now=self._now,
            data_handling=_HANDLING[form],
        )


def _form_bytes(form: GenerationForm, body: Any) -> bytes:
    """Serialize one form of a generation to its canonical newline-ended bytes."""
    return json_bytes({"form": form, "output": body}) + b"\n"


async def read_generation_form(artifacts: ArtifactStore, ref: ArtifactRef) -> Any:
    """Read one stored generation form back and return the output it holds."""
    data = await artifacts.read_artifact(ref.artifact_id)
    return read_jsonl(data)[0]["output"]


__all__ = [
    "GENERATION_FORMS",
    "ArtifactOutputTape",
    "GenerationForm",
    "GenerationForms",
    "Normalize",
    "RenderVisible",
    "normalize_output",
    "read_generation_form",
    "render_visible",
]
