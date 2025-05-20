#!/usr/bin/env python3
"""
fetch_affiliations_from_bib.py
──────────────────────────────
Pipeline:
 1.  DOI present?  → Crossref works/DOI
 2.  DOI missing? → Crossref title+first-author search → DOI → step 1
 3.  Any author still blank → OpenAlex /authors?search=  (batches of 25)
Outputs CSV with author, names, affiliation, doi, title.
"""

import bibtexparser, requests, pandas as pd, time, re, html, urllib.parse, random
from pathlib import Path
from unidecode import unidecode

# ───────── CONFIG ─────────────────────────────────────────────
BIB_FILE = Path("works.bib")
CR_W    = "https://api.crossref.org/works/"           # Crossref works
CR_Q    = "https://api.crossref.org/works"            # Crossref query
OA_API  = "https://api.openalex.org/authors"
UA      = {"User-Agent": "affil-fetch/0.4 (your_email@domain.com)"}
PAUSE   = 0.15       # between GETs
BATCH   = 25         # OpenAlex batch size
DOI_RE  = re.compile(r"10\.\d{4,9}/[^\s\}\),;]+", re.I)

session = requests.Session()
session.headers.update(UA)

# ───────── BASIC HELPERS ─────────────────────────────────────
def latex2txt(s: str) -> str:
    return re.sub(r"[\\{}']", "", html.unescape(s or ""))

def extract_doi(entry):
    if (d := entry.get("doi") or entry.get("DOI")):
        return d.strip().lower()
    for v in entry.values():
        if isinstance(v, str) and (m := DOI_RE.search(v)):
            return m.group(0).rstrip(").,;").lower()
    return ""

def parse_authors(raw):
    objs, key = [], {}
    for chunk in re.split(r"\s+and\s+", raw, flags=re.I):
        c = latex2txt(chunk.strip())
        if "," in c:
            last, first = [x.strip() for x in c.split(",", 1)]
        else:
            parts = c.split()
            last, first = parts[-1], " ".join(parts[:-1])
        label = f"{last}, {first}".strip().rstrip(".")
        k_last = unidecode(last).lower()
        k_init = unidecode(first[:1]).lower() if first else ""
        objs.append(dict(label=label,last=last,first=first,
                         k_last=k_last,k_init=k_init,affil=None))
        key[(k_last,k_init)] = label
    return objs, key

def names_match(local, remote):
    r = unidecode(remote).lower()
    return local["k_last"] in r and (not local["k_init"] or local["k_init"] in r)

def cr_affil(blob):
    a = blob.get("affiliation") or []
    return a[0]["name"] if a else None

# ───────── NETWORK WRAPPER WITH BACKOFF ──────────────────────
def get_json(url, tries=4):
    for attempt in range(tries):
        try:
            r = session.get(url, timeout=10)
            if r.status_code in (429, 503):
                time.sleep(2**attempt)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(2**attempt + random.random())
    return None

# ───────── STEP 0:  DOI RESOLUTION WHEN MISSING ──────────────
def find_doi_by_title_author(title, first_last):
    qt = urllib.parse.quote(title[:150])
    qa = urllib.parse.quote(first_last)
    url = f"{CR_Q}?query.title={qt}&query.author={qa}&rows=1&mailto=you@domain.com"
    j = get_json(url)
    if j and (items := j.get("message", {}).get("items")):
        return items[0].get("DOI")
    return None

# ───────── STEP 1:  CROSSREF LOOKUP ───────────────────────────
def crossref_fill(parsed, key_map, doi):
    url = CR_W + urllib.parse.quote(doi) + "?mailto=you@domain.com"
    j = get_json(url)
    if not j: return
    for a in j["message"].get("author", []):
        last, first = a.get("family",""), a.get("given","")
        k = unidecode(last).lower(), (first[:1].lower() if first else "")
        if k in key_map:
            label = key_map[k]
            aff   = cr_affil(a)
            if aff:
                next(p for p in parsed if p["label"]==label)["affil"]=aff

# ───────── STEP 2:  OPENALEX AUTHOR FALLBACK ──────────────────
def openalex_batch_fill(objs):
    for o in objs:
        qry = urllib.parse.quote(f"{o['last']} {o['first'].split('.')[0]}")
        j = get_json(f"{OA_API}?search={qry}&per-page=1")
        if j and (res := j.get("results")):
            o["affil"] = (res[0].get("last_known_institution") or {}
                          ).get("display_name")
        time.sleep(PAUSE)

# ───────── PER-MANUSCRIPT PIPELINE ───────────────────────────
def process_entry(entry):
    doi   = extract_doi(entry)
    title = latex2txt(entry.get("title","")).strip()
    parsed, key_map = parse_authors(entry["author"])
    # try DOI discovery if needed
    if not doi:
        first_last = parsed[0]["last"]
        doi = find_doi_by_title_author(title, first_last) or ""
        if doi:
            print(f"   DOI found by title/author → {doi}")
    # Crossref fill
    if doi:
        crossref_fill(parsed, key_map, doi)
        print("   Crossref pass ✓")
    else:
        print("   Crossref pass ✗ (no DOI)")
    time.sleep(PAUSE)
    # OpenAlex batches for blanks
    missing = [p for p in parsed if p["affil"] is None]
    for i in range(0, len(missing), BATCH):
        openalex_batch_fill(missing[i:i+BATCH])
        print(f"   OpenAlex batch {i//BATCH+1} ✓")
        time.sleep(5)          # gentle on rate-limit
    # emit rows
    for p in parsed:
        yield dict(author=p["label"],
                   last_name=p["last"],
                   first=p["first"],
                   affiliation=p["affil"],
                   doi=doi,
                   title=title)

# ───────── MAIN ───────────────────────────────────────────────
def main():
    if not BIB_FILE.exists():
        raise SystemExit("works.bib not found")
    with BIB_FILE.open(encoding="utf-8") as fh:
        bib = bibtexparser.load(fh)

    rows=[]
    for e in bib.entries:
        if "author" in e:
            print(f"\n▶ {e.get('ID','N/A')}  ({len(e['author'].split(' and '))} authors)")
            rows.extend(process_entry(e))

    pd.DataFrame(rows).to_csv("bib_authors_with_affils.csv", index=False)
    print("\n✓ Finished – see bib_authors_with_affils.csv")

if __name__ == "__main__":
    main()
