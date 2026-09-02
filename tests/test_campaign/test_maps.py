"""Maps, pins, and the asymmetry that keeps a twist off the table's screen.

An accidental reveal cannot be taken back; an accidental concealment costs one
click. So pins are born hidden, and the player query cannot be made to return a
hidden one by getting an argument wrong.
"""

import pytest

from backend.campaign import assets, maps
from backend.core.database import neo4j_session

PREFIX = "pytest-map"
SLUG = f"{PREFIX}-camp"
WHEN = "2026-09-02T00:00:00Z"
PLACE = f"{PREFIX}:barovia"
NPC = f"{PREFIX}:strahd"


@pytest.fixture
def graph():
    with neo4j_session() as session:
        def clean(s):
            s.run("MATCH (n) WHERE n.campaign = $c DETACH DELETE n", {"c": SLUG}).consume()
            s.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n",
                  {"p": PREFIX}).consume()
            s.run("MATCH (a:Asset) WHERE a.sha256 STARTS WITH 'pytestmap' "
                  "DETACH DELETE a").consume()

        clean(session)
        session.run(
            "CREATE (:Entity:LOCATION {id:$p, plane:'canon', name:'Barovia'}) "
            "CREATE (:Entity:NPC {id:$n, plane:'canon', name:'Strahd von Zarovich'}) "
            "CREATE (:Entity:ITEM {id:$i, plane:'canon', name:'Tome'})",
            {"p": PLACE, "n": NPC, "i": f"{PREFIX}:tome"},
        ).consume()
        yield session
        clean(session)


def _asset(graph, sha="pytestmap1"):
    return graph.execute_write(lambda tx: assets.store_upload(
        tx, sha256=sha, media_type="image/png", campaign=SLUG,
        uploaded_by="ana", created_at=WHEN))["id"]


def _map(graph, name="Barovia"):
    # HOISTED OUT OF THE LAMBDA. Calling `_asset` inside the `execute_write`
    # callback opens a write inside a write, which kills the connection.
    asset = _asset(graph)
    return graph.execute_write(lambda tx: maps.create(
        tx, slug=SLUG, name=name, place=PLACE, asset=asset,
        created_at=WHEN))["id"]


class TestAMapBelongsToThePlaceItDepicts:
    def test_it_attaches_to_a_location(self, graph):
        found = _map(graph)
        assert found == f"hb:{SLUG}:map-barovia"

    def test_the_graph_is_the_atlas_index(self, graph):
        _map(graph)
        listed = graph.execute_read(lambda tx: maps.maps_of(tx, slug=SLUG))
        assert [m["place"] for m in listed] == ["Barovia"]

    def test_a_map_of_something_that_is_not_a_place_is_refused(self, graph):
        """The same range discipline `DESCRIBES` keeps: a quest is not a place
        and cannot hold a map."""
        asset = _asset(graph, "pytestmap2")
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: maps.create(
                tx, slug=SLUG, name="Nope", place=NPC, asset=asset,
                created_at=WHEN))


class TestPinsAreFractionsOfTheImage:
    """A DM re-uploads a better scan; the map keeps its id and every pin
    survives. Pixel coordinates would silently shear all of them."""

    def test_a_pin_lands_where_it_was_put(self, graph):
        m = _map(graph)
        found = graph.execute_write(lambda tx: maps.pin(
            tx, slug=SLUG, map_ref=m, entity=NPC, x=0.25, y=0.75))
        assert (found["x"], found["y"]) == (0.25, 0.75)

    def test_pinning_twice_moves_it_rather_than_doubling_it(self, graph):
        m = _map(graph)
        for x in (0.1, 0.9):
            graph.execute_write(lambda tx: maps.pin(
                tx, slug=SLUG, map_ref=m, entity=NPC, x=x, y=0.5))
        found = graph.execute_read(lambda tx: maps.pins(
            tx, slug=SLUG, map_ref=m, for_player=False))
        assert len(found) == 1 and found[0]["x"] == 0.9

    @pytest.mark.parametrize("x,y", [(1.4, 0.5), (-0.1, 0.5), (0.5, 812.0)])
    def test_a_coordinate_outside_the_image_is_refused(self, graph, x, y):
        """A pixel coordinate that escaped conversion is the likely cause, and
        storing it puts a token off the edge where nobody can delete it."""
        m = _map(graph)
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: maps.pin(
                tx, slug=SLUG, map_ref=m, entity=NPC, x=x, y=y))

    def test_unpinning_removes_it(self, graph):
        m = _map(graph)
        graph.execute_write(lambda tx: maps.pin(
            tx, slug=SLUG, map_ref=m, entity=NPC, x=0.5, y=0.5))
        assert graph.execute_write(lambda tx: maps.unpin(
            tx, slug=SLUG, map_ref=m, entity=NPC)) == 1


