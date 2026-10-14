"""Bound already-decoded free-form request containers before persistence."""
from pydantic_core import PydanticCustomError

MAX_PAYLOAD_DEPTH = 32


def validate_payload_depth(value):
    """Preserve values; count dict/list roots as one and scalars as zero.

    Revisit shared children only when reached deeper. Cycles reach the bound
    without recursive calls or expanding an alias graph.
    """
    pending = [(value, 1)]
    greatest_depth = {}
    while pending:
        current, depth = pending.pop()
        if not isinstance(current, (dict, list)):
            continue
        if depth > MAX_PAYLOAD_DEPTH:
            raise PydanticCustomError(
                'payload_depth',
                'Payload nesting must not exceed {max_depth} container levels',
                {'max_depth': MAX_PAYLOAD_DEPTH},
            )
        identity = id(current)
        if greatest_depth.get(identity, 0) >= depth:
            continue
        greatest_depth[identity] = depth
        children = current.values() if isinstance(current, dict) else current
        pending.extend((child, depth + 1) for child in children)
    return value
