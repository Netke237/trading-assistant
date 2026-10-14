"""Broker adapter signals with authoritative submission semantics."""


class OrderAdmissionRefusedError(RuntimeError):
    """Admission failed before the adapter made any order POST.

    Raise only where the adapter can prove nothing was sent. Transport errors
    once POST is attempted must remain ambiguous and retain reserved risk.
    """
