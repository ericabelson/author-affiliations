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
                first_name_parts = " ".join(parts[:-1)

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
                            if (local_author["last_name"].lower() in author_name_oa.lower() and
                                (not local_author["first_name_parts"] or local_author["first_name_parts"][0].lower() in author_name_oa.lower())):
                                if local_author["full_name"] not in current_entry_authors: # Add if not already found for this paper
                                    current_entry_authors[local_author["full_name" = affiliation_name
                                    print(f"    Found (DOI): {local_author['full_name']} - {affiliation_name}")
                                break # Found match for this OA author
                time.sleep(0.1) # Be polite to the API
            except requests.exceptions.RequestException as e:
                print(f"    DOI lookup failed for {doi}: {e}")
            except ValueError as e: # JSON decoding error
                print(f"    Error decoding JSON for DOI {doi}: {e}")


        # For authors not found via DOI, or if no DOI, try with title + author name (less reliable)
        for author_info in authors_list:
            author_full_name = author_info["full_name"]
            if author_full_name in current_entry_authors and current_entry_authors[author_full_name is not None:
                # Already found with DOI and has affiliation
                all_authors_data.append({
                    "author_full_name": author_full_name,
                    "affiliation": current_entry_authors[author_full_name,
                    "doi_used": doi if doi else "N/A",
                    "title_used": title[:100]
                })
                continue
            elif author_full_name in current_entry_authors and current_entry_authors[author_full_name] is None:
                # Found with DOI but no affiliation, still try title search as fallback
                pass


            # Fallback to title search if DOI didn't yield this author or no DOI
            # This part is more complex due to disambiguation challenges
            print(f"  Querying OpenAlex with Title for: {author_full_name} (Title: '{title[:30]}...')")
            # Ensure title is not too short for a meaningful search
            if title and len(title) > 10 :
                # Search for works by title, then try to match author
                # A simpler approach: search for author and see if any of their works match the title (approx.)
                # This requires careful matching. For now, let's keep it a bit simpler and acknowledge its limitations.
                # query_name = f"{author_info['first_name_parts']} {author_info['last_name']}"
                # search_url = f"https://api.openalex.org/authors?search={requests.utils.quote(query_name)}"
                # For simplicity, we'll rely on the DOI lookup for now, as title-based matching
                # without more sophisticated disambiguation is tricky and error-prone.
                # If we want to implement title-based search effectively, we'd:
                # 1. Search for the work by title: https://api.openalex.org/works?search={title}
                # 2. In the results, iterate through authorships and match by name.

                # For this script, if DOI didn't work for a specific author, we'll mark affiliation as None.
                # A more advanced version could implement the title + author search more robustly.
                affiliation = current_entry_authors.get(author_full_name) # Might be None if DOI found paper but not this author's affil
                all_authors_data.append({
                    "author_full_name": author_full_name,
                    "affiliation": affiliation,
                    "doi_used": doi if doi else "N/A",
                    "title_used": title[:100]
                })
                if affiliation is None:
                    print(f"    Could not find affiliation for {author_full_name} via DOI (or no DOI). Title-based fallback not fully implemented for individual author if DOI fails.")

            else: # No DOI and no sufficient title
                 all_authors_data.append({
                    "author_full_name": author_full_name,
                    "affiliation": None,
                    "doi_used": "N/A",
                    "title_used": title[:100 if title else "N/A"
                })
                 print(f"    Skipping OpenAlex query for {author_full_name} due to missing DOI and insufficient title.")
            time.sleep(0.1) # Be polite

    # Create DataFrame and remove duplicates, keeping the first non-null affiliation if any
    df = pd.DataFrame(all_authors_data)
    if not df.empty:
        df_deduplicated = (df.sort_values('affiliation', na_position='last')
                           .drop_duplicates(subset=['author_full_name'], keep='first'))
        # Prioritize entries where a DOI was used if names are identical
        df_deduplicated = (df_deduplicated.sort_values('doi_used', ascending=False, na_position='last')
                                     .drop_duplicates(subset=['author_full_name'], keep='first'))
        return df_deduplicated.sort_values('author_full_name')
    return df

if __name__ == "__main__":
    # Create a dummy works.bib for testing if it doesn't exist
    dummy_bib_content = """
    @article{Kling2021,
        author = {Kling, Matthias M. and Govaerts, Lynn and Nuts, Felix A. and Borer, Elizabeth T.},
        title = {Global grassland productivity response to species and functional trait composition},
        journal = {Nature Ecology & Evolution},
        year = {2021},
        volume = {5},
        pages = {311--320},
        doi = {10.1038/s41559-020-01362-x}
    }
    @article{Smith2020,
        author = {Smith, John P. and Doe, Jane X.},
        title = {A study on interesting things},
        journal = {Journal of Studies},
        year = {2020},
        doi = {10.1234/js.2020.5678}
    }
    @inproceedings{Alon2019,
      author    = {Alon, M. and Chen, Wei},
      title     = {Deep Learning for Citations},
      booktitle = {Proceedings of the Conference},
      year      = {2019}
    }
    """
    try:
        with open("works.bib", "r") as f:
            pass
        print("Using existing works.bib file.")
    except FileNotFoundError:
        with open("works.bib", "w", encoding='utf-8') as f:
            f.write(dummy_bib_content)
        print("Created a dummy works.bib for testing.")

    affiliations_df = get_affiliations_from_bib(bib_file_path="works.bib")

    if not affiliations_df.empty:
        output_csv_path = "authors_with_affiliations.csv"
        affiliations_df.to_csv(output_csv_path, index=False, encoding='utf-8')
        print(f"\nResults saved to {output_csv_path}")
        print("\nPreview of the first few rows:")
        print(affiliations_df.head())
    else:
        print("\nNo affiliation data to save.")
