"""Food-store helper built only on the skeleton API.

knowledge = Catalog (foods.json as a short store guide; its version is the file hash plus the day, so the cache
starts fresh when the catalog or the day's specials change). verify = Catalog.grounded: an answer may only quote
prices and aisles that are in the catalog, and "I don't know" climbs to the 763B.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re

from skeleton.core import Assistant
from skeleton.core.demo import words
from skeleton.core.kblookup import QWORDS, KBLookup, Semantic, backed, swarm_check, swarm_covered

HERE = pathlib.Path(__file__).resolve().parent
CONFIG, FOODS, QUESTIONS = HERE / "store.toml", HERE / "foods.json", HERE / "questions.json"
UNSURE = re.compile(r"\b(i don'?t know|i do not know|not sure|no information)\b", re.I)
QWORDS = {"where", "when", "what", "how", "much", "which", "who", "why"}


class Catalog:
    """shortcut: the whole guide goes in every model prompt (about 900 tokens); switch to retrieval past ~200 items."""

    def __init__(self, path: pathlib.Path = FOODS, today: dt.date | None = None) -> None:
        raw = path.read_text()
        self.data, self.day = json.loads(raw), (today or dt.date.today())
        self.weekday = self.day.strftime("%A").lower()
        self.version = f"{hashlib.sha256(raw.encode()).hexdigest()[:12]}:{self.day.isoformat()}"
        self.prices = set(re.findall(r"\d+\.\d\d", raw))
        self.text = "\n".join(self.lines())
        self.embedder, self._sem, self.judge = None, None, None

    def attach(self, embedder) -> "Catalog":
        """Use meaning as well as shared words (the cache's embedder). None: word overlap only."""
        self.embedder, self._sem = embedder, None
        return self

    def semantic(self) -> "Semantic | None":
        if self.embedder is None:
            return None
        if self._sem is None:
            d = self.data
            lines = self.lines()
            keys = list(lines)
            for n, it in enumerate(d["items"]):  # an item line is asked for by its name: "vegan options" is not an item
                at = lines.index(next(x for x in lines if x.startswith(it["name"] + ":")))
                keys[at] = it["name"]
            members = {}
            hours = [i for i, x in enumerate(lines) if " hours: " in x]
            lines.append("Opening hours. " + " ".join(f"{k.title()} hours: {v}." for k, v in d["hours"].items()))
            keys.append("What are your opening hours? When do you close? What time are you open?")
            members[len(lines) - 1] = hours
            for tag in sorted({t for i in d["items"] for t in i.get("tags", [])}):
                tagged = [i for i in d["items"] if tag in i.get("tags", [])]
                lines.append(f"{tag.title()} items: " + "; ".join(f"{i['name']} aisle {i['aisle']}, ${i['price']}" for i in tagged) + ".")
                keys.append(f"Do you have {tag} options, {tag} food or {tag} items?")
                members[len(lines) - 1] = [next(k for k, x in enumerate(lines) if x.startswith(i["name"] + ":")) for i in tagged]
            self._sem = Semantic(self.embedder, keys, lines, members)
        return self._sem

    def lines(self) -> list[str]:
        d = self.data
        out = [f"Store guide for {d['store']} ({self.weekday.title()})."]
        out += [f"{k.title()} hours: {v}." for k, v in d["hours"].items()]
        out.append(f"Today's specials ({self.weekday.title()}): " + "; ".join(f"{s}" for s in d["specials"][self.weekday]) + ".")
        out.append("Kitchen menu: " + ", ".join(d["kitchen_menu"]) + ".")
        out += [f"Aisle {n}: {name}." for n, name in d["aisles"].items()]
        out += [f"{i['name']}: aisle {i['aisle']}, ${i['price']}" + (f" ({', '.join(i['tags'])})" if i.get("tags") else "")
                + "." for i in d["items"]]
        return out + d["services"]

    def __call__(self, question: str) -> str:
        return self.text

    def grounded(self, answer: str) -> bool:
        """Non-empty, sure, and every quoted price and aisle exists in the catalog. When the question asks about an
        item that is on special today, the regular price is not the right answer: refuse it."""
        if not answer.strip() or UNSURE.search(answer):
            return False
        prices = re.findall(r"\$\s?(\d+(?:\.\d\d)?)", answer)
        aisles = re.findall(r"\baisles?\s+(\d+)", answer, re.I)
        return all(p in self.prices for p in prices) and all(a in self.data["aisles"] for a in aisles)

    def checked(self, question: str, answer: str) -> bool:
        """The swarm's check: grounded (prices, aisles) AND backed by the guide lines that match the question.
        An answer that quotes the regular price for a specials item is wrong: refuse it."""
        if not self.grounded(answer):
            return False
        # specials guard: if the question is about an item on special today, the regular price is not right
        specials_text = " ".join(self.data["specials"].get(self.weekday, [])).lower()
        for item in self.data.get("items", []):
            name = item["name"].lower()
            regular = item["price"]
            if name in specials_text and name in question.lower() and regular in answer:
                return False  # the regular price for a specials item is not the current price
        return swarm_check(self.lines(), self.semantic(), self.judge, question, answer)

    def covered(self, question: str) -> bool:
        """Does the knowledge base hold a fact for this question? False: no model is asked (the fallback is served)."""
        return swarm_covered(self.semantic(), self.judge, question)

    def lookup(self) -> KBLookup:
        """$0 item lookup: "where are the eggs" -> that item's guide line, when exactly one item name fits the question."""
        d = self.data
        special = " ".join(d["specials"][self.weekday]).lower()  # an item on special today has a second price: not a lookup
        return KBLookup([(i["name"], f"{i['name']}: aisle {i['aisle']}, ${i['price']}.") for i in d["items"]
                         if i["name"].lower() not in special],
                        drop=QWORDS | {"aisle", "price", "cost", "buy", "item"}, q_cov=1.0, k_cov=0.5, margin=0.3)


FALLBACK = "I don't know. Please ask at the customer service desk."


def demo_30b(prompt: str) -> str:
    """Demo stand-in for the 30B: the guide lines that cover at least half of the question's words, else ""."""
    guide, _, q = prompt.rpartition("Question:")
    guide = guide[guide.find("Store guide for"):]  # the guide lines only, not the instructions
    want = set(words(q)) - QWORDS
    if not want:
        return ""
    scored = []
    for line in (x for x in guide.splitlines() if x.strip()):
        w = set(words(line))
        scored.append((len(want & w), len(want & w) / max(len(w), 1), line))
    best = max((s[0] for s in scored), default=0)
    if best * 2 < len(want):
        return ""
    top = sorted((s for s in scored if s[0] == best), key=lambda s: -s[1])[:3]  # most on-topic lines first
    return " ".join(s[2] for s in top)


DEMO_MODELS = {"gpu-small": demo_30b,
               "cloud-deepseek": lambda p: "I don't know: the store guide does not cover that. "
                                           "Please ask at the customer service desk."}


SWARM_DEMO_MODELS = {"crusoe-small": demo_30b, "cloud-top": demo_30b, "cloud-deepseek": DEMO_MODELS["cloud-deepseek"]}


def make_assistant(live: bool = False, catalog: Catalog | None = None, no_gpu: bool = False, swarm: bool = False,
                   namespace: str | None = None, embedder=None, judge=None):
    """swarm=True: item lookup at $0, then the cache, then crusoe-small, cloud-top, cloud-deepseek (no GPU)."""
    import tomllib
    catalog = catalog or Catalog()
    cfg = {**tomllib.loads(CONFIG.read_text()), **({"mode": "live"} if live else {}),
           **({"namespace": namespace} if namespace else {})}
    if no_gpu:
        cfg["ladder"] = ["cloud-deepseek"]
    if swarm:
        from skeleton.core.swarm import SWARM_LADDER, Swarm, make_judge, need_embedder
        bot = Assistant({**cfg, "ladder": SWARM_LADDER}, knowledge=catalog, verify=catalog.grounded,
                        demo_models=SWARM_DEMO_MODELS)
        catalog.attach(need_embedder(bot, embedder))  # live: all-MiniLM-L6-v2, or fail loudly; demo/CI: word overlap
        catalog.judge = judge if judge is not None else make_judge(bot.cfg.model_dump(), bot.cfg.namespace)
        return Swarm(bot, free=[("kb_lookup", catalog.lookup().match)], check=catalog.checked, fallback=FALLBACK,
                     covered=catalog.covered)
    return Assistant(cfg, knowledge=catalog, verify=catalog.grounded, demo_models=DEMO_MODELS)


def seed(bot: Assistant, questions: list[str] | None = None) -> dict:
    """Ask the common questions once so shoppers get cache hits. Returns the seeding totals; stats restart at 0."""
    for q in questions or json.loads(QUESTIONS.read_text())["seed"]:
        bot.ask(q)
    done = bot.stats()
    bot.reset_stats()
    return done
