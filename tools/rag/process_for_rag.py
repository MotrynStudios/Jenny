#!/usr/bin/env python3
"""
Process extracted modpack data for RAG (Retrieval-Augmented Generation)
Converts raw JSON data into structured documents optimized for vector embeddings
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from collections import defaultdict
import re

# Set up logging with absolute path
script_dir = Path(__file__).resolve().parents[2]
logs_dir = script_dir / "logs"
logs_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(logs_dir / 'processing.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class Document:
    """A document chunk for RAG"""
    text: str
    metadata: Dict[str, Any]
    doc_id: str


class ModpackDataProcessor:
    """Processes extracted modpack data for RAG"""
    
    def __init__(self, raw_data_dir: str, output_dir: str):
        self.raw_data_dir = Path(raw_data_dir)
        self.output_dir = Path(output_dir)
        self.processed_dir = self.output_dir / "processed"
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        
        # Statistics
        self.total_documents = 0
        self.total_chunks = 0
        
    def load_mod_metadata(self, mod_dir: Path) -> Optional[Dict[str, Any]]:
        """Load mod metadata from JSON file"""
        metadata_path = mod_dir / "metadata.json"
        if not metadata_path.exists():
            return None
        
        with open(metadata_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def load_language_data(self, mod_dir: Path) -> Optional[Dict[str, str]]:
        """Load language data from JSON file"""
        lang_path = mod_dir / "language.json"
        if not lang_path.exists():
            return None
        
        try:
            with open(lang_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Could not read language data %s: %s", lang_path, error)
            return None
    
    def load_recipes(self, mod_dir: Path) -> Optional[List[Dict[str, Any]]]:
        """Load recipe data from JSON file"""
        recipes_path = mod_dir / "recipes.json"
        if not recipes_path.exists():
            return None
        
        try:
            with open(recipes_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
            if isinstance(data, dict):
                nested = data.get("recipes")
                if isinstance(nested, list):
                    return [row for row in nested if isinstance(row, dict)]
                return [data]
            return []
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Could not read recipes %s: %s", recipes_path, error)
            return []
    
    def load_advancements(self, mod_dir: Path) -> Optional[List[Dict[str, Any]]]:
        """Load advancement data from JSON file"""
        advancements_path = mod_dir / "advancements.json"
        if not advancements_path.exists():
            return None
        
        try:
            with open(advancements_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
            if isinstance(data, dict):
                nested = data.get("advancements")
                return [row for row in nested if isinstance(row, dict)] if isinstance(nested, list) else [data]
            return []
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Could not read advancements %s: %s", advancements_path, error)
            return []
    
    def load_items_blocks(self, mod_dir: Path) -> Optional[Dict[str, List[str]]]:
        """Load items and blocks data from JSON file"""
        items_blocks_path = mod_dir / "items_blocks.json"
        if not items_blocks_path.exists():
            return None
        
        with open(items_blocks_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def load_gun_data(self, mod_dir: Path) -> List[Dict[str, Any]]:
        """Load structured gunpack records emitted by the TaCZ extractor."""
        path = mod_dir / "gun_data.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Could not read TaCZ gun data %s: %s", path, error)
            return []

    def load_structured_rows(self, mod_dir: Path, filename: str) -> List[Dict[str, Any]]:
        """Load extractor-owned JSON row lists, tolerating older root shapes."""
        path = mod_dir / filename
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
            if isinstance(data, dict):
                return [data]
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Could not read structured data %s: %s", path, error)
        return []

    def create_custom_data_documents(self, mod_id: str, display_name: str,
                                     rows: List[Dict[str, Any]]) -> List[Document]:
        """Flatten custom per-mod JSON records into searchable evidence notes."""
        documents = []
        for row in rows:
            fields = []

            def visit(value: Any, prefix: str = "data") -> None:
                if isinstance(value, dict):
                    for key, nested in value.items():
                        if not str(key).startswith("_"):
                            visit(nested, f"{prefix}.{key}")
                elif isinstance(value, list):
                    for index, nested in enumerate(value):
                        visit(nested, f"{prefix}[{index}]")
                elif value is not None and str(value).strip():
                    fields.append(f"{prefix}: {value}")

            visit(row.get("data", row))
            path = str(row.get("_data_path", "unknown JSON data"))
            text = (f"Custom structured data from {display_name} ({mod_id})\n"
                    f"Namespace: {row.get('_namespace', mod_id)}\n"
                    f"Category: {row.get('_category', 'custom')}\nSource: {path}\n" + "\n".join(fields))
            if not fields:
                continue
            safe_path = re.sub(r"[^a-zA-Z0-9_-]+", "_", path)[:140]
            documents.append(Document(text=text[:6000], metadata={
                "mod_id": mod_id, "display_name": display_name,
                "document_type": "mod_data", "data_category": str(row.get("_category", "custom")),
                "namespace": str(row.get("_namespace", mod_id)), "source_path": path,
            }, doc_id=f"{mod_id}_custom_{safe_path}"))
        return documents

    def create_asset_documents(self, mod_id: str, display_name: str,
                               rows: List[Dict[str, Any]], language_data: Dict[str, str]) -> List[Document]:
        """Index image/model identifiers and localization hints, not image pixels."""
        if not rows:
            return []
        documents = []
        asset_lines = []
        for row in rows[:500]:
            asset_type = str(row.get("_asset_type", "asset"))
            asset_path = str(row.get("_asset_path", "unknown"))
            identifier = str(row.get("_asset_id", asset_path))
            normalized_id = identifier.replace("/", ".")
            name_hints = [value for key, value in language_data.items()
                          if normalized_id in key and isinstance(value, str)]
            references = row.get("textures", [])
            localized = ", ".join(name_hints[:2]) or "no localized name"
            texture_refs = ", ".join(map(str, references[:8])) if isinstance(references, list) else ""
            asset_lines.append(f"{asset_type}: {identifier} | {localized} | {asset_path}" +
                               (f" | textures: {texture_refs}" if texture_refs else ""))
        text = (f"Visual asset reference manifest for {display_name} ({mod_id}). "
                "This describes resource names and model links only; it does not describe the visual appearance of the image pixels.\n" +
                "\n".join(asset_lines))
        documents.append(Document(text=text[:12000], metadata={
            "mod_id": mod_id, "display_name": display_name,
            "document_type": "asset_reference", "asset_count": len(asset_lines),
        }, doc_id=f"{mod_id}_asset_manifest"))
        return documents

    def create_gun_data_documents(self, mod_id: str, display_name: str,
                                  rows: List[Dict[str, Any]]) -> List[Document]:
        """Index human-readable gun/ammo/attachment stats without binary assets."""
        documents = []
        for row in rows:
            identifier = str(row.get("_data_id", "unknown"))
            category = str(row.get("_category", "data")).lower()
            name = str(row.get("name") or row.get("display_name") or identifier.replace("_", " ").title())
            flattened = []

            def visit(value: Any, prefix: str = "") -> None:
                if isinstance(value, dict):
                    for key, nested in value.items():
                        if key.startswith("_"):
                            continue
                        visit(nested, f"{prefix}.{key}" if prefix else key)
                elif isinstance(value, list):
                    if value and all(not isinstance(item, (dict, list)) for item in value):
                        flattened.append(f"{prefix}: {', '.join(map(str, value))}")
                    else:
                        for index, nested in enumerate(value):
                            visit(nested, f"{prefix}[{index}]")
                elif value is not None and str(value).strip():
                    flattened.append(f"{prefix}: {value}")

            visit(row)
            text = (f"{category.title()} data: {name}\nMod: {display_name}\nMod ID: {mod_id}\n"
                    f"Pack: {row.get('_pack_name', 'unknown')}\nIdentifier: {identifier}\n" + "\n".join(flattened))
            documents.append(Document(text=text[:6000], metadata={
                "mod_id": mod_id, "display_name": display_name,
                "document_type": "mod_stat", "stat_category": category,
                "stat_name": name, "data_id": identifier,
                "pack_name": str(row.get("_pack_name", "unknown")),
            }, doc_id=f"{mod_id}_{row.get('_pack_name', 'pack')}_{category}_{identifier}"))
        return documents
    
    def create_mod_overview_document(self, metadata: Dict[str, Any], language_data: Dict[str, str]) -> Document:
        """Create a comprehensive overview document for a mod"""
        mod_id = metadata.get('mod_id', 'unknown')
        display_name = metadata.get('display_name', mod_id)
        description = metadata.get('description', 'No description available')
        authors = metadata.get('authors', [])
        version = metadata.get('version', 'unknown')
        
        # Build overview text
        text_parts = [
            f"# {display_name}",
            f"**Mod ID:** {mod_id}",
            f"**Version:** {version}",
            f"**Authors:** {', '.join(authors) if authors else 'Unknown'}",
            f"",
            f"## Description",
            f"{description}",
            f""
        ]
        
        # Add key features from language data if available
        if language_data:
            # Look for advancement descriptions which often indicate features
            features = []
            for key, value in language_data.items():
                if key.startswith('advancement.') and key.endswith('.desc'):
                    feature_name = key.split('.')[-2].replace('_', ' ').title()
                    features.append(f"- {feature_name}: {value}")
            
            if features:
                text_parts.extend([
                    "## Key Features",
                    *features[:10],  # Limit to top 10 features
                    ""
                ])
        
        text = "\n".join(text_parts)
        
        return Document(
            text=text,
            metadata={
                'mod_id': mod_id,
                'display_name': display_name,
                'document_type': 'mod_overview',
                'version': version
            },
            doc_id=f"{mod_id}_overview"
        )
    
    def create_item_documents(self, mod_id: str, display_name: str, language_data: Dict[str, str]) -> List[Document]:
        """Create documents for individual items"""
        documents = []
        
        for key, value in language_data.items():
            if key.startswith('item.'):
                # Extract item name from key
                item_key = key.replace(f'item.{mod_id}.', '').replace('_', ' ')
                item_name = value  # This is the display name
                
                # Look for related description in language data
                desc_key = f"{key}.description"
                description = language_data.get(desc_key, '')
                
                text = f"**Item:** {item_name}\n"
                if description:
                    text += f"**Description:** {description}\n"
                text += f"**Mod:** {display_name}\n"
                text += f"**Mod ID:** {mod_id}\n"
                
                documents.append(Document(
                    text=text,
                    metadata={
                        'mod_id': mod_id,
                        'display_name': display_name,
                        'document_type': 'item',
                        'item_name': item_name,
                        'item_key': item_key
                    },
                    doc_id=f"{mod_id}_item_{item_key.replace(' ', '_')}"
                ))
        
        return documents
    
    def create_block_documents(self, mod_id: str, display_name: str, language_data: Dict[str, str]) -> List[Document]:
        """Create documents for individual blocks"""
        documents = []
        
        for key, value in language_data.items():
            if key.startswith('block.'):
                # Extract block name from key
                block_key = key.replace(f'block.{mod_id}.', '').replace('_', ' ')
                block_name = value  # This is the display name
                
                # Look for related description in language data
                desc_key = f"{key}.description"
                description = language_data.get(desc_key, '')
                
                text = f"**Block:** {block_name}\n"
                if description:
                    text += f"**Description:** {description}\n"
                text += f"**Mod:** {display_name}\n"
                text += f"**Mod ID:** {mod_id}\n"
                
                documents.append(Document(
                    text=text,
                    metadata={
                        'mod_id': mod_id,
                        'display_name': display_name,
                        'document_type': 'block',
                        'block_name': block_name,
                        'block_key': block_key
                    },
                    doc_id=f"{mod_id}_block_{block_key.replace(' ', '_')}"
                ))
        
        return documents
    
    def create_recipe_documents(self, mod_id: str, display_name: str, recipes: List[Dict[str, Any]], language_data: Dict[str, str]) -> List[Document]:
        """Create documents for crafting recipes"""
        documents = []
        
        for recipe in recipes:
            # Extract recipe type from file path or structure
            file_path = recipe.get('_file_path', '')
            recipe_type = recipe.get('type', 'unknown')
            
            # Try to get the result item name
            result = recipe.get('result', {})
            if isinstance(result, dict):
                result_item = result.get('item', result.get('id', 'unknown'))
                result_count = result.get('count', 1)
            else:
                result_item = str(result)
                result_count = 1
            
            # Normalize to a string up front: result_item can come back as
            # a non-string value (e.g. a number/tag) from odd recipe JSON,
            # and doc_id below does string operations on it.
            result_item = str(result_item)

            # Try to get a human-readable name from language data
            item_name = language_data.get(f'item.{mod_id}.{result_item}', result_item)
            
            # Format ingredients
            ingredients = recipe.get('ingredients', recipe.get('key', {}))
            ingredient_text = []
            
            if isinstance(ingredients, dict):
                for slot, ingredient in ingredients.items():
                    if isinstance(ingredient, list):
                        for item in ingredient:
                            item_id = item.get('item', '') if isinstance(item, dict) else str(item)
                            ingredient_text.append(item_id)
                    elif isinstance(ingredient, dict):
                        item_id = ingredient.get('item', '')
                        ingredient_text.append(item_id)
            
            text = f"**Recipe:** {item_name}\n"
            text += f"**Result Count:** {result_count}\n"
            text += f"**Recipe Type:** {recipe_type}\n"
            text += f"**Mod:** {display_name}\n"
            text += f"**Ingredients:** {', '.join(ingredient_text)}\n"
            
            documents.append(Document(
                text=text,
                metadata={
                    'mod_id': mod_id,
                    'display_name': display_name,
                    'document_type': 'recipe',
                    'recipe_type': recipe_type,
                    'result_item': item_name,
                    # Stored as a joined string, not a raw list. chromadb's
                    # metadata validation rejects an empty list outright
                    # ("Expected metadata list value for key 'ingredients'
                    # to be non-empty in add."), and any recipe whose
                    # ingredients couldn't be parsed (or that legitimately
                    # has none) produces exactly that empty list, which
                    # crashes the entire batch .add() call, not just that
                    # one recipe.
                    'ingredients': ', '.join(ingredient_text) if ingredient_text else 'none'
                },
                doc_id=f"{mod_id}_recipe_{result_item.replace(' ', '_')}"
            ))
        
        return documents
    
    def create_advancement_documents(self, mod_id: str, display_name: str, advancements: List[Dict[str, Any]], language_data: Dict[str, str]) -> List[Document]:
        """Create documents for advancements/achievements"""
        documents = []
        
        for idx, advancement in enumerate(advancements):
            # Extract advancement info
            file_path = advancement.get('_file_path', '')
            if file_path:
                advancement_id = file_path.split('/')[-1].replace('.json', '')
            else:
                # Without a file path there's nothing to derive an id from.
                # Fall back to a positional id instead of leaving this
                # blank, since a blank advancement_id means every such
                # advancement collides on the same doc_id
                # ("{mod_id}_advancement_") and silently overwrites the
                # previous one in the vector store.
                advancement_id = f"unknown_{idx}"
            
            # Try to get advancement name and description from language data
            name_key = f'advancement.{mod_id}.{advancement_id}'
            desc_key = f'advancement.{mod_id}.{advancement_id}.desc'
            
            name = language_data.get(name_key, advancement_id.replace('_', ' ').title())
            description = language_data.get(desc_key, '')
            
            # Get requirements
            requirements = advancement.get('criteria', {})
            
            text = f"**Achievement:** {name}\n"
            if description:
                text += f"**Description:** {description}\n"
            text += f"**Mod:** {display_name}\n"
            text += f"**Requirements:** {json.dumps(requirements, indent=2)}\n"
            
            documents.append(Document(
                text=text,
                metadata={
                    'mod_id': mod_id,
                    'display_name': display_name,
                    'document_type': 'advancement',
                    'advancement_name': name,
                    'advancement_id': advancement_id
                },
                doc_id=f"{mod_id}_advancement_{advancement_id}"
            ))
        
        return documents
    
    def process_mod(self, mod_dir: Path) -> List[Document]:
        """Process a single mod's data into documents"""
        logger.info(f"Processing mod: {mod_dir.name}")
        
        # Load all data
        metadata = self.load_mod_metadata(mod_dir)
        if not metadata:
            logger.warning(f"No metadata found for {mod_dir.name}")
            return []
        
        language_data = self.load_language_data(mod_dir) or {}
        recipes = self.load_recipes(mod_dir) or []
        advancements = self.load_advancements(mod_dir) or []
        gun_data = self.load_gun_data(mod_dir)
        custom_data = self.load_structured_rows(mod_dir, "custom_data.json")
        asset_data = self.load_structured_rows(mod_dir, "asset_manifest.json")
        
        mod_id = metadata.get('mod_id', mod_dir.name)
        display_name = metadata.get('display_name', mod_id)
        
        documents = []
        
        # Create overview document
        overview_doc = self.create_mod_overview_document(metadata, language_data)
        documents.append(overview_doc)
        
        # Create item documents
        if language_data:
            item_docs = self.create_item_documents(mod_id, display_name, language_data)
            documents.extend(item_docs)
        
        # Create block documents
        if language_data:
            block_docs = self.create_block_documents(mod_id, display_name, language_data)
            documents.extend(block_docs)
        
        # Create recipe documents
        if recipes:
            recipe_docs = self.create_recipe_documents(mod_id, display_name, recipes, language_data)
            documents.extend(recipe_docs)
        
        # Create advancement documents
        if advancements:
            advancement_docs = self.create_advancement_documents(mod_id, display_name, advancements, language_data)
            documents.extend(advancement_docs)

        if gun_data:
            documents.extend(self.create_gun_data_documents(mod_id, display_name, gun_data))
        if custom_data:
            documents.extend(self.create_custom_data_documents(mod_id, display_name, custom_data))
        if asset_data:
            documents.extend(self.create_asset_documents(mod_id, display_name, asset_data, language_data))
        
        return documents
    
    def chunk_documents(self, documents: List[Document], max_chunk_size: int = 700) -> List[Document]:
        """Split large documents into smaller chunks for better retrieval"""
        chunked_documents = []
        
        for doc in documents:
            text = doc.text or ""
            # Some configs end with a newline that used to create a final
            # whitespace-only chunk. Empty chunks consume vector slots but can
            # never provide useful evidence.
            if not text.strip():
                continue
            if len(text) <= max_chunk_size:
                chunked_documents.append(doc)
                continue
            
            # Split document into chunks
            chunks = []
            current_chunk = ""
            lines = text.split('\n')
            
            for line in lines:
                if len(current_chunk) + len(line) + 1 <= max_chunk_size:
                    current_chunk += line + '\n'
                else:
                    if current_chunk and current_chunk.strip():
                        chunks.append(current_chunk.strip())
                    current_chunk = line + '\n'
            
            if current_chunk and current_chunk.strip():
                chunks.append(current_chunk.strip())
            
            # Create chunked documents
            for i, chunk in enumerate(chunks):
                chunked_doc = Document(
                    text=chunk,
                    metadata={
                        **doc.metadata,
                        'chunk_index': i,
                        'total_chunks': len(chunks)
                    },
                    doc_id=f"{doc.doc_id}_chunk_{i}"
                )
                chunked_documents.append(chunked_doc)
        
        return chunked_documents
    
    def save_documents(self, documents: List[Document], filename: str):
        """Save processed documents to JSON file"""
        data = [
            {
                'text': doc.text,
                'metadata': doc.metadata,
                'doc_id': doc.doc_id
            }
            for doc in documents
        ]
        
        output_path = self.processed_dir / filename
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved {len(documents)} documents to {output_path}")
    
    def run(self, limit: Optional[int] = None):
        """Run the data processing pipeline"""
        logger.info("Starting modpack data processing for RAG")
        
        # Get all mod directories
        mod_dirs = [d for d in self.raw_data_dir.iterdir() if d.is_dir()]
        
        if limit:
            mod_dirs = mod_dirs[:limit]
            logger.info(f"Limited to first {limit} mods")
        
        all_documents = []
        
        for i, mod_dir in enumerate(mod_dirs, 1):
            logger.info(f"Progress: {i}/{len(mod_dirs)}")
            
            try:
                documents = self.process_mod(mod_dir)
                all_documents.extend(documents)
                
            except Exception as e:
                logger.error(f"Error processing {mod_dir.name}: {e}")

        # Minecraft instance configs are extracted separately from mod JARs.
        config_path = self.raw_data_dir / "configs.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config_files = json.load(f)
                for config in config_files:
                    relative_path = str(config.get("path", "unknown"))
                    text = str(config.get("text", ""))
                    if not text.strip():
                        continue
                    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", relative_path).strip("_")
                    all_documents.append(Document(
                        text=f"Minecraft config file: {relative_path}\n\n{text}",
                        metadata={
                            "mod_id": "minecraft_config",
                            "display_name": relative_path,
                            "document_type": "config_file",
                            "source_path": relative_path,
                        },
                        doc_id=f"config_{safe_id or 'unknown'}",
                    ))
            except (OSError, json.JSONDecodeError, TypeError) as error:
                logger.error("Could not process extracted config files: %s", error)
        
        # Chunk documents
        logger.info("Chunking documents...")
        chunked_documents = self.chunk_documents(all_documents)
        
        # Save documents
        self.save_documents(chunked_documents, "all_documents.json")
        
        # Create document statistics
        stats = {
            'total_documents': len(chunked_documents),
            'original_documents': len(all_documents),
            'document_types': defaultdict(int),
            'mods_processed': len(mod_dirs)
        }
        
        for doc in chunked_documents:
            doc_type = doc.metadata.get('document_type', 'unknown')
            stats['document_types'][doc_type] += 1
        
        stats_path = self.processed_dir / "processing_stats.json"
        with open(stats_path, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, default=str)
        
        # Log final statistics
        logger.info("=" * 50)
        logger.info("Processing Complete")
        logger.info(f"Total documents: {len(chunked_documents)}")
        logger.info(f"Document types: {dict(stats['document_types'])}")
        logger.info(f"Mods processed: {stats['mods_processed']}")
        logger.info("=" * 50)


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Process modpack data for RAG')
    parser.add_argument('--raw-data-dir', default=str(script_dir / 'data' / 'raw_data'), help='Directory containing raw extracted data')
    parser.add_argument('--output-dir', default=str(script_dir / 'data'), help='Output directory for processed data')
    parser.add_argument('--limit', type=int, help='Limit number of mods to process (for testing)')
    
    args = parser.parse_args()
    
    processor = ModpackDataProcessor(args.raw_data_dir, args.output_dir)
    processor.run(limit=args.limit)


if __name__ == "__main__":
    main()
