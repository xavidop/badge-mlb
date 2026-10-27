"""Rebuild apps/mlb/assets/teams.json from the MLB Stats API teams endpoint.

    python3 tools/build_teams.py
"""
import json
import urllib.request
from pathlib import Path

URL = "https://statsapi.mlb.com/api/v1/teams?sportId=1&fields=teams,id,abbreviation,teamName,division,id"


def main():
    with urllib.request.urlopen(URL) as reply:
        teams = json.load(reply)["teams"]
    table = {str(t["id"]): [t["abbreviation"], t["teamName"], t["division"]["id"]] for t in teams}
    out = Path(__file__).resolve().parents[1] / "apps" / "mlb" / "assets" / "teams.json"
    out.write_text(json.dumps(table, separators=(",", ":"), sort_keys=True))
    print("wrote", len(table), "teams to", out)


if __name__ == "__main__":
    main()
