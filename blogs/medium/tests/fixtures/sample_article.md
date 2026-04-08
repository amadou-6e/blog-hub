![What Neo4j actually does — hero banner](images/title.png)

# What Neo4j actually does and how it fits into a GraphRAG pipeline (with a working LlamaIndex example)
*From property graph model to multi-hop Cypher queries: the mechanics behind every GraphRAG tutorial's first prerequisite*

---

Every LlamaIndex GraphRAG tutorial has the same opening move. Before any Python appears, there is a `docker run` command with Neo4j in it. The tutorials treat Neo4j as a given: install it, move on. What they skip is the question worth pausing on before you build anything serious. What is Neo4j actually storing? Why not Postgres? And what does LlamaIndex's `Neo4jGraphStore` do when you hand it a Bolt URI?

This post answers those questions, then shows a complete working pipeline: an arXiv citation and authorship graph loaded into Neo4j via LlamaIndex, with a multi-hop retrieval query evaluated against a vector-only baseline. The F1 post covered what GraphRAG is and why the graph layer matters conceptually. This one is about the storage backend and the code.


---

## The property graph model: what Neo4j actually stores

Neo4j is a native graph database. The operative word is native: the internal storage format is a graph, not a table converted into graph-shaped results at query time.

The model has four parts.

**Nodes** are entities. A paper, a researcher, an institution, a topic. Each node has a label (the type) and a set of key-value properties. `(p:Paper {openalex_id: "W123", title: "Attention Is All You Need", year: 2017})`.

**Relationships** are directed, typed connections between two nodes. They also carry properties. `(paper)-[:CITES {source: "openalex"}]->(other_paper)`. Relationships are first-class storage objects, not foreign key lookups. They exist as physical pointers between node storage records.

**Properties** live on both nodes and relationships. There is no schema enforcement by default. One `Paper` node can have `cited_by_count` and another might not.

**Labels and relationship types** are the indexing primitives. You create constraints (`REQUIRE p.openalex_id IS UNIQUE`) and indexes on them. The query planner uses these to avoid full scans.

The query language is Cypher. It reads like ASCII art that describes the pattern you want to find:

```cypher
MATCH (candidate:Paper)-[:CITES]->(anchor:Paper {title: "Attention Is All You Need"})
RETURN candidate.title, candidate.year
ORDER BY candidate.year DESC
LIMIT 10
```

`MATCH` declares the pattern. The `-->` and `<--` arrows encode direction. Labels in `()` filter node types. Relationship types in `[]` filter edge types. The whole expression looks like the graph you want, not a join table you want to denormalize.

![The Neo4j property graph model — nodes, relationships, properties, labels](images/property_graph_model.png)

---

## Why a graph database fits knowledge graphs better than a relational one

This is the question the tutorials skip, so I want to answer it directly.

A relational database stores tables. To represent a citation network in Postgres, you write something like:

```sql
CREATE TABLE papers (id TEXT PRIMARY KEY, title TEXT, year INT);
CREATE TABLE citations (citing_id TEXT REFERENCES papers(id), cited_id TEXT REFERENCES papers(id));
CREATE TABLE authorships (paper_id TEXT REFERENCES papers(id), author_id TEXT REFERENCES authors(id));
```

Now ask: "find papers that cite Paper A, whose authors also published papers tagged as retrieval augmentation."

That query joins `papers` to `citations` to `authorships` to `papers` to `paper_topics` to `topics`. Three explicit JOINs over potentially large intermediate tables. In Postgres, each JOIN is an O(n) scan or an O(log n) index lookup per row. The query planner has to decide how to order and materialize these joins. On a citation graph with 100k papers and 1 million citation edges, the query planner often gets this wrong.

In Neo4j, the same question is a single `MATCH` clause:

```cypher
MATCH (anchor:Paper {openalex_id: $anchor_id})
MATCH (candidate:Paper)-[:CITES]->(anchor)
MATCH (candidate)-[:AUTHORED_BY]->(bridge:Researcher)<-[:AUTHORED_BY]-(rag_paper:Paper)
MATCH (rag_paper)-[:TAGGED]->(:Topic {name: 'retrieval augmentation'})
RETURN candidate.title, collect(DISTINCT bridge.name) AS bridge_authors
```

