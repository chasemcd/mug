"""Small command value types shared by commands and errors.

``CommandTypeRef`` names a command. ``CommandPreconditions`` states the optimistic
concurrency guard. Both the command envelope and the domain error reference the
command type, so these types live apart to keep the import graph acyclic.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from mug.kernel._base import KernelModel
from mug.kernel.refs import NonNegativeSafeInteger, PositiveSafeInteger


class CommandTypeRef(KernelModel):
    """A command name plus its integer version."""

    name: Annotated[
        str, Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$", max_length=128)
    ]
    version: NonNegativeSafeInteger


class CommandPreconditions(KernelModel):
    """An optimistic-concurrency guard for a command.

    Exactly one form is valid: assert absence (``expected_absent`` alone), or
    assert an expected revision (with an optional expected state). The two forms
    never combine.
    """

    expected_revision: PositiveSafeInteger | None = None
    expected_state: (
        Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$", max_length=64)]
        | None
    ) = None
    expected_absent: bool | None = None

    @model_validator(mode="after")
    def _exactly_one_form(self) -> CommandPreconditions:
        if self.expected_absent is not None:
            if self.expected_absent is not True:
                raise ValueError("expected_absent must be true when present")
            if self.expected_revision is not None or self.expected_state is not None:
                raise ValueError("expected_absent must stand alone")
        elif self.expected_revision is None:
            raise ValueError(
                "preconditions require expected_absent or expected_revision"
            )
        return self
