# Author Affiliations Extractor

When submitting NSF grants, applicants must list all co-authors from the current year and the four prior years. Export your works from ORCID as a BibTeX file named `works.bib`, then run this script to gather each paper's authors and their affiliations.

## What it does

`fetch_affiliations_from_bib.py` parses your BibTeX file, looks up missing DOIs, then queries Crossref and OpenAlex to collect affiliation information for every author.
It outputs a CSV `bib_authors_with_affils.csv` with columns for author name, affiliation, DOI, and title.  Use this to compile your required co-author list.

## Usage

```bash
pip install -r requirements.txt
python fetch_affiliations_from_bib.py
```

The script expects `works.bib` in the repository directory and writes `bib_authors_with_affils.csv` when done. Review the script header for settings such as the email used in API queries.

