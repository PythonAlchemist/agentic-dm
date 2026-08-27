"""DM Agent for running games and assisting DMs."""

import logging
from dataclasses import replace

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from backend.agents import canon_context, graph_tools, homebrew_tool
from backend.agents import subgraph as subgraph_module
from backend.agents.conversation import ConversationManager
from backend.agents.prompts import SYSTEM_PROMPT
from backend.agents.subgraph import Subgraph, note_named
from backend.agents.subgraph import seed as seed_subgraph
from backend.agents.tools import DiceResult, DMTools
from backend.canon import ontology
from backend.canon.lookup import CANON_PLANE, TOGETHER
from backend.canon.retrieval import (
    PATH_GRAPH,
    PATH_TEXT,
    CanonRetriever,
    Retrieval,
)
from backend.core.config import settings
from backend.core.database import read_only_session
from backend.core.pricing import Usage, estimate
from backend.rag import HybridRAGPipeline, QueryType

logger = logging.getLogger(__name__)


#: How many times a turn may go back to the graph before answering with what
#: it has. A model still asking after three rounds is not converging, and each
#: round is another call, another few seconds, and another chance to be
#: inconsistent -- this model already varies run to run on whether it cites.
_TOOL_ROUNDS = 3

#: How the agent samples in normal use. A DM asking the same question twice
#: wants two readings rather than the same sentence back, so this is not 0.
_TEMPERATURE = 0.5

#: Pinned by the evaluation harness and by nothing else -- see `eval_answers`.
#: `temperature=0` plus a fixed `seed` is what the extraction path already uses
#: (`EXTRACTION_SEED`) and for the same reason: a measurement whose inputs move
#: between runs cannot say whether its output moved because of a change.
#:
#: Best-effort, not a guarantee. OpenAI documents the seed that way, and
#: `system_fingerprint` is how a caller learns the backend changed underneath
#: it. Reducing the noise is not the same as removing it, and the harness
#: reports what is left rather than assuming there is none.


class DMResponse(BaseModel):
    """Response from the DM Agent."""

    message: str
    query_type: QueryType | None = None
    tool_results: list[dict] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    #: Tokens the call consumed and what the rate table says that cost. Absent
    #: on a tool command, which never reaches a model. Reported rather than
    #: merely logged: the number that matters to somebody paying for this is the
    #: one attached to the answer they just read.
    usage: dict | None = None
    cost: dict | None = None
    #: What retrieval did -- which names anchored, which path answered, what the
    #: budget cut. The dashboard shows it beside the answer so a thin answer can
    #: be traced to thin context rather than blamed on the model.
    retrieval: dict | None = None
    #: What the CONVERSATION is holding, after this turn. Sent every turn
    #: rather than only when it changes: a panel that updated on some turns and
    #: not others would leave a reader unsure whether nothing changed or
    #: nothing was sent.
    subgraph: dict | None = None
    #: Draft cards the model asked for this turn, each with its provenance
    #: split. NEVER folded into `message`: a generation that reached the reader
    #: as prose would be invention wearing an answer's clothes, with none of
    #: the envelope the generator exists to enforce. A person approves a card;
    #: nothing here has been written to the graph.
    generations: list[dict] = Field(default_factory=list)


#: Kinds that CONTAIN other things, and so are worth a second call to declare
#: what they contain. An npc or a monster is one thing; annotating it would
#: spend a call to be told so.
CLUSTER_KINDS = frozenset({"quest", "scene"})


