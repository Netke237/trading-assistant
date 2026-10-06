"""Capture production Tradier chain evidence without transforming quote values."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import date, datetime, timezone
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = "https://api.tradier.com/v1/markets/options/chains"
FIELDS = ("bid", "ask", "last", "volume", "open_interest", "bid_date", "ask_date", "trade_date")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ValueError("Provider redirect refused before forwarding credentials")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def capture(symbol, expiration, session, token, opener=None):
    """Return an evidence envelope only after a successful valid chain response."""
    url = ENDPOINT + "?" + urlencode({"symbol": symbol, "expiration": expiration})
    request = Request(url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    if opener is None:
        opener = build_opener(NoRedirect()).open
    started = utc_now()
    # Default urllib handlers preserve inherited proxy configuration and CA verification.
    with opener(request, timeout=30) as response:
        status = response.status
        if status != 200:
            raise ValueError("Provider did not return HTTP 200")
        # Refuse redirects: evidence must come from the requested production endpoint.
        if response.geturl() != url:
            raise ValueError("Provider redirected the request")
        raw = response.read()
        received = utc_now()
    payload = json.loads(raw)
    options = payload.get("options") if isinstance(payload, dict) else None
    if not isinstance(options, dict) or "option" not in options:
        raise ValueError("Response does not contain an options.option chain")
    rows = options["option"]
    if rows is None:
        rows = []
    elif isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Invalid option rows")
    return {
        "schema_version": 1,
        "provider": "Tradier",
        "environment": "production",
        "endpoint": url,
        "symbol": symbol,
        "expiration": expiration,
        "session_label": session,
        "session_label_source": "operator supplied; not calendar verified",
        "request_started_utc": started,
        "payload_received_utc": received,
        "http_status": status,
        "row_count": len(rows),
        "quote_fields": list(FIELDS),
        "field_presence_counts": {field: sum(field in row for row in rows) for field in FIELDS},
        "raw_payload_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_payload_base64": base64.b64encode(raw).decode("ascii"),
        "payload": payload,
    }


def write_evidence(output, evidence):
    """Publish a complete private file without overwriting an existing capture."""
    output = Path(output)
    data = (json.dumps(evidence, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".tradier-capture-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and fails if the destination exists.
        os.link(temporary, output)
    finally:
        os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--expiration", required=True, type=date.fromisoformat)
    parser.add_argument("--session", required=True, choices=("premarket", "in-session", "after-close", "weekend"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11):
        parser.error("Use the project's Python 3.11 interpreter")
    token = os.environ.get("TRADIER_API_TOKEN")
    if not token or "\n" in token or "\r" in token:
        parser.error("Set TRADIER_API_TOKEN in the environment to a production token")
    if not args.symbol.strip() or args.output.exists():
        parser.error("Provide a symbol and a new output path")
    try:
        evidence = capture(args.symbol, args.expiration.isoformat(), args.session, token)
        write_evidence(args.output, evidence)
    except Exception:
        # Provider bodies and exception strings are deliberately not logged.
        print("Capture failed; no new evidence file published. Check access and request parameters.", file=sys.stderr)
        return 1
    print(f"Captured {evidence['row_count']} raw rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
