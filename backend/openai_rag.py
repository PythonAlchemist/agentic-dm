"""
OpenAI-based RAG system for better performance and quality.
Uses OpenAI embeddings and API for superior results.
"""

import openai
import json
import os
from typing import List, Dict, Tuple, Optional
import numpy as np
from pathlib import Path
import time


# Load environment variables from .env file if it exists
def load_env():
    """Load environment variables from .env file."""
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        print(f"📁 Loading environment from {env_path}")
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()


# Load environment variables
load_env()


class OpenAIChunkMetadata:
    """Metadata for each text chunk."""

    def __init__(
        self,
        chunk_id: int,
        text: str,
        page_number: Optional[int] = None,
        content_type: str = "general",
        section: str = "",
        chunk_index: int = 0,
        total_chunks: int = 0,
    ):
        self.chunk_id = chunk_id
        self.text = text
        self.page_number = page_number
        self.content_type = content_type
        self.section = section
        self.chunk_index = chunk_index
        self.total_chunks = total_chunks

    def to_dict(self):
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "page_number": self.page_number,
            "content_type": self.content_type,
            "section": self.section,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
        }


class OpenAIRAGSystem:
    def __init__(self, api_key: str = None, model: str = "gpt-3.5-turbo"):
        """
        Initialize OpenAI-based RAG system.

        Args:
            api_key: OpenAI API key. If None, tries to get from environment.
            model: OpenAI model to use for chat completions.
        """
        # Get API key
        if api_key is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError(
                    "OpenAI API key not found. Set OPENAI_API_KEY environment variable."
                )

        self.client = openai.OpenAI(api_key=api_key)
        self.model = model
        self.chunks: List[OpenAIChunkMetadata] = []
        self.embeddings: List[List[float]] = []
        self.chunk_id_counter = 0
        self.full_text = ""

        print(f"🔧 Initializing OpenAI RAG system with {model}")

    def _detect_content_type(self, text: str) -> str:
        """Detect the type of content in a chunk."""
        text_lower = text.lower()

        # D&D specific content detection
        combat_words = [
            "initiative",
            "attack",
            "damage",
            "hp",
            "ac",
            "dc",
            "saving throw",
        ]
        npc_words = ["npc", "character", "speaks", "says", "responds", "personality"]
        location_words = ["location", "area", "room", "chamber", "passage", "dungeon"]
        quest_words = ["quest", "mission", "objective", "goal", "adventure"]
        rules_words = ["rule", "mechanic", "ability", "spell", "feature"]
        treasure_words = ["treasure", "loot", "item", "magic", "weapon", "armor"]
        encounter_words = ["encounter", "battle", "fight", "conflict", "challenge"]

        if any(word in text_lower for word in combat_words):
            return "combat"
        elif any(word in text_lower for word in npc_words):
            return "npc"
        elif any(word in text_lower for word in location_words):
            return "location"
        elif any(word in text_lower for word in quest_words):
            return "quest"
        elif any(word in text_lower for word in rules_words):
            return "rules"
        elif any(word in text_lower for word in treasure_words):
            return "treasure"
        elif any(word in text_lower for word in encounter_words):
            return "encounter"
        else:
            return "general"

    def _create_dnd_chunks(self, markdown_content: str) -> List[OpenAIChunkMetadata]:
        """Create D&D-specific chunks that respect narrative structure."""
        chunks = []
        current_section = ""

        # Split by major sections first
        sections = markdown_content.split("\n\n")

        for section_idx, section in enumerate(sections):
            if not section.strip():
                continue

            # Update section if we find a header
            if section.strip().startswith("#"):
                current_section = section.strip()
                chunks.append(
                    OpenAIChunkMetadata(
                        chunk_id=self.chunk_id_counter,
                        text=section.strip(),
                        content_type="header",
                        section=current_section,
                        chunk_index=len(chunks),
                        total_chunks=0,
                    )
                )
                self.chunk_id_counter += 1
                continue

            # For D&D content, group related information
            section_text = section.strip()

            if len(section_text) > 1500:  # Long section, needs chunking
                sub_sections = self._split_dnd_section(section_text)
                for sub_section in sub_sections:
                    if sub_section.strip():
                        content_type = self._detect_content_type(sub_section)
                        chunks.append(
                            OpenAIChunkMetadata(
                                chunk_id=self.chunk_id_counter,
                                text=sub_section.strip(),
                                content_type=content_type,
                                section=current_section,
                                chunk_index=len(chunks),
                                total_chunks=0,
                            )
                        )
                        self.chunk_id_counter += 1
            else:
                # Short section, keep as one chunk
                content_type = self._detect_content_type(section_text)
                chunks.append(
                    OpenAIChunkMetadata(
                        chunk_id=self.chunk_id_counter,
                        text=section_text,
                        content_type=content_type,
                        section=current_section,
                        chunk_index=len(chunks),
                        total_chunks=0,
                    )
                )
                self.chunk_id_counter += 1

        # Update total_chunks for all chunks
        for chunk in chunks:
            chunk.total_chunks = len(chunks)

        return chunks

    def _split_dnd_section(self, text: str) -> List[str]:
        """Split a D&D section into logical chunks."""
        chunks = []

        # Look for D&D-specific patterns to split on
        split_patterns = [
            r"\n(?=\*\*[^*]+\*\*:)",  # Bold NPC names followed by colon
            r"\n(?=\*\*[^*]+\*\*\.)",  # Bold NPC names followed by period
            r"\n(?=The [^.]+\.[^.]*:)",  # "The [description]:" pattern
            r"\n(?=If [^.]+\.[^.]*:)",  # "If [condition]:" pattern
            r"\n(?=When [^.]+\.[^.]*:)",  # "When [condition]:" pattern
            r"\n(?=\*\*Wave [0-9]+\*\*)",  # Combat wave markers
            r"\n(?=\*\*Round [0-9]+\*\*)",  # Combat round markers
        ]

        # Try to split on these patterns
        split_points = []
        for pattern in split_patterns:
            import re

            matches = re.finditer(pattern, text)
            for match in matches:
                split_points.append(match.start())

        # Sort split points
        split_points.sort()

        # Create chunks based on split points
        if split_points:
            start = 0
            for split_point in split_points:
                chunk = text[start:split_point].strip()
                if chunk and len(chunk) > 50:
                    chunks.append(chunk)
                start = split_point

            # Add the final chunk
            final_chunk = text[start:].strip()
            if final_chunk and len(final_chunk) > 50:
                chunks.append(final_chunk)
        else:
            # No natural splits found, use simple chunking
            chunk_size = 800
            overlap = 100
            for i in range(0, len(text), chunk_size - overlap):
                chunk = text[i : i + chunk_size].strip()
                if chunk and len(chunk) > 50:
                    chunks.append(chunk)

        return chunks

    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings from OpenAI API."""
        try:
            response = self.client.embeddings.create(
                model="text-embedding-3-small", input=texts
            )
            return [embedding.embedding for embedding in response.data]
        except Exception as e:
            print(f"❌ Error getting embeddings: {e}")
            return []

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

    def add_to_index(self, chunks: List[OpenAIChunkMetadata]) -> None:
        """Add chunks to the index with embeddings."""
        if not chunks:
            return

        print(f"📊 Getting embeddings for {len(chunks)} chunks...")
        texts = [chunk.text for chunk in chunks]

        # Get embeddings in batches to avoid rate limits
        batch_size = 100
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_embeddings = self._get_embeddings(batch)
            all_embeddings.extend(batch_embeddings)

            if i + batch_size < len(texts):
                time.sleep(0.1)  # Small delay to avoid rate limits

        if all_embeddings:
            self.embeddings.extend(all_embeddings)
            self.chunks.extend(chunks)
            print(f"✅ Added {len(chunks)} chunks to index")
        else:
            print("❌ Failed to get embeddings")

    def search(
        self, query: str, top_k: int = 5, content_type_filter: Optional[str] = None
    ) -> List[Tuple[OpenAIChunkMetadata, float]]:
        """Search for relevant chunks using cosine similarity."""
        if not self.embeddings:
            return []

        # Get query embedding
        query_embedding = self._get_embeddings([query])
        if not query_embedding:
            return []

        query_vec = query_embedding[0]

        # Calculate similarities
        similarities = []
        for i, chunk_embedding in enumerate(self.embeddings):
            similarity = self._cosine_similarity(query_vec, chunk_embedding)
            chunk = self.chunks[i]

            # Apply content type filter if specified
            if content_type_filter and chunk.content_type != content_type_filter:
                continue

            similarities.append((chunk, similarity))

        # Sort by similarity and return top_k
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]

    def get_context_for_query(
        self,
        query: str,
        top_k: int = 5,
        include_surrounding: bool = True,
        max_context_length: int = 4000,
    ) -> str:
        """Get relevant context for a query."""
        results = self.search(query, top_k=top_k)

        if not results:
            return "No relevant information found for your query."

        context_parts = []
        used_chunks = set()

        for chunk, score in results:
            if chunk.chunk_id in used_chunks:
                continue

            # Add the main chunk
            context_parts.append(f"[{chunk.content_type.upper()}] {chunk.text}")
            used_chunks.add(chunk.chunk_id)

            # Optionally add surrounding chunks for context
            if include_surrounding:
                surrounding_indices = [chunk.chunk_index - 1, chunk.chunk_index + 1]

                for idx in surrounding_indices:
                    if (
                        0 <= idx < len(self.chunks)
                        and self.chunks[idx].chunk_id not in used_chunks
                    ):

                        surrounding_chunk = self.chunks[idx]
                        context_parts.append(
                            f"[{surrounding_chunk.content_type.upper()}] {surrounding_chunk.text}"
                        )
                        used_chunks.add(surrounding_chunk.chunk_id)

        context = "\n\n".join(context_parts)

        # Truncate if too long
        if len(context) > max_context_length:
            context = (
                context[:max_context_length] + "...\n\n[Context truncated for length]"
            )

        return context

    def ask_question(self, question: str, context: str) -> str:
        """
        Ask a question using OpenAI's chat completions API.

        Args:
            question: The question to ask
            context: The context from the RAG system

        Returns:
            The AI-generated response
        """
        try:
            # Enhanced system prompt for better DM assistance
            system_prompt = """You are a concise, factual Dungeon Master assistant. Your responses must be:

