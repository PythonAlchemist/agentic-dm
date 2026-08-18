"""The audit that finds golds the book also answers elsewhere.

Pure functions only: the fingerprint and the rival rule. Whether a rival really
answers the question is a reading, and the script is explicit that it only
prints a queue.
"""

from backend.scripts.audit_questions import fingerprint, rivals


def section(sid: str, heading: str, head: str = "") -> dict:
    return {"id": sid, "heading": heading, "head": head}


class TestFingerprint:
    def test_it_takes_the_names_out_of_the_note(self):
        assert fingerprint("Rahadin. He approaches quietly.", "Who is the chamberlain?") == [
            "Rahadin"
        ]

    def test_a_name_the_question_already_uses_is_not_distinctive(self):
        """Every section about Strahd contains `Strahd`. Keeping it would flag
        the whole book for every question that names him."""
        assert "Rahadin" not in fingerprint("Rahadin serves him.", "Who is Rahadin?")

    def test_the_ubiquitous_place_names_are_dropped(self):
        """`Castle Ravenloft` is in a third of the book's sections, so a
        fingerprint containing it matches the corpus rather than an answer."""
        got = fingerprint("Vladimir Horngaard, in Castle Ravenloft.", "Who?")
        assert got == ["Horngaard", "Vladimir"]

    def test_a_sentence_opener_is_not_a_name(self):
        assert fingerprint("Two of them, one at Tser Pool.", "Where?") == ["Pool", "Tser"]

    def test_a_note_with_no_names_yields_nothing_rather_than_everything(self):
        assert fingerprint("A d20, rolled once per hour.", "What do I roll?") == []


class TestRivals:
    def test_a_section_headed_with_the_answers_name_is_queued(self):
        q = {
            "id": "q22",
            "question": "Who are the undead enemies?",
            "sections": ["cos:argynvostholt#1"],
            "note": "Revenants led by Vladimir Horngaard.",
        }
        sections = [
            section("cos:argynvostholt#1", "The Order of the Silver Dragon"),
            section("cos:appendix-d#38", "Vladimir Horngaard"),
            section("cos:elsewhere#1", "Wine Cellar"),
        ]
        got = {s["id"] for s in rivals(q, sections, {s["id"]: s for s in sections})}
        assert got == {"cos:appendix-d#38"}

    def test_the_gold_itself_is_never_queued_against_itself(self):
        q = {
            "id": "q1",
            "question": "Who?",
            "sections": ["cos:a#1"],
            "note": "Rahadin.",
        }
        sections = [section("cos:a#1", "Rahadin")]
        assert rivals(q, sections, {"cos:a#1": sections[0]}) == []

    def test_a_second_section_sharing_the_golds_heading_is_queued(self):
        """The q25 shape. The book heads two different sections `Rahadin` --
        the encounter and the NPC entry -- and no fingerprint separates them
        because the name is identical, so the heading match is what finds it."""
        q = {
            "id": "q25",
            "question": "Who is the chamberlain?",
            "sections": ["cos:castle-ravenloft#7"],
            # Deliberately noteless, so ONLY the shared-heading rule can fire.
            "note": "",
        }
        sections = [
            section("cos:castle-ravenloft#7", "Rahadin"),
            section("cos:appendix-d#28", "Rahadin"),
            section("cos:other#1", "Lair Actions"),
        ]
        got = {s["id"] for s in rivals(q, sections, {s["id"]: s for s in sections})}
        assert got == {"cos:appendix-d#28"}

    def test_a_question_with_nothing_to_match_queues_nothing(self):
        q = {"id": "q1", "question": "What do I roll?", "sections": ["cos:a#1"],
             "note": "A d20."}
        sections = [section("cos:a#1", "House Occupants"), section("cos:b#2", "Wolves")]
        assert rivals(q, sections, {s["id"]: s for s in sections}) == []

    def test_a_section_is_queued_once_even_when_both_rules_fire(self):
        q = {"id": "q1", "question": "Who?", "sections": ["cos:a#1"], "note": "Rahadin."}
        sections = [section("cos:a#1", "Rahadin"), section("cos:b#2", "Rahadin")]
        assert len(rivals(q, sections, {s["id"]: s for s in sections})) == 1
