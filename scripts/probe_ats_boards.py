"""Find the public Greenhouse / Ashby / Lever board of companies whose careers page does not show one.

For each company name it tries a few slugs derived from the name and the website domain against the public job-board
APIs (read-only GETs). A board counts only when the API answers with jobs and the slug equals the company name or its
domain label (Greenhouse also reports the board's own name, which must match). Nothing is written to the project; the
result is a JSON list to review, then to turn into leads with the board URL as ``careers_url``.

Usage: python scripts/probe_ats_boards.py leads.json out.json [--only "Name 1,Name 2"]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import httpx

HEADERS = {"User-Agent": "ai-job-hunter-board-probe/1.0 (personal job search; read-only)"}
SUFFIXES = (" inc", " inc.", " labs", " lab", " technologies", " technology", " b.v.", " bv", " gmbh", " co.", " ai")


def fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def slugs_for(name: str, website: str | None) -> list[str]:
    base = name.lower()
    variants = {base}
    for suffix in SUFFIXES:
        if base.endswith(suffix):
            variants.add(base[: -len(suffix)])
    variants |= {re.sub(r"\(.*?\)", "", v).strip() for v in list(variants)}
    result: list[str] = []
    for variant in variants:
        plain = re.sub(r"[^a-z0-9 -]+", "", unicodedata.normalize("NFKD", variant).encode("ascii", "ignore").decode())
        words = plain.split()
        if not words:
            continue
        result += ["".join(words), "-".join(words)]
    if website:
        host = (urlsplit(website).hostname or "").removeprefix("www.")
        label = host.split(".")[0] if host else ""
        if label:
            result.append(label)
    return list(dict.fromkeys(slug for slug in result if slug))


def probe(client: httpx.Client, company: dict) -> dict:
    name, website = company["company_name"], company.get("website_url")
    wanted = {fold(name), *{fold(s) for s in slugs_for(name, website)}}
    found: list[dict] = []
    for slug in slugs_for(name, website):
        if fold(slug) not in wanted:
            continue
        try:
            r = client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
            if r.status_code == 200 and isinstance(r.json(), dict) and r.json().get("name"):
                board_name = r.json()["name"]
                jobs = client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs").json().get("jobs", [])
                found.append({
                    "ats": "greenhouse", "slug": slug, "board_name": board_name, "jobs": len(jobs),
                    "name_matches": fold(board_name) in wanted or fold(name) in fold(board_name),
                    "url": f"https://boards.greenhouse.io/{slug}",
                })
        except (httpx.HTTPError, ValueError):
            pass
        try:
            r = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
            if r.status_code == 200:
                jobs = r.json().get("jobs", [])
                if jobs:
                    found.append({"ats": "ashby", "slug": slug, "jobs": len(jobs), "name_matches": None,
                                  "url": f"https://jobs.ashbyhq.com/{slug}"})
        except (httpx.HTTPError, ValueError):
            pass
        try:
            r = client.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
            if r.status_code == 200 and isinstance(r.json(), list) and r.json():
                found.append({"ats": "lever", "slug": slug, "jobs": len(r.json()), "name_matches": None,
                              "url": f"https://jobs.lever.co/{slug}"})
        except (httpx.HTTPError, ValueError):
            pass
    return {"company_name": name, "website_url": website, "boards": found}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("leads", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    companies = json.loads(args.leads.read_text(encoding="utf-8"))["leads"]
    only = {fold(n) for n in args.only.split(",") if n.strip()}
    if only:
        companies = [c for c in companies if fold(c["company_name"]) in only]
    with httpx.Client(headers=HEADERS, timeout=15.0, follow_redirects=False) as client, ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda c: probe(client, c), companies))
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for item in results:
        boards = ", ".join(f"{b['ats']}:{b['slug']}({b['jobs']})" for b in item["boards"]) or "-"
        print(f"{item['company_name'][:30]:30} {boards}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