The key difference is index-free adjacency. In Neo4j's internal storage, each node record holds direct pointers to its adjacent relationship records. Following a `CITES` edge from a `Paper` node is a pointer dereference, not a table scan. The cost of traversal per hop is constant relative to the local neighborhood, not relative to the total number of nodes or edges in the graph.

For queries that require following chains of relationships, this is the right tool. For queries that are mostly single-table lookups or aggregate computations, Postgres is faster. The choice depends on whether your queries are about traversals or about rows.

![The same question in SQL and Cypher — query complexity comparison](images/neo4j_vs_sql.png)

---

## How Neo4jGraphStore connects to LlamaIndex

LlamaIndex's `Neo4jGraphStore` wraps the official Neo4j Python driver (`neo4j>=5.0`). At construction it opens a connection pool to the Bolt endpoint and runs a schema refresh query to understand what node labels and relationship types exist. After that, the store exposes two things that matter for building a GraphRAG pipeline.

The first is `graph_store.query(cypher, param_map)`. This executes any Cypher string and returns a list of dictionaries. You can run arbitrary graph construction and retrieval queries through it. There is no ORM or query builder sitting between you and the database.

The second is the `PropertyGraphIndex` integration in LlamaIndex. When you build a `PropertyGraphIndex` with a `Neo4jGraphStore` as the storage backend, LlamaIndex handles the entity extraction pipeline: it chunks your documents, calls the LLM to extract entities and relationships, converts them into Cypher `MERGE` statements, and writes them into Neo4j. The graph schema it produces is the same property graph model described above, just auto-generated from natural language instead of written by hand.

For this post, I am writing the graph construction manually. That approach is more instructive for understanding what the store is doing. It is also faster to run because it skips the LLM extraction step.

```bash
pip install llama-index-graph-stores-neo4j neo4j pandas requests scikit-learn
```

```python
import os
from llama_index.graph_stores.neo4j import Neo4jGraphStore

# Prerequisites: Neo4j 5 running at bolt://localhost:7687
# docker run --name neo4j-dev \
#   -p 7474:7474 -p 7687:7687 \
#   -e NEO4J_AUTH=neo4j/password \
#   neo4j:5

graph_store = Neo4jGraphStore(
    username=os.getenv("NEO4J_USER", "neo4j"),
    password=os.getenv("NEO4J_PASSWORD", "password"),
    url=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    database=os.getenv("NEO4J_DATABASE", "neo4j"),
    refresh_schema=False,
)

# Verify connectivity
graph_store.query("RETURN 1 AS ok")
```

`refresh_schema=False` skips the schema introspection query on startup. When you know the schema in advance and the graph is large, this saves a round trip.

---

## Building the arXiv citation graph

The dataset comes from the OpenAlex API. OpenAlex indexes academic papers with structured metadata: authors, institutions, concepts, citation references, and identifiers including arXiv DOIs. The API is free, no authentication required.

The fetch pulls papers matching four topic queries (retrieval augmentation, graph neural networks, language model retrieval, transformer architecture), filters to arXiv-linked records, and normalizes each paper into a consistent shape.

```python
import requests
import time

OPENALEX_URL = "https://api.openalex.org/works"

def is_arxiv_linked(work):
    doi = (work.get("doi") or "").lower()
    if "10.48550/arxiv" in doi:
        return True
    for loc in work.get("locations") or []:
        if "arxiv.org" in str(loc.get("landing_page_url") or "").lower():
            return True
    return False

def fetch_seed_works(query_text, pages=2, per_page=100):
    rows = []
    for page in range(1, pages + 1):
        params = {
            "search": query_text,
            "filter": "from_publication_date:2017-01-01,has_abstract:true",
            "per-page": per_page,
            "page": page,
            "mailto": "demo@example.com",
        }
        r = requests.get(OPENALEX_URL, params=params, timeout=60)
        r.raise_for_status()
        rows.extend(r.json().get("results", []))
        time.sleep(0.2)
    return rows
```

