"""
clean_dataset.py - repairs puppet_dataset.jsonl

Scans every line of the dataset, reports corrupt rows (blank lines,
invalid JSON, null/missing/empty 'text'), backs up the original file,
then rewrites it with only valid rows.

Run:  python clean_dataset.py
"""

import json
import shutil

DATASET_PATH = r"E:\puppet_ai\puppet_dataset.jsonl"
BACKUP_PATH = DATASET_PATH + ".bak"


def main():
    # 1. Backup the original before touching it
    shutil.copy2(DATASET_PATH, BACKUP_PATH)
    print(f"Backup saved to: {BACKUP_PATH}")

    # 2. Scan every line, classify good vs corrupt
    good_rows = []
    bad_lines = []          # (line_number, reason)
    total = 0

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            total += 1
            line = raw.strip()

            if not line:
                bad_lines.append((line_no, "blank line"))
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                bad_lines.append((line_no, f"invalid JSON ({e})"))
                continue

            text = row.get("text") if isinstance(row, dict) else None
            if not isinstance(text, str) or not text.strip():
                bad_lines.append((line_no, f"'text' is {text!r} (null/missing/empty)"))
                continue

            good_rows.append(row)

    # 3. Report
    print(f"\nLines scanned : {total}")
    print(f"Valid rows    : {len(good_rows)}")
    print(f"Corrupt rows  : {len(bad_lines)}")
    for line_no, reason in bad_lines:
        print(f"  - line {line_no}: {reason}")

    if not bad_lines:
        print("\nDataset was already clean - nothing removed.")
        return

    # 4. Rewrite the file with only valid rows
    with open(DATASET_PATH, "w", encoding="utf-8") as f:
        for row in good_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\nCleaned dataset written to {DATASET_PATH}")
    print("If anything looks wrong, restore with:")
    print(f'  copy "{BACKUP_PATH}" "{DATASET_PATH}"')


if __name__ == "__main__":
    main()
