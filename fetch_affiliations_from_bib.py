#!/usr/bin/env python3
"""
fetch_affiliations_from_bib.py
--------------------------------
1.  DOI-first:  Crossref → (full author list, incl. affils)
2.  If Crossref lacks an author OR no DOI:  OpenAlex /works (first 200 auth.)
3.  Any author still blank → OpenAlex /authors?search=  (processed in batches of 25)
4.  Outputs CSV with:  author (Last, FirstInit) · last_name · first · affiliation · doi · title
"""

import bibtexparser, requests, pandas as pd, time, re, html, urllib.parse
from pathlib import Path
from unidecode import unidecode

# ───────────────────────── CONFIG ──────────────────────────
BIB_FILE = Path("works.bib")          # your BibTeX file
CR_API   = "https://api.crossref.org/works/"
OA_API   = "https://api.openalex.org"
PAUSE    = 0.15                       # seconds between HTTP calls
BATCH    = 25                         # author-search batch size
DOI_RE   = re.compile(r"10\.\d{4,9}/[^\s\}\),;]+", re.I)


# ────────────────────── BASIC HELPERS ──────────────────────
def latex2txt(s: str) -> str:
    """Strip LaTeX braces/back-slashes and unescape HTML entities."""
    s = html.unescape(s)
    return re.sub(r"[\\{}']", "", s)


def extract_doi(entry):
    """Find DOI anywhere in the BibTeX entry."""
    explicit = entry.get("doi") or entry.get("DOI")
    if explicit:
        return explicit.strip().lower()
    for v in entry.values():
        if isinstance(v, str):
            m = DOI_RE.search(v)
            if m:
                return m.group(0).rstrip(").,;").lower()
    return ""


def parse_authors(raw):
    """Return list[dict] and lookup map keyed by 'Last, F'."""
    items, key_map = [], {}
    for chunk in re.split(r"\s+and\s+", raw, flags=re.I):
        clean = latex2txt(chunk.strip())
        if "," in clean:
            last, first = [x.strip() for x in clean.split(",", 1)]
        else:
            parts = clean.split()
            last, first = parts[-1], " ".join(parts[:-1])
        label   = f"{last}, {first}".strip().rstrip(".")
        key     = unidecode(last).lower(), (first[:1].lower() if first else "")
        items.append(dict(label=label,
                          last=last,
                          first=first,
                          key_last=key[0],
                          key_init=key[1],
                          affil=None))
        key_map[key] = label
    return items, key_map


def names_match(a_key, remote_name):
    r = unidecode(remote_name).lower()
    return a_key[0] in r and (not a_key[1] or a_key[1] in r)


def first_crossref_affil(author_blob):
    """Pull first affiliation string from Crossref author block."""
    affs = author_blob.get("affiliation") or []
    return affs[0]["name"] if affs else None


def first_oa_affil(authorship):
    insts = authorship.get("institutions") or []
    return insts[0].get("display_name") if insts else None


def oa_author_affil(author_id):
    try:
        r = requests.get(f"{OA_API}/authors/{author_id.split('/')[-1]}", timeout=10)
        r.raise_for_status()
        return (r.json().get("last_known_institution") or {}).get("display_name")
    except requests.RequestException:
        return None


# ────────────────────── PER-PAPER PROCESS ──────────────────────
def process_entry(entry):
    doi   = extract_doi(entry)
    title = latex2txt(entry.get("title", "")).strip()
    authors_raw = entry.get("author", "")
    parsed, key_map = parse_authors(authors_raw)

    # --- 1.  Crossref via DOI ------------------------------------
    if doi:
        try:
            r = requests.get(CR_API + urllib.parse.quote(doi), timeout=10)
            r.raise_for_status()
            for cr_auth in r.json()["message"].get("author", []):
                last  = cr_auth.get("family", "")
                first = cr_auth.get("given", "")
                key   = unidecode(last).lower(), (first[:1].lower() if first else "")
                if key in key_map:
                    label = key_map[key]
                    affil = first_crossref_affil(cr_auth)
                    if affil:
                        next(p for p in parsed if p["label"] == label)["affil"] = affil
            print(f"   Crossref ✓   ({doi})")
        except requests.RequestException:
            print(f"   Crossref ✗   ({doi})")
        time.sleep(PAUSE)

    # --- 2.  OpenAlex /works (if any blank affils) ---------------
    if any(a["affil"] is None for a in parsed):
        try:
            if doi:
                r = requests.get(f"{OA_API}/works/doi:{doi}", timeout=10)
            else:  # title fallback
                q = urllib.parse.quote(title)
                r = requests.get(f"{OA_API}/works?filter=title.search:{q}&per_page=1",
                                 timeout=10)
            r.raise_for_status()
            work = r.json() if doi else r.json()["results"][0]
            for au in work.get("authorships", []):
                remote = au["author"]["display_name"]
                affil  = first_oa_affil(au) or oa_author_affil(au["author"]["id"])
                for p in parsed:
                    if p["affil"] is None and names_match((p["key_last"], p["key_init"]), remote):
                        p["affil"] = affil
            print("   OpenAlex work ✓")
        except (requests.RequestException, IndexError):
            print("   OpenAlex work ✗")
        time.sleep(PAUSE)

    # --- 3.  Batch author-search fallback ------------------------
    still_missing = [p for p in parsed if p["affil"] is None]
    for i in range(0, len(still_missing), BATCH):
        batch = still_missing[i:i+BATCH]
        for p in batch:
            qry = urllib.parse.quote(f"{p['last']} {p['first'].split('.')[0]}")
            try:
                r = requests.get(f"{OA_API}/authors?search={qry}&per_page=1", timeout=10)
                r.raise_for_status()
                hits = r.json().get("results")
                if hits:
                    p["affil"] = (hits[0].get("last_known_institution") or {}).get("display_name")
            except requests.RequestException:
                pass
            time.sleep(PAUSE)  # per-author pause
        print(f"   Author search batch {i//BATCH+1} ✓")

    # build rows
    for p in parsed:
        yield {
            "author": p["label"],
            "last_name": p["last"],
            "first": p["first"],
            "affiliation": p["affil"],
            "doi": doi,
            "title": title
        }


# ─────────────────────────── MAIN ───────────────────────────
def main():
    if not BIB_FILE.exists():
        raise SystemExit(f"{BIB_FILE} not found")

    with BIB_FILE.open(encoding="utf-8") as fh:
        bib = bibtexparser.load(fh)

    rows = []
    for e in bib.entries:
        if e.get("author"):
            print(f"\n▶ {e.get('ID', 'N/A')}  [{len(e['author'].split(' and '))} authors]")
            rows.extend(process_entry(e))

    pd.DataFrame(rows).to_csv("bib_authors_with_affils.csv", index=False)
    print("\n✓ Finished – results in bib_authors_with_affils.csv")


if __name__ == "__main__":
    main()
