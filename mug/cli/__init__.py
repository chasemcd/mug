"""The ``mug`` command line: one more actor on the command spine.

The command line is a thin front end above the runtime. It opens the same store a
deployment opens, holds one gateway, and drives each verb through the family
runtime the edge already drives -- ``publish`` and ``deploy`` through the shared
``dispatch_command``, ``simulate`` through the durable job runtime, ``export`` and
``replay`` through the export and replay runtimes. It holds no domain logic, so a
command from the command line and a command from a client reach a family the same
way.
"""

from __future__ import annotations

from mug.cli.commands import (
    CliError,
    run_deploy,
    run_export,
    run_publish,
    run_replay,
    run_simulate,
    run_stop,
)
from mug.cli.main import build_parser, main
from mug.cli.session import CliSession

__all__ = [
    "CliError",
    "CliSession",
    "build_parser",
    "main",
    "run_deploy",
    "run_export",
    "run_publish",
    "run_replay",
    "run_simulate",
    "run_stop",
]
