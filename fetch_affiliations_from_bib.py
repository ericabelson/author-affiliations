import bibtexparser
import requests
import pandas as pd
import time
import re

def get_affiliations_from_bib(bib_file_path="works.bib"):
    """
    Parses a BibTeX file, queries OpenAlex for author affiliations based on DOI or title,
    and returns a Pandas DataFrame with author names and their affiliations.
    """
    try:
        with open(bib_file_path, encoding='utf-8') as bibtex_file:
            bib_database = bibtexparser.load(bibtex_file)
    except FileNotFoundError:
        print(f"Error: The file {bib_file_path} was not found.")
        return pd.DataFrame(columns=["author_full_name", "affiliation", "doi_used", "title_used"])
    except Exception as e:
        print(f"Error parsing bibtex file: {e}")
        return pd.DataFrame(columns=["author_full_name", "affiliation", "doi_used", "title_used"])

    all_authors_data = []
    processed_authors_in_entry = set() # To avoid duplicate lookups for the same author in the same paper

    print(f"Found {len(bib_database.entries)} entries in {bib_file_path}.")

    for entry_count, entry in enumerate(bib_database.entries):
        doi = entry.get("doi", "").strip()
        title = entry.get("title", "").strip()
        authors_raw = entry.get("author", "")

        if not authors_raw:
            print(f"Skipping entry {entry.get('ID', 'N/A')} due to missing author field.")
            continue

        # Clean title (remove extra whitespace, LaTeX commands for simplicity here)
        title = re.sub(r'\{.*?\}', '', title) # Remove things like {Title Title}
        title = re.sub(r'\s+', ' ', title).strip()

        print(f"\nProcessing entry {entry_count + 1}/{len(bib_database.entries)}: ID={entry.get('ID', 'N/A')}, Title='{title[:50]}...'")

        authors_list = []
        # Splitting authors - robustly handling "and" and multiple authors
        raw_author_names = re.split(r'\s+and\s+', authors_raw, flags=re.IGNORECASE)
        for author_name_str in raw_author_names:
            # Basic parsing: Last, First or First Last
            if ',' in author_name_str:
                parts = author_name_str.split(',', 1)
                last_name = parts[0].strip()
                first_name_parts = parts[1].strip()
            else:
                parts = author_name_str.strip().split(' ')
                last_name = parts[-1]
                first_name_parts = " ".join(parts[:-1])

            # Normalize to "First Last" for consistency in lookups if needed
            # and for the final output, though OpenAlex might handle variations.
            full_name_normalized = f"{first_name_parts} {last_name}".strip()
            authors_list.append({"full_name": full_name_normalized, "last_name": last_name, "first_name_parts": first_name_parts})

        current_entry_authors = {} # To store affiliations found for authors in this specific entry

        # Try DOI first
        if doi:
            print(f"  Querying OpenAlex with DOI: {doi}")
            url = f"https://api.openalex.org/works/doi:{doi}"
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status() # Raise an exception for HTTP errors
                work_data = response.json()
                
                if work_data and "authorships" in work_data:
                    for authorship in work_data["authorships"]:
                        author_oa = authorship.get("author", {})
                        author_name_oa = author_oa.get("display_name", "")
                        institution = authorship.get("institutions", [{}])[0] # Take the first institution
                        affiliation_name = institution.get("display_name", None)
                        
                        # Match OpenAlex author to our parsed author list
                        for local_author in authors_list:
                            # A simple match: check if OpenAlex name contains local parsed last name and first initial
                            # This could be made more robust
                            if (local_author["last_name".lower() in author_name_oa.lower() and
                                (not local_author["first_name_parts"] or local_author["first_name_parts"][0].lower() in author_name_oa.lower())):
                                if local_author["full_name"] not in current_entry_authors: # Add if not already found for this paper
                                    current_entry_authors[local_author["full_name" = affiliation_name
                                    print(f"    Found (DOI): {local_author['full_name']} - {affiliation_name}")
                                    # Mark author as processed for this entry to avoid re-adding if matched multiple times by OA data
                                    # Note: current_entry_authors check already does this implicitly for this entry.
                                    # processed_authors_in_entry.add((entry.get('ID', doi), local_author["full_name"]))

                # Populate all_authors_data from current_entry_authors if DOI lookup was successful
                for author_name, affil in current_entry_authors.items():
                    all_authors_data.append({
                        "author_full_name": author_name,
                        "affiliation": affil,
                        "doi_used": doi,
                        "title_used": ""
                    })

                # If all authors found via DOI, we might skip title search for this entry
                # For simplicity, we continue to title search if any author wasn't found or if DOI search failed.
                # A more sophisticated logic could check if all authors_list members are in current_entry_authors.

            except requests.exceptions.RequestException as e:
                print(f"    Error querying OpenAlex with DOI {doi}: {e}")
            except ValueError as e: # Includes JSONDecodeError
                print(f"    Error decoding JSON response for DOI {doi}: {e}")
            time.sleep(0.1) # Politeness delay

        # If DOI is not present, or if not all authors were found via DOI (simplistic check: current_entry_authors is empty or not all authors covered)
        # We will proceed with title-based search if needed.
        # Refined logic: search by title if any author from authors_list is not yet in current_entry_authors

        authors_needing_affiliation_from_title_search = [
            author for author in authors_list if author["full_name"] not in current_entry_authors
        ]

        if title and authors_needing_affiliation_from_title_search:
            print(f"  Querying OpenAlex with Title: {title[:50]}... for {len(authors_needing_affiliation_from_title_search)} authors")
            # Note: OpenAlex work search by title is more complex, often needs author names too for disambiguation
            # For this example, a simple title search then matching authors.
            # Using filter: title.search and then matching authors from results.
            # A more direct way might be to search for works and then iterate authorships.
            # However, to directly get affiliations for specific authors by title, OpenAlex API might not be as direct as by DOI.
            # We'll search for the work by title, then try to match authors.

            search_title_param = requests.utils.quote(title)
            url_title = f"https://api.openalex.org/works?filter=title.search:{search_title_param}"

            # If we have author names, we can try to add them to the filter for better results
            # This is a simplification; OpenAlex filtering can be more nuanced.
            # For example, we could try:
            # if authors_list:
            #    author_name_example = authors_list[0]['last_name'] # Using one author to narrow down
            #    url_title += f",author.search:{requests.utils.quote(author_name_example)}"

            try:
                response = requests.get(url_title, timeout=10)
                response.raise_for_status()
                works_data = response.json()

                if works_data and "results" in works_data and works_data["results"]:
                    # Assuming the first result is the most relevant. This is a big assumption.
                    # A more robust solution would iterate results and match more carefully.
                    work_data_title = works_data["results"][0]

                    if work_data_title and "authorships" in work_data_title:
                        print(f"    Found work by title: {work_data_title.get('display_name', 'N/A')[:50]}...")
                        for authorship in work_data_title["authors
