"""Broker adapter signals with authoritative submission semantics."""


class OrderAdmissionRefusedError(RuntimeError):
    """Admission failed before the adapter made any order POST.

    Raise only where the adapter can prove nothing was sent. Transport errors
    once POST is attempted must remain ambiguous and retain reserved risk.
    """


class OrderBeforeSubmissionError(RuntimeError):
    """Local setup failed before any order POST. Not an admission refusal."""


class OrderPreflightRefusedError(ValueError):
    """The request is invalid here, before any order POST."""


class OrderSubmissionUnknownError(RuntimeError):
    """The broker was contacted and the outcome was not proved."""
