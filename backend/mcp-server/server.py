# server.py  — FastMCP, minimal graph tools
import os, yaml
from typing import List, Dict, Any

from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver

# ✨ FastMCP API
from mcp.server.fastmcp import FastMCP

load_dotenv()

# ---- Config (schema.yml) ----
SCHEMA = yaml.safe_load(open("schema.yml"))
E_LABEL: str = SCHEMA["entity_label"]
NODE_FIELDS: List[str] = SCHEMA["node_properties"]
NAV_RELS: List[str] = SCHEMA["nav_relationships"]
SEARCH_FIELDS: List[str] = SCHEMA.get(
    "searchable_node_properties", ["name", "summary", "tags"]
)

# ---- Neo4j driver ----
URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PWD = os.getenv("NEO4J_PASSWORD", "testpassword")
driver: Driver = GraphDatabase.driver(URI, auth=(USER, PWD))


def node_projection(alias: str = "e") -> str:
    parts = []
    for f in NODE_FIELDS:
        if f == "labels":
            parts.append(f"labels: labels({alias})")
        elif f in ("id", "name", "summary", "details", "importance", "tags"):
            parts.append(f"{f}: {alias}.{f}")
    parts.append(f"labels: labels({alias})")
    return f"{alias} {{ {', '.join(parts)} }}"


CYPHER_GET_NODE = f"""
MATCH (e:{E_LABEL} {{id:$id}})
RETURN {node_projection('e')} AS node
"""

CYPHER_NEIGHBORS = f"""
MATCH (root:{E_LABEL} {{id:$id}})
WITH root
MATCH path=(root)-[rels*1..$HOPS]->(m:{E_LABEL})
WHERE (size($types)=0 OR ANY(l IN labels(m) WHERE l IN $types))
  AND ANY(rt IN $nav_rels WHERE rt IN [r IN rels | type(r)])
RETURN DISTINCT {node_projection('root')} AS root,
       collect(DISTINCT {{ node: {node_projection('m')}, via: [r IN rels | type(r)] }}) AS neighbors
"""


def cypher_search_simple() -> str:
    ors = " OR ".join(
        [f"toLower(toString(e.{f})) CONTAINS toLower($q)" for f in SEARCH_FIELDS]
    )
    return f"""
    MATCH (e:{E_LABEL})
    WHERE (size($types)=0 OR ANY(l IN labels(e) WHERE l IN $types))
      AND ({ors})
    RETURN {node_projection('e')} AS node
    ORDER BY coalesce(e.importance, 0.5) DESC
    LIMIT $k
    """


CYPHER_SEARCH = cypher_search_simple()

# ---- FastMCP server ----
mcp = FastMCP("neo4j-mcp-basic")


@mcp.tool()
def schema_describe() -> Dict[str, Any]:
    """Return the configured graph schema."""
    return SCHEMA


@mcp.tool()
def graph_get_node(id: str) -> Dict[str, Any] | None:
    """Fetch a node by id."""
    with driver.session() as s:
        rec = s.run(CYPHER_GET_NODE, id=id).single()
        return rec["node"] if rec else None


@mcp.tool()
def graph_neighbors(
    id: str, max_hops: int = 1, types: List[str] = []
) -> Dict[str, Any] | None:
    """Fetch neighboring nodes within N hops (optionally filter by labels)."""
    with driver.session() as s:
        rec = s.run(
            CYPHER_NEIGHBORS, id=id, HOPS=max_hops, types=types, nav_rels=NAV_RELS
        ).single()
        if not rec:
            return None
        return {"root": rec["root"], "neighbors": rec["neighbors"]}


@mcp.tool()
def graph_search(q: str, k: int = 8, types: List[str] = []) -> List[Dict[str, Any]]:
    """Substring search over name/summary/tags."""
    with driver.session() as s:
        rows = s.run(CYPHER_SEARCH, q=q, k=k, types=types)
        return [r["node"] for r in rows]


if __name__ == "__main__":
    # stdio transport by default
    mcp.run()
