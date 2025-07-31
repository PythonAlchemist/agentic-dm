import ollama


class OllamaChatClient:
    def __init__(self, model: str = "llama3") -> None:
        self.model = model
        self.history = [
            {
                "role": "system",
                "content": """You are an assistant that answers questions based on the provided context. This content comes from a RAG system from a dungeons and dragons module which you are assisting the DM in running. \
                    I will provide relevant context from the document to help you answer questions. \
                    Keep answers concise and relevant. You may use your prior knowledge about dungeons and dragons, but do not make up information.""",
            }
        ]

    def ask(self, user_input: str) -> str:
        self.history.append({"role": "user", "content": user_input})

        try:
            response = ollama.chat(model=self.model, messages=self.history)
            message = response["message"]["content"]
            self.history.append({"role": "assistant", "content": message})
            return message
        except Exception as e:
            raise RuntimeError(f"Chat failed: {e}")

    def reset(self):
        self.history = []


# Example usage
if __name__ == "__main__":
    client = OllamaChatClient(model="gemma3:4b")

    print("Start chatting with the model. Type 'exit' to quit.")
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ("exit", "quit"):
            break
        response = client.ask(user_input)
        print(f"Ollama: {response}")
