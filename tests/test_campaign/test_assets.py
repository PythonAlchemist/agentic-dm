"""Pictures, and where each one came from.

`origin` is `plane` for pixels. The promise does not stop at sentences: a
portrait the book printed, one a DM uploaded, and a face a model imagined are
three different things, and the moment they render alike the promise is broken
in the most persuasive medium the product has.
"""

import pytest

from backend.campaign import assets
from backend.campaign.invariants import UNSOURCED_ASSETS
from backend.core.database import neo4j_session

PREFIX = "pytest-asset"
SLUG = f"{PREFIX}-camp"
WHEN = "2026-09-02T00:00:00Z"


@pytest.fixture
def graph():
    with neo4j_session() as session:
        def clean(s):
            s.run("MATCH (a:Asset) WHERE a.sha256 STARTS WITH 'pytest' "
                  "DETACH DELETE a").consume()
            s.run("MATCH (e:Entity) WHERE e.id STARTS WITH $p DETACH DELETE e",
                  {"p": PREFIX}).consume()

        clean(session)
        session.run("CREATE (:Entity {id:$e, plane:'canon', name:'Strahd'})",
                    {"e": f"{PREFIX}:strahd"}).consume()
        yield session
        clean(session)


class TestOriginIsPinnedAtOneWriterPerKind:
    """No route may choose. `store_upload` can only ever stamp `uploaded`, the
    same way `plane:'canon'` is the seed loader's alone."""

    def test_an_upload_is_recorded_as_yours(self, graph):
        row = graph.execute_write(lambda tx: assets.store_upload(
            tx, sha256="pytest1", media_type="image/png", campaign=SLUG,
            uploaded_by="ana", created_at=WHEN))
        assert row["origin"] == assets.UPLOADED

    def test_a_generated_asset_is_recorded_as_imagined(self, graph):
        row = graph.execute_write(lambda tx: assets.store_generated(
            tx, sha256="pytest2", media_type="image/png", campaign=SLUG,
            generator="some-model", prompt="a pale count", created_at=WHEN))
        assert row["origin"] == assets.GENERATED

    def test_a_generated_asset_must_name_its_generator(self, graph):
        """Its evidence, the way a canon claim carries the sentence it was read
        from. An image with no record of what made it cannot be checked."""
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: assets.store_generated(
                tx, sha256="pytest3", media_type="image/png", campaign=SLUG,
                generator="", prompt="x", created_at=WHEN))

    def test_an_origin_outside_the_three_is_refused(self, graph):
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: assets._write(
                tx, sha256="pytest4", media_type="image/png", origin="scanned",
                campaign=SLUG, created_at=WHEN))

    def test_every_origin_has_words_for_a_reader(self, graph):
        """Kept beside the property so the caption cannot drift from the thing
        that decides it."""
        assert set(assets.CAPTION) == assets.ORIGINS


class TestTheSameImageTwiceIsOneAsset:
    def test_content_addressed(self, graph):
        first = graph.execute_write(lambda tx: assets.store_upload(
            tx, sha256="pytest5", media_type="image/png", campaign=SLUG,
            uploaded_by="ana", created_at=WHEN))
        again = graph.execute_write(lambda tx: assets.store_upload(
            tx, sha256="pytest5", media_type="image/png", campaign=SLUG,
            uploaded_by="bob", created_at=WHEN))
        assert first["id"] == again["id"]

    def test_a_path_fans_out_so_one_directory_never_holds_everything(self):
        from pathlib import Path

        found = assets.path_for(Path("/root"), "abcdef0123", ".png")
        assert found == Path("/root/ab/cd/abcdef0123.png")


class TestPortraitsHangOffTheCampaign:
    """Two tables may imagine the same canon NPC differently and neither is the
    book's, so the edge carries the campaign -- which is also what lets
    `delete_campaign` take the portrait without touching a node the book owns."""

    def test_an_entity_can_be_portrayed(self, graph):
        row = graph.execute_write(lambda tx: assets.store_generated(
            tx, sha256="pytest6", media_type="image/png", campaign=SLUG,
            generator="m", prompt="p", created_at=WHEN))
        graph.execute_write(lambda tx: assets.portray(
            tx, entity=f"{PREFIX}:strahd", asset=row["id"], campaign=SLUG))
        found = graph.execute_read(lambda tx: assets.portraits(
            tx, entity=f"{PREFIX}:strahd", campaign=SLUG))
        assert [p["origin"] for p in found] == [assets.GENERATED]

    def test_the_canon_node_itself_is_not_touched(self, graph):
        row = graph.execute_write(lambda tx: assets.store_upload(
            tx, sha256="pytest7", media_type="image/png", campaign=SLUG,
            uploaded_by="ana", created_at=WHEN))
        graph.execute_write(lambda tx: assets.portray(
            tx, entity=f"{PREFIX}:strahd", asset=row["id"], campaign=SLUG))
        keys = graph.run("MATCH (e:Entity {id:$e}) RETURN keys(e) AS k",
                         {"e": f"{PREFIX}:strahd"}).single()["k"]
        assert "portrait" not in keys and "image" not in keys

    def test_another_table_sees_none_of_it(self, graph):
        row = graph.execute_write(lambda tx: assets.store_upload(
            tx, sha256="pytest8", media_type="image/png", campaign=SLUG,
            uploaded_by="ana", created_at=WHEN))
        graph.execute_write(lambda tx: assets.portray(
            tx, entity=f"{PREFIX}:strahd", asset=row["id"], campaign=SLUG))
        found = graph.execute_read(lambda tx: assets.portraits(
            tx, entity=f"{PREFIX}:strahd", campaign="somebody-else"))
        assert found == []


class TestTheInvariantSeesAnAssetWithNoOrigin:
    def test_it_is_caught(self, graph):
        graph.run("CREATE (:Asset {id:'pytest-bare', sha256:'pytest9'})").consume()
        try:
            rows = [dict(r) for r in graph.run(UNSOURCED_ASSETS)]
            assert any(r["id"] == "pytest-bare" for r in rows), rows
        finally:
            graph.run("MATCH (a:Asset {id:'pytest-bare'}) DETACH DELETE a").consume()

    def test_a_generated_asset_with_no_generator_is_caught(self, graph):
        graph.run("CREATE (:Asset {id:'pytest-nogen', sha256:'pytest10', "
                  "origin:'generated'})").consume()
        try:
            rows = [dict(r) for r in graph.run(UNSOURCED_ASSETS)]
            assert any(r["id"] == "pytest-nogen" for r in rows), rows
        finally:
            graph.run("MATCH (a:Asset {id:'pytest-nogen'}) DETACH DELETE a").consume()
