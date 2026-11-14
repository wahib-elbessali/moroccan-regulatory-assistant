"""Local step for T5/T6 (P6): after `seed`, marks the public documents non-blocking in web-search.

`seed` registers every document as blocking. What turns a public document non-blocking is
RealDocumentRights.set_document_roles (src/core/db/rights.py), which needs Postgres and P5's
routes. Until they exist, this script does the same thing from data/raw/manifest.csv, through the
real leak index. It goes away when P5 publishes through set_document_roles (planned day 7).

Run it inside `api` (`make seed` does): the leak index must be real and web-search reachable.
"""

import csv
import sys
from pathlib import Path

from src.core.config import cfg
from src.core.contracts.ids import make_doc_id
from src.core.contracts.registry import get_leak_index


def main(raw_dir: str = "data/raw") -> int:
    if cfg.contracts.get("leak_index") != "real":
        sys.stderr.write("contracts.leak_index must be 'real': run this inside api\n")
        return 2

    raw = Path(raw_dir)
    leak = get_leak_index()
    done = 0
    missing = 0
    with open(raw / "manifest.csv", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if row.get("visibility", "").strip().lower() != "public":
                continue
            path = raw / row["file"].strip()
            if not path.is_file():
                missing += 1
                print(f"file={row['file']} status=missing")
                continue
            doc_id = make_doc_id(path.read_bytes(), None)  # public documents have no owner
            leak.set_blocking(doc_id, False)
            done += 1
            print(f"doc_id={doc_id} file={row['file']} blocking=False")

    print(f"Summary: non-blocking={done} missing={missing}")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
