"""What a cluster would write, checked without a database.

Asserted on the PLAN rather than on the graph, for `test_chain.py`'s reason:
the plan is what the card shows a DM and what the store re-derives, so it is
the thing that has to be right.
"""

import pytest

from backend.campaign.cluster import plan_cluster

CAMPAIGN = "p13-home"


def element(name, kind="npc", **extra):
    return {"name": name, "kind": kind, "role": "", **extra}


class TestPlanning:
    def test_each_element_gets_an_id_in_the_campaign(self):
        plan = plan_cluster(campaign=CAMPAIGN, elements=[element("Captain Saltmarrow")])
        assert plan.elements[0].entity_id == "hb:p13-home:captain-saltmarrow"

    def test_provenance_travels(self):
        """The three-list split is the product; a plan that lost it would store
        a node nobody could tell the origin of."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[
                element(
                    "The Red Barge",
                    kind="location",
                    from_canon=[{"claim": "the voyage is by sea", "cite": "[1]"}],
                    invented=["her name", "her crew"],
                )
            ],
        )
        assert plan.elements[0].from_canon[0]["cite"] == "[1]"
        assert plan.elements[0].invented == ("her name", "her crew")

    def test_a_clean_plan_is_storable(self):
        assert plan_cluster(campaign=CAMPAIGN, elements=[element("A Guard")]).storable


class TestDropsAreCountedAndNamed:
    """"3 dropped" tells a reader nothing about whose fault it was."""

    def test_an_unslugifiable_name_is_dropped(self):
        plan = plan_cluster(campaign=CAMPAIGN, elements=[element("!!!")])
        assert plan.elements == ()
        assert plan.dropped == {"name slugifies to nothing": 1}

    def test_two_elements_minting_one_id_keep_the_first(self):
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("The Red Barge"), element("the red barge")],
        )
        assert len(plan.elements) == 1
        assert plan.dropped == {"two elements mint the same id": 1}

    def test_something_already_in_the_campaign_is_refused_not_merged(self):
        """`AlreadyStored`'s rule, checked before a person presses store."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("Captain Saltmarrow")],
            existing_ids=frozenset({"hb:p13-home:captain-saltmarrow"}),
        )
        assert plan.elements == ()
        assert plan.dropped == {"already in this campaign": 1}

    def test_declared_edges_are_counted_rather_than_silently_lost(self):
        """Edges are not stored in this slice -- measured at 27% type-impossible
        against a 20% gate. A model that proposed six relationships and had
        none kept should say so on the card."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("A Guard")],
            edges=[{"source": "a", "target": "b", "rel_type": "GUARDS"}] * 6,
        )
        assert plan.edges_deferred == 6


class TestApproval:
    def test_rejecting_an_element_drops_it_and_counts_it(self):
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("Kept"), element("Rejected")],
            approved=frozenset({"Kept"}),
        )
        assert [e.name for e in plan.elements] == ["Kept"]
        assert plan.dropped == {"rejected by the DM": 1}

    def test_no_selection_means_everything(self):
        """A freshly generated card has approved nothing explicitly yet."""
        plan = plan_cluster(campaign=CAMPAIGN, elements=[element("A"), element("B")])
        assert len(plan.elements) == 2

    def test_approval_is_case_insensitive(self):
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("Captain Saltmarrow")],
            approved=frozenset({"captain saltmarrow"}),
        )
        assert len(plan.elements) == 1


class TestCanonCollisions:
    """The trap: `hb:` and `cos:` are different namespaces, so a generated
    Varrin would mint happily and leave two nodes answering to one name."""

    ALIASES = frozenset({("varrin axebreaker", "kftgv:prisoner-13:varrin-axebreaker")})

    def test_a_collision_is_reported(self):
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("Varrin Axebreaker")],
            canon_aliases=self.ALIASES,
        )
        assert plan.collisions[0].canon_id == "kftgv:prisoner-13:varrin-axebreaker"

    def test_and_makes_the_plan_unstorable(self):
        """Refuse to guess about identity: the DM did not name the canon one."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("Varrin Axebreaker")],
            canon_aliases=self.ALIASES,
        )
        assert not plan.storable

    def test_linking_mints_nothing_but_records_the_link(self):
        """It was a drop and nothing else, which made "use the book's" a
        decision with no consequence: the DM said their scene involves the
        book's Varrin and asking about him tomorrow surfaced nothing."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("Varrin Axebreaker")],
            canon_aliases=self.ALIASES,
            resolutions={"Varrin Axebreaker": "link"},
        )
        assert plan.elements == () and plan.storable
        assert plan.links == (
            ("Varrin Axebreaker", "kftgv:prisoner-13:varrin-axebreaker"),
        )

    def test_a_link_is_not_counted_as_a_drop(self):
        """A drop report is what a DM reads to see what was thrown away. A
        link was not thrown away."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("Varrin Axebreaker")],
            canon_aliases=self.ALIASES,
            resolutions={"Varrin Axebreaker": "link"},
        )
        assert plan.dropped == {}

    def test_there_is_no_mint_it_anyway_choice(self):
        """`Alias.name` is globally unique, so a second node spelled the same
        cannot exist. Offering the choice would offer something the database
        forbids."""
        from backend.campaign.cluster import Collision

        assert set(Collision.choices) == {"link", "rename"}

    def test_an_unrecognised_resolution_leaves_the_collision_standing(self):
        """A typo in a choice must not become a decision nobody made."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("Varrin Axebreaker")],
            canon_aliases=self.ALIASES,
            resolutions={"Varrin Axebreaker": "seperate"},
        )
        assert not plan.storable

    def test_renaming_clears_the_collision(self):
        """A rename is a re-plan, which is why planning is pure and cheap."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("Varrin Stonebeard")],
            canon_aliases=self.ALIASES,
        )
        assert plan.storable and plan.collisions == ()

    def test_the_scan_folds_the_way_the_graph_folds(self):
        """`normalize`, never a second normalizer -- the curly-apostrophe
        defect is the precedent."""
        aliases = frozenset({("vidorant's vault", "kftgv:vidorants-vault")})
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("Vidorant’s Vault", kind="location")],
            canon_aliases=aliases,
        )
        assert plan.collisions, "a curly apostrophe must not hide a collision"


