"""The failure type for an ingest that went wrong in a way we understand.

Ingest talks to the open web on a schedule, so most of what goes wrong is
ordinary: a site is down, a bridge is misconfigured, a host is rate limiting,
a feed answers with nothing. Those are conditions to report, not crashes to
debug — the message is already written for a person to read, it is stored on
the source and shown in the UI, and printing a stack trace for each one
buries the traces that do mean a bug.

So the backends and scrapers raise `IngestError` for anything they can
explain, and the jobs log it as a single line. Anything else that escapes
keeps its traceback, because anything else is a bug.
"""


class IngestError(Exception):
    """An ingest failure with a reason worth showing the person who added
    the source."""
