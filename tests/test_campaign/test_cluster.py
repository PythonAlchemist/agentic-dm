"""What a cluster would write, checked without a database.

Asserted on the PLAN rather than on the graph, for `test_chain.py`'s reason:
the plan is what the card shows a DM and what the store re-derives, so it is
the thing that has to be right.
"""

import pytest

from backend.campaign.cluster import edge_key, plan_cluster

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

    def test_an_edge_reaching_outside_the_cluster_is_dropped_and_named(self):
        """A cross-plane edge into canon is readable from neither plane, so it
        is refused with that said rather than written where nobody looks."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("A Guard")],
            edges=[{"source": "Strahd", "target": "A Guard", "rel_type": "SEEKS"}],
        )
        assert plan.edges == ()
        assert plan.edges_dropped == {"an endpoint is not in this cluster": 1}

    def test_a_type_impossible_edge_is_dropped_and_says_why(self):
        """The same domain/range check canon extraction runs -- there is one
        table, not a laxer one for material a DM wrote. An edge that is wrong
        BOTH ways round is a drop; one that is merely backwards is offered
        instead, which `TestAnEdgeWrittenBackwards` covers."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("A Cutlass", kind="item"), element("A Vault", kind="location")],
            edges=[{"source": "A Cutlass", "target": "A Vault", "rel_type": "GAVE_QUEST"}],
        )
        assert plan.edges == ()
        assert plan.edges_reversible == ()
        assert plan.edges_dropped == {"GAVE_QUEST: both": 1}

    def test_a_type_valid_edge_between_two_of_its_own_survives(self):
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("A Guard"), element("The Vault", kind="location")],
            edges=[{"source": "A Guard", "target": "The Vault", "rel_type": "LOCATED_IN"}],
        )
        assert plan.edges == (("A Guard", "The Vault", "LOCATED_IN"),)
        assert plan.edges_dropped == {}

    def test_the_generation_itself_is_an_endpoint(self):
        """Most of what a model declares points at the scene. Leaving the root
        out of the node set dropped nearly all of it."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("A Guard")],
            edges=[{"source": "The Ambush", "target": "A Guard", "rel_type": "INVOLVES"}],
            root_name="The Ambush",
            root_kind="scene",
        )
        assert plan.edges == (("The Ambush", "A Guard", "INVOLVES"),)

    def test_unticking_an_element_takes_its_edges_with_it(self):
        """Which is what unticking it means. `planned` is already the approved
        set, so this falls out rather than needing its own pass."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("A Guard"), element("The Vault", kind="location")],
            edges=[{"source": "A Guard", "target": "The Vault", "rel_type": "LOCATED_IN"}],
            approved=frozenset({"The Vault"}),
        )
        assert plan.edges == ()
        assert plan.edges_dropped == {"an endpoint is not in this cluster": 1}


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


class TestAnEdgeWrittenBackwards:
    """Four of twenty-two declared edges in a ten-subject run were legal in one
    direction and impossible in the other. Every one was a real relationship
    pointing the wrong way, and dropping them lost the relationship with the
    mistake."""

    ELEMENTS = [element("Wolves", kind="monster"), element("Vistani Camp", kind="location")]
    BACKWARDS = [{"source": "Vistani Camp", "target": "Wolves", "rel_type": "THREATENS"}]

    def test_it_is_offered_in_the_direction_that_would_work(self):
        plan = plan_cluster(
            campaign=CAMPAIGN, elements=self.ELEMENTS, edges=self.BACKWARDS,
            root_name="Dusk", root_kind="scene",
        )
        assert plan.edges_reversible == (("Wolves", "Vistani Camp", "THREATENS"),)

    def test_it_is_not_written_until_somebody_says_so(self):
        """`Strahd SEEKS Ireena` and its reverse are different claims about one
        pair. Turning an edge round is a decision, not a repair."""
        plan = plan_cluster(
            campaign=CAMPAIGN, elements=self.ELEMENTS, edges=self.BACKWARDS,
            root_name="Dusk", root_kind="scene",
        )
        assert plan.edges == ()

    def test_accepting_it_writes_the_turned_edge(self):
        plan = plan_cluster(
            campaign=CAMPAIGN, elements=self.ELEMENTS, edges=self.BACKWARDS,
            root_name="Dusk", root_kind="scene",
            accept_reversed=frozenset({edge_key("Wolves", "Vistani Camp", "THREATENS")}),
        )
        assert plan.edges == (("Wolves", "Vistani Camp", "THREATENS"),)
        assert plan.edges_reversible == ()

    def test_an_edge_wrong_in_both_directions_is_still_dropped(self):
        """Only a genuine reversal is offered. `Wolves CONNECTED_TO Dire Wolf`
        is not a route between two places whichever way it is read."""
        plan = plan_cluster(
            campaign=CAMPAIGN,
            elements=[element("Wolves", kind="monster"), element("Dire Wolf", kind="monster")],
            edges=[{"source": "Wolves", "target": "Dire Wolf", "rel_type": "CONNECTED_TO"}],
            root_name="Dusk", root_kind="scene",
        )
        assert plan.edges_reversible == ()
        assert plan.edges == ()
        assert plan.edges_dropped == {"CONNECTED_TO: both": 1}
