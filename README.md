# Deduplication Tool

This repository provides a command-line utility for identifying potential duplicate records in CSV master data using fuzzy string matching. The tool focuses on spelling similarity and avoids brute-force all-vs-all comparisons by blocking records that share similar prefixes and phonetic signatures.

## Requirements

- Python 3.10+
- [pandas](https://pandas.pydata.org/)
- [rapidfuzz](https://maxbachmann.github.io/RapidFuzz/) (optional but recommended for speed)
- [fuzzywuzzy](https://github.com/seatgeek/fuzzywuzzy) (optional fallback if `rapidfuzz` is unavailable)

If neither `rapidfuzz` nor `fuzzywuzzy` is installed, the script falls back to Python's built-in `difflib`, which is slower but keeps the tool usable.

Install the recommended dependencies:

```bash
pip install pandas rapidfuzz
```

## Usage

```bash
python deduplicate.py <path/to/input.csv> -c "Material Description"
```

### Options

- `-c / --columns`: One or more column names to use when comparing rows. At least one column is required.
- `-t / --threshold`: Similarity threshold (0-100). Rows that score equal to or above the threshold are grouped as potential duplicates. Default: 88.
- `-p / --prefix-length`: Number of leading characters from the normalized comparison text that contribute to the blocking key. Default: 4.
- `--output`: Optional custom output path for the annotated CSV. Defaults to `Potential_Duplicates_Marked.csv` alongside the input file.
- `--log-level`: Configure verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL). Default: INFO.

### Output

The script creates a `Potential_Duplicate_Group` column and sorts the data so that related rows appear together. Duplicate rows are labeled with identifiers such as `DUP_00001`. The script also prints the number of rows that belong to potential duplicate groups and writes the annotated CSV to `Potential_Duplicates_Marked.csv` in the same directory as the input file (unless `--output` is specified).

### Example

```bash
python deduplicate.py PRD-MM_List_20251105_123208.csv -c "Material Description" --threshold 90 --log-level INFO
```

## Logging

Progress is logged throughout the run, including the number of blocking keys created and a running count of processed rows (reported every 1,000 records). This makes it easier to monitor long-running jobs.