class TestThePlannerStaysPure:
    def test_it_imports_no_database(self):
        """The card calls this on every edit. A planner that opened a session
        would make a rename a round trip, and would put a rule inside a
        transaction where it cannot be argued with."""
        import ast
        from pathlib import Path

        tree = ast.parse(Path("backend/campaign/cluster.py").read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        # Checked as IMPORTS, not as text: the module docstring says the word
        # "Neo4j" while explaining that it does not touch one, and a substring
        # search failed on its own explanation.
        assert not any(
            m.startswith(("neo4j", "backend.core.database")) for m in imported
        ), sorted(imported)

    def test_planning_twice_gives_the_same_plan(self):
        args = dict(campaign=CAMPAIGN, elements=[element("A"), element("B")])
        assert plan_cluster(**args).as_dict() == plan_cluster(**args).as_dict()


class TestTheAccountingBalances:
    def test_every_declared_element_is_planned_or_counted(self):
        """The identity `written + every named drop == declared`, which is what
        makes a drop report trustworthy rather than decorative."""
        declared = [
            element("Kept One"),
            element("Kept Two"),
            element("!!!"),
            element("Rejected"),
            element("Kept One"),
        ]
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=declared,
            approved=frozenset({"Kept One", "Kept Two", "!!!"}),
        )
        assert len(plan.elements) + sum(plan.dropped.values()) == len(declared)


@pytest.mark.parametrize("kind", ["npc", "monster", "location", "item", "lore"])
def test_every_offered_element_kind_plans(kind):
    plan = plan_cluster(campaign=CAMPAIGN, elements=[element(f"A {kind}", kind=kind)])
    assert plan.elements[0].kind == kind


class TestHomebrewSlugsMatchCanonSlugs:
    """Two slug rules in one graph would be two answers to one question.

    `homebrew.slugify` and the canon writer's `mint_id` both turn a name into
    an id, and they must agree: an apostrophe becoming a separator in one and
    vanishing in the other would make `hb:...:the-kraken-s-purse` and
    `cos:the-krakens-purse` two spellings of one thing, with the collision
    scan blind to it.
    """

    @pytest.mark.parametrize(
        "name",
        ["The Kraken's Purse", "Vidorant’s Vault", "Revel's End", "Chef Tiny Toulaine"],
    )
    def test_the_same_name_slugifies_the_same_way(self, name):
        from backend.campaign.homebrew import slugify
        from backend.canon.writer import mint_id

        assert mint_id("a-chapter", name).split(":", 1)[1] == slugify(name)
