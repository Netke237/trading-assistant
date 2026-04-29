#!/usr/bin/env python3
"""Health check script for Docker Compose."""

import sys
import urllib.request
import urllib.error

HEALTH_URL = "http://localhost:8000/health"
TIMEOUT = 5


def main():
    try:
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            if response.status == 200:
                data = response.read().decode("utf-8")
                if '"status": "ok"' in data:
                    print("Health check passed")
                    sys.exit(0)
            print(f"Health check failed: unexpected status {response.status}")
            sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Health check failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Health check failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