class TestBornHidden:
    """The asymmetry is the argument: an accidental reveal cannot be taken
    back, an accidental concealment costs one click."""

    def test_a_new_pin_is_not_revealed(self, graph):
        m = _map(graph)
        found = graph.execute_write(lambda tx: maps.pin(
            tx, slug=SLUG, map_ref=m, entity=NPC, x=0.5, y=0.5))
        assert found["revealed"] is False

    def test_the_player_view_does_not_contain_it_at_all(self, graph):
        """Not blurred, not silhouetted: a blurred pin is a spoiler of
        EXISTENCE."""
        m = _map(graph)
        graph.execute_write(lambda tx: maps.pin(
            tx, slug=SLUG, map_ref=m, entity=NPC, x=0.5, y=0.5))
        assert graph.execute_read(lambda tx: maps.pins(
            tx, slug=SLUG, map_ref=m, for_player=True)) == []

    def test_the_dm_sees_it_and_that_it_is_hidden(self, graph):
        m = _map(graph)
        graph.execute_write(lambda tx: maps.pin(
            tx, slug=SLUG, map_ref=m, entity=NPC, x=0.5, y=0.5))
        found = graph.execute_read(lambda tx: maps.pins(
            tx, slug=SLUG, map_ref=m, for_player=False))
        assert len(found) == 1 and found[0]["revealed"] is False

    def test_revealing_puts_it_on_the_table_screen(self, graph):
        m = _map(graph)
        graph.execute_write(lambda tx: maps.pin(
            tx, slug=SLUG, map_ref=m, entity=NPC, x=0.5, y=0.5))
        graph.execute_write(lambda tx: maps.reveal(
            tx, slug=SLUG, map_ref=m, entity=NPC))
        found = graph.execute_read(lambda tx: maps.pins(
            tx, slug=SLUG, map_ref=m, for_player=True))
        assert [p["name"] for p in found] == ["Strahd von Zarovich"]

    def test_it_can_be_hidden_again(self, graph):
        m = _map(graph)
        graph.execute_write(lambda tx: maps.pin(
            tx, slug=SLUG, map_ref=m, entity=NPC, x=0.5, y=0.5))
        graph.execute_write(lambda tx: maps.reveal(
            tx, slug=SLUG, map_ref=m, entity=NPC))
        graph.execute_write(lambda tx: maps.reveal(
            tx, slug=SLUG, map_ref=m, entity=NPC, revealed=False))
        assert graph.execute_read(lambda tx: maps.pins(
            tx, slug=SLUG, map_ref=m, for_player=True)) == []


class TestRevealingUnderAnotherName:
    """The players know the coachman for three sessions before they know
    Strahd. The mention system already separates a surface from a name."""

    def test_the_table_is_told_the_alias(self, graph):
        m = _map(graph)
        graph.execute_write(lambda tx: maps.pin(
            tx, slug=SLUG, map_ref=m, entity=NPC, x=0.5, y=0.5))
        graph.execute_write(lambda tx: maps.reveal(
            tx, slug=SLUG, map_ref=m, entity=NPC, as_name="the coachman"))
        found = graph.execute_read(lambda tx: maps.pins(
            tx, slug=SLUG, map_ref=m, for_player=True))
        assert [p["name"] for p in found] == ["the coachman"]

    def test_the_true_name_does_not_travel_to_the_table(self, graph):
        m = _map(graph)
        graph.execute_write(lambda tx: maps.pin(
            tx, slug=SLUG, map_ref=m, entity=NPC, x=0.5, y=0.5))
        graph.execute_write(lambda tx: maps.reveal(
            tx, slug=SLUG, map_ref=m, entity=NPC, as_name="the coachman"))
        payload = str(graph.execute_read(lambda tx: maps.pins(
            tx, slug=SLUG, map_ref=m, for_player=True)))
        assert "Strahd" not in payload

    def test_the_dm_sees_both(self, graph):
        m = _map(graph)
        graph.execute_write(lambda tx: maps.pin(
            tx, slug=SLUG, map_ref=m, entity=NPC, x=0.5, y=0.5))
        graph.execute_write(lambda tx: maps.reveal(
            tx, slug=SLUG, map_ref=m, entity=NPC, as_name="the coachman"))
        found = graph.execute_read(lambda tx: maps.pins(
            tx, slug=SLUG, map_ref=m, for_player=False))[0]
        assert found["name"] == "Strahd von Zarovich"
        assert found["as_name"] == "the coachman"
