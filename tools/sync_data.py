# -*- coding: utf-8 -*-
"""Rigenera il bundle frontend (frontend/src/data/*.json + index.ts) da backend/server.py.

Uso:  python tools/sync_data.py
Sostituisce i vecchi script temporanei _gen_bundle.py. Dopo ogni modifica ai
dataset in server.py eseguire questo script e poi tools/validate_data.py.
"""
import json
import os

from datasets import DATA_DIR, DATASETS, load_datasets_from_server


def main():
    data = load_datasets_from_server()
    for var, fname in DATASETS.items():
        path = os.path.join(DATA_DIR, f"{fname}.json")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data[var], fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"{fname}.json: {len(data[var])} voci")

    lines = ["// AUTO-GENERATO da tools/sync_data.py — non modificare a mano", ""]
    for _, fname in DATASETS.items():
        lines.append(f"import {fname} from './{fname}.json';")
    lines.append("")
    for var, fname in DATASETS.items():
        lines.append(f"export const {var} = {fname} as any[];")
    lines.append("")
    with open(os.path.join(DATA_DIR, "index.ts"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    print("index.ts rigenerato")


if __name__ == "__main__":
    main()