class DMAgent:
    """AI Dungeon Master agent."""

    def __init__(
        self,
        campaign_id: str | None = None,
        campaign_context: dict | None = None,
        canon: CanonRetriever | None = None,
        model: str | None = None,
        depth: canon_context.Depth | None = None,
        temperature: float = _TEMPERATURE,
        seed: int | None = None,
    ):
        """Initialize the DM Agent.

        Args:
            campaign_id: Optional campaign to load context from.
            campaign_context: Optional campaign context fields to inject into system prompt.
            canon: Read path into the canon graph. Injectable so a test can
                exercise the grounding without a live Neo4j.
        """
        self.campaign_id = campaign_id
        self.campaign_context = campaign_context

        # Initialize components
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = model or settings.openai_model
        # Injected rather than read from settings: only the evaluation harness
        # pins these, and a global that changed sampling for every DM in order
        # to make a measurement repeatable would be the measurement altering
        # the thing measured.
        self.temperature = temperature
        self.seed = seed
        self.depth = depth or canon_context.Depth()
        self.rag_pipeline = HybridRAGPipeline()
        self.tools = DMTools()
        self.canon = canon or CanonRetriever(
            limit=self.depth.passages, passage_width=self.depth.passage_width
        )
        self.conversation = ConversationManager()
        #: What this conversation is holding, as graph entities. The transcript
        #: is bounded and short; THIS is how a follow-up knows who "him" is.
        self.subgraph = Subgraph()
        #: Validated generation asks from THIS turn, cleared at the start of
        #: each one. Per-turn rather than per-session: a card the DM has
        #: already been shown must not be re-generated on the next question.
        self._requested_generations: list = []
        #: Section ids this session has actually put in front of the model.
        #: The anchor a generation may name is checked against it, so a model
        #: cannot place a scene into a chapter nobody has opened.
        self._seen_sections: set[str] = set()

        # Set system prompt
        self._set_system_prompt()

    def _set_system_prompt(self) -> None:
        """Set the system prompt, optionally enriched with campaign context."""
        prompt = SYSTEM_PROMPT

        if self.campaign_context:
            context_parts = []
            field_labels = {
                "name": "Campaign",
                "setting": "Setting",
                "world_description": "World",
                "theme": "Theme",
                "rule_system": "Rule System",
                "level_range": "Level Range",
                "house_rules": "House Rules",
                "allowed_sources": "Allowed Sources",
                "premise": "Premise",
                "current_story_arc": "Current Story Arc",
                "dm_notes": "DM Notes",
            }
            for key, label in field_labels.items():
                value = self.campaign_context.get(key)
                if value:
                    context_parts.append(f"- **{label}:** {value}")

            if context_parts:
                prompt += "\n\n**Active Campaign Context:**\n" + "\n".join(context_parts)

        self.conversation.set_system_prompt(prompt)

    async def process_message(
        self,
        user_input: str,
        use_rag: bool = True,
        use_canon: bool = True,
    ) -> DMResponse:
        """Process a user message.

        Args:
            user_input: User's input text.
            use_rag: Whether to use RAG for context.
            use_canon: Whether to ground the answer in the canon graph.

        Returns:
            DMResponse with the agent's response.
        """
        # A turn is one exchange, and everything touched during it is pinned
        # against eviction -- see `Subgraph.evict`. Beginning the turn also
        # expires the previous answer's unused name-drops; see
        # `Subgraph.expire` for why that is a turn boundary and not a budget.
        self.subgraph.begin_turn()

        # Add user message to history
        self.conversation.add_user_message(user_input)

        # Check for tool commands first
        tool_result = self._check_tool_commands(user_input)
        if tool_result:
            response = await self._generate_tool_response(user_input, tool_result)
            self.conversation.add_assistant_message(response.message)
            return response

        # Retrieve canon BEFORE the RAG pipeline, and unconditionally when
        # enabled. It is deterministic and costs no API call, so there is
        # nothing to gate it on -- and a heuristic deciding when a question is
        # "about the book" would fail exactly on the questions a DM most needs
        # grounded. A question naming nothing simply retrieves little.
        # Cleared per TURN: a card the DM has already been shown must not
        # re-generate on the next question.
        self._requested_generations = []

        retrieval = self._retrieve_canon(user_input) if use_canon else None
        if retrieval is not None:
            seed_subgraph(self.subgraph, retrieval)
            self.subgraph.evict(self.depth.subgraph_budget)
            # Accumulates across the session, because a model may anchor a
            # scene to a section it read two questions ago.
            self._seen_sections.update(p.section_id for p in retrieval.passages)

        # Use RAG pipeline for context
        rag_response = None
        if use_rag:
            rag_response = await self.rag_pipeline.query(
                question=user_input,
                conversation_history=self.conversation.get_context(include_system=False),
            )

        # Generate response
        response = await self._generate_response(user_input, rag_response, retrieval)

        # What the ANSWER named. Retrieval's anchors are what the QUESTION
        # resolved, and a question often names nothing while its answer names
        # the subject -- "who owns the tavern" anchors nothing and is answered
        # about the Blood of the Vine Tavern.
        note_named(self.subgraph, response.message, self._names_in)
        self.subgraph.evict(self.depth.subgraph_budget)

        # Add to history
        self.conversation.add_assistant_message(
            response.message,
            metadata={"sources": response.sources},
        )

        return response

    def _check_tool_commands(self, user_input: str) -> dict | None:
        """Check if input is a tool command.

        Args:
            user_input: User's input text.

        Returns:
            Tool result if command detected, None otherwise.
        """
        input_lower = user_input.lower().strip()

        # Dice rolling
        if input_lower.startswith(("roll ", "/roll ", "/r ")):
            expression = user_input.split(" ", 1)[1] if " " in user_input else "1d20"
            result = self.tools.roll_dice(expression)
            return {"type": "dice", "result": result}

        # NO `generate npc` OR `generate encounter` HERE, DELIBERATELY.
        #
        # Both used to short-circuit to random tables in `DMTools` -- name
        # sampled from a pool, two traits, an appearance keyed off race -- with
        # no model, no canon and no provenance split. And they ran BEFORE
        # retrieval, so in one chat box "generate npc" got random tables while
        # "make me an NPC for the tavern" got a grounded card with citations.
        # The phrasing silently chose the engine and the answer never said
        # which one had written it, in a project whose whole method is that a
        # DM can always tell.
        #
        # Both phrasings now fall through to the ordinary grounded path, where
        # the model can call `generate_homebrew` and the result arrives as a
        # card a person approves. `DMTools.generate_npc` still exists and is
        # still reachable at `POST /api/chat/tools/npc`, which nothing calls;
        # that surface is dormant rather than misleading, because reaching it
        # takes a deliberate request rather than a turn of phrase.

        # Start combat
        if input_lower.startswith(("/combat", "start combat")):
            return {"type": "combat_start", "result": None}

        # Next turn in combat
        if input_lower.startswith(("/next", "next turn")):
            result = self.tools.next_turn()
            return {"type": "combat_next", "result": result}

        return None

    async def _generate_tool_response(
        self,
        user_input: str,
        tool_result: dict,
    ) -> DMResponse:
        """Generate response for a tool command.

        Args:
            user_input: Original user input.
            tool_result: Result from tool execution.

        Returns:
            DMResponse with formatted tool output.
        """
        tool_type = tool_result["type"]
        result = tool_result["result"]

        if tool_type == "dice":
            dice: DiceResult = result
            message = f"**Rolled {dice.expression}:** {dice.rolls}"
            if dice.modifier != 0:
                message += f" + {dice.modifier}" if dice.modifier > 0 else f" - {abs(dice.modifier)}"
            message += f" = **{dice.total}**"
            if dice.critical:
                message += " (Critical!)" if dice.total > 10 else " (Critical Fail!)"

            return DMResponse(
                message=message,
                tool_results=[{"type": "dice", "result": dice.model_dump()}],
            )

        elif tool_type == "combat_next":
            if result:
                current = result["current"]
                message = f"**Round {result['round']}** - {current['name']}'s turn"
                message += f" ({current['hp']}/{current['max_hp']} HP)"
            else:
                message = "No combat active. Use /combat to start."

            return DMResponse(
                message=message,
                tool_results=[{"type": "combat", "result": result}] if result else [],
            )

        return DMResponse(message="Command processed.")

    def _names_in(self, text: str) -> list[tuple[str, str, tuple[str, ...]]]:
        """Every canon entity a piece of prose names, as `(id, name, labels)`.

        The retriever's own machinery, so an answer is read exactly as a
        question is: whole-word, apostrophe-folded, and refusing the common
        nouns `anchorable_forms` refuses. A second matcher here would be free
        to disagree with the first about what counts as a name.

        Degrades to nothing if the graph is unreachable, for the same reason
        `_retrieve_canon` returns an empty retrieval: a DM mid-session gets a
        thinner memory, never a stack trace.
        """
        from backend.canon.aliases import normalize
        from backend.canon.lookup import type_labels
        from backend.canon.retrieval import (
            ALL_ALIASES,
            BY_ALIAS,
            anchorable_forms,
            find_names,
        )

        try:
            with self.canon._session() as session:
                forms = anchorable_forms(self.canon._rows(session, ALL_ALIASES))
                found: list[tuple[str, str, tuple[str, ...]]] = []
                for surface in find_names(text, forms):
                    for row in self.canon._rows(
                        session, BY_ALIAS, {"normalized": normalize(surface)}
                    ):
                        found.append(
                            (row["id"], row["name"], tuple(type_labels(row["labels"])))
                        )
                return found
        except Exception:  # noqa: BLE001 - a thinner memory beats a crash
            logger.warning("could not read names out of the answer", exc_info=True)
            return []

    def _ontology(self) -> str:
        """The graph's vocabulary, or nothing at all if it cannot be read.

        Empty on failure, unlike `_retrieve_canon`, and the asymmetry is
        deliberate. A missing canon block has to be replaced by an explicit
        "the canon covers nothing", because silence there lets the model answer
        from its own memory of the published adventure. Silence HERE returns
        the model to exactly where it was before this existed -- reading the
        schema off whatever instances come back -- which is degraded but not
        misleading. Inventing a vocabulary to fill the gap would be.
        """
        try:
            with read_only_session() as session:
                return ontology.read(session).render()
        except Exception:  # noqa: BLE001 - a vocabulary must not fail a turn
            logger.warning("could not read the graph vocabulary", exc_info=True)
            return ""

    def _named_together(self, view: dict) -> list[dict]:
        """Which held entities the book names in one sentence.

        Attached to the view a READER gets and never to `Subgraph.render()`,
        which is what the model reads -- see `lookup.TOGETHER` for why that
        line is drawn where it is.

        Degrades to nothing, like `_ontology`: this is an extra way of looking
        at what the panel already shows, and a panel missing one of its layers
        beats a turn that failed.
        """
        ids = [node["id"] for node in view["nodes"]]
        if len(ids) < 2:
            return []
        try:
            with read_only_session() as session:
                return [
                    dict(record)
                    for record in session.run(
                        TOGETHER, {"ids": ids, "plane": CANON_PLANE}
                    )
                ]
        except Exception:  # noqa: BLE001 - a panel layer must not fail a turn
            logger.warning("could not read what was named together", exc_info=True)
            return []

    def _subgraph_view(self) -> dict:
        """The working set as a reader sees it, with the sentence layer on top."""
        view = self.subgraph.as_dict()
        view["together"] = self._named_together(view)
        return view

    def _retrieve_canon(self, user_input: str) -> Retrieval:
        """Canon for this question. An EMPTY retrieval if the graph is unreachable.

        Empty rather than None, and the difference is the whole point of the
        `except`. A DM mid-session should get a degraded answer rather than a
        stack trace -- but "degraded" must mean the model is TOLD the canon
        covers nothing, which is what an empty retrieval renders to. Returning
        None would omit the block entirely, and a model with no canon block and
        no instruction about one answers from its own memory of the published
        adventure. That is the failure this whole path exists to prevent, and it
        would appear exactly when the database is down: silently, and only in
        production.
        """
        try:
            # The conversation's own subjects, used ONLY if the question
            # resolves nothing itself. This is what makes the subgraph reach
            # RETRIEVAL and not merely the prompt: knowing that "the pub" means
            # the Blood of the Vine Tavern is no use while the eight sections
            # in front of the model are `Tyger, Tyger` and `Crypt 10`.
            carry = [held.id for held in self.subgraph.subjects()]
            return self.canon.retrieve(user_input, carry=carry)
        except Exception:  # noqa: BLE001 - degraded answer beats a crash mid-session
            logger.warning("canon retrieval failed; answering without it", exc_info=True)
            return Retrieval(question=user_input)

    async def _generate_response(
        self,
        user_input: str,
        rag_response=None,
        retrieval=None,
    ) -> DMResponse:
        """Generate a response using the LLM.

        Args:
            user_input: User's input.
            rag_response: Optional RAG response with context.
            retrieval: Optional canon retrieval to ground the answer in.

        Returns:
            DMResponse with generated content.
        """
        # Build context for the prompt
        context = self.conversation.get_context(include_system=True)

        # The canon block carries the PASSAGES THEMSELVES, not a list of what
        # was consulted. Inserted after the system prompt and before the
        # conversation, so the model reads the book's words before the question
        # rather than after its own previous answers.
        canon_sources: list[dict] = []
        retrieval_report: dict | None = None

        # Ordered blocks rather than three hardcoded indices, which had to
        # agree with each other by hand and would silently reorder the moment a
        # fourth one appeared -- as it just did.
        #
        # The vocabulary comes FIRST and is not conditional on retrieval: it
        # describes the tools, which are offered on every call, and a question
        # that retrieved nothing is exactly when the model is most likely to go
        # looking through them.
        blocks = [self._ontology()]
        if retrieval is not None:
            shown = canon_context.apply(retrieval, self.depth)
            blocks.append(
                canon_context.render(shown, max_edges=self.depth.max_edges)
            )
            # AFTER the canon block, so the model reads the book's words
            # first and then what the conversation has been about -- the same
            # ordering argument as inserting canon before the question.
            blocks.append(self.subgraph.render(self.depth.include_proposed))
        for offset, block in enumerate(b for b in blocks if b):
            context.insert(1 + offset, {"role": "system", "content": block})

        if retrieval is not None:
            canon_sources = canon_context.sources(shown)
            # Reported off the UNFILTERED retrieval on purpose: a reader needs
            # to see that 30 proposed edges existed and were withheld, not that
            # there were none.
            retrieval_report = {
                # How the QUESTION resolved -- on a name, or on nothing. This
                # says nothing about which path produced any given passage.
                "path": retrieval.path,
                # WHICH PATH PUT EACH PASSAGE THERE. A result that anchored on a
                # name now also carries text passages, because `TEXT_SLOTS`
                # reserves room for them, so `path` alone reported `graph` for a
                # mixed result and the panel showed "by name" over passages
                # Lucene had found. The same mislabelling was fixed in
                # `canon_context.sources` and in the evaluation harness, which
                # had been crediting a resolved name for answers a keyword
                # match earned; this was the third copy of it.
                "passages_by_path": {
                    PATH_GRAPH: sum(
                        1 for p in shown.passages if p.path == PATH_GRAPH
                    ),
                    PATH_TEXT: sum(1 for p in shown.passages if p.path == PATH_TEXT),
                },
                "anchors": [f"{a.surface} → {a.name}" for a in retrieval.anchors],
                "passages": len(shown.passages),
                "dropped": retrieval.dropped,
                "accepted_edges": len(retrieval.accepted),
                "proposed_edges": len(retrieval.proposed),
                "proposed_withheld": not self.depth.include_proposed,
                "loose": retrieval.loose,
                "carried": retrieval.carried,
                "terms": list(retrieval.terms),
                "miss_reason": retrieval.miss_reason,
            }

        # Add RAG context if available
        if rag_response and rag_response.context_used:
            sources_text = "\n".join([
                f"- {s.get('source', 'unknown')}: {s.get('type', 'unknown')}"
                for s in rag_response.sources[:5]
            ])
            context_note = {
                "role": "system",
                "content": f"Relevant context has been retrieved. Sources consulted:\n{sources_text}",
            }
            context.insert(1, context_note)  # After system prompt

        # Generate response, letting the model reach into the graph first.
        response, usage = await self._answer_with_tools(self._trim(context))
        # `or ""` because a model that used its last round on a tool call can
        # come back with no content at all. An empty answer is honest; `None`
        # reaches `DMResponse` and fails the turn on a validation error.
        message = response.choices[0].message.content or ""
        cost = estimate(self.model, usage)

        # Always generate suggestions
        suggestions = []
        if rag_response:
            suggestions = self._generate_suggestions(rag_response.query_type)

        # AFTER the answer, because generation is a second model call and its
        # cost belongs to the card rather than to the turn's reasoning. The
        # model has already been told a card is coming and told not to write
        # the content itself.
        cards = await self._run_requested_generations(retrieval)

        # Canon citations FIRST: they are the ones a DM can open the book to.
        return DMResponse(
            message=message,
            generations=cards,
            query_type=rag_response.query_type if rag_response else None,
            sources=canon_sources + (rag_response.sources if rag_response else []),
            suggestions=suggestions,
            usage={"input": usage.input_tokens, "output": usage.output_tokens,
                   "total": usage.total},
            cost=cost.as_dict(),
            retrieval=retrieval_report,
            subgraph=self._subgraph_view(),
        )

    async def _run_requested_generations(self, retrieval) -> list[dict]:
        """Draft each card the model asked for. Never raises into the turn.

        A generation that fails is reported as a card carrying its error, for
        the reason `Generated.error` exists at all: a malformed result is
        evidence about the prompt, and swallowing it leaves a DM wondering
        whether they asked for the wrong thing.
        """
        if not self._requested_generations:
            return []

        from backend.agents import generator

        cards = []
        for request in self._requested_generations:
            names = tuple(
                self.subgraph.nodes[entity_id].name
                for entity_id in request.context_entity_ids
                if entity_id in self.subgraph.nodes
            )
            context = generator.GenerationContext(entities=names, note=request.note)
            try:
                # ITS OWN RETRIEVAL, on its own subject. The generator is not
                # handed the chat's passages: it reads the graph for what it is
                # being asked to make, and the conversation is the ADDITIONAL
                # context on top -- which is the division the two panes exist
                # to express.
                own = self.canon.retrieve(request.subject) if self.canon else retrieval
                drafted = await generator.generate(
                    self.openai,
                    kind=request.kind,
                    subject=request.subject,
                    retrieval=own,
                    depth=self.depth,
                    model=self.model,
                    context=context,
                )
                # A QUEST OR A SCENE CONTAINS THINGS; an NPC or a monster IS
                # one. Only the first two are annotated, so the second call is
                # spent where there is something to declare.
                #
                # TWO CALLS RATHER THAN ONE, on measurement. Asking a single
                # response to invent and to classify at once put 51% of its
                # declared edges outside what the type table allows; annotating
                # finished prose brought that to 27%, and element agreement
                # over fixed prose to 0.78. See `measure_manifest`.
                if request.kind in CLUSTER_KINDS and not drafted.error:
                    elements, edges, dropped, annotate_error = await generator.annotate(
                        self.openai,
                        body=drafted.body,
                        retrieval=own,
                        depth=self.depth,
                        model=self.model,
                    )
                    if not annotate_error:
                        drafted = replace(
                            drafted, elements=elements, edges=edges,
                            manifest_dropped=dropped,
                        )
                    else:
                        # A failed annotation loses the manifest, never the
                        # prose: the DM still gets the scene they asked for.
                        logger.warning("cluster annotation failed: %s", annotate_error)
                card = drafted.as_dict()
            except Exception as exc:  # noqa: BLE001 - a bad card must not lose the answer
                logger.warning("homebrew generation failed", exc_info=True)
                card = {"kind": request.kind, "subject": request.subject,
                        "error": f"{type(exc).__name__}: {exc}"}
            # WHERE IT FITS, PROPOSED RATHER THAN LEFT TO A SEARCH. The model
            # may name an anchor; when it does not, the generation's own
            # retrieval already says which passages it is grounded in, and the
            # best of those is the obvious place. The card offered 546 sections
            # across thirteen unconnected heists with no suggestion at all.
            suggested, chapters = canon_context.suggest_anchor(own)
            card["anchor"] = request.insert_after or suggested
            #: The chapters this scene is actually about, so a picker can lead
            #: with them instead of listing the whole book flat.
            card["relevant_chapters"] = list(chapters)
            card["carried"] = list(names)
            cards.append(card)
        return cards

    @property
    def _sampling(self) -> dict:
        """Temperature, and a seed only when one was asked for.

        `seed=None` is NOT the same as omitting it for every provider, and this
        code runs against more than one endpoint, so the key is absent unless
        it carries a value.
        """
        options: dict = {"temperature": self.temperature}
        if self.seed is not None:
            options["seed"] = self.seed
        return options

    async def _answer_with_tools(self, messages: list[dict]):
        """Call the model, run any graph tools it asks for, call it again.

        THE TOOL TRANSCRIPT IS DISCARDED. Tool calls and their results are
        appended to THIS list -- a local copy, rebuilt from `self.conversation`
        every turn -- and never to the conversation itself. So forty edges
        fetched on turn three are not re-sent on turn four, or forty, which is
        the accumulation that makes a long campaign chat expensive and mostly
        irrelevant. What survives a turn is the SUBGRAPH: what was found, not
        the transcript of finding it.

        BOUNDED. `_TOOL_ROUNDS` caps the loop, because a model that keeps
        asking is a model that is not converging, and each round is another
        call and another chance to be inconsistent. On exhausting the rounds it
        answers from what it has rather than failing the turn -- a DM mid
        session gets a degraded answer, never a stack trace.

        Usage ACCUMULATES across the rounds. Reporting only the final call
        would tell somebody a turn cost a third of what it did.
        """
        total = Usage()
        for _ in range(_TOOL_ROUNDS):
            response = await self.openai.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=1000,
                tools=[
                    *graph_tools.SCHEMA,
                    homebrew_tool.SCHEMA,
                    # Only where there IS a campaign. Offering "read my
                    # material" to a canon-only session invites a tool call
                    # that can only ever come back empty.
                    *([homebrew_tool.READ_SCHEMA] if self.canon.campaign else []),
                ],
                **self._sampling,
            )
            total = total + Usage.from_response(response)
            choice = response.choices[0].message
            calls = getattr(choice, "tool_calls", None)
            if not calls:
                return response, total

            messages.append(
                {"role": "assistant", "content": choice.content or "",
                 "tool_calls": [
                     {"id": c.id, "type": "function",
                      "function": {"name": c.function.name,
                                   "arguments": c.function.arguments}}
                     for c in calls
                 ]}
            )
            for tool_call in calls:
                messages.append(self._run_tool(tool_call))

        # Rounds exhausted: ask once more with no tools, so the model answers
        # from what it gathered instead of asking again forever.
        response = await self.openai.chat.completions.create(
            model=self.model, messages=messages, max_tokens=1000, **self._sampling,
        )
        return response, total + Usage.from_response(response)

    def _run_tool(self, tool_call) -> dict:
        """One tool call, and its result as a message.

        A FAILURE IS REPORTED TO THE MODEL, not raised. A malformed argument or
        an unknown tool is something the model can correct on the next round;
        raising would fail the whole turn over a recoverable mistake. What it
        must never do is return an empty result, which would read as "the graph
        holds nothing".
        """
        import json

        name = tool_call.function.name
        try:
            arguments = json.loads(tool_call.function.arguments or "{}")
            if name == homebrew_tool.SCHEMA["function"]["name"]:
                # RECORDED, NOT RUN. Generation is a second model call and a
                # real cost; doing it inside the tool loop would spend money
                # mid-round and hand prose back to a model told not to quote
                # it. The request is validated here and generated after the
                # loop, so what the reader gets is a card.
                request, error = homebrew_tool.validate(
                    arguments,
                    held_ids=frozenset(self.subgraph.nodes),
                    seen_sections=frozenset(self._seen_sections),
                )
                if error:
                    payload = {"error": error}
                else:
                    self._requested_generations.append(request)
                    payload = request.acknowledgement
                return {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(payload, default=str),
                }
            if name == homebrew_tool.READ_SCHEMA["function"]["name"]:
                # RUN HERE AND ANSWERED HERE, unlike generation. This reads
                # back words the DM already wrote and approved, so there is no
                # invention to keep in an envelope and nothing to gate.
                with read_only_session() as session:
                    payload = homebrew_tool.read(
                        session, self.canon.campaign or "",
                        str(arguments.get("name") or ""),
                    )
                return {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(payload, default=str),
                }
            result = graph_tools.call(name, arguments)
            self._fold_tool_result(name, result)
            payload = result.as_dict
        except Exception as exc:  # noqa: BLE001 - handed back for a retry
            logger.warning("graph tool %s failed", name, exc_info=True)
            payload = {"error": f"{type(exc).__name__}: {exc}"}

        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(payload, default=str),
        }

    def _fold_tool_result(self, name: str, result) -> None:
        """Put what a tool found into the subgraph, marked as EXPANDED.

        Marked apart from `seeded` because it is weaker evidence: a seeded node
        is one a question resolved by name, an expanded one is somewhere a
        model chose to look. `touch_node` keeps the stronger of the two when
        both happen, so expanding into a node the question already named does
        not demote it.
        """
        for row in result.rows:
            if name == "resolve":
                self.subgraph.touch_node(
                    row["entity_id"], row["name"], row.get("labels", ()),
                    how=subgraph_module.EXPANDED,
                )
            elif name == "expand":
                source, target = row.get("entity"), row.get("other")
                if row.get("direction") == "in":
                    source, target = target, source
                self.subgraph.touch_edge(
                    source, row.get("relationship", "?"), target,
                    row.get("status", "proposed"), how=subgraph_module.EXPANDED,
                )
            elif name == "passages":
                self.subgraph.touch_passage(row["section_id"])

    def _trim(self, context: list[dict]) -> list[dict]:
        """The system messages, plus the current question. THE TRANSCRIPT IS
        NOT THE MEMORY.

        This used to keep `history_turns` exchanges, defaulting to six. That is
        both too little to reach session 3 from session 7 and the wrong thing
        to enlarge: a bigger number re-sends old dialogue on every turn in the
        hope the answer is somewhere in it. What carries instead is the
        SUBGRAPH -- what the conversation is about, as entities with ids -- and
        the campaign plane, which the graph already holds. A long campaign
        grows the graph rather than the context.

        THE COST, ACCEPTED DELIBERATELY: conversational repair. "No, the other
        one", "shorter", "explain that again" are about the dialogue rather
        than about entities, and nothing in the subgraph holds them. Reference
        resolution is unaffected -- "him" works because Rictavio is a node with
        an id, not because the previous message is still in view.

        System messages are never trimmed: they carry the canon block, the
        subgraph, and the instructions for reading both.
        """
        system = [m for m in context if m["role"] == "system"]
        rest = [m for m in context if m["role"] != "system"]
        keep = 1  # the current question
        return system + rest[-keep:] if keep < len(rest) else system + rest

    def _generate_suggestions(self, query_type: QueryType | None) -> list[str]:
        """Generate contextual suggestions.

        Args:
            query_type: The classified query type.

        Returns:
            List of suggested follow-up actions.
        """
        if not query_type:
            return []

        suggestions_map = {
            QueryType.RULES_LOOKUP: [
                "Roll for it?",
                "See related rules",
                "Common mistakes to avoid",
            ],
            QueryType.ENCOUNTER_GENERATION: [
                "Generate another encounter",
                "Adjust difficulty",
                "Add terrain features",
            ],
            QueryType.NPC_GENERATION: [
                "Generate another NPC",
                "Create a rival for this NPC",
                "Add a secret or hook",
            ],
            QueryType.CAMPAIGN_STATE: [
                "View related NPCs",
                "Check location details",
                "Review recent events",
            ],
            QueryType.CAMPAIGN_HISTORY: [
                "Full session recap",
                "Find related events",
                "Check NPC involvement",
            ],
        }

        return suggestions_map.get(query_type, [])

    def roll_dice(self, expression: str) -> DiceResult:
        """Roll dice using standard notation.

        Args:
            expression: Dice expression like "2d6+3".

        Returns:
            DiceResult with the roll outcome.
        """
        return self.tools.roll_dice(expression)

    def get_conversation_history(self) -> list[dict]:
        """Get conversation history.

        Returns:
            List of message dicts.
        """
        return self.conversation.export_history()

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.conversation.clear()
