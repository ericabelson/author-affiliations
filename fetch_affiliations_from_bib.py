#!/usr/bin/env python3
"""
fetch_affiliations_from_bib.py – pull author affiliations from works.bib via OpenAlex

This version
– removes LaTeX braces and backslashes before matching
– uses Unidecode for accent-insensitive name comparisons
– falls back to the author endpoint if no institution in the work record
"""

import bibtexparser
import requests
import pandas as pd
import time
import re
import html
from pathlib import Path
from unidecode import unidecode

# --------------- CONFIG ---------------
BIB_FILE = Path("works.bib")
API_BASE = "https://api.openalex.org"
DELAY    = 0.15
DOI_RE   = re.compile(r"10\.\d{4,9}/[^\s\}\),;]+", re.I)


# -------------- HELPERS --------------
def latex2text(s: str) -> str:
    """Strip LaTeX braces/commands and HTML entities → plain text."""
    s = html.unescape(s)
    # remove braces and backslashes
    s = s.replace("{", "").replace("}", "").replace("\\", "")
    return s.strip()


def extract_doi(entry: dict) -> str:
    """Find DOI in any field of a BibTeX entry."""
    explicit = entry.get("doi") or entry.get("DOI")
    if explicit:
        return explicit.strip().lower()

    for v in entry.values():
        if isinstance(v, str):
            m = DOI_RE.search(v)
            if m:
                return m.group(0).rstrip(").,;").lower()
    return ""


def split_authors(raw: str) -> list[dict]:
    """
    Split the raw BibTeX author string into dicts:
      { full, first, last, key_last, key_first_initial }
    """
    out = []
    for part in re.split(r"\s+and\s+", raw, flags=re.I):
        clean = latex2text(part)
        if "," in clean:
            last, first = [x.strip() for x in clean.split(",", 1)]
        else:
            toks = clean.split()
            last, first = toks[-1], " ".join(toks[:-1])
        out.append({
            "full": f"{first} {last}".strip(),
            "first": first,
            "last": last,
            "key_last": unidecode(last).lower(),
            "key_first_initial": unidecode(first[:1]).lower() if first else ""
        })
    return out


def names_match(local: dict, remote: str) -> bool:
    """Accent-insensitive: last name + first initial match."""
    r = unidecode(remote).lower()
    return (local["key_last"] in r and
            (not local["key_first_initial"] or local["key_first_initial"] in r))


def first_affil(authorship: dict) -> str | None:
    insts = authorship.get("institutions") or []
    return insts[0].get("display_name") if insts else None


def fetch_author_affil(author_id: str) -> str | None:
    """If work record has no institution, pull last_known_institution from /authors."""
    aid = author_id.split("/")[-1]
    try:
        r = requests.get(f"{API_BASE}/authors/{aid}", timeout=10)
        r.raise_for_status()
        return (r.json().get("last_known_institution") or {}).get("display_name")
    except requests.RequestException:
        return None


# ------------- WORKFLOW -------------
def parse_bib(path: Path) -> list[tuple]:
    with path.open(encoding="utf-8") as fh:
        db = bibtexparser.load(fh)

    recs = []
    for e in db.entries:
        doi    = extract_doi(e)
        title  = latex2text(e.get("title", ""))
        authors = e.get("author", "")
        if authors:
            recs.append((e.get("ID", "N/A"), doi, title, authors))
    return recs


def collect_affils(records: list[tuple]) -> dict:
    for rec_id, doi, title, authors_raw in records:
        print(f"\n▶ {rec_id}: {title[:60]}")
        locals_ = split_authors(authors_raw)
        found   = {a["full"]: None for a in locals_}

        # 1) DOI lookup
        if doi:
            try:
                r = requests.get(f"{API_BASE}/works/doi:{doi}", timeout=10)
                r.raise_for_status()
                for au in r.json().get("authorships", []):
                    remote = au["author"]["display_name"]
                    affil  = first_affil(au)
                    for loc in locals_:
                        if names_match(loc, remote):
                            found[loc["full"]] = affil or found[loc["full"]] \
                                                 or fetch_author_affil(au["author"]["id"])
                print("   DOI lookup ✓")
            except requests.RequestException as e:
                print(f"   DOI lookup ✗ ({e})")
            time.sleep(DELAY)

        # 2) Title fallback
        if title and any(v is None for v in found.values()):
            q = requests.utils.quote(title)
            try:
                r = requests.get(f"{API_BASE}/works?filter=title.search:{q}&per_page=1",
                                 timeout=10)
                r.raise_for_status()
                hits = r.json().get("results", [])
                if hits:
                    for au in hits[0].get("authorships", []):
                        remote = au["author"]["display_name"]
                        affil  = first_affil(au)
                        for loc in locals_:
                            if found[loc["full"]] is None and names_match(loc, remote):
                                found[loc["full"]] = affil or fetch_author_affil(au["author"]["id"])
                print("   title lookup ✓")
            except requests.RequestException as e:
                print(f"   title lookup ✗ ({e})")
            time.sleep(DELAY)

        # emit rows
        for full, affil in found.items():
            yield {
                "author_full_name": full,
                "affiliation":      affil,
                "doi_used":         doi,
                "title_used":       title if not doi else ""
            }


def main():
    if not BIB_FILE.exists():
        raise SystemExit(f"{BIB_FILE} not found")

    records = parse_bib(BIB_FILE)
    print(f"Parsed {len(records)} entries")

    df = pd.DataFrame(collect_affils(records))
    df.to_csv("bib_authors_with_affils.csv", index=False)
    print(f"\n✓ Wrote {len(df)} rows to bib_authors_with_affils.csv")


if __name__ == "__main__":
    main()