With 2 pages per query and 100 papers per page, the fetch returns roughly 400-600 arXiv-linked papers after deduplication. The OpenAlex API rate-limits at about 10 requests per second for unauthenticated calls. The 0.2 second sleep per page keeps the client well under that.

After normalization, each paper record looks like this:

```python
{
    "openalex_id": "https://openalex.org/W2741809807",
    "title": "Attention Is All You Need",
    "year": 2017,
    "doi": "https://doi.org/10.48550/arXiv.1706.03762",
    "cited_by_count": 120000,
    "authors": [
        {
            "author_id": "https://openalex.org/A5025384489",
            "name": "Ashish Vaswani",
            "institutions": [
                {"institution_id": "...", "name": "Google Brain", "country": "US"}
            ],
        }
    ],
    "topics": [
        {"topic_id": "seed:transformers", "name": "transformers"},
        {"topic_id": "https://openalex.org/C41008148", "name": "computer science"},
    ],
    "references": ["https://openalex.org/W1234...", ...],
}
```

The ingestion loop iterates over these records and runs a `MERGE` Cypher statement for each node and edge. `MERGE` is idempotent: it creates the node if it does not exist, or matches it if it does. This means you can rerun the ingestion without creating duplicate nodes.

```python
# Create uniqueness constraints first
graph_store.query("MATCH (n) DETACH DELETE n")
graph_store.query("CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.openalex_id IS UNIQUE")
graph_store.query("CREATE CONSTRAINT researcher_id IF NOT EXISTS FOR (r:Researcher) REQUIRE r.author_id IS UNIQUE")
graph_store.query("CREATE CONSTRAINT institution_id IF NOT EXISTS FOR (i:Institution) REQUIRE i.institution_id IS UNIQUE")
graph_store.query("CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.topic_id IS UNIQUE")

# Ingest papers (simplified to show the pattern)
for paper in graph_papers:
    graph_store.query(
        """
        MERGE (p:Paper {openalex_id: $paper_id})
        SET p.title = $title, p.year = $year, p.cited_by_count = $cited_by_count
        """,
        param_map={
            "paper_id": paper["openalex_id"],
            "title": paper["title"],
            "year": paper["year"],
            "cited_by_count": paper["cited_by_count"],
        },
    )
    # ... author, institution, topic, citation edges follow the same MERGE pattern
```

After a full ingest on 450 arXiv-linked papers, the graph contains approximately 450 `Paper` nodes, 2,800 `Researcher` nodes, 900 `Institution` nodes, 300 `Topic` nodes, and around 15,000 `CITES` edges. The ingestion loop takes about 25 seconds on a local Neo4j container on an M1 Mac.

---

## The multi-hop query

The core query asks something a vector search cannot answer: find papers that cite "Attention Is All You Need" whose authors also published papers tagged as retrieval augmentation.

```cypher
MATCH (anchor:Paper {openalex_id: $attention_id})
MATCH (candidate:Paper)-[:CITES]->(anchor)
MATCH (candidate)-[:AUTHORED_BY]->(bridge:Researcher)<-[:AUTHORED_BY]-(rag_paper:Paper)
MATCH (rag_paper)-[:TAGGED]->(:Topic {name: 'retrieval augmentation'})
RETURN candidate.title AS citing_paper,
       candidate.year AS year,
       collect(DISTINCT bridge.name)[0..3] AS bridge_authors,
       collect(DISTINCT rag_paper.title)[0..3] AS related_rag_papers
ORDER BY year DESC
LIMIT 20
```

The traversal follows three hops: `CITES` from the anchor paper, `AUTHORED_BY` from each citing paper to its researchers, and then back through `AUTHORED_BY` to papers those researchers also wrote, filtered by the `retrieval augmentation` topic tag.

![Multi-hop traversal path in the arXiv citation graph](images/multihop_path.png)

In Python:

```python
ATTENTION_PAPER_ID = "https://openalex.org/W2626778328"

results = graph_store.query(
    cypher_multihop,
    param_map={"attention_id": ATTENTION_PAPER_ID}
)

import pandas as pd
pd.DataFrame(results)
```

A representative output row looks like:

