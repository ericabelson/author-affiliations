#!/usr/bin/env python3
"""
fetch_affiliations_from_bib.py
Pull affiliations for every author in works.bib using OpenAlex.

– Robust title matching: choose the hit with the most shared last names
– Final fallback: author-level search if still blank
– Accent-insensitive matching, handles LaTeX accents without external libs
"""

import bibtexparser, requests, pandas as pd, time, re, html, urllib.parse
from pathlib import Path
from unidecode import unidecode

# ------------------------------------------------------------------------ #
# CONFIG
# ------------------------------------------------------------------------ #
BIB_FILE = Path("works.bib")                 # your BibTeX file
API      = "https://api.openalex.org"
PAUSE    = 0.15                              # polite delay
DOI_RE   = re.compile(r"10\.\d{4,9}/[^\s\}\),;]+", re.I)


# ------------------------------------------------------------------------ #
# HELPER FUNCTIONS
# ------------------------------------------------------------------------ #
def latex2txt(s: str) -> str:
    """Very simple LaTeX accent stripper + HTML unescape."""
    s = html.unescape(s)
    return re.sub(r"[\\{}']", "", s)               # drop braces, slashes, accents


def extract_doi(entry: dict) -> str:
    explicit = entry.get("doi") or entry.get("DOI")
    if explicit:
        return explicit.strip().lower()
    for v in entry.values():
        if isinstance(v, str):
            m = DOI_RE.search(v)
            if m:
                return m.group(0).rstrip(").,;").lower()
    return ""


def split_authors(raw: str):
    """Return list of parsed author dicts + a set of their last-name keys."""
    parsed, last_keys = [], set()
    for chunk in re.split(r"\s+and\s+", raw, flags=re.I):
        clean = latex2txt(chunk)
        if "," in clean:
            last, first = [x.strip() for x in clean.split(",", 1)]
        else:
            parts = clean.split()
            last, first = parts[-1], " ".join(parts[:-1])
        key_last = unidecode(last).lower()
        parsed.append(dict(
            full=f"{first} {last}".strip(),
            key_last=key_last,
            key_first=unidecode(first[:1]).lower() if first else ""
        ))
        last_keys.add(key_last)
    return parsed, last_keys


def names_match(local, remote_display: str) -> bool:
    r = unidecode(remote_display).lower()
    return local["key_last"] in r and (
        not local["key_first"] or local["key_first"] in r
    )


def first_affil(authorship):
    insts = authorship.get("institutions") or []
    return insts[0].get("display_name") if insts else None


def author_endpoint_affil(author_id):
    try:
        r = requests.get(f"{API}/authors/{author_id.split('/')[-1]}", timeout=10)
        r.raise_for_status()
        return (r.json().get("last_known_institution") or {}).get("display_name")
    except requests.RequestException:
        return None


def best_work_by_title(title: str, local_last_keys: set):
    """Pick the OpenAlex work whose author list overlaps the most last names."""
    q = urllib.parse.quote(title)
    try:
        r = requests.get(f"{API}/works?filter=title.search:{q}&per_page=25", timeout=10)
        r.raise_for_status()
        best, best_score = None, -1
        for w in r.json().get("results", []):
            remote_keys = {
                unidecode(a["author"]["display_name"].split()[-1]).lower()
                for a in w.get("authorships", [])
            }
            score = len(remote_keys & local_last_keys)
            if score > best_score:
                best, best_score = w, score
        return best
    except requests.RequestException:
        return None


def author_search_affil(name: str):
    """Final fallback: OpenAlex author search by full name."""
    q = urllib.parse.quote(name)
    try:
        r = requests.get(f"{API}/authors?search={q}&per_page=1", timeout=10)
        r.raise_for_status()
        res = r.json().get("results")
        if res:
            return (res[0].get("last_known_institution") or {}).get("display_name")
    except requests.RequestException:
        pass
    return None


# ------------------------------------------------------------------------ #
# MAIN COLLECTOR
# ------------------------------------------------------------------------ #
def gather_affiliations(entries):
    for rec_id, doi, title, raw in entries:
        print(f"\n▶ {rec_id}: {title[:60]}")
        locals_, last_keys = split_authors(raw)
        found = {a["full"]: None for a in locals_}

        # 1) DOI route ----------------------------------------------------
        if doi:
            try:
                r = requests.get(f"{API}/works/doi:{doi}", timeout=10)
                r.raise_for_status()
                work = r.json()
            except requests.RequestException:
                work = None
        else:
            work = None

        # 2) Smart title route if no DOI work
        if work is None:
            work = best_work_by_title(title, last_keys)

        # 3) Fill from the chosen work
        if work:
            for au in work.get("authorships", []):
                remote = au["author"]["display_name"]
                aff = first_affil(au) or author_endpoint_affil(au["author"]["id"])
                for loc in locals_:
                    if found[loc["full"]] is None and names_match(loc, remote):
                        found[loc["full"]] = aff
            print("   work lookup ✓")
        else:
            print("   work lookup ✗")

        time.sleep(PAUSE)

        # 4) Author-level fallback
        for loc in locals_:
            if found[loc["full"]] is None:
                found[loc["full"]] = author_search_affil(loc["full"])
                time.sleep(PAUSE)

        # emit rows
        for full, aff in found.items():
            yield {"author_full_name": full,
                   "affiliation": aff,
                   "source": "OpenAlex"}


def main():
    if not BIB_FILE.exists():
        raise SystemExit(f"{BIB_FILE} not found")

    # Parse BibTeX
    with BIB_FILE.open(encoding="utf-8") as fh:
        db = bibtexparser.load(fh)

    entries = [
        (e.get("ID", "N/A"),
         extract_doi(e),
         latex2txt(e.get("title", "")),
         e.get("author", ""))
        for e in db.entries if e.get("author")
    ]
    print(f"Parsed {len(entries)} BibTeX entries")

    # Collect affiliations
    df = pd.DataFrame(gather_affiliations(entries))
    df.to_csv("bib_authors_with_affils.csv", index=False)
    print(f"\n✓ Saved {len(df)} rows to bib_authors_with_affils.csv")


if __name__ == "__main__":
    main()
