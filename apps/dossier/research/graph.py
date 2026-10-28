"""The connection graph: who links to what, and how two subjects are related.

This is deliberately arithmetic over data already on disk. No model is involved
and none should be - a model asked how two people are connected will invent a
plausible chain, and a plausible chain is exactly what this app exists not to
produce. Every hop here comes from a stored `relations.json` entry that carries
its own source, so a path can always be checked.

Being model-free is also what lets it run on the CPU while a deep dive has the
iGPU busy, which is how the user asked for it to work.

The graph has two kinds of node:

  held    a subject with a dossier of its own, keyed by its slug
  outside a target named by some subject's relations that has no dossier yet -
          a university, an ideology, an office

Outside nodes matter as much as held ones, because they are usually what makes
a connection interesting: two politicians who never mention each other both
turn out to have been educated at the same place. Traversal is undirected -
"how are they linked" does not care which of the two named the other.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path

import dossier
import store

# Rebuilding reads one small file per subject, so it is cheap but not free on a
# USB drive. The graph only changes when research finishes, so a short cache
# keeps the mind map responsive without ever showing badly stale links.
CACHE_SECONDS = 60.0

# A hub like "social democracy" can join hundreds of subjects. Paths through
# one are real but rarely what was meant, so they are allowed and simply ranked
# after everything else.
HUB_DEGREE = 25


class Graph:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.adj: dict[str, list[dict]] = {}

    def add_node(self, key: str, name: str, held: bool, entity_type: str = "") -> dict:
        node = self.nodes.get(key)
        if node is None:
            node = {
                "key": key,
                "name": name,
                "slug": key if held else "",
                "held": held,
                "entity_type": entity_type,
                "degree": 0,
            }
            self.nodes[key] = node
            self.adj[key] = []
        elif held and not node["held"]:
            # A subject researched after something else already named it.
            node.update({"held": True, "slug": key, "name": name})
            if entity_type:
                node["entity_type"] = entity_type
        return node

    def add_edge(self, a: str, b: str, relation: str, url: str = ""):
        if a == b:
            return
        self.adj[a].append({"to": b, "relation": relation, "via": a, "url": url})
        self.adj[b].append({"to": a, "relation": relation, "via": a, "url": url})
        self.nodes[a]["degree"] += 1
        self.nodes[b]["degree"] += 1

    # --- reading it ------------------------------------------------------

    def neighbours(self, key: str) -> list[dict]:
        return self.adj.get(key, [])

    def path(self, start: str, goal: str, max_hops: int = 6) -> list[dict] | None:
        """The shortest chain of stored relations joining two nodes.

        Breadth-first, so the first path found is a shortest one. Hub nodes are
        visited last at each level: a route through "social democracy" is true
        but says little, and a route through a shared employer says a lot.
        """
        if start not in self.nodes or goal not in self.nodes:
            return None
        if start == goal:
            return []

        came_from: dict[str, tuple[str, dict]] = {}
        seen = {start}
        queue = deque([(start, 0)])
        while queue:
            key, depth = queue.popleft()
            if depth >= max_hops:
                continue
            edges = sorted(
                self.neighbours(key),
                key=lambda e: self.nodes[e["to"]]["degree"] >= HUB_DEGREE,
            )
            for edge in edges:
                nxt = edge["to"]
                if nxt in seen:
                    continue
                seen.add(nxt)
                came_from[nxt] = (key, edge)
                if nxt == goal:
                    return self._rebuild(start, goal, came_from)
                queue.append((nxt, depth + 1))
        return None

    def _rebuild(self, start: str, goal: str, came_from: dict) -> list[dict]:
        hops: list[dict] = []
        key = goal
        while key != start:
            previous, edge = came_from[key]
            hops.append(
                {
                    "from": self.nodes[previous],
                    "to": self.nodes[key],
                    "relation": edge["relation"],
                    "url": edge.get("url", ""),
                    # Which subject's file recorded this, so the claim that
                    # these two are linked can be checked at its source.
                    "stated_by": self.nodes[edge["via"]]["name"],
                }
            )
            key = previous
        hops.reverse()
        return hops

    def around(self, key: str, depth: int = 2, budget: int = 90) -> dict:
        """A neighbourhood to draw: nodes and edges within `depth` hops.

        Budgeted, because a well-connected subject two hops out is thousands of
        nodes and an unreadable hairball. Held subjects are kept first, then the
        best-connected, so what survives the budget is what is worth seeing.
        """
        if key not in self.nodes:
            return {"nodes": [], "edges": [], "truncated": False}

        levels = {key: 0}
        order = [key]
        queue = deque([key])
        while queue:
            current = queue.popleft()
            if levels[current] >= depth:
                continue
            ranked = sorted(
                self.neighbours(current),
                key=lambda e: (
                    not self.nodes[e["to"]]["held"],
                    self.nodes[e["to"]]["degree"] >= HUB_DEGREE,
                    -self.nodes[e["to"]]["degree"],
                ),
            )
            for edge in ranked:
                nxt = edge["to"]
                if nxt in levels:
                    continue
                levels[nxt] = levels[current] + 1
                order.append(nxt)
                queue.append(nxt)

        truncated = len(order) > budget
        kept = set(order[:budget])
        edges = []
        drawn = set()
        for node_key in kept:
            for edge in self.neighbours(node_key):
                if edge["to"] not in kept:
                    continue
                pair = tuple(sorted((node_key, edge["to"]))) + (edge["relation"],)
                if pair in drawn:
                    continue
                drawn.add(pair)
                edges.append(
                    {
                        "from": node_key,
                        "to": edge["to"],
                        "relation": edge["relation"],
                    }
                )
        return {
            "nodes": [{**self.nodes[k], "hops": levels[k]} for k in order[:budget]],
            "edges": edges,
            "truncated": truncated,
            "centre": key,
        }


# --- building it ------------------------------------------------------------


def build(root: Path | None = None) -> Graph:
    """Read every stored subject's relations and index them both ways."""
    g = Graph()
    rows = dossier.library(root)
    for row in rows:
        g.add_node(
            row["slug"], row["name"], held=True, entity_type=row.get("entity_type", "")
        )
    for row in rows:
        d = store.subject_dir(row["slug"], root)
        relations = store.read_json(d / dossier.FILES["relations"], []) or []
        for relation in relations:
            target = (relation.get("target") or "").strip()
            if not target:
                continue
            # Targets are names, not slugs. Slugifying is what makes a mention
            # of "Angela Merkel" land on her dossier when she has one, and
            # makes two subjects who name the same university meet at one node.
            target_key = store.slugify(target)
            if target_key not in g.nodes:
                g.add_node(target_key, target, held=False)
            g.add_edge(
                row["slug"],
                target_key,
                relation.get("relation", "linked to"),
                relation.get("url", ""),
            )
    return g


_cached: Graph | None = None
_cached_at: float = 0.0
_cached_root: Path | None = None
_cache_lock = threading.Lock()


def current(root: Path | None = None, refresh: bool = False) -> Graph:
    """The graph, rebuilt when it is stale. Cheap to call repeatedly."""
    global _cached, _cached_at, _cached_root
    with _cache_lock:
        fresh = (
            not refresh
            and _cached is not None
            and _cached_root == root
            and (time.time() - _cached_at) < CACHE_SECONDS
        )
        if not fresh or _cached is None:
            _cached = build(root)
            _cached_at = time.time()
            _cached_root = root
        return _cached


def resolve(name_or_slug: str, graph: Graph) -> str | None:
    """Find a node from whatever the caller typed."""
    key = store.slugify(name_or_slug)
    if key in graph.nodes:
        return key
    wanted = name_or_slug.strip().lower()
    for node in graph.nodes.values():
        if node["name"].lower() == wanted:
            return node["key"]
    return None
