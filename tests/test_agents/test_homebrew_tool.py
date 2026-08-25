"""The contract between the chat agent and the generator.

The rule this file exists to hold: a model may ASK for material and may never
WRITE it into an answer. Everything else here is about not letting a model
invent an id.
"""


from backend.agents import homebrew_tool

HELD = frozenset({"kftgv:prisoner-13:varrin-axebreaker", "kftgv:golden-vault"})
SEEN = frozenset({"kftgv:prisoner-13#7", "kftgv:prisoner-13#8"})


def _validate(**arguments):
    return homebrew_tool.validate(arguments, held_ids=HELD, seen_sections=SEEN)


class TestTheAsk:
    def test_a_well_formed_ask_is_accepted(self):
        request, error = _validate(
            kind="scene",
            subject="a sea battle on the voyage",
            context_entity_ids=["kftgv:golden-vault"],
            insert_after_section_id="kftgv:prisoner-13#7",
            note="the party chartered a boat",
        )
        assert error == ""
        assert request.kind == "scene"
        assert request.context_entity_ids == ("kftgv:golden-vault",)
        assert request.insert_after == "kftgv:prisoner-13#7"

    def test_an_unknown_kind_is_refused(self):
        _, error = _validate(kind="sea-shanty", subject="x")
        assert "unknown kind" in error

    def test_a_missing_subject_is_refused(self):
        _, error = _validate(kind="npc", subject="   ")
        assert "subject" in error


class TestIdsAreCheckedAgainstTheConversation:
    """A constrained menu, not free text."""

    def test_an_invented_entity_id_is_dropped_and_reported(self):
        """Silently dropping it would let the model make the same mistake
        again next round with no idea why nothing happened."""
        request, _ = _validate(
            kind="npc", subject="a guard", context_entity_ids=["cos:strahd-von-zarovich"]
        )
        assert request.context_entity_ids == ()
        assert "cos:strahd-von-zarovich" in request.rejected

    def test_an_unseen_anchor_is_dropped_and_reported(self):
        """A model must not place a scene in a chapter nobody has opened."""
        request, _ = _validate(
            kind="scene", subject="a battle", insert_after_section_id="cos:the-village#3"
        )
        assert request.insert_after == ""
        assert "cos:the-village#3" in request.rejected

    def test_too_much_context_is_truncated_and_counted(self):
        held = frozenset(f"kftgv:e{i}" for i in range(10))
        request, _ = _validate_with(
            held, kind="npc", subject="x",
            context_entity_ids=[f"kftgv:e{i}" for i in range(10)],
        )
        assert len(request.context_entity_ids) == homebrew_tool.MAX_CONTEXT
        assert len(request.rejected) == 10 - homebrew_tool.MAX_CONTEXT

    def test_a_non_list_context_is_refused(self):
        _, error = _validate(kind="npc", subject="x", context_entity_ids="everything")
        assert "list" in error


def _validate_with(held, **arguments):
    return homebrew_tool.validate(arguments, held_ids=held, seen_sections=SEEN)


class TestWhatTheModelGetsBack:
    """THE LOAD-BEARING RULE. The tool returns an acknowledgement, never the
    material -- so a model cannot weave invention into an answer without the
    provenance envelope the generator enforces."""

    def test_the_result_carries_no_material(self):
        request, _ = _validate(kind="npc", subject="a harbour master")
        payload = request.acknowledgement
        assert "body" not in payload and "title" not in payload
        assert payload["queued"] is True

    def test_the_model_is_told_not_to_write_it(self):
        request, _ = _validate(kind="npc", subject="a harbour master")
        assert "Do not write it out yourself" in request.acknowledgement["instruction"]

    def test_rejected_ids_are_reported_back(self):
        request, _ = _validate(
            kind="npc", subject="x", context_entity_ids=["made:up"]
        )
        assert "made:up" in request.acknowledgement["ignored"]


class TestTheSchema:
    def test_the_description_tells_the_model_it_gets_a_card(self):
        description = homebrew_tool.SCHEMA["function"]["description"]
        assert "card" in description and "do not write the content" in description.lower()

    def test_scene_is_offered(self):
        enum = homebrew_tool.SCHEMA["function"]["parameters"]["properties"]["kind"]["enum"]
        assert "scene" in enum
