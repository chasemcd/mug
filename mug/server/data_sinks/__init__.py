"""Reference data sink implementations for MUG.

The core ``DataSink`` ABC and built-in sinks (``FilesystemSink``,
``MultiSink``, ``AsyncSinkWrapper``) live in :mod:`mug.server.data_sink`.
This subpackage hosts additional concrete sinks — currently just
:class:`SQLiteSink` — that users can drop in or copy as a template for
their own backends.
"""

from __future__ import annotations

from mug.server.data_sinks.sqlite_sink import SQLiteSink

__all__ = ["SQLiteSink"]
