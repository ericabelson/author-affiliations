#!/usr/bin/env python3
"""
fetch_affils.py – pull author affiliations from a BibTeX file via OpenAlex

Usage
-----
    pip install bibtexparser pandas requests
    python fetch_affils.py            # assumes works.bib in the same folder
"""

import bibtexparser
import requests
import pandas as pd
import time
import re
from pathlib import Path

BIB_FILE = Path("works.bib")          # change if your file lives elsewhere
API_BASE = "https://api.openalex.org"
DELAY_S   = 0.15                      # polite pause between calls


def parse_bib(bib_path: Path):
    """Return a list of (entry_id, doi, title, authors_raw)."""
    with bib_path.open(encoding="utf-8") as fh:
        db = bibtexparser.load(fh)

    records = []
    for e in db.entries:
        doi    = e.get("doi", "").strip().lower()
        title  = re.sub(r"\s+", " ", e.get("title", "")).strip()
        title  = re.sub(r"\{.*?}", "", title)          # drop {LaTeX bits}
        authors_raw = e.get("author", "")
        if authors_raw:
            records.append((e.get("ID", "N/A"), doi, title, authors_raw))
    return records


def split_authors(authors_raw: str):
    """Return list of dicts with full, first, last names."""
    output = []
    for a in re.split(r"\s+and\s+", authors_raw, flags=re.I):
        if "," in a:                     # “Last, First”
            last, first = [s.strip() for s in a.split(",", 1)]
        else:                            # “First Last”
            parts = a.strip().split()
            last, first = parts[-1], " ".join(parts[:-1])
        output.append(
            dict(full=f"{first} {last}".strip(),
                 first=first,
                 last=last)
        )
    return output


def match_local_remote(local, remote_name):
    """Heuristic: last names must match; first initial (if any) must match."""
    return (
        local["last"].lower() in remote_name.lower()
        and (not local["first"]
             or local["first"][0].lower() in remote_name.lower())
    )


def fetch_affils(records):
    """Yield dicts: author_full_name, affiliation, doi_used, title_used."""
    for rec_id, doi, title, authors_raw in records:
        print(f"\n▶ {rec_id}: {title[:60]}")
        local_authors = split_authors(authors_raw)
        found = {a["full"]: None for a in local_authors}

        # 1) DOI route
        if doi:
            try:
                r = requests.get(f"{API_BASE}/works/doi:{doi}", timeout=10)
                r.raise_for_status()
                work = r.json()
                for au in work.get("authorships", []):
                    remote_name = au["author"]["display_name"]
                    affil = (au.get("institutions") or [{}])[0].get("display_name")
                    for local in local_authors:
                        if match_local_remote(local, remote_name):
                            found[local["full"]] = affil
                print(f"   DOI lookup done")
            except requests.RequestException as e:
                print(f"   DOI lookup failed – {e}")
            time.sleep(DELAY_S)

        # 2) Title route for anything still unknown
        if title and any(v is None for v in found.values()):
            q = requests.utils.quote(title)
            try:
                r = requests.get(f"{API_BASE}/works?filter=title.search:{q}&per_page=1",
                                 timeout=10)
                r.raise_for_status()
                results = r.json().get("results", [])
                if results:
                    work = results[0]
                    for au in work.get("authorships", []):
                        remote_name = au["author"]["display_name"]
                        affil = (au.get("institutions") or [{}])[0].get("display_name")
                        for local in local_authors:
                            if found[local["full"]] is None and match_local_remote(local, remote_name):
                                found[local["full"]] = affil
                print("   title lookup done")
            except requests.RequestException as e:
                print(f"   title lookup failed – {e}")
            time.sleep(DELAY_S)

        # Emit
        for full_name, affil in found.items():
            yield dict(author_full_name=full_name,
                       affiliation=affil,
                       doi_used=doi,
                       title_used=title if not doi else "")


def main():
    if not BIB_FILE.exists():
        raise SystemExit(f"Error – {BIB_FILE} not found")

    records = parse_bib(BIB_FILE)
    print(f"Parsed {len(records)} BibTeX entries")

    rows = list(fetch_affils(records))
    df = pd.DataFrame(rows)
    df.to_csv("bib_authors_with_affils.csv", index=False)
    print(f"\n✓ Saved {len(df)} rows to bib_authors_with_affils.csv")


if __name__ == "__main__":
    main()
    
