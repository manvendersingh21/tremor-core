"""`chimera keys ...` and `chimera cache purge`: admin commands that act on the local files."""
from __future__ import annotations

import sys
import time

from chimera_core.cache.exact_cache import ExactCache
from chimera_core.cache.semantic_cache import SemanticCache

from .store import KeyStore


def run_admin(args, cfg) -> int:
    if args.cmd == "cache":
        path = str(cfg.cache_path)
        n = ExactCache(path=path).purge(args.tenant)
        n += SemanticCache(None, path=path).purge(args.tenant)  # purge never embeds, so no embedder is needed
        print(f"purged {n} cached answers for tenant {args.tenant}. Restart the gateway to clear its memory copy.")
        return 0
    store = KeyStore(str(cfg.gateway_db))
    try:
        if args.action == "create":
            key_id, raw = store.create(args.tenant)
            print(f"key id {key_id} for tenant {args.tenant}. Shown once, store it now:", file=sys.stderr)
            print(raw)
        elif args.action == "list":
            for k in store.list():
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(k["created_at"]))
                print(f"{k['id']:>4}  {k['tenant']:<24} {k['prefix']}...  {when}  {'revoked' if k['revoked'] else 'active'}")
        else:
            if (args.tenant is None) == (args.id is None):
                print("error: give --tenant or --id", file=sys.stderr)
                return 2
            print(f"revoked {store.revoke(tenant=args.tenant, key_id=args.id)} key(s)")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0
