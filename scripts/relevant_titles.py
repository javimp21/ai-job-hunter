"""Count how many job titles are relevant for the candidate (used by the weekly funded-startups routine).

Usage: python scripts/relevant_titles.py titles.json [sector]
``titles.json`` holds a JSON list of job titles. Prints the number of relevant titles and the first few, nothing else.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ai_job_hunter.candidates.prefilter import title_may_be_relevant


def main(argv: list[str]) -> int:
    titles = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    sector = argv[2] if len(argv) > 2 else "software"
    relevant = [title for title in titles if isinstance(title, str) and title_may_be_relevant(title, sector)]
    print(f"{len(relevant)} relevant of {len(titles)}")
    for title in relevant[:10]:
        print(f"- {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
