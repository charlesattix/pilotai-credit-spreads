"""
check_accounts.py — Programmatic status check for all 4 Alpaca paper trading accounts.

Usage:
    python3 scripts/check_accounts.py

Importable:
    from scripts.check_accounts import check_all_accounts
    results = check_all_accounts()
"""

import requests

BASE_URL = "https://paper-api.alpaca.markets"

ACCOUNTS = {
    "exp036": {
        "key": "PK4SGNFT3BGN54TCVOE4G44OYQ",
        "secret": "D3pVjqqBF9kLjyW1W9UMJcoqzVvqex5azhGB15fzgTCh",
        "account_id": "PA3D6UPXF5F2",
    },
    "exp059": {
        "key": "PK6URS6OBCSSHZZ2RQZSE2FOAH",
        "secret": "4PTrX1ppT5iZRAnwpcY7282of8UiFyN9pCEE2ZcmjzJ1",
        "account_id": "PA3LP867WNGU",
    },
    "exp154": {
        "key": "PKANAYVKHZX24Z3KCYNI2PLSCR",
        "secret": "GyBN2gCyuXfG7yTqFKs5JKTHL8eyC8SYTQ77Y3oyQp4J",
        "account_id": "PA3UNOV58WGK",
    },
    "exp305": {
        "key": "PKSPAM5732NK425PEUR7ZBELCB",
        "secret": "4Xmjn5wynCWoiJboiAf95tGozQCBD96rnQYujNTNuiZX",
        "account_id": "PA3W9FZKK6XD",
    },
}


def _headers(key: str, secret: str) -> dict:
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    }


def _fetch_account(key: str, secret: str) -> dict:
    """Fetch /v2/account. Returns parsed JSON dict or raises on error."""
    resp = requests.get(
        f"{BASE_URL}/v2/account",
        headers=_headers(key, secret),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_positions(key: str, secret: str) -> list:
    """Fetch /v2/positions. Returns list of position dicts or raises on error."""
    resp = requests.get(
        f"{BASE_URL}/v2/positions",
        headers=_headers(key, secret),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def check_all_accounts() -> dict:
    """
    Check all 4 Alpaca paper trading accounts.

    Returns a dict keyed by exp name, e.g.:
        {
          "exp036": {
            "account_id": "PA3D6UPXF5F2",
            "status": "OK",           # or "ERROR"
            "equity": 100000.0,
            "buying_power": 50000.0,
            "positions_count": 3,
            "positions": [...],        # raw list from Alpaca
            "error": None,             # or error message string
          },
          ...
        }
    """
    results = {}

    for exp, creds in ACCOUNTS.items():
        key = creds["key"]
        secret = creds["secret"]
        account_id = creds["account_id"]

        entry: dict = {
            "account_id": account_id,
            "status": "ERROR",
            "equity": None,
            "buying_power": None,
            "positions_count": 0,
            "positions": [],
            "error": None,
        }

        try:
            acct = _fetch_account(key, secret)

            # Alpaca returns an error dict (with "code") for auth failures even on 200
            if "code" in acct:
                entry["error"] = acct.get("message", "API error (code: {})".format(acct["code"]))
                results[exp] = entry
                continue

            entry["equity"] = float(acct.get("equity") or 0)
            entry["buying_power"] = float(acct.get("buying_power") or 0)

            positions = _fetch_positions(key, secret)
            entry["positions"] = positions
            entry["positions_count"] = len(positions)
            entry["status"] = "OK"

        except requests.exceptions.HTTPError as exc:
            entry["error"] = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        except requests.exceptions.ConnectionError as exc:
            entry["error"] = f"Connection error: {exc}"
        except requests.exceptions.Timeout:
            entry["error"] = "Request timed out"
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc)

        results[exp] = entry

    return results


def _print_summary(results: dict) -> None:
    print("\n=== PilotAI Portfolio Status ===")
    header = f"{'EXP':<8} {'ACCOUNT':<14} {'STATUS':<8} {'EQUITY':>13} {'BUYING PWR':>13} {'POSITIONS':>9}"
    separator = f"{'----':<8} {'-----------':<14} {'------':<8} {'-----------':>13} {'-----------':>13} {'---------':>9}"
    print(header)
    print(separator)

    has_error = False
    for exp, data in results.items():
        exp_short = exp.replace("exp", "")
        account_id = data["account_id"]
        status = data["status"]

        if status == "OK":
            equity_str = "${:,.2f}".format(data["equity"])
            bp_str = "${:,.2f}".format(data["buying_power"])
            pos_str = str(data["positions_count"])
        else:
            equity_str = data.get("error") or "error"
            # Truncate long error messages for table display
            if len(equity_str) > 13:
                equity_str = equity_str[:10] + "..."
            bp_str = "-"
            pos_str = "-"
            has_error = True

        print(
            f"{exp_short:<8} {account_id:<14} {status:<8} {equity_str:>13} {bp_str:>13} {pos_str:>9}"
        )

    print()

    if has_error:
        print("WARNING: One or more accounts reported errors.")
        for exp, data in results.items():
            if data["status"] == "ERROR":
                print(f"  {exp} ({data['account_id']}): {data.get('error')}")
        print()


if __name__ == "__main__":
    results = check_all_accounts()
    _print_summary(results)
