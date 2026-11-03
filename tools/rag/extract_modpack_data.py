#!/usr/bin/env python3
"""
Minecraft Modpack Data Extractor
Extracts data from Minecraft mod JAR files for AI processing
"""

import json
import zipfile
import toml
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging
from dataclasses import dataclass, asdict
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
        logging.FileHandler(logs_dir / 'extraction.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class ModMetadata:
    """Metadata extracted from mod JAR files"""
    mod_id: str
    version: str
    display_name: str
    description: str
    authors: List[str]
    dependencies: List[Dict[str, str]]
    file_path: str


@dataclass
class ModData:
    """Complete data extracted from a mod"""
    metadata: ModMetadata
    language_data: Dict[str, str]  # en_us.json content
    recipes: List[Dict[str, Any]]  # Recipe data
    advancements: List[Dict[str, Any]]  # Achievement data
    items: List[str]  # Item names from language files
    blocks: List[str]  # Block names from language files


class ModpackExtractor:
    """Extracts and processes data from Minecraft mod JAR files"""
    
    def __init__(self, mods_dir: str, output_dir: str, config_dir: Optional[str] = None):
        self.mods_dir = Path(mods_dir)
        self.output_dir = Path(output_dir)
        self.config_dir = Path(config_dir) if config_dir else self.mods_dir.parent / "config"
        self.raw_data_dir = self.output_dir / "raw_data"
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
        
        # Statistics
        self.processed_count = 0
        self.failed_count = 0
        self.total_mods = 0
        
    def get_mod_jars(self) -> List[Path]:
        """Get all JAR files from the mods directory"""
        jar_files = sorted(self.mods_dir.rglob("*.jar"))
        # Filter out disabled mods
        jar_files = [f for f in jar_files if not f.name.endswith(".disabled")]
        self.total_mods = len(jar_files)
        logger.info(f"Found {self.total_mods} mod JAR files")
        return jar_files
    
    def extract_mod_metadata(self, jar_path: Path) -> Optional[ModMetadata]:
        """Extract metadata from neoforge.mods.toml or mods.toml"""
        try:
            with zipfile.ZipFile(jar_path, 'r') as jar:
                # Try different possible locations for mods.toml
                possible_paths = [
                    "META-INF/neoforge.mods.toml",
                    "META-INF/mods.toml",
                    "META-INF/forge.mods.toml"
                ]
                
                mods_toml_path = None
                for path in possible_paths:
                    if path in jar.namelist():
                        mods_toml_path = path
                        break
                
                if not mods_toml_path:
                    # Try to extract mod ID from filename as fallback
                    filename = jar_path.stem
                    mod_id = re.sub(r'[-0-9.]+$', '', filename).replace('-', '_')
                    return ModMetadata(
                        mod_id=mod_id,
                        version="unknown",
                        display_name=filename,
                        description="No description available",
                        authors=[],
                        dependencies=[],
                        file_path=str(jar_path)
                    )
                
                # Parse TOML file
                with jar.open(mods_toml_path) as f:
                    content = f.read().decode('utf-8')
                    data = toml.loads(content)
                
                # Extract mod data
                mods_data = data.get('mods', [])
                if not mods_data:
                    return None
                
                mod_info = mods_data[0]
                mod_id = mod_info.get('modId', '').strip()
                version = mod_info.get('version', 'unknown').strip()
                display_name = mod_info.get('displayName', mod_id).strip()
                description = mod_info.get('description', '').strip()
                authors = mod_info.get('authors', '').split(',') if mod_info.get('authors') else []
                
                # Extract dependencies
                dependencies = []
                for dep_key, dep_data in data.items():
                    if dep_key.startswith('dependencies.'):
                        mod_name = dep_key.split('.')[1]
                        dep_info = {
                            'mod_id': mod_name,
                            'type': dep_data.get('type', 'unknown'),
                            'version_range': dep_data.get('versionRange', '*')
                        }
                        dependencies.append(dep_info)
                
                return ModMetadata(
                    mod_id=mod_id,
                    version=version,
                    display_name=display_name,
                    description=description,
                    authors=[a.strip() for a in authors],
                    dependencies=dependencies,
                    file_path=str(jar_path)
                )
                
        except Exception as e:
            logger.error(f"Error extracting metadata from {jar_path.name}: {e}")
            return None
    
    def extract_language_data(self, jar_path: Path, mod_id: str) -> Dict[str, str]:
        """Extract English language data from mod JAR"""
        language_data = {}
        try:
            with zipfile.ZipFile(jar_path, 'r') as jar:
                # Look for English language file
                possible_paths = [
                    f"assets/{mod_id}/lang/en_us.json",
                    f"assets/{mod_id}/lang/en_ud.json",
                    f"assets/{mod_id}/lang/en.json"
                ]
                
                lang_file_path = None
                for path in possible_paths:
                    if path in jar.namelist():
                        lang_file_path = path
                        break
                
                if not lang_file_path:
                    return language_data
                
                with jar.open(lang_file_path) as f:
                    content = f.read().decode('utf-8')
                    language_data = json.loads(content)
                    
        except Exception as e:
            logger.warning(f"Error extracting language data from {jar_path.name}: {e}")
        
        return language_data
    
    def extract_recipes(self, jar_path: Path, mod_id: str) -> List[Dict[str, Any]]:
        """Extract recipe data from mod JAR"""
        recipes = []
        try:
            with zipfile.ZipFile(jar_path, 'r') as jar:
                # Look for recipe files. Minecraft 1.21 renamed this
                # datapack folder from "recipes" to "recipe" (singular),
                # alongside the same rename for advancements below.
                # Matching both means this keeps working regardless of
                # which Minecraft version the modpack's mods target.
                recipe_pattern = re.compile(rf"data/{mod_id}/(?:recipes|recipe)/.*\.json$")
                
                for file_path in jar.namelist():
                    if recipe_pattern.match(file_path):
                        try:
                            with jar.open(file_path) as f:
                                content = f.read().decode('utf-8')
                                recipe_data = json.loads(content)
                                recipe_data['_file_path'] = file_path
                                recipe_data['_mod_id'] = mod_id
                                recipes.append(recipe_data)
                        except Exception as e:
                            logger.warning(f"Error parsing recipe {file_path}: {e}")
                            
        except Exception as e:
            logger.warning(f"Error extracting recipes from {jar_path.name}: {e}")
        
        return recipes
    
    def extract_advancements(self, jar_path: Path, mod_id: str) -> List[Dict[str, Any]]:
        """Extract advancement data from mod JAR"""
        advancements = []
        try:
            with zipfile.ZipFile(jar_path, 'r') as jar:
                # Look for advancement files. Same 1.21 rename story as
                # recipes above ("advancements" -> "advancement"); matching
                # both plural and singular covers pre- and post-1.21 mods.
                advancement_pattern = re.compile(rf"data/{mod_id}/(?:advancements|advancement)/.*\.json$")
                
                for file_path in jar.namelist():
                    if advancement_pattern.match(file_path):
                        try:
                            with jar.open(file_path) as f:
                                content = f.read().decode('utf-8')
                                advancement_data = json.loads(content)
                                advancement_data['_file_path'] = file_path
                                advancement_data['_mod_id'] = mod_id
                                advancements.append(advancement_data)
                        except Exception as e:
                            logger.warning(f"Error parsing advancement {file_path}: {e}")
                            
        except Exception as e:
            logger.warning(f"Error extracting advancements from {jar_path.name}: {e}")
        
        return advancements
    
    def extract_items_and_blocks(self, language_data: Dict[str, str]) -> tuple[List[str], List[str]]:
        """Extract item and block names from language data"""
        items = []
        blocks = []
        
        for key, value in language_data.items():
            if key.startswith('item.'):
                items.append(value)
            elif key.startswith('block.'):
                blocks.append(value)
        
        return items, blocks
    
    def process_mod(self, jar_path: Path) -> Optional[ModData]:
        """Process a single mod JAR file"""
        logger.info(f"Processing: {jar_path.name}")
        
        # Extract metadata
        metadata = self.extract_mod_metadata(jar_path)
        if not metadata:
            logger.warning(f"Could not extract metadata from {jar_path.name}")
            return None
        
        # Extract other data
        language_data = self.extract_language_data(jar_path, metadata.mod_id)
        recipes = self.extract_recipes(jar_path, metadata.mod_id)
        advancements = self.extract_advancements(jar_path, metadata.mod_id)
        items, blocks = self.extract_items_and_blocks(language_data)
        
        return ModData(
            metadata=metadata,
            language_data=language_data,
            recipes=recipes,
            advancements=advancements,
            items=items,
            blocks=blocks
        )
    
    def save_mod_data(self, mod_data: ModData):
        """Save extracted mod data to JSON files"""
        mod_dir = self.raw_data_dir / mod_data.metadata.mod_id
        mod_dir.mkdir(exist_ok=True)
        
        # Save metadata
        metadata_path = mod_dir / "metadata.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(mod_data.metadata), f, indent=2, ensure_ascii=False)
        
        # Save language data
        if mod_data.language_data:
            lang_path = mod_dir / "language.json"
            with open(lang_path, 'w', encoding='utf-8') as f:
                json.dump(mod_data.language_data, f, indent=2, ensure_ascii=False)
        
        # Save recipes
        if mod_data.recipes:
            recipes_path = mod_dir / "recipes.json"
            with open(recipes_path, 'w', encoding='utf-8') as f:
                json.dump(mod_data.recipes, f, indent=2, ensure_ascii=False)
        
        # Save advancements
        if mod_data.advancements:
            advancements_path = mod_dir / "advancements.json"
            with open(advancements_path, 'w', encoding='utf-8') as f:
                json.dump(mod_data.advancements, f, indent=2, ensure_ascii=False)
        
        # Save items and blocks
        items_blocks_path = mod_dir / "items_blocks.json"
        with open(items_blocks_path, 'w', encoding='utf-8') as f:
            json.dump({
                'items': mod_data.items,
                'blocks': mod_data.blocks
            }, f, indent=2, ensure_ascii=False)
    
    def create_summary(self, all_mod_data: List[ModData]):
        """Create a summary file with all mod information"""
        summary = {
            'total_mods': len(all_mod_data),
            'mods': []
        }
        
        for mod_data in all_mod_data:
            mod_summary = {
                'mod_id': mod_data.metadata.mod_id,
                'version': mod_data.metadata.version,
                'display_name': mod_data.metadata.display_name,
                'description': mod_data.metadata.description,
                'authors': mod_data.metadata.authors,
                'items_count': len(mod_data.items),
                'blocks_count': len(mod_data.blocks),
                'recipes_count': len(mod_data.recipes),
                'advancements_count': len(mod_data.advancements)
            }
            summary['mods'].append(mod_summary)
        
        summary_path = self.output_dir / "modpack_summary.json"
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Summary saved to {summary_path}")

    def extract_config_files(self) -> int:
        """Copy text-based Minecraft configs into the RAG source corpus.

        Files that look like credentials are retained with their values
        redacted. Binary and unusually large files are skipped.
        """
        supported = {".toml", ".json", ".json5", ".yaml", ".yml", ".properties", ".cfg", ".conf", ".ini", ".snbt", ".txt"}
        secret = re.compile(
            r'(?im)^([^\r\n]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)[^\r\n]*?'
            r'(?:=|:)\s*)([^\r\n,}\]]+)',
        )
        configs = []
        if not self.config_dir.exists():
            logger.warning("Config folder not found at %s; skipping config extraction", self.config_dir)
        else:
            for path in self.config_dir.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in supported:
                    continue
                try:
                    if path.stat().st_size > 2_000_000:
                        logger.warning("Skipping config over 2 MB: %s", path)
                        continue
                    content = path.read_text(encoding="utf-8", errors="replace")
                    content = secret.sub(r"\1[REDACTED]", content)
                    configs.append({"path": path.relative_to(self.config_dir).as_posix(), "text": content})
                except OSError as error:
                    logger.warning("Could not read config %s: %s", path, error)
        output = self.raw_data_dir / "configs.json"
        output.write_text(json.dumps(configs, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Extracted %s config files into %s", len(configs), output)
        return len(configs)
    
    def run(self, limit: Optional[int] = None):
        """Run the extraction process"""
        logger.info("Starting modpack data extraction")
        
        jar_files = self.get_mod_jars()
        if limit:
            jar_files = jar_files[:limit]
            logger.info(f"Limited to first {limit} mods")
        
        all_mod_data = []
        
        for i, jar_path in enumerate(jar_files, 1):
            logger.info(f"Progress: {i}/{len(jar_files)}")
            
            try:
                mod_data = self.process_mod(jar_path)
                if mod_data:
                    self.save_mod_data(mod_data)
                    all_mod_data.append(mod_data)
                    self.processed_count += 1
                else:
                    self.failed_count += 1
                    
            except Exception as e:
                logger.error(f"Error processing {jar_path.name}: {e}")
                self.failed_count += 1
        
        # Create summary
        if all_mod_data:
            self.create_summary(all_mod_data)

        self.extract_config_files()
        
        # Log final statistics
        logger.info("=" * 50)
        logger.info("Extraction Complete")
        logger.info(f"Total mods processed: {self.processed_count}")
        logger.info(f"Failed extractions: {self.failed_count}")
        success_rate = (self.processed_count / self.total_mods * 100) if self.total_mods else 0.0
        logger.info(f"Success rate: {success_rate:.1f}%")
        logger.info("=" * 50)


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Extract data from Minecraft modpack')
    parser.add_argument('--mods-dir', default=str(script_dir / 'mods'), help='Directory containing mod JAR files')
    parser.add_argument('--output-dir', default=str(script_dir / 'data'), help='Output directory for extracted data')
    parser.add_argument('--config-dir', help='Minecraft instance config folder (defaults to a sibling config/ folder)')
    parser.add_argument('--limit', type=int, help='Limit number of mods to process (for testing)')
    
    args = parser.parse_args()
    
    extractor = ModpackExtractor(args.mods_dir, args.output_dir, args.config_dir)
    extractor.run(limit=args.limit)


if __name__ == "__main__":
    main()
