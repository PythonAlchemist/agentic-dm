# Agentic DM

An AI-powered Dungeon Master assistant that uses OpenAI's API to provide intelligent, context-aware help for running D&D campaigns.

## Features

- **OpenAI Integration**: Uses GPT-3.5-turbo and text-embedding-3-small for superior quality
- **Full Document Indexing**: Comprehensive coverage of campaign materials
- **Conversation Memory**: Maintains context across chat sessions
- **Smart Context Retrieval**: Finds relevant information from your campaign documents
- **Professional Formatting**: Tables, bullet points, and structured responses

## Quick Start

1. **Set up environment**:
   ```bash
   # Create .env file with your OpenAI API key
   echo "OPENAI_API_KEY=your-key-here" > .env
   ```

2. **Install dependencies**:
   ```bash
   uv sync
   ```

3. **Run the DM chat**:
   ```bash
   python scripts/dm_chat.py
   # or
   python main.py
   ```

## Usage

- **Ask questions** about NPCs, locations, encounters, rules, or story elements
- **View history** with `history` command
- **Clear conversation** with `clear` command
- **Exit** with `exit` command

## File Structure

```
agentic-dm/
├── backend/
│   └── openai_rag.py      # OpenAI RAG system
├── scripts/
│   └── dm_chat.py         # Main chat interface
├── data/                   # PDF campaign files
├── indices/                # Saved indexes
└── config.py              # Configuration
```

## Requirements

- OpenAI API key
- Python 3.8+
- PDF campaign documents in `data/` directory