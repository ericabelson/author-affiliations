#!/usr/bin/env python3
"""
fetch_affils.py – pull author affiliations from works.bib via OpenAlex

Improvements v2
---------------
• decodes LaTeX diacritics (latexcodec) → proper Unicode names
• accent-insensitive name matching (Unidecode)
• if work record has no institution, fetch author endpoint for last_known_institution
"""

import bibtexparser, requests, pandas as pd, time, re, html
from pathlib import Path
from latexcodec.decoder import decode as latex_decode
from unidecode import unidecode

BIB_FILE = Path("works.bib")
API_BASE = "https://api.openalex.org"
DELAY = 0.15                                   # seconds between calls
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\}\),;]+", re.I)


# ---------- helpers -----------------------------------------------------------
def latex2uni(s: str) -> str:
    """Decode LaTeX accent codes → Unicode, then unescape HTML entities."""
    return html.unescape(latex_decode(s))


def extract_doi(entry):
    """Return the first DOI found anywhere in a BibTeX entry (lower-case)."""
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
    """Return list of dicts with Unicode first/last plus comparison keys."""
    out = []
    for a in re.split(r"\s+and\s+", raw, flags=re.I):
        a = latex2uni(a)
        if "," in a:
            last, first = [s.strip() for s in a.split(",", 1)]
        else:
            parts = a.strip().split()
            last, first = parts[-1], " ".join(parts[:-1])
        out.append(
            dict(
                full=f"{first} {last}".strip(),
                first=first,
                last=last,
                key_last=unidecode(last).lower(),
                key_first_initial=(unidecode(first[:1]).lower() if first else "")
            )
        )
    return out


def names_match(local, remote_display):
    remote_key = unidecode(remote_display).lower()
    return (
        local["key_last"] in remote_key
        and (not local["key_first_initial"]
             or local["key_first_initial"] in remote_key)
    )


def first_affil(authorship):
    """Try the affiliation directly from the work record."""
    inst = (authorship.get("institutions") or [])
    return inst[0]["display_name"] if inst else None


def fetch_author_affil(author_id):
    """Hit /authors/{id} for last_known_institution, return str|None."""
    try:
        r = requests.get(f"{API_BASE}/authors/{author_id.split('/')[-1]}", timeout=10)
        r.raise_for_status()
        inst = (r.json().get("last_known_institution") or {}).get("display_name")
        return inst
    except requests.RequestException:
        return None


# ---------- main workflow -----------------------------------------------------
def parse_bib(path: Path):
    with path.open(encoding="utf-8") as fh:
        db = bibtexparser.load(fh)
    recs = []
    for e in db.entries:
        doi   = extract_doi(e)
        title = latex2uni(e.get("title", ""))
        title = re.sub(r"\{.*?}", "", title)         # drop leftover braces
        title = re.sub(r"\s+", " ", title).strip()
        au_raw = e.get("author", "")
        if au_raw:
            recs.append((e.get("ID", "N/A"), doi, title, au_raw))
    return recs


def collect_affils(records):
    for rec_id, doi, title, au_raw in records:
        print(f"\n▶ {rec_id}: {title[:60]}")
        locals_ = split_authors(au_raw)
        found = {a["full"]: None for a in locals_}

        # ---- 1. DOI route ------------------------------------------------
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
                            if not found[loc["full"]]:  # fetch author endpoint
                                found[loc["full"]] = fetch_author_affil(au["author"]["id"])
                print("   DOI lookup ✓")
            except requests.RequestException as e:
                print(f"   DOI lookup ✗ ({e})")
            time.sleep(DELAY)

        # ---- 2. title route (remaining blanks) --------------------------
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
                        remote_name = au["author"]["display_name"]
                        affil = first_affil(au)
                        for loc in locals_:
                            if found[loc["full"]] is None and names_match(loc, remote_name):
                                found[loc["full"]] = affil or fetch_author_affil(au["author"]["id"])
                print("   title lookup ✓")
            except requests.RequestException as e:
                print(f"   title lookup ✗ ({e})")
            time.sleep(DELAY)

        for full, affil in found.items():
            yield dict(author_full_name=full, affiliation=affil, doi_used=doi, title_used=title if not doi else "")


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
