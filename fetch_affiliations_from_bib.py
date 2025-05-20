#!/usr/bin/env python3
"""
fetch_affiliations_from_bib.py – pulls author affiliations from a BibTeX file using OpenAlex
Handles LaTeX accents, works with author metadata if needed.
"""

import bibtexparser, requests, pandas as pd, time, re, html
from pathlib import Path
from unidecode import unidecode

# latexcodec fallback import
try:
    from latexcodec import latex_to_text as _latex_decode
except ImportError:
    from latexcodec.decoder import decode as _latex_decode


# --- CONFIG -------------------------------------------------------------------
BIB_FILE = Path("works.bib")
API_BASE = "https://api.openalex.org"
DELAY = 0.15  # delay between requests (in seconds)
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\}\),;]+", re.I)


# --- HELPERS ------------------------------------------------------------------
def latex2uni(s: str) -> str:
    """Decode LaTeX accent codes and HTML entities to plain Unicode."""
    return html.unescape(_latex_decode(s))


def extract_doi(entry):
    """Try to find a DOI in any field of the BibTeX entry."""
    explicit = entry.get("doi") or entry.get("DOI")
    if explicit:
        return explicit.strip().lower()

    for v in entry.values():
        if not isinstance(v, str):
            continue
        m = DOI_RE.search(v)
        if m:
            return m.group(0).rstrip(").,;").lower()
    return ""


def split_authors(raw):
    """Return list of authors with parsed names and matching keys."""
    out = []
    for a in re.split(r"\s+and\s+", raw, flags=re.I):
        a = latex2uni(a)
        if "," in a:
            last, first = [s.strip() for s in a.split(",", 1)]
        else:
            parts = a.strip().split()
            last, first = parts[-1], " ".join(parts[:-1])
        out.append(dict(
            full=f"{first} {last}".strip(),
            first=first,
            last=last,
            key_last=unidecode(last).lower(),
            key_first_initial=(unidecode(first[:1]).lower() if first else "")
        ))
    return out


def names_match(local, remote_display):
    """Compare author names using accent-insensitive partial matching."""
    remote_key = unidecode(remote_display).lower()
    return (
        local["key_last"] in remote_key and
        (not local["key_first_initial"] or local["key_first_initial"] in remote_key)
    )


def first_affil(authorship):
    """Get first affiliation name from OpenAlex authorship record."""
    inst = authorship.get("institutions") or []
    return inst[0].get("display_name") if inst else None


def fetch_author_affil(author_id):
    """Get last_known_institution for an author from OpenAlex."""
    try:
        r = requests.get(f"{API_BASE}/authors/{author_id.split('/')[-1]}", timeout=10)
        r.raise_for_status()
        return (r.json().get("last_known_institution") or {}).get("display_name")
    except requests.RequestException:
        return None


# --- MAIN WORKFLOW -----------------------------------------------------------
def parse_bib(path: Path):
    """Parse BibTeX file and return list of (entry_id, doi, title, authors_raw)"""
    with path.open(encoding="utf-8") as fh:
        db = bibtexparser.load(fh)

    recs = []
    for e in db.entries:
        doi = extract_doi(e)
        title = latex2uni(e.get("title", ""))
        title = re.sub(r"\{.*?}", "", title)
        title = re.sub(r"\s+", " ", title).strip()
        au_raw = e.get("author", "")
        if au_raw:
            recs.append((e.get("ID", "N/A"), doi, title, au_raw))
    return recs


def collect_affils(records):
    """Main loop to collect affiliations for all author-paper records."""
    for rec_id, doi, title, au_raw in records:
        print(f"\n▶ {rec_id}: {title[:60]}")
        locals_ = split_authors(au_raw)
        found = {a["full"]: None for a in locals_}

        # Step 1: DOI-based lookup
        if doi:
            try:
                r = requests.get(f"{API_BASE}/works/doi:{doi}", timeout=10)
                r.raise_for_status()
                for au in r.json().get("authorships", []):
                    remote_name = au["author"]["display_name"]
                    affil = first_affil(au)
                    for loc in locals_:
                        if names_match(loc, remote_name):
                            found[loc["full"]] = affil or found[loc["full"]]
                            if not found[loc["full"]]:
                                found[loc["full"]] = fetch_author_affil(au["author"]["id"])
                print("   DOI lookup ✓")
            except requests.RequestException as e:
                print(f"   DOI lookup ✗ ({e})")
            time.sleep(DELAY)

        # Step 2: fallback – title-based lookup
        if title and any(v is None for v in found.values()):
            q = requests.utils.quote(title)
            try:
                r = requests.get(f"{API_BASE}/works?filter=title.search:{q}&per_page=1", timeout=10)
                r.raise_for_status()
                hits = r.json().get("results", [])
                if hits:
                    hit = hits[0]
                    for au in hit.get("authorships", []):
                        remote_name = au["author"]["display_name"]
                        affil = first_affil(au)
                        for loc in locals_:
                            if found[loc["full"]] is None and names_match(loc, remote_name):
                                found[loc["full"]] = affil or fetch_author_affil(au["author"]["id"])
                print("   title lookup ✓")
            except requests.RequestException as e:
                print(f"   title lookup ✗ ({e})")
            time.sleep(DELAY)

        # Emit final rows
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

    df = pd.DataFrame(collect_affils(recs))
    df.to_csv("bib_authors_with_affils.csv", index=False)
    print(f"\n✓ Wrote {len(df)} rows to bib_authors_with_affils.csv")


if __name__ == "__main__":
    main()