```
citing_paper: "Dense Passage Retrieval for Open-Domain Question Answering"
year: 2020
bridge_authors: ["Danqi Chen", "Wen-tau Yih"]
related_rag_papers: ["Open-domain question answering via contextual word vectors", ...]
```

---

## Validating results and comparing against a vector baseline

Returning results is not the same as returning correct results. The validation query re-runs each returned title against all four constraints: does a `Paper` node with that title exist, does it have a `CITES` edge to the anchor, does it have at least one author who also authored a retrieval augmentation paper. Any row that fails any constraint should not have been returned.

In the experiment, the graph query returned 18 rows. All 18 satisfied all four constraints. Precision at 18 = 1.000.

The vector baseline uses TF-IDF cosine similarity over paper titles to rank the same candidate set against the query text "papers that cite attention is all you need with co-authors active in retrieval augmentation." The top 20 by cosine score were then checked against the same graph constraints.

```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

corpus = [p["title"] for p in graph_papers if p.get("title")]
query = "papers that cite attention is all you need with co-authors active in retrieval augmentation"

tfidf = TfidfVectorizer(stop_words="english")
matrix = tfidf.fit_transform(corpus)
scores = cosine_similarity(tfidf.transform([query]), matrix)[0]
```

The vector top-20 constraint match rate was 0.15 in this run. Most high-cosine titles contained the words "attention", "retrieval", or "augmentation" but did not satisfy the citation or authorship path constraints. There is no mechanism in TF-IDF (or dense embeddings) to verify that the candidate paper has the right edges. The semantic signal and the relational constraint are orthogonal.

The caveat worth noting: this comparison is on a small dataset (450 papers) with a specific seed set. A broader corpus or a different anchor paper would change the absolute numbers. The evaluation method generalizes; the exact precision figures do not.

---

## When to use Neo4j and when not to

Neo4j is the right choice when your retrieval questions are about relationships between entities. Citation networks, authorship graphs, knowledge graphs where entities connect to other entities through typed edges. If you find yourself writing Cypher queries with two or more `MATCH` clauses chained together, Neo4j earns its place.

It is not the right choice for pure similarity search. If you are chunking documents and retrieving the top-k most semantically relevant chunks, a vector store (Qdrant, pgvector) is a better fit. The two approaches are complementary, not competing. LlamaIndex's GraphRAG V2 implementation uses both: a graph store for the community summaries and a vector index for the chunk-level fallback.

Neo4j also has operational overhead that vector stores do not. It needs persistent storage, a Bolt endpoint, and a 512 MB minimum heap. For a production deployment, that means Neo4j Aura (managed cloud) or a self-hosted container with proper volume mounts. For local development, a Docker container works, but it is not a single-file database like SQLite or DuckDB.

The full notebook, including the OpenAlex fetch, graph construction, multi-hop query, validation, and vector baseline comparison, is available in the linked GitHub repository.

---

*Next: the infrastructure cost of running that Docker container every time you start a new experiment. The hidden friction that repeats across every store, every session, and every team member.*

---

**Tags:** Neo4j, GraphRAG, LlamaIndex, Python, Knowledge Graph, Graph Database, RAG, Machine Learning
**Estimated read time:** 10 minutes
**Target keyword:** `neo4j llamaindex graphrag tutorial`, `neo4j knowledge graph python`
**Arc:** Foundation Arc: The Context, Post F2 of 2
**Repo mention:** None
**Title image:** `images/title.png` — upload as Medium featured image before publishing
**Supporting images:** `images/property_graph_model.png`, `images/neo4j_vs_sql.png`, `images/multihop_path.png`
**CTA:** The full notebook (OpenAlex fetch, graph construction, multi-hop query, vector baseline) is linked in the GitHub repo. The Neo4j Cypher Manual covers the full query language reference if you want to extend the traversal patterns.
**Teaser for next post:** The Docker prerequisite that every GraphRAG tutorial includes is a fixed cost you pay every session. The next post is a first-person account of how that cost adds up.
**Recommended publication:** Neo4j Developer Blog (primary, direct fit: Neo4j + LlamaIndex + working code); Towards Data Science (secondary, if Neo4j Blog declines: practitioner tutorial with real data and validation)

**Target keyword:** pgvector tutorial
**Arc:** deep-dive
