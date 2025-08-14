from backend.openai_rag import OpenAIRAGSystem
from termcolor import cprint
import os
import sys

# Add parent directory to path for config import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def initialize_dm_chat(
    pdf_path: str = None, use_existing_index: bool = True
) -> OpenAIRAGSystem:
    """
    Initializes the Dungeon Master chatbot by setting up the OpenAI RAG system
    and indexing the campaign module.

    Args:
        pdf_path: Path to the PDF file. If None, uses default.
        use_existing_index: Whether to try loading an existing index first.
    """
    if pdf_path is None:
        pdf_path = "data/armyofthedamned.pdf"

    # Initialize OpenAI RAG system
    print("🔧 Initializing OpenAI RAG system...")
    rag = OpenAIRAGSystem()

    # Try to load existing index first
    index_name = os.path.splitext(os.path.basename(pdf_path))[0]
    index_path = f"indices/{index_name}"

    if use_existing_index and (
        os.path.exists(f"{index_path}_embeddings.npy")
        or os.path.exists(f"{index_path}_metadata.json")
    ):
        print(f"📚 Loading existing OpenAI index from {index_path}...")
        try:
            rag.load_index(index_path)
            print(f"✅ Index loaded successfully with {len(rag.chunks)} chunks")
            return rag
        except Exception as e:
            print(f"❌ Failed to load existing index: {e}")
            print("🔄 Creating new index...")

    # Create indices directory if it doesn't exist
    os.makedirs("indices", exist_ok=True)

    # Index the campaign module (start with 50% for faster setup)
    print(f"📖 Indexing PDF: {pdf_path}")
    print(
        "💡 Indexing 100% of content for comprehensive coverage. This may take a few minutes."
    )
    rag.parse_and_index_pdf(
        pdf_path, percentage=100, save_index=True, index_name=index_name
    )

    return rag


def dm_chat_loop(rag: OpenAIRAGSystem):
    """
    Starts an interactive chat loop for the Dungeon Master chatbot.

    Args:
        rag (OpenAIRAGSystem): The initialized OpenAI RAG system.
    """
    # Initialize conversation history
    conversation_history = []

    # Print system info
    stats = rag.get_statistics()
    print("\n" + "=" * 60)
    print("🎲 DUNGEON MASTER ASSISTANT (OpenAI) 🎲")
    print("=" * 60)
    print(f"📚 Indexed {stats['total_chunks']} chunks from the campaign")
    print(
        f"📊 Content types: {', '.join([f'{k}: {v}' for k, v in stats['content_types'].items()])}"
    )
    print(f"🔧 Using OpenAI GPT-3.5-turbo for responses")
    print("💬 Conversation history enabled - I'll remember our discussion!")
    print("=" * 60)
    print("\nAsk questions about the campaign (type 'exit' to quit):")
    print("💡 Try asking about: NPCs, locations, encounters, rules, or specific events")
    print(
        "💡 Example: 'Who is the main villain?' or 'What monsters appear in the adventure?'"
    )
    print("💡 I'll remember our conversation and build on previous answers!")
    print(
        "💡 Commands: 'history' to see conversation, 'clear' to reset, 'exit' to quit"
    )
    print()

    while True:
        try:
            query = input("\n🔍 Your question: ").strip()
            if query.lower() in ["exit", "quit", "q"]:
                print("👋 Goodbye! May your dice roll true!")
                break

            if query.lower() in ["history", "h", "memory"]:
                if conversation_history:
                    print("\n📚 Conversation History:")
                    print("-" * 40)
                    for i, msg in enumerate(conversation_history, 1):
                        role = "You" if msg["role"] == "user" else "Assistant"
                        content_preview = (
                            msg["content"][:80] + "..."
                            if len(msg["content"]) > 80
                            else msg["content"]
                        )
                        print(f"{i}. {role}: {content_preview}")
                else:
                    print("💭 No conversation history yet.")
                continue

            if query.lower() in ["clear", "reset", "new"]:
                conversation_history.clear()
                print("🧹 Conversation history cleared.")
                continue

            if not query:
                continue

            print("\n🔍 Searching for relevant information...")

            # Get relevant context from the RAG system
            context = rag.get_context_for_query(
                query, top_k=3, include_surrounding=True, max_context_length=4000
            )

            if context == "No relevant information found for your query.":
                print("❌ No relevant information found. Try rephrasing your question.")
                continue

            # Show the context being used
            print("\n📖 Relevant context found:")
            cprint(context, "cyan")

            # Use OpenAI to generate a response with conversation history
            print("\n🤖 Generating response with OpenAI...")
            try:
                # Get response from OpenAI
                answer = rag.ask_question(query, context)

                # Add to conversation history
                conversation_history.append({"role": "user", "content": query})
                conversation_history.append({"role": "assistant", "content": answer})

                print(f"\n💬 Assistant:")
                print("-" * 40)
                print(answer)
                print("-" * 40)

                # Show conversation memory
                if len(conversation_history) > 2:
                    print(
                        f"\n💭 Remembering {len(conversation_history)//2} previous exchanges"
                    )

            except Exception as e:
                print(f"❌ OpenAI response failed: {e}")
                print("💡 This might be due to API quota issues or network problems.")
                continue

            # Show search statistics
            results = rag.search(query, top_k=3)
            print(f"\n📊 Search results (top {len(results)}):")
            for i, (chunk, score) in enumerate(results, 1):
                content_preview = (
                    chunk.text[:100] + "..." if len(chunk.text) > 100 else chunk.text
                )
                print(f"  {i}. [{chunk.content_type.upper()}] (Score: {score:.3f})")
                print(f"     {content_preview}")

        except KeyboardInterrupt:
            print("\n\n👋 Chat interrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            print("Please try again or rephrase your question.")


def main():
    """Main function to run the DM chat system."""
    try:
        # Initialize the Dungeon Master chatbot
        rag_system = initialize_dm_chat()

        # Start the chat loop
        dm_chat_loop(rag_system)

    except Exception as e:
        print(f"❌ Failed to initialize DM chat system: {e}")
        print("Please check that:")
        print("  - The PDF file exists in the data/ directory")
        print("  - Your OpenAI API key is set in the .env file")
        print("  - You have sufficient OpenAI API quota")
        print("  - All dependencies are installed")
        print("\n💡 If you're having API issues, you can:")
        print("  - Check your quota at: https://platform.openai.com/account/usage")
        print("  - Add payment method at: https://platform.openai.com/account/billing")


if __name__ == "__main__":
    main()
