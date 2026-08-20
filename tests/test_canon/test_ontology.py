"""The vocabulary the model is told the graph has.

Rendering is tested exactly and without a database, because it is a pure
function of an `Ontology`; reading is tested against a real graph, loosely,
because the shared database holds the whole corpus and an exact assertion would
be an assertion about Curse of Strahd rather than about this code.
"""

import pytest

from backend.canon.lookup import CANON_PLANE
from backend.canon.ontology import Ontology, read
from tests.conftest import TEST_ID_PREFIX


class TestRendering:
    def test_an_empty_graph_says_nothing(self):
        """Not an empty vocabulary. "Entity types: " with a blank after it is a
        positive claim that there are none."""
        assert Ontology().render() == ""

    def test_it_names_the_entity_types(self):
        block = Ontology(entity_types=("ITEM", "NPC")).render()
        assert "Entity types: ITEM, NPC" in block

    def test_derived_and_guessed_are_never_listed_together(self):
        """One derived type and twenty-one guessed ones is the measured shape
        of this corpus. Listing all twenty-two as one vocabulary would read as
        twenty-two kinds of knowledge."""
        block = Ontology(
            entity_types=("NPC",), derived=("CONTAINS",), guessed=("SERVES",)
        ).render()
        derived_line = next(ln for ln in block.splitlines() if "CONTAINS" in ln)
        assert "SERVES" not in derived_line
        assert "reliable" in derived_line

    def test_a_guessed_type_carries_its_warning(self):
        block = Ontology(entity_types=("NPC",), guessed=("SERVES",)).render()
        guessed_line = next(ln for ln in block.splitlines() if "SERVES" in ln)
        assert "third are wrong" in guessed_line
        assert "never as fact" in guessed_line

    def test_a_heading_is_omitted_when_it_would_be_empty(self):
        """A corpus with no derived edges at all must not print "Relationships
        derived from the book's own structure, and reliable:" followed by
        nothing, which reads as a claim that they exist and are hidden."""
        block = Ontology(entity_types=("NPC",), guessed=("SERVES",)).render()
        assert "reliable" not in block

    def test_it_says_what_an_ABSENT_type_means(self):
        """The point of the whole block. Without this an empty result is
        unreadable: no OWNS edge could mean nobody owns it, or that the graph
        has no notion of ownership, and the model cannot tell which."""
        block = Ontology(entity_types=("NPC",), guessed=("OWNS",)).render()
        assert "FOR THAT ENTITY" in block

    def test_it_closes_the_vocabulary(self):
        """A model that may compose a query has to know the list is complete,
        or it will invent a plausible label and read the empty result as an
        absence of facts rather than of that label."""
        assert "not in the graph" in Ontology(entity_types=("NPC",)).render()


class TestReadingItFromTheGraph:
    """Loose assertions against the shared database: this checks that `read`
    finds what is there and classifies it, not what the corpus contains."""

    @staticmethod
    def _two_entities(graph, relationship: str, status: str) -> None:
        graph.run(
            f"""
            CREATE (a:Entity:NPC {{id:$a, name:'Test A', plane:$plane}})
            CREATE (b:Entity:SITE {{id:$b, name:'Test B', plane:$plane}})
            CREATE (a)-[:{relationship} {{status:$status}}]->(b)
            """,
            {
                "a": f"{TEST_ID_PREFIX}a",
                "b": f"{TEST_ID_PREFIX}b",
                "plane": CANON_PLANE,
                "status": status,
            },
        )

    def test_an_accepted_type_is_derived(self, graph):
        self._two_entities(graph, "PYTEST_DERIVED", "accepted")
        assert "PYTEST_DERIVED" in read(graph).derived

    def test_a_proposed_type_is_guessed(self, graph):
        self._two_entities(graph, "PYTEST_GUESSED", "proposed")
        found = read(graph)
        assert "PYTEST_GUESSED" in found.guessed
        assert "PYTEST_GUESSED" not in found.derived

    def test_the_bare_entity_rung_is_not_a_type(self, graph):
        """`Entity` is the label everything wears. Offering it as a kind of
        thing would be offering the model a distinction that distinguishes
        nothing."""
        self._two_entities(graph, "PYTEST_ANY", "proposed")
        assert "Entity" not in read(graph).entity_types

    def test_the_mention_plumbing_is_not_offered(self, graph):
        """`REFERS_TO`, `IN_SECTION` and `USES_ALIAS` are most of the graph's
        edges and NO tool returns them -- `EDGES` matches entity to entity.
        Advertising them would send the model asking for what it cannot get."""
        offered = read(graph)
        assert not {"REFERS_TO", "IN_SECTION", "USES_ALIAS", "HAS_SECTION"} & set(
            offered.derived + offered.guessed
        )

    def test_it_reads_the_plane_it_is_asked_for(self, graph):
        """Canon and campaign never blur -- the same invariant every tool in
        `graph_tools` holds."""
        self._two_entities(graph, "PYTEST_CANON_ONLY", "accepted")
        assert "PYTEST_CANON_ONLY" not in read(graph, plane="campaign").derived


class TestItAgreesWithWhatTheToolsReturn:
    """A vocabulary is a promise about what `expand` can return. If the two
    disagree, the block is worse than nothing: it sends the model looking for
    relationships no tool surfaces, or hides ones it does."""

    def test_every_type_expand_returns_is_in_the_vocabulary(self, graph):
        from backend.agents.graph_tools import expand

        offered = set(read(graph).derived + read(graph).guessed)
        # A real entity with a lot of edges; skipped rather than failed when
        # the database has no corpus loaded, because that is an environment
        # fact and not a defect in this code.
        rows = [
            dict(r)
            for r in graph.run(
                "MATCH (n:Entity {plane:$plane})-[]->(:Entity {plane:$plane}) "
                "RETURN n.id AS id, count(*) AS n ORDER BY n DESC LIMIT 1",
                {"plane": CANON_PLANE},
            )
        ]
        if not rows:
            pytest.skip("no canon corpus loaded")
        returned = {row["relationship"] for row in expand(rows[0]["id"], limit=999).rows}
        assert returned <= offered
