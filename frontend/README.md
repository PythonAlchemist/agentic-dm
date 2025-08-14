# Agentic DM Frontend

A modern, responsive web interface for the AI-powered Dungeon Master assistant.

## Features

- 🎨 **Modern UI**: Dark theme with glassmorphism effects
- 📱 **Responsive Design**: Works on desktop, tablet, and mobile
- 💬 **Real-time Chat**: Interactive conversation with the AI
- 🧠 **Smart Responses**: Different response styles based on question type
- 📊 **Visual Feedback**: Question type detection and response formatting
- 🔄 **Conversation Memory**: Maintains chat history

## Quick Start

### Option 1: FastAPI (Python) - Recommended

1. **Install dependencies**:
   ```bash
   cd frontend
   pip install fastapi uvicorn[standard]
   ```

2. **Start the server**:
   ```bash
   python server.py
   ```

3. **Open in browser**: http://localhost:8000

### Option 2: Node.js

1. **Install dependencies**:
   ```bash
   cd frontend
   npm install
   ```

2. **Start the server**:
   ```bash
   npm start
   # or for development with auto-reload:
   npm run dev
   ```

3. **Open in browser**: http://localhost:3000

### Option 3: Simple HTTP Server

For quick testing without installing dependencies:

```bash
cd frontend
npx http-server . -p 3000 -o
```

## API Endpoints

- `GET /` - Frontend page
- `POST /api/chat` - Chat endpoint
- `GET /api/status` - System status

## Question Types & Response Styles

| Type | Style | Example Questions |
|------|-------|-------------------|
| **📊 Factual** | Tables, lists, dense info | "List monsters", "What stats" |
| **📖 Narrative** | Story-like, descriptive | "Tell me the story", "Describe" |
| **⚙️ Procedural** | Step-by-step guidance | "How to run", "Steps for" |
| **🎨 Creative** | Imaginative suggestions | "What if", "Creative ideas" |

## Development

### File Structure
```
frontend/
├── index.html          # Main HTML file
├── styles.css          # CSS styling
├── script.js           # Frontend JavaScript
├── server.py           # FastAPI server
├── server.js           # Node.js server
└── package.json        # Node.js dependencies
```

### Customization

- **Colors**: Modify CSS variables in `styles.css`
- **Response Styles**: Update system prompts in the backend
- **Question Types**: Adjust detection logic in the servers

## Next Steps

1. **Connect to Backend**: Replace mock responses with actual OpenAI RAG system
2. **Add Authentication**: User management and session handling
3. **Real-time Updates**: WebSocket support for live responses
4. **File Upload**: PDF upload and indexing interface
5. **Advanced Features**: Campaign management, character sheets, etc.

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile browsers (iOS Safari, Chrome Mobile)

## License

MIT License - see main project README for details.
