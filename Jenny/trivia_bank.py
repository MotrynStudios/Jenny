"""Build grounded trivia from extracted mod descriptions, recipes, and item names."""

import asyncio
import hashlib
import json
import random
import re
from functools import lru_cache
from pathlib import Path

from ai import generate_pack_trivia
from pack_browser import recipe_rows
from trivia_cache import add_questions, bank_questions

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
CATEGORIES = {"descriptions": "Mod descriptions", "recipes": "Recipes", "items": "Items and blocks"}
DIFFICULTIES = ("easy", "medium", "hard")


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _name(value, labels):
    if not isinstance(value, str) or not value:
        return ""
    namespace, _, name = value.rpartition(":")
    for prefix in ("item", "block"):
        localized = labels.get(f"{prefix}.{namespace}.{name}")
        if isinstance(localized, str):
            return localized
    for kind in ("gun", "ammo", "attachment"):
        localized = labels.get(f"{namespace}.{kind}.{name}.name")
        if isinstance(localized, str):
            return localized
    return name.replace("_", " ").replace("/", " ").title()


def _ingredient(node, labels):
    if isinstance(node, list):
        choices = [_ingredient(value, labels) for value in node]
        return " or ".join(choices) if choices and all(choices) else ""
    if isinstance(node, dict):
        tag = node.get("tag")
        value = "#" + tag.lstrip("#") if isinstance(tag, str) else node.get("item") or node.get("id")
        name = _ingredient(value, labels)
        count = node.get("count")
        return f"{count} × {name}" if name and type(count) is int and count > 1 else name
    if isinstance(node, str) and node.startswith("#"):
        return "any " + _name(node[1:], labels)
    return _name(node, labels)


def _recipe_fact(recipe, labels):
    if not isinstance(recipe, dict):
        return None
    kind = str(recipe.get("type", "")).removeprefix("minecraft:")
    output = recipe.get("result") or recipe.get("output")
    if isinstance(output, dict):
        output = output.get("id") or output.get("item")
    answer = _name(output, labels)
    if not answer:
        return None
    if kind == "crafting_shaped":
        key, pattern = recipe.get("key"), recipe.get("pattern")
        if not isinstance(key, dict) or not isinstance(pattern, list) or not all(isinstance(row, str) for row in pattern):
            return None
        names = {symbol: _ingredient(value, labels) for symbol, value in key.items()}
        if not names or not all(names.values()) or any(symbol != " " and symbol not in names for row in pattern for symbol in row):
            return None
        grid = " / ".join("".join(row) for row in pattern)
        legend = ", ".join(f"{symbol} = {value}" for symbol, value in sorted(names.items()))
        return answer, f"Shaped crafting: [{grid}] ({legend})"
    if kind == "tacz:gun_smith_table_crafting":
        ingredients = recipe.get("materials")
        method = "Gun Smith Table"
    elif kind == "smithing_transform":
        ingredients = [recipe.get(field) for field in ("template", "base", "addition")]
        method = "Smithing table"
    elif kind == "crafting_shapeless":
        ingredients = recipe.get("ingredients")
        method = "Shapeless crafting"
    elif kind in {"smelting", "blasting", "smoking", "campfire_cooking", "stonecutting"}:
        ingredients = [recipe.get("ingredient")]
        method = kind.replace("_", " ").capitalize()
    else:
        return None
    if not isinstance(ingredients, list) or not ingredients:
        return None
    names = [_ingredient(value, labels) for value in ingredients]
    if not all(names):
        return None
    return answer, f"{method}: {', '.join(sorted(names))}"


def load_facts(root=DATA_ROOT):
    manifest = root / "modpack_summary.json"
    if not manifest.is_file():
        return {category: {} for category in CATEGORIES}
    # The extractor writes the manifest after writing the raw files.
    return _read_facts(root, manifest.stat().st_mtime_ns)


