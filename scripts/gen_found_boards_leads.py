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


def build(probe_path: Path) -> dict:
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    leads = []
    for item in probe:
        boards = [b for b in item["boards"] if b["jobs"] > 0 and b.get("name_matches") is not False]
        if item["company_name"] in UNSURE or len(boards) != 1:
            continue
        board = boards[0]
        lead = {
            "company_name": item["company_name"],
            "careers_url": board["url"],
            "source_type": "web_research",
            "source_label": "board_probe_2026_10_08",
            "hiring_hint": f"Public {board['ats']} board '{board['slug']}' answered with {board['jobs']} postings on 2026-10-08.",
            "notes": "Board found by trying the company name as a slug on the public Greenhouse/Ashby/Lever APIs "
                     "(scripts/probe_ats_boards.py); the slug equals the company name.",
        }
        if item.get("website_url"):
            lead["website_url"] = item["website_url"]
        leads.append(lead)
    leads.append({
        "company_name": "Inditex",
        "website_url": "https://www.inditex.com",
        "source_type": "web_research",
        "source_label": "user_request_2026_10_08",
        "location_hint": "Arteixo, A Coruña, Spain",
        "hiring_hint": "Requested by the user: technology roles in Spain (Inditex Tech).",
        "notes": "Careers page to be found by the resolver from the website.",
    })
    return {"leads": leads}


if __name__ == "__main__":
    data = build(Path(sys.argv[1]))
    target = ROOT / "config" / "leads" / "boards-found-2026-10.json"
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(data['leads'])} leads)")
