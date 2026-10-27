"""Fetch the 30 team spot logos from MLB's CDN into apps/mlb/assets.

Writes the 32px spots to assets/logos and 16px copies to assets/logos16
(the scoreboard blits those 1:1, which is much cheaper than scaling on the
badge). Needs ImageMagick's `magick` on the PATH for the 16px copies.

    python3 tools/build_logos.py
"""
import json
import subprocess
import urllib.request
from pathlib import Path

SPOT = "https://midfield.mlbstatic.com/v1/team/%s/spots/32"


def main():
    assets = Path(__file__).resolve().parents[1] / "apps" / "mlb" / "assets"
    big, small = assets / "logos", assets / "logos16"
    big.mkdir(exist_ok=True)
    small.mkdir(exist_ok=True)
    for team_id in json.loads((assets / "teams.json").read_text()):
        target = big / ("%s.png" % team_id)
        with urllib.request.urlopen(SPOT % team_id) as reply:
            target.write_bytes(reply.read())
        subprocess.run(["magick", str(target), "-filter", "Lanczos", "-resize", "16x16", "-colors", "64",
                        "PNG8:" + str(small / target.name)], check=True)
    print("logos written to", big, "and", small)


if __name__ == "__main__":
    main()