@lru_cache(maxsize=2)
def _read_facts(root, manifest_revision):
    raw = _load(root / "modpack_summary.json", {})
    mods = raw.get("mods", []) if isinstance(raw, dict) else raw
    facts = {category: {} for category in CATEGORIES}
    recipe_sources, item_sources = {}, {}
    if not isinstance(mods, list):
        return facts

    def add(category, answer, evidence):
        if not answer or len(answer) > 80 or not 5 <= len(evidence) <= 680:
            return
        # Do not turn a resource namespace or an answer printed in its own clue into trivia.
        normalized = lambda text: re.sub(r"[^\w]+", " ", text.casefold()).strip()
        if f" {normalized(answer)} " in f" {normalized(evidence)} ":
            return
        key = hashlib.sha256(f"{category}\0{answer}\0{evidence}".encode()).hexdigest()[:24]
        facts[category][key] = {"answer": answer, "evidence": evidence}

    for mod in mods:
        if not isinstance(mod, dict):
            continue
        mod_id = str(mod.get("mod_id") or "")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", mod_id) or mod_id in {".", ".."}:
            continue
        name = str(mod.get("display_name") or mod_id)
        folder = root / "raw_data" / mod_id
        labels = _load(folder / "language.json", {})
        labels = labels if isinstance(labels, dict) else {}
        for excerpt in re.split(r"(?<=[.!?])\s+|\n+", str(mod.get("description") or "")):
            if len(excerpt.strip()) >= 26:
                add("descriptions", name, excerpt.strip())
        items = _load(folder / "items_blocks.json", [])
        if isinstance(items, list):
            items = {"items": items}
        if isinstance(items, dict):
            for kind in ("items", "blocks"):
                values = items.get(kind)
                if not isinstance(values, list):
                    continue
                for value in values:
                    label = _name(value, labels) if isinstance(value, str) and ":" in value else value
                    if isinstance(label, str) and label.strip():
                        item_sources.setdefault(f"{kind[:-1].capitalize()}: {label.strip()}", set()).add(name)
        recipes = _load(folder / "recipes.json", [])
        custom = _load(folder / "custom_data.json", [])
        custom_recipes = [row.get("data") for row in custom if isinstance(row, dict)
                          and row.get("_category") == "custom_recipe"] if isinstance(custom, list) else []
        for recipe, _, _ in recipe_rows([recipes, custom_recipes]):
            row = _recipe_fact(recipe, labels)
            if row:
                answer, evidence = row
                recipe_sources.setdefault(evidence, set()).add(answer)
    for category, sources in (("recipes", recipe_sources), ("items", item_sources)):
        for evidence, answers in sources.items():
            if len(answers) == 1:
                add(category, next(iter(answers)), evidence)
    return facts


async def fill_bank(facts, category, difficulty, count, path, *, extraction=False, exclude=(), additional=False):
    """Generate in small batches. A cached question always keeps its source identity."""
    eligible = facts.keys() - set(exclude)
    cached = await asyncio.to_thread(bank_questions, category, difficulty, eligible, path)
    known = {row["fact_key"] for row in cached}
    available = list(eligible - known)
    attempts = (count + 9) // 10 + 3 if extraction or additional else 1
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 720 if additional else None
    total_added = 0
    for _ in range(attempts):
        remaining = count - (total_added if additional else len(cached))
        if remaining <= 0 or not available:
            break
        size = min(12 if extraction or additional else 20, remaining, len(available))
        selected = random.sample(available, min(len(available), size + 6))
        try:
            timeout = max(0, deadline - loop.time()) if deadline is not None else None
            rows = await asyncio.wait_for(
                generate_pack_trivia({key: facts[key] for key in selected}, category, difficulty,
                                     size, extraction=extraction),
                timeout,
            )
        except TimeoutError:
            print(f"[TRIVIA] {category}/{difficulty}: generation deadline reached")
            break
        if not rows:
            break
        added = await asyncio.to_thread(add_questions, rows, path)
        total_added += added
        cached = await asyncio.to_thread(bank_questions, category, difficulty, eligible, path)
        known.update(row["fact_key"] for row in cached)
        available = [key for key in available if key not in known]
        print(f"[TRIVIA] {category}/{difficulty}: {len(cached)} ready, {total_added} added this run")
        if not added:
            break
    return cached, total_added


