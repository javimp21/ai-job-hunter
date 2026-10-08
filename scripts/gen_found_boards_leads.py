"""Turn the result of probe_ats_boards.py into leads that carry the board URL as ``careers_url``.

Boards whose slug is a common word (the company name is shared with other companies) are left out: the board must be
the company's. Inditex is added by hand: the user asked for it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNSURE = {"Parallel Web Systems", "Arena", "Ditto", "Brain Co.", "Runway", "Metronome", "Merge", "Eventual"}
# Big or generic names whose small board on another system is a different organisation, and a junk lead name.
BLOCKED = {
    "Amazon", "Google", "HPE", "Personio", "Perry Street Software", "Remote", "Medium", "Align Technology",
    "Revel", "Speak", "Owner", "Phantom", "Coder", "Perk", "Searchable", "Sieve Data", "Numa",
}
NAME_CHECKED = {"greenhouse", "workable", "smartrecruiters"}  # the API gives the board's own name
MIN_JOBS = 5


def choose(item: dict) -> dict | None:
    """The one board that is safely the company's, or None."""

    name = item["company_name"]
    if name in UNSURE or name in BLOCKED or name.startswith("At Tether"):
        return None
    boards = [
        b for b in item["boards"]
        if b["jobs"] >= MIN_JOBS and b.get("name_matches") is not False
        and (b["ats"] not in NAME_CHECKED or b.get("name_matches") is True)
    ]
    if not boards:
        return None
    boards.sort(key=lambda b: -b["jobs"])
    if len(boards) > 1 and boards[0]["jobs"] < 2 * boards[1]["jobs"]:
        return None  # two boards of similar size: one of them is probably another organisation
    return boards[0]


def build(probe_path: Path) -> dict:
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    leads = []
    for item in probe:
        board = choose(item)
        if board is None:
            continue
        lead = {
            "company_name": item["company_name"],
            "careers_url": board["url"],
            "source_type": "web_research",
            "source_label": "board_probe_2026_10_08",
            "hiring_hint": f"Public {board['ats']} board '{board['slug']}' answered with {board['jobs']} postings on 2026-10-08.",
            "notes": "Board found by trying the company name as a slug on the public Greenhouse/Ashby/Lever/Workable/"
                     "Recruitee/SmartRecruiters/Personio APIs (scripts/probe_ats_boards.py); the slug equals the company name.",
        }
        if item.get("website_url"):
            lead["website_url"] = item["website_url"]
        leads.append(lead)
    return {"leads": leads}


if __name__ == "__main__":
    data = build(Path(sys.argv[1]))
    target = ROOT / "config" / "leads" / (sys.argv[2] if len(sys.argv) > 2 else "boards-found-2026-10.json")
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(data['leads'])} leads)")
