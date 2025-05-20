#!/usr/bin/env python3
"""
fetch_affils.py – pull author affiliations from works.bib via OpenAlex
"""

import bibtexparser, requests, pandas as pd, time, re, html
from pathlib import Path

BIB_FILE = Path("works.bib")
API_BASE = "https://api.openalex.org"
PAUSE = 0.15                        # polite delay between API calls
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\}\),;]+", re.I)   # generic DOI pattern


def extract_doi(entry_dict):
    """Return first DOI seen anywhere in this BibTeX entry (or '')"""
    # 1. explicit field
    explicit = entry_dict.get("doi", "") or entry_dict.get("DOI", "")
    if explicit:
        return explicit.strip().lower()

    # 2. scan all fields
    for v in entry_dict.values():
        if not isinstance(v, str):
            continue
        m = DOI_RE.search(v)
        if m:
            return m.group(0).rstrip(").,;").lower()  # trim trailing junk
    return ""


def parse_bib(path: Path):
    with path.open(encoding="utf-8") as fh:
        db = bibtexparser.load(fh)

    records = []
    for e in db.entries:
        doi = extract_doi(e)
        title = html.unescape(e.get("title", ""))
        title = re.sub(r"\{.*?}", "", title)          # drop LaTeX braces
        title = re.sub(r"\s+", " ", title).strip()
        authors_raw = e.get("author", "")
        if authors_raw:
            records.append((e.get("ID", "N/A"), doi, title, authors_raw))
    return records


def split_authors(raw):
    out = []
    for a in re.split(r"\s+and\s+", raw, flags=re.I):
        if "," in a:
            last, first = [s.strip() for s in a.split(",", 1)]
        else:
            parts = a.split()
            last, first = parts[-1], " ".join(parts[:-1])
        out.append(dict(full=f"{first} {last}".strip(),
                        first=first, last=last))
    return out


def name_match(local, remote):
    return (
        local["last"].lower() in remote.lower()
        and (not local["first"] or local["first"][0].lower() in remote.lower())
    )


def fetch_affils(recs):
    for rid, doi, title, raw_auth in recs:
        print(f"\n▶ {rid}: {title[:60]}")

        locals_ = split_authors(raw_auth)
        found = {a["full"]: None for a in locals_}

        # --- DOI route ----------------------------------------------------
        if doi:
            try:
                r = requests.get(f"{API_BASE}/works/doi:{doi}", timeout=10)
                r.raise_for_status()
                for au in r.json().get("authorships", []):
                    remote = au["author"]["display_name"]
                    affil = (au.get("institutions") or [{}])[0].get("display_name")
                    for loc in locals_:
                        if name_match(loc, remote):
                            found[loc["full"]] = affil
                print("   DOI lookup ✓")
            except requests.RequestException as e:
                print(f"   DOI lookup ✗  ({e})")
            time.sleep(PAUSE)

        # --- Title route --------------------------------------------------
        if title and any(v is None for v in found.values()):
            q = requests.utils.quote(title)
            try:
                r = requests.get(f"{API_BASE}/works?filter=title.search:{q}&per_page=1",
                                 timeout=10)
                r.raise_for_status()
                hits = r.json().get("results", [])
                if hits:
                    hit = hits[0]
                    for au in hit.get("authorships", []):
                        remote = au["author"]["display_name"]
                        affil = (au.get("institutions") or [{}])[0].get("display_name")
                        for loc in locals_:
                            if found[loc["full"]] is None and name_match(loc, remote):
                                found[loc["full"]] = affil
                print("   title lookup ✓")
            except requests.RequestException as e:
                print(f"   title lookup ✗  ({e})")
            time.sleep(PAUSE)

        # emit rows
        for full, affil in found.items():
            yield dict(author_full_name=full,
                       affiliation=affil,
                       doi_used=doi,
                       title_used=title if not doi else "")


def main():
    if not BIB_FILE.exists():
        raise SystemExit(f"{BIB_FILE} not found")
    recs = parse_bib(BIB_FILE)
    print(f"Parsed {len(recs)} entries")

    df = pd.DataFrame(fetch_affils(recs))
    df.to_csv("bib_authors_with_affils.csv", index=False)
    print(f"\n✓ Wrote {len(df)} rows to bib_authors_with_affils.csv")


if __name__ == "__main__":
    main()