async def generate_extra_trivia(category, difficulty, count):
    """Add fresh questions without overwriting existing clues or solve history."""
    if category not in CATEGORIES or difficulty not in DIFFICULTIES or not 1 <= count <= 100:
        raise ValueError("Choose a valid trivia category, difficulty and count between 1 and 100.")
    corpus = await asyncio.to_thread(load_facts)
    facts = corpus[category]
    if len({row["answer"] for row in facts.values()}) < 2:
        return 0
    _, added = await fill_bank(facts, category, difficulty, count, DATA_ROOT / "trivia_cache.sqlite3", additional=True)
    return added


async def seed_trivia_bank(root):
    corpus = await asyncio.to_thread(load_facts, root)
    path = root / "trivia_cache.sqlite3"
    for category, facts in corpus.items():
        total = 0
        for difficulty, target in zip(DIFFICULTIES, (34, 33, 33)):
            rows, _ = await fill_bank(facts, category, difficulty, target, path, extraction=True)
            total += min(len(rows), target)
        print(f"[TRIVIA] Extraction bank for {CATEGORIES[category]}: {total}/100 across difficulties")


async def make_pack_trivia(difficulty="medium", rounds=5, category="mixed", *, exclude=()):
    if difficulty not in DIFFICULTIES or category not in {"mixed", *CATEGORIES}:
        raise ValueError("Choose a valid trivia category and difficulty.")
    corpus = await asyncio.to_thread(load_facts)
    categories = list(CATEGORIES) if category == "mixed" else [category]
    pools = {}
    for kind in categories:
        answers = {row["answer"] for row in corpus[kind].values()}
        if len(answers) >= 2:
            pools[kind] = answers
    categories = list(pools)
    random.shuffle(categories)
    if not categories:
        return []
    path = DATA_ROOT / "trivia_cache.sqlite3"
    # In mixed games, alternate recipe clues with the other available categories.
    other = [kind for kind in categories if kind != "recipes"]
    rotation = [kind for alternate in other for kind in ("recipes", alternate)] if other and "recipes" in pools else categories
    slots = (rotation * ((rounds + len(rotation) - 1) // len(rotation)))[:rounds]
    banks = {}
    for kind in categories:
        count = slots.count(kind)
        if count:
            fresh, _ = await fill_bank(corpus[kind], kind, difficulty, count, path, exclude=exclude)
            random.shuffle(fresh)
            if len(fresh) < count and exclude:
                repeats = await asyncio.to_thread(bank_questions, kind, difficulty, set(exclude) & corpus[kind].keys(), path)
                random.shuffle(repeats)
                banks[kind] = repeats + fresh  # Pop fresh questions first.
            else:
                banks[kind] = fresh
    # A short recipe bank must not cut the game short when another category
    # has cached questions but received no slot in the initial rotation.
    if sum(len(bank) for bank in banks.values()) < rounds:
        for kind in categories:
            if kind not in banks:
                cached = await asyncio.to_thread(bank_questions, kind, difficulty,
                                                 corpus[kind].keys() - set(exclude), path)
                random.shuffle(cached)
                banks[kind] = cached
    # Interleave categories while avoiding duplicate factual clues within a game.
    questions, used = [], set()
    while len(questions) < rounds and any(banks.values()):
        for kind in rotation:
            bank = banks.get(kind, [])
            while bank and bank[-1]["fact_key"] in used:
                bank.pop()
            if not bank or len(questions) >= rounds:
                continue
            row = dict(bank.pop())
            used.add(row["fact_key"])
            distractors = sorted(pools[kind] - {row["answer"]})
            choice_count = {"easy": 2, "medium": 3, "hard": 4}[difficulty]
            row["options"] = random.sample(distractors, min(choice_count - 1, len(distractors))) + [row["answer"]]
            random.shuffle(row["options"])
            questions.append(row)
    return questions
