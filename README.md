# Author Affiliations Extractor

When submitting NSF grants, applicants must list all co-authors from the prior 48 months. Export your works from ORCID as a BibTeX file named `works.bib`, then run this script to gather each paper's authors and their affiliations.

## What it does

`fetch_affiliations_from_bib.py` parses your BibTeX file, looks up missing DOIs, then queries Crossref and OpenAlex to collect affiliation information for every author.
It outputs a CSV `bib_authors_with_affils.csv` with columns for author name, affiliation, DOI, and title.  

## Usage

```bash
pip install -r requirements.txt
python fetch_affiliations_from_bib.py
```

The script expects `works.bib` in the repository directory and writes `bib_authors_with_affils.csv` when done. No API keys are required. While not necessary, if you want to identify yourself with a contact email, edit the `User-Agent` header at the top of the script; this email is sent with Crossref and OpenAlex requests.

A sample `works.bib` file is included to provide the option to run a reproducible example – replace this file with your `works.bib ` file exported from ORCID.
