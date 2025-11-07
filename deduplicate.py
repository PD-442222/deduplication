#!/usr/bin/env python3
"""Command line tool for fuzzy deduplication of CSV master data."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Sequence

try:
    import pandas as pd
except ModuleNotFoundError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "The 'pandas' package is required to run this script. Please install it with 'pip install pandas'."
    ) from exc

try:
    from rapidfuzz import fuzz  # type: ignore

    def similarity(a: str, b: str) -> float:
        return fuzz.token_sort_ratio(a, b)

    FUZZY_LIBRARY = "rapidfuzz"
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    try:
        from fuzzywuzzy import fuzz  # type: ignore

        def similarity(a: str, b: str) -> float:
            return fuzz.token_sort_ratio(a, b)

        FUZZY_LIBRARY = "fuzzywuzzy"
    except ModuleNotFoundError:  # pragma: no cover - optional dependency
        from difflib import SequenceMatcher

        def similarity(a: str, b: str) -> float:
            return SequenceMatcher(None, a, b).ratio() * 100

        FUZZY_LIBRARY = "difflib"


DEFAULT_THRESHOLD = 88.0
DEFAULT_PREFIX_LENGTH = 4


@dataclass
class UnionFind:
    parent: List[int]
    rank: List[int]

    @classmethod
    def create(cls, size: int) -> "UnionFind":
        return cls(list(range(size)), [0] * size)

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: int, b: int) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return
        if self.rank[root_a] < self.rank[root_b]:
            self.parent[root_a] = root_b
        elif self.rank[root_a] > self.rank[root_b]:
            self.parent[root_b] = root_a
        else:
            self.parent[root_b] = root_a
            self.rank[root_a] += 1


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_csv",
        help="Path to the source CSV file (e.g., PRD-MM_List_20251105_123208.csv)",
    )
    parser.add_argument(
        "-c",
        "--columns",
        nargs="+",
        required=True,
        help="Column names that should be compared for duplicate detection (space separated)",
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Similarity threshold (0-100) to consider rows duplicates (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "-p",
        "--prefix-length",
        type=int,
        default=DEFAULT_PREFIX_LENGTH,
        help="Normalized text prefix length used to limit comparisons",
    )
    parser.add_argument(
        "--output",
        help="Optional custom output path. Defaults to Potential_Duplicates_Marked.csv next to the input file.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    return parser.parse_args(argv)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def normalize_text(value: str) -> str:
    cleaned = "".join(ch for ch in value.upper() if ch.isalnum() or ch.isspace())
    return " ".join(cleaned.split())


def soundex(value: str) -> str:
    if not value:
        return "0000"
    value = value.upper()
    first_letter = value[0]
    translations = {
        "BFPV": "1",
        "CGJKQSXZ": "2",
        "DT": "3",
        "L": "4",
        "MN": "5",
        "R": "6",
    }
    char_to_digit = {ch: digit for letters, digit in translations.items() for ch in letters}
    digits: List[str] = []
    previous_digit = ""
    for char in value[1:]:
        digit = char_to_digit.get(char, "")
        if digit != previous_digit:
            if digit:
                digits.append(digit)
            previous_digit = digit
        if len(digits) == 3:
            break
    encoded = first_letter + "".join(digits)
    return encoded.ljust(4, "0")


def build_block_key(text: str, prefix_length: int) -> str:
    prefix = text[:prefix_length]
    primary_word = text.split(" ", 1)[0] if text else ""
    return f"{prefix}|{soundex(primary_word)}"


def create_comparison_series(df: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    missing = [col for col in columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing column(s) in CSV: {', '.join(missing)}")
    combined = df[columns].fillna("").astype(str).agg(" ".join, axis=1)
    return combined.map(normalize_text)


def detect_duplicates(
    df: pd.DataFrame,
    comparison_texts: pd.Series,
    prefix_length: int,
    threshold: float,
) -> pd.Series:
    keys = comparison_texts.map(lambda text: build_block_key(text, prefix_length))
    logging.info("Using fuzzy library: %s", FUZZY_LIBRARY)
    logging.info("Created %d blocking keys", keys.nunique())

    group_counter = 1
    duplicate_labels = pd.Series(data=["" for _ in range(len(df))], index=df.index, dtype="object")
    processed_rows = 0

    for block_value, block_indices in keys.groupby(keys):
        block_list = list(block_indices.index)
        block_size = len(block_list)
        processed_rows += block_size
        if processed_rows % 1000 == 0:
            logging.info("Processed %d rows", processed_rows)
        if block_size < 2:
            continue
        block_texts = comparison_texts.loc[block_list]
        union_find = UnionFind.create(block_size)
        for i in range(block_size - 1):
            text_i = block_texts.iloc[i]
            for j in range(i + 1, block_size):
                text_j = block_texts.iloc[j]
                score = similarity(text_i, text_j)
                if score >= threshold:
                    union_find.union(i, j)
        clusters: defaultdict[int, List[int]] = defaultdict(list)
        for local_idx, global_idx in enumerate(block_list):
            clusters[union_find.find(local_idx)].append(global_idx)
        for members in clusters.values():
            if len(members) < 2:
                continue
            label = f"DUP_{group_counter:05d}"
            group_counter += 1
            for idx in members:
                duplicate_labels.at[idx] = label
    duplicate_labels.replace("", pd.NA, inplace=True)
    return duplicate_labels


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    configure_logging(args.log_level)

    logging.info("Loading CSV: %s", args.input_csv)
    df = pd.read_csv(args.input_csv, dtype=str)
    logging.info("Loaded %d rows and %d columns", len(df), len(df.columns))

    comparison_texts = create_comparison_series(df, args.columns)
    duplicate_labels = detect_duplicates(
        df,
        comparison_texts,
        prefix_length=max(1, args.prefix_length),
        threshold=max(0.0, min(args.threshold, 100.0)),
    )

    df = df.copy()
    df["Potential_Duplicate_Group"] = duplicate_labels

    duplicates_found = duplicate_labels.notna().sum()
    logging.info("Detected %d rows that belong to potential duplicate groups", duplicates_found)
    print(f"Potential duplicate rows detected: {duplicates_found}")

    sort_columns = ["Potential_Duplicate_Group"] + [col for col in args.columns if col in df.columns]
    df.sort_values(by=sort_columns, inplace=True, na_position="last")

    output_path = args.output or os.path.join(
        os.path.dirname(os.path.abspath(args.input_csv)) or ".",
        "Potential_Duplicates_Marked.csv",
    )

    logging.info("Saving annotated CSV to %s", output_path)
    df.to_csv(output_path, index=False)
    logging.info("Processing complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
