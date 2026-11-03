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


def _metadata_text(value: Any, default: str = "") -> str:
    """Normalize TOML metadata values because mods use strings and arrays."""
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value).strip()


def _strip_jsonc_comments(content: str) -> str:
    """Remove // and /* */ comments while preserving quoted JSON strings."""
    result, index, quoted, escaped = [], 0, False, False
    while index < len(content):
        char = content[index]
        if quoted:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            index += 1
            continue
        if char == '"':
            quoted = True
            result.append(char)
            index += 1
        elif char == "/" and index + 1 < len(content) and content[index + 1] == "/":
            while index < len(content) and content[index] not in "\r\n":
                index += 1
        elif char == "/" and index + 1 < len(content) and content[index + 1] == "*":
            index += 2
            while index + 1 < len(content) and content[index:index + 2] != "*/":
                result.append("\n" if content[index] == "\n" else " ")
                index += 1
            index = min(len(content), index + 2)
        else:
            result.append(char)
            index += 1
    return re.sub(r",\s*([}\]])", r"\1", "".join(result))


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
    gun_data: List[Dict[str, Any]]  # TaCZ custom gunpack stats and attachment data
    custom_data: List[Dict[str, Any]]  # Structured per-mod JSON from data and custom namespaces
    asset_data: List[Dict[str, Any]]  # Texture/model references, not raw image pixels


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
        """Read current loader metadata plus legacy pre-1.13 Forge mcmod.info."""
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
                    if "mcmod.info" in jar.namelist():
                        with jar.open("mcmod.info") as source:
                            legacy = json.load(source)
                        if isinstance(legacy, dict):
                            legacy = legacy.get("modList", legacy.get("mods", [legacy]))
                        if isinstance(legacy, list):
                            info = next((row for row in legacy if isinstance(row, dict)), None)
                            if info:
                                mod_id = _metadata_text(info.get("modid") or info.get("modId") or info.get("mod_id"), jar_path.stem)
                                version = _metadata_text(info.get("version"), "unknown")
                                display_name = _metadata_text(info.get("name") or info.get("displayName"), mod_id)
                                description = _metadata_text(info.get("description"))
                                authors_value = info.get("authorList", info.get("authors", []))
                                authors = authors_value if isinstance(authors_value, list) else [authors_value] if authors_value else []
                                return ModMetadata(mod_id, version, display_name, description,
                                                   [_metadata_text(author) for author in authors if _metadata_text(author)], [], str(jar_path))
                    for json_path in ("fabric.mod.json", "quilt.mod.json"):
                        if json_path not in jar.namelist():
                            continue
                        with jar.open(json_path) as source:
                            document = json.load(source)
                        if json_path == "fabric.mod.json":
                            mod_id = _metadata_text(document.get("id"), jar_path.stem)
                            version = _metadata_text(document.get("version"), "unknown")
                            display_name = _metadata_text(document.get("name"), mod_id)
                            authors_value = document.get("authors", [])
                            authors = [_metadata_text(a.get("name") if isinstance(a, dict) else a) for a in authors_value] if isinstance(authors_value, list) else []
                            description = _metadata_text(document.get("description"))
                        else:
                            quilt = document.get("quilt_loader", {})
                            metadata = quilt.get("metadata", {})
                            mod_id = _metadata_text(quilt.get("id"), jar_path.stem)
                            version = _metadata_text(quilt.get("version"), "unknown")
                            display_name = _metadata_text(metadata.get("name"), mod_id)
                            authors_value = metadata.get("contributors", {})
                            authors = [str(value) for value in authors_value.values()] if isinstance(authors_value, dict) else []
                            description = _metadata_text(metadata.get("description"))
                        return ModMetadata(mod_id, version, display_name, description, authors, [], str(jar_path))
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
                if isinstance(mods_data, dict):
                    mods_data = [mods_data]
                if not isinstance(mods_data, list):
                    return None

                mod_info = next((item for item in mods_data if isinstance(item, dict)), None)
                if mod_info is None:
                    logger.warning("No usable [[mods]] entry in %s", jar_path.name)
                    return None
                mod_id = _metadata_text(mod_info.get('modId'))
                if not mod_id:
                    logger.warning("Mod metadata has no modId in %s", jar_path.name)
                    return None
                version = _metadata_text(mod_info.get('version'), 'unknown')
                display_name = _metadata_text(mod_info.get('displayName'), mod_id)
                description = _metadata_text(mod_info.get('description'))
                authors_value = mod_info.get('authors', [])
                if isinstance(authors_value, str):
                    authors = authors_value.split(',') if authors_value else []
                elif isinstance(authors_value, list):
                    authors = [_metadata_text(author) for author in authors_value]
                elif authors_value:
                    authors = [_metadata_text(authors_value)]
                else:
                    authors = []
                
                # Extract dependencies
                dependencies = []
                for dep_key, dep_data in data.items():
                    if dep_key.startswith('dependencies.'):
                        mod_name = dep_key.split('.')[1]
                        # TOML array tables such as [[dependencies.mod]] are
                        # parsed as lists, while single tables are dicts.
                        dep_entries = dep_data if isinstance(dep_data, list) else [dep_data]
                        for dep_entry in dep_entries:
                            if not isinstance(dep_entry, dict):
                                continue
                            dependencies.append({
                                'mod_id': _metadata_text(dep_entry.get('modId'), mod_name),
                                'type': _metadata_text(dep_entry.get('type'), 'unknown'),
                                'version_range': _metadata_text(dep_entry.get('versionRange'), '*'),
                            })
                
                return ModMetadata(
                    mod_id=mod_id,
                    version=version,
                    display_name=display_name,
                    description=description,
                    authors=[author.strip() for author in authors if author.strip()],
                    dependencies=dependencies,
                    file_path=str(jar_path)
                )
                
        except Exception as e:
            logger.error(f"Error extracting metadata from {jar_path.name}: {e}")
            return None
    
    def extract_language_data(self, jar_path: Path, mod_id: str) -> Dict[str, str]:
        """Merge English localization across all resource namespaces in a JAR."""
        language_data = {}
        try:
            with zipfile.ZipFile(jar_path, 'r') as jar:
                paths = [path for path in jar.namelist() if re.match(
                    r"^assets/[^/]+/lang/(en_us|en_US|en|en_ud)\.(json|lang)$", path)]
                for path in sorted(paths):
                    try:
                        with jar.open(path) as source:
                            content = source.read().decode("utf-8-sig")
                        if path.lower().endswith(".json"):
                            data = json.loads(content)
                            if isinstance(data, dict):
                                language_data.update({str(key): _metadata_text(value) for key, value in data.items()})
                        else:
                            # Legacy Forge/FML localization format: key=value.
                            for line in content.splitlines():
                                stripped = line.strip()
                                if stripped and not stripped.startswith(("#", "!")) and "=" in stripped:
                                    key, value = stripped.split("=", 1)
                                    language_data[key.strip()] = value.strip()
                    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as error:
                        logger.warning("Could not parse language file %s in %s: %s", path, jar_path.name, error)
                    
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
                # Resource namespace is not guaranteed to equal the loader's
                # mod ID. This occurs with renamed projects and bundled content.
                recipe_pattern = re.compile(r"^data/([^/]+)/(?:recipes|recipe)/.+\.json$", re.I)
                
                for file_path in jar.namelist():
                    match = recipe_pattern.match(file_path)
                    if match:
                        try:
                            with jar.open(file_path) as f:
                                content = f.read().decode('utf-8')
                                recipe_data = json.loads(content)
                                recipe_data['_file_path'] = file_path
                                recipe_data['_mod_id'] = mod_id
                                recipe_data['_namespace'] = match.group(1)
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
                advancement_pattern = re.compile(r"^data/([^/]+)/(?:advancements|advancement)/.+\.json$", re.I)
                
                for file_path in jar.namelist():
                    match = advancement_pattern.match(file_path)
                    if match:
                        try:
                            with jar.open(file_path) as f:
                                content = f.read().decode('utf-8')
                                advancement_data = json.loads(content)
                                advancement_data['_file_path'] = file_path
                                advancement_data['_mod_id'] = mod_id
                                advancement_data['_namespace'] = match.group(1)
                                advancements.append(advancement_data)
                        except Exception as e:
                            logger.warning(f"Error parsing advancement {file_path}: {e}")
                            
        except Exception as e:
            logger.warning(f"Error extracting advancements from {jar_path.name}: {e}")
        
        return advancements

    def extract_tacz_gun_data(self, jar_path: Path) -> List[Dict[str, Any]]:
        """Extract TaCZ custom gunpack JSON stat records (not models or textures)."""
        records = []
        pattern = re.compile(r"assets/tacz/custom/([^/]+)/data/tacz/data/(guns|ammo|attachments)/(.+?)\.json$", re.I)
        try:
            with zipfile.ZipFile(jar_path, "r") as jar:
                for file_path in jar.namelist():
                    match = pattern.match(file_path)
                    if not match:
                        continue
                    pack_name, category, basename = match.groups()
                    basename = basename.replace("/", "__")
                    try:
                        with jar.open(file_path) as source:
                            data = json.loads(_strip_jsonc_comments(source.read().decode("utf-8-sig")))
                        if not isinstance(data, dict):
                            continue
                        data.update({"_pack_name": pack_name, "_category": category,
                                     "_data_id": basename, "_file_path": file_path,
                                     "_source_mod": "tacz"})
                        records.append(data)
                    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as error:
                        logger.warning("Could not parse TaCZ data %s in %s: %s", file_path, jar_path.name, error)
        except (OSError, zipfile.BadZipFile) as error:
            logger.warning("Could not inspect TaCZ data in %s: %s", jar_path.name, error)
        return records

    def extract_custom_json_data(self, jar_path: Path) -> List[Dict[str, Any]]:
        """Extract structured JSON data used by mods with nonstandard layouts.

        Covers datapack namespaces and mod-owned ``assets/*/custom/*/data``
        trees, which include gunpacks and other custom item/stat registries.
        Standard recipes and advancements remain in their dedicated parsers.
        """
        records: List[Dict[str, Any]] = []
        datapack = re.compile(r"^data/([^/]+)/(.+\.json)$", re.I)
        custom_asset = re.compile(r"^assets/([^/]+)/custom/(.+?/data/.+\.json)$", re.I)
        try:
            with zipfile.ZipFile(jar_path, "r") as jar:
                for file_path in jar.namelist():
                    match = datapack.match(file_path) or custom_asset.match(file_path)
                    if not match:
                        continue
                    namespace, relative_path = match.groups()
                    category = relative_path.split("/", 1)[0].lower()
                    if category in {"recipe", "recipes", "advancement", "advancements"}:
                        continue
                    info = jar.getinfo(file_path)
                    if info.file_size > 1_000_000:
                        logger.debug("Skipping large structured JSON %s", file_path)
                        continue
                    try:
                        with jar.open(file_path) as source:
                            payload = json.loads(_strip_jsonc_comments(source.read().decode("utf-8-sig")))
                        records.append({"_namespace": namespace, "_data_path": file_path,
                                        "_category": category, "data": payload})
                    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as error:
                        logger.debug("Skipping non-standard JSON %s: %s", file_path, error)
                    if len(records) >= 500:
                        logger.warning("Structured JSON record limit reached in %s", jar_path.name)
                        break
        except (OSError, zipfile.BadZipFile) as error:
            logger.warning("Could not inspect custom JSON data in %s: %s", jar_path.name, error)
        return records

    def extract_asset_manifest(self, jar_path: Path) -> List[Dict[str, Any]]:
        """Index texture names and model-to-texture references as RAG metadata.

        The extractor intentionally does not embed binary pixels. This gives
        Jenny searchable asset IDs and file references without bloating Chroma.
        """
        texture_assets: List[Dict[str, Any]] = []
        model_assets: List[Dict[str, Any]] = []
        try:
            with zipfile.ZipFile(jar_path, "r") as jar:
                names = jar.namelist()
                for path in names:
                    if re.match(r"^assets/[^/]+/textures/.+\.(png|jpe?g|webp)$", path, re.I):
                        texture_assets.append({"_asset_type": "texture", "_asset_path": path,
                                               "_asset_id": path.rsplit("/textures/", 1)[-1].rsplit(".", 1)[0]})
                        if len(texture_assets) >= 250:
                            break
                for path in names:
                    if not re.match(r"^assets/[^/]+/models/.+\.json$", path, re.I):
                        continue
                    if len(model_assets) >= 250:
                        break
                    info = jar.getinfo(path)
                    if info.file_size > 100_000:
                        continue
                    try:
                        with jar.open(path) as source:
                            model = json.load(source)
                    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
                        continue
                    textures = model.get("textures", {}) if isinstance(model, dict) else {}
                    if isinstance(textures, dict):
                        refs = [str(value) for value in textures.values() if isinstance(value, str)]
                        if refs:
                            model_assets.append({"_asset_type": "model", "_asset_path": path,
                                                 "_asset_id": path.rsplit("/models/", 1)[-1].removesuffix(".json"),
                                                 "textures": refs})
                return texture_assets + model_assets
        except (OSError, zipfile.BadZipFile) as error:
            logger.warning("Could not inspect visual assets in %s: %s", jar_path.name, error)
        return texture_assets + model_assets
    
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
        # Custom gunpacks can be separate JARs with their own mod IDs, so scan
        # every archive for the TaCZ resource-data path, not just the core mod.
        gun_data = self.extract_tacz_gun_data(jar_path)
        custom_data = self.extract_custom_json_data(jar_path)
        asset_data = self.extract_asset_manifest(jar_path)
        items, blocks = self.extract_items_and_blocks(language_data)
        
        return ModData(
            metadata=metadata,
            language_data=language_data,
            recipes=recipes,
            advancements=advancements,
            items=items,
            blocks=blocks,
            gun_data=gun_data,
            custom_data=custom_data,
            asset_data=asset_data
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

        if mod_data.gun_data:
            with open(mod_dir / "gun_data.json", "w", encoding="utf-8") as f:
                json.dump(mod_data.gun_data, f, indent=2, ensure_ascii=False)

        if mod_data.custom_data:
            with open(mod_dir / "custom_data.json", "w", encoding="utf-8") as f:
                json.dump(mod_data.custom_data, f, indent=2, ensure_ascii=False)

        if mod_data.asset_data:
            with open(mod_dir / "asset_manifest.json", "w", encoding="utf-8") as f:
                json.dump(mod_data.asset_data, f, indent=2, ensure_ascii=False)
        
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
            mod_summary['gun_data_count'] = len(mod_data.gun_data)
            mod_summary['custom_data_count'] = len(mod_data.custom_data)
            mod_summary['asset_reference_count'] = len(mod_data.asset_data)
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