**CONCISE**: No fluff, no "according to context" phrases, no unnecessary explanations
**FACTUALLY DENSE**: Pack maximum useful information into minimal words
**WELL-FORMATTED**: Use tables for lists, bullet points for details, clear structure
**ACTIONABLE**: Provide practical information DMs can use immediately
**DIRECT**: Answer the question directly without preamble

When creating lists or comparing items, use tables. When describing locations or NPCs, use structured formats. Be brief but comprehensive. Every word should add value."""

            # User prompt with context
            user_prompt = f"""Question: {question}

Context from campaign module:
{context}

Provide a direct, factual answer with good formatting."""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=500,
                temperature=0.3,
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            return f"Error getting response: {e}"

    def parse_and_index_pdf(
        self,
        pdf_path: str,
        percentage: int = 100,
        save_index: bool = True,
        index_name: str = None,
    ) -> None:
        """Parse PDF and create index with OpenAI embeddings."""
        import pymupdf4llm

        print(f"📖 Parsing PDF: {pdf_path}")
        markdown_content = pymupdf4llm.to_markdown(pdf_path)
        self.full_text = markdown_content

        print("Creating D&D-specific chunks...")
        chunks = self._create_dnd_chunks(markdown_content)

        # Apply percentage limit if specified
        if percentage < 100:
            num_chunks = len(chunks)
            limit = max(1, (num_chunks * percentage) // 100)
            chunks = chunks[:limit]
            print(f"Processing {limit}/{num_chunks} chunks ({percentage}%)")

        print(f"Indexing {len(chunks)} chunks with OpenAI embeddings...")
        self.add_to_index(chunks)

        print(f"Index created with {len(self.chunks)} chunks")

        # Save index if requested
        if save_index:
            index_name = index_name or Path(pdf_path).stem
            self.save_index(f"indices/{index_name}")
            print(f"Index saved to indices/{index_name}")

    def save_index(self, file_path: str):
        """Save the index and metadata."""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Save metadata
        metadata = [chunk.to_dict() for chunk in self.chunks]
        with open(f"{file_path}_metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        # Save embeddings as numpy array (only if we have embeddings)
        if self.embeddings:
            embeddings_array = np.array(self.embeddings)
            np.save(f"{file_path}_embeddings.npy", embeddings_array)
            print(
                f"💾 Index saved: {len(self.chunks)} chunks, {embeddings_array.shape[1]} dimensions"
            )
        else:
            print(
                f"⚠️  Index saved with {len(self.chunks)} chunks but no embeddings (API quota issue)"
            )
            print("💡 You can retry indexing once your OpenAI quota is restored")

    def load_index(self, file_path: str):
        """Load the index and metadata."""
        # Load metadata
        metadata_path = f"{file_path}_metadata.json"
        if os.path.exists(metadata_path):
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
                self.chunks = [
                    OpenAIChunkMetadata(**chunk_data) for chunk_data in metadata
                ]
                if self.chunks:
                    self.chunk_id_counter = (
                        max(chunk.chunk_id for chunk in self.chunks) + 1
                    )

        # Load embeddings
        embeddings_path = f"{file_path}_embeddings.npy"
        if os.path.exists(embeddings_path):
            embeddings_array = np.load(embeddings_path)
            self.embeddings = embeddings_array.tolist()
            print(
                f"✅ Index loaded: {len(self.chunks)} chunks, {embeddings_array.shape[1]} dimensions"
            )

    def get_statistics(self) -> Dict:
        """Get statistics about the indexed content."""
        if not self.chunks:
            return {"total_chunks": 0, "content_types": {}, "total_text_length": 0}

        content_types = {}
        total_length = 0

        for chunk in self.chunks:
            content_types[chunk.content_type] = (
                content_types.get(chunk.content_type, 0) + 1
            )
            total_length += len(chunk.text)

        return {
            "total_chunks": len(self.chunks),
            "content_types": content_types,
            "total_text_length": total_length,
            "average_chunk_length": (
                total_length / len(self.chunks) if self.chunks else 0
            ),
            "embedding_dimensions": len(self.embeddings[0]) if self.embeddings else 0,
        }
