import faiss
from sentence_transformers import SentenceTransformer
import pymupdf4llm
import pandas as pd


class RAGSystem:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", dimension: int = 384):
        """
        Initializes the RAG system with FAISS and a SentenceTransformer model.

        Args:
            model_name (str): Name of the SentenceTransformer model.
            dimension (int): Dimension of the embeddings.
        """
        self.model = SentenceTransformer(model_name)
        self.index = faiss.IndexFlatL2(dimension)
        self.chunks = list()
        self.full_text = ""

    def add_to_index(self, texts: list[str]) -> None:
        """
        Adds text data to the FAISS index after embedding.

        Args:
            texts (list of str): List of text data to index.
        """
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        self.index.add(embeddings)
        self.chunks.extend(texts)

    def search(self, query: str, top_k: int = 5) -> list[int]:
        """
        Searches the FAISS index for the most relevant texts.

        Args:
            query (str): Query string.
            top_k (int): Number of top results to return.

        Returns:
            list: A list of indices from the index.
        """
        query_embedding = self.model.encode([query], convert_to_numpy=True)
        distances, indices = self.index.search(query_embedding, top_k)
        results = []
        for idx in indices[0]:
            if idx != -1:
                results.append(idx)
        return results

    def save_index(self, file_path="faiss_index.bin"):
        """
        Saves the FAISS index to a file.

        Args:
            file_path (str): Path to save the FAISS index.
                Defaults to 'faiss_index.bin'.
        """
        faiss.write_index(self.index, file_path)

    def load_index(self, file_path="faiss_index.bin"):
        """
        Loads the FAISS index from a file.

        Args:
            file_path (str): Path to the FAISS index file.
                Defaults to 'faiss_index.bin'.
        """
        self.index = faiss.read_index(file_path)

    def parse_and_index_pdf(self, pdf_path: str, percentage: int = 10) -> None:
        """
        Parses the first percentage of a PDF and indexes the content.

        Args:
            rag_system (RAGSystem): The RAG system instance.
            pdf_path (str): Path to the PDF file.
            percentage (int): Percentage of the document to parse and index.
        """
        markdown_content = pymupdf4llm.to_markdown(pdf_path)
        self.full_text = markdown_content
        chunks = markdown_content.split("\n\n")  # Split by paragraphs
        num_chunks = len(chunks)
        limit = max(1, (num_chunks * percentage) // 100)
        self.add_to_index(chunks[:limit])


if __name__ == "__main__":
    # Initialize RAG system
    rag = RAGSystem()

    # Parse and index the first 10% of the PDF
    pdf_path = "data/armyofthedamned.pdf"  # Update with the correct path
    rag.parse_and_index_pdf(pdf_path, percentage=10)

    # Interactive loop to ask questions
    print("Ask questions about the document (type 'exit' to quit):")
    while True:
        query = input("Your question: ")
        if query.lower() == "exit":
            break
        results = rag.search(query)
        texts = [rag.chunks[idx] for idx in results]
        df = pd.DataFrame(zip(*[texts, results]), columns=["text", "index"])
        print(df)
