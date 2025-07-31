from backend.rag_faiss import RAGSystem
from backend.ollama_chat import OllamaChatClient
from termcolor import cprint


def initialize_dm_chat() -> RAGSystem:
    """
    Initializes the Dungeon Master chatbot by setting up the RAG system
    and indexing the entire campaign module.
    """
    # Initialize RAG system
    rag = RAGSystem()

    # Path to the campaign module PDF
    pdf_path = "data/armyofthedamned.pdf"  # Update with the correct path

    # Index the entire campaign module
    rag.parse_and_index_pdf(pdf_path, percentage=100)

    return rag


def dm_chat_loop(rag: RAGSystem):
    """
    Starts an interactive chat loop for the Dungeon Master chatbot.

    Args:
        rag (RAGSystem): The initialized RAG system.
    """
    # load ollama model
    client = OllamaChatClient(model="llama3:8b")
    print(
        "Welcome to the Dungeon Master Chatbot! Ask your questions (type 'exit' to quit):"
    )

    while True:
        query = input("Your question: ")
        if query.lower() == "exit":
            print("Goodbye!")
            break

        # # Retrieve context from the RAG system
        # results = rag.search(query)

        # # take a few chunks of context around each result
        # if not results:
        #     print("No relevant context found. Please try a different question.")
        #     continue

        # # add extra context index, 2 before and 2 after each result
        # updated_indices = (
        #     [max(0, idx - 2) for idx in results]
        #     + [max(0, idx - 1) for idx in results]
        #     + results
        #     + [min(len(rag.chunks) - 1, idx + 1) for idx in results]
        #     + [min(len(rag.chunks) - 1, idx + 2) for idx in results]
        # )
        # updated_indices = sorted(list(set(updated_indices)))
        # context = "\n".join([rag.chunks[idx] for idx in updated_indices])

        # cprint(context, "cyan")

        context = rag.full_text

        # Use Ollama to generate a response
        answer = client.ask(query + "\nContext: " + context)
        print(f"Answer: {answer}")


if __name__ == "__main__":
    # Initialize the Dungeon Master chatbot
    rag_system = initialize_dm_chat()

    # Start the chat loop
    dm_chat_loop(rag_system)
