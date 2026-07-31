"""Exceptions raised by transferegovpy.

Every error the package raises inherits from :class:`TransferegovError`, so a
caller can catch the whole family with one ``except``. The subclasses exist so
that a caller can tell a bad query from a bad connection without parsing
messages.
"""

from __future__ import annotations


class TransferegovError(Exception):
    """Base class for every error this package raises."""


class SchemaError(TransferegovError):
    """An unknown module, table or column."""


class FilterError(TransferegovError):
    """A filter that cannot be turned into a query parameter."""


class URLTooLongError(TransferegovError):
    """A request URL beyond what the service accepts.

    Usually a filter built with :func:`~transferegovpy.in_` over a long vector.
    """


class ResponseError(TransferegovError):
    """A response the package cannot make sense of."""


class HTTPError(TransferegovError):
    """A non-success HTTP status.

    Attributes
    ----------
    status:
        The HTTP status code.
    detail:
        The ``message``, ``details`` and ``hint`` fields of the PostgREST error
        body, when it sent one.
    """

    def __init__(self, message: str, status: int, detail: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail or {}


class IncompleteResultWarning(UserWarning):
    """Fewer rows were collected than the API reported as matching."""


class ColumnTypeWarning(UserWarning):
    """A column could not be coerced to the type the schema declares."""
