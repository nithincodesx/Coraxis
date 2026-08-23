"""
CLI Health Check — Validates live API server status, health endpoint, and config endpoint.
Usage: python scripts/health_check.py
"""

import sys
import httpx

BASE_URL = "http://127.0.0.1:8000"

def main():
    print(f"Pinging Coraxis API backend at {BASE_URL}...")
    try:
        r_health = httpx.get(f"{BASE_URL}/api/health", timeout=5.0)
        if r_health.status_code == 200:
            data = r_health.json()
            print(f"[OK] Health Status: {data.get('status')} | History Count: {data.get('history_count')}")
        else:
            print(f"[FAIL] /api/health returned HTTP {r_health.status_code}")
            sys.exit(1)

        r_cfg = httpx.get(f"{BASE_URL}/api/config", timeout=5.0)
        if r_cfg.status_code == 200:
            cfg = r_cfg.json()
            print(f"[OK] Config endpoint active | Global Key Set: {cfg.get('global_key_set')}")
        else:
            print(f"[FAIL] /api/config returned HTTP {r_cfg.status_code}")
            sys.exit(1)

        print("\nAll Coraxis system health checks passed successfully!")
    except Exception as e:
        print(f"[ERROR] Could not connect to API server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
