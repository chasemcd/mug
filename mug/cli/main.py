"""The ``mug`` command-line entry point: parse, dispatch, and report.

This module owns the argument parser and the one ``asyncio.run`` boundary. It
opens the session synchronously -- before any event loop starts, so a Postgres
open never nests loops -- parses the verb, runs the matching command coroutine,
and prints a short, safe summary. It maps a ``CliError`` to a non-zero exit with a
clear message; it never prints a stack trace or an input value.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from mug.cli import commands
from mug.cli.commands import CliError
from mug.cli.session import CliSession
from mug.kernel import CommandReceipt


def build_parser() -> argparse.ArgumentParser:
    """Build the ``mug`` parser: one subcommand per verb."""
    parser = argparse.ArgumentParser(prog="mug", description="Operate a MUG study.")
    subparsers = parser.add_subparsers(dest="verb", required=True)

    publish = subparsers.add_parser(
        "publish", help="publish a compiled study version"
    )
    publish.add_argument(
        "envelope",
        type=Path,
        nargs="?",
        help="the prepared command envelope the compiler emits",
    )
    publish.add_argument(
        "--study",
        help="compile and publish the study a module names, as 'module:attribute'",
    )

    deploy = subparsers.add_parser("deploy", help="deploy a published study version")
    deploy.add_argument(
        "envelope", type=Path, help="the prepared deploy command envelope"
    )

    stop = subparsers.add_parser("stop", help="stop or start a deployment")
    stop.add_argument("deployment", help="the deployment identifier")
    stop.add_argument(
        "--start", action="store_true", help="start a stopped deployment again"
    )

    export = subparsers.add_parser("export", help="export a study's whole dataset")
    export.add_argument("out", type=Path, help="the directory to write the bundles to")
    export.add_argument(
        "--kind", action="append", dest="kinds", help="a dataset kind to export"
    )
    export.add_argument(
        "--study-version", type=Path, help="a StudyVersionRef file to export"
    )
    export.add_argument("--export-key", default="dataset", help="the export key stem")

    replay = subparsers.add_parser("replay", help="assemble an interaction's replay")
    replay.add_argument("out", type=Path, help="the directory to write the manifest to")
    replay.add_argument("--interaction", required=True, help="the interaction id")
    replay.add_argument(
        "--stream",
        action="append",
        dest="streams",
        default=[],
        help="a canonical stream id",
    )

    simulate = subparsers.add_parser("simulate", help="drain the durable job queue")
    simulate.add_argument(
        "--handler",
        required=True,
        help="the 'module:function' work handler a study provides",
    )
    simulate.add_argument("--workers", type=int, default=1, help="concurrent workers")

    return parser


def _print_receipt(verb: str, receipt: CommandReceipt) -> None:
    """Print a short, safe summary of a command receipt."""
    line = f"{verb}: {receipt.outcome}"
    if receipt.outcome == "accepted" and receipt.result is not None:
        outcome = receipt.result.data.get("outcome")
        if outcome is not None:
            line += f" ({outcome})"
        line += f" -- positions {dict(receipt.stream_positions)}"
    elif receipt.error is not None:
        line += f" [{receipt.error.category}] {receipt.error.code}"
    print(line)


async def _run(args: argparse.Namespace, session: CliSession) -> None:
    """Dispatch one parsed verb to its command coroutine and report."""
    if args.verb == "publish":
        if args.study:
            published = await commands.run_publish_study(session, args.study)
            print(f"published {published.study_version.study_version_id}")
        elif args.envelope:
            _print_receipt(
                "publish", await commands.run_publish(session, args.envelope)
            )
        else:
            raise commands.CliError("publish needs an envelope or --study")
    elif args.verb == "deploy":
        _print_receipt("deploy", await commands.run_deploy(session, args.envelope))
    elif args.verb == "stop":
        deployment = await commands.run_stop(
            session, args.deployment, start=args.start
        )
        print(f"{deployment.deployment_id} is {deployment.disposition}")
    elif args.verb == "export":
        export = await commands.run_export(
            session,
            args.out,
            kinds=args.kinds,
            study_version_path=args.study_version,
            export_key=args.export_key,
        )
        kinds = ", ".join(b.dataset_kind for b in export.bundles) or "nothing"
        print(f"export: wrote {len(export.bundles)} bundle(s) [{kinds}] to {args.out}")
    elif args.verb == "replay":
        bundle = await commands.run_replay(
            session, args.out, interaction_id=args.interaction, stream_ids=args.streams
        )
        print(
            f"replay: assembled {bundle.event_count} event(s) "
            f"from {len(bundle.stream_artifacts)} stream(s) to {args.out}"
        )
    elif args.verb == "simulate":
        handler = commands.resolve_handler(args.handler)
        drained = await commands.run_simulate(
            session, handler=handler, workers=args.workers
        )
        print(f"simulate: drained {drained} job(s)")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``mug`` command line and return a process exit code."""
    args = build_parser().parse_args(argv)
    try:
        session = CliSession.open()
        asyncio.run(_run(args, session))
    except CliError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
