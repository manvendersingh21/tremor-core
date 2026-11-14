"""N+1 memory. See docs/memory.md."""
from .extract import heuristic_extract, llm_extractor
from .graph import GraphStore, InMemoryStore, PgGraphStore
from .memory import Example, Memory, MemoryContext
from .neo4j_store import Neo4jGraphStore, default_store
from .safety import scrub

def build(embedder, tenant: str = "default", extractor=None, **kw) -> Memory:
    """Memory on the best reachable graph store (Aura, else Akash Neo4j, else Supabase, else in-process)."""
    return Memory(default_store(), embedder, tenant, **({"extractor": extractor} if extractor else {}), **kw)


__all__ = ["build", "Memory", "MemoryContext", "Example", "GraphStore", "InMemoryStore", "PgGraphStore", "Neo4jGraphStore",
           "default_store", "scrub", "llm_extractor", "heuristic_extract"]
