#!/usr/bin/env python3
"""Build or refresh Jenny's local Minecraft mod and config knowledge index."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXTRACTOR = Path(__file__).with_name("extract_modpack_data.py")
PROCESSOR = Path(__file__).with_name("process_for_rag.py")


def run_step(command: list[str], label: str) -> None:
    print(f"\n== {label} ==")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mods-dir", type=Path, default=PROJECT_ROOT / "mods", help="Minecraft instance mods folder")
    parser.add_argument("--config-dir", type=Path, default=PROJECT_ROOT / "config", help="Minecraft instance config folder")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data", help="Generated data/index folder")
    parser.add_argument("--limit", type=int, help="Limit mod JARs for a quick development run")
    args = parser.parse_args()
    output = args.output_dir.resolve()

    extract_command = [sys.executable, str(EXTRACTOR), "--mods-dir", str(args.mods_dir.resolve()),
                       "--config-dir", str(args.config_dir.resolve()), "--output-dir", str(output)]
    process_command = [sys.executable, str(PROCESSOR), "--raw-data-dir", str(output / "raw_data"),
                       "--output-dir", str(output)]
    if args.limit:
        extract_command.extend(["--limit", str(args.limit)])
        process_command.extend(["--limit", str(args.limit)])

    try:
        run_step(extract_command, "Extract mods and config files")
        run_step(process_command, "Create searchable evidence documents")
        sys.path.insert(0, str(PROJECT_ROOT))
        from jenny_rag_integration import JennyRAGSystem

        rag = JennyRAGSystem(
            processed_data_path=str(output / "processed" / "all_documents.json"),
            embeddings_path=str(output / "embeddings"),
        )
        if not rag.load_documents():
            raise RuntimeError(f"Processed documents were not created at {rag.processed_data_path}")
        if not rag.documents:
            raise RuntimeError(
                f"Processed corpus is empty at {rag.processed_data_path}; "
                "check the mods/config paths and processing.log before building ChromaDB"
            )
        print(f"Loaded {len(rag.documents)} processed evidence documents")
        summary = rag.create_modpack_summary()
        summary_path = output / "processed" / "modpack_summary.txt"
        summary_path.write_text(summary, encoding="utf-8")
        rag.initialize_vector_database()
        print(f"\nIndex ready: {rag.collection.count() if rag.collection else 0} evidence documents")
        print(f"Mod list summary: {summary_path}")
        return 0
    except Exception as error:
        print(f"RAG build failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

