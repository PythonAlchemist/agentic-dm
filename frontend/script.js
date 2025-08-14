// Frontend JavaScript for Agentic DM Chatbot

class DMChatbot {
    constructor() {
        this.conversationHistory = [];
        this.isLoading = false;
        this.init();
    }

    init() {
        this.bindEvents();
        this.updateStatus('Ready');
    }

    bindEvents() {
        // Chat input
        const chatInput = document.getElementById('chat-input');
        const sendButton = document.getElementById('send-button');

        // Auto-resize textarea
        chatInput.addEventListener('input', () => {
            this.autoResizeTextarea(chatInput);
        });

        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        sendButton.addEventListener('click', () => {
            this.sendMessage();
        });

        // Control buttons
        document.getElementById('clear-chat').addEventListener('click', () => {
            this.clearChat();
        });

        document.getElementById('show-history').addEventListener('click', () => {
            this.showHistory();
        });

        // Suggestion chips
        document.querySelectorAll('.suggestion-chip').forEach(chip => {
            chip.addEventListener('click', (e) => {
                const question = e.currentTarget.dataset.question;
                chatInput.value = question;
                this.autoResizeTextarea(chatInput);
                this.sendMessage();
            });
        });
    }

    autoResizeTextarea(textarea) {
        // Reset height to auto to get the correct scrollHeight
        textarea.style.height = 'auto';
        
        // Set the height to match the content
        const newHeight = Math.min(textarea.scrollHeight, 200); // Max height of 200px
        textarea.style.height = newHeight + 'px';
        
        // Update rows attribute for better UX
        const lineHeight = parseInt(window.getComputedStyle(textarea).lineHeight);
        const rows = Math.ceil(newHeight / lineHeight);
        textarea.rows = Math.max(1, Math.min(rows, 8)); // Between 1 and 8 rows
    }

    async sendMessage() {
        const input = document.getElementById('chat-input');
        const message = input.value.trim();
        
        if (!message || this.isLoading) return;

        // Clear input and reset height
        input.value = '';
        this.autoResizeTextarea(input);

        // Add user message to chat
        this.addMessage('user', message);

        // Show loading
        this.setLoading(true);

        try {
            // Send to backend API
            const response = await this.callAPI(message);
            
            // Add assistant response
            this.addMessage('assistant', response.answer, response.question_type);
            
            // Update conversation history
            this.conversationHistory.push({
                role: 'user',
                content: message,
                timestamp: new Date()
            });
            
            this.conversationHistory.push({
                role: 'assistant',
                content: response.answer,
                question_type: response.question_type,
                timestamp: new Date()
            });

        } catch (error) {
            console.error('Error sending message:', error);
            this.addMessage('assistant', 'Sorry, I encountered an error. Please try again.', 'error');
        } finally {
            this.setLoading(false);
        }
    }

    async callAPI(message) {
        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message: message })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            return data;
            
        } catch (error) {
            console.error('API call failed:', error);
            throw error;
        }
    }

    addMessage(role, content, questionType = null) {
        const chatMessages = document.getElementById('chat-messages');
        
        // Remove welcome message if it's the first real message
        if (this.conversationHistory.length === 0) {
            const welcomeMessage = chatMessages.querySelector('.welcome-message');
            if (welcomeMessage) {
                welcomeMessage.remove();
            }
        }
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;
        
        const messageHeader = document.createElement('div');
        messageHeader.className = 'message-header';
        
        if (role === 'user') {
            messageHeader.innerHTML = `
                <i class="fas fa-user"></i>
                <span>You</span>
            `;
        } else {
            messageHeader.innerHTML = `
                <i class="fas fa-robot"></i>
                <span>Assistant</span>
                ${questionType ? `<span class="question-type ${questionType}">${questionType}</span>` : ''}
            `;
        }
        
        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';
        messageContent.innerHTML = this.formatMessage(content);
        
        messageDiv.appendChild(messageHeader);
        messageDiv.appendChild(messageContent);
        
        chatMessages.appendChild(messageDiv);
        
        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    formatMessage(content) {
        // First, handle tables (markdown-style) - this needs to be done first
        let formatted = content;
        
        // Find table patterns: lines that start and end with |
        const tableRegex = /^(\|.*\|)$/gm;
        const tableMatches = formatted.match(tableRegex);
        
        if (tableMatches && tableMatches.length > 0) {
            // Process tables line by line
            const lines = formatted.split('\n');
            let inTable = false;
            let tableHTML = '';
            let processedLines = [];
            
            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
                
                if (line.trim().match(/^\|.*\|$/)) {
                    // Check if this is a separator row (all dashes and spaces)
                    const isSeparatorRow = line.trim().match(/^\|[\s\-:|]+\|$/);
                    
                    if (!inTable) {
                        // Start of table
                        inTable = true;
                        tableHTML = '<table class="message-table">';
                    }
                    
                    // Skip separator rows (the dashes)
                    if (!isSeparatorRow) {
                        // Process table row
                        const cells = line.split('|').slice(1, -1); // Remove empty first/last elements
                        const rowHTML = '<tr>' + cells.map(cell => 
                            `<td>${cell.trim()}</td>`
                        ).join('') + '</tr>';
                        
                        tableHTML += rowHTML;
                    }
                    
                } else if (inTable) {
                    // End of table
                    inTable = false;
                    tableHTML += '</table>';
                    processedLines.push(tableHTML);
                    processedLines.push(line);
                } else {
                    // Regular line
                    processedLines.push(line);
                }
            }
            
            // Handle case where table is at the end
            if (inTable) {
                tableHTML += '</table>';
                processedLines.push(tableHTML);
            }
            
            formatted = processedLines.join('\n');
        }
        
        // Handle bold text
        formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        
        // Handle italic text
        formatted = formatted.replace(/\*(.*?)\*/g, '<em>$1</em>');
        
        // Handle numbered lists
        formatted = formatted.replace(/^(\d+)\.\s+(.*)$/gm, '<li class="numbered-list">$2</li>');
        
        // Handle bullet points
        formatted = formatted.replace(/^[-*]\s+(.*)$/gm, '<li class="bullet-list">$1</li>');
        
        // Handle headers (lines that end with colons and are followed by content)
        formatted = formatted.replace(/^([^:\n]+):\s*$/gm, '<h4 class="response-header">$1:</h4>');
        
        // Handle double newlines as paragraph breaks
        formatted = formatted.replace(/\n\n+/g, '</p><p>');
        
        // Handle single newlines as line breaks (but not in lists or tables)
        formatted = formatted.replace(/\n(?!<)/g, '<br>');
        
        // Wrap in paragraphs if not already wrapped
        if (!formatted.startsWith('<')) {
            formatted = '<p>' + formatted + '</p>';
        }
        
        // Clean up empty paragraphs
        formatted = formatted.replace(/<p><\/p>/g, '');
        formatted = formatted.replace(/<p>\s*<\/p>/g, '');
        
        return formatted;
    }

    clearChat() {
        const chatMessages = document.getElementById('chat-messages');
        chatMessages.innerHTML = '';
        
        // Reset welcome message
        const welcomeMessage = document.createElement('div');
        welcomeMessage.className = 'welcome-message';
        welcomeMessage.innerHTML = `
            <div class="welcome-icon">
                <i class="fas fa-magic"></i>
            </div>
            <h3>Welcome, Dungeon Master!</h3>
            <p>I'm your AI assistant, ready to help you run your campaign. Ask me about:</p>
            <div class="suggestion-chips">
                <button class="suggestion-chip" data-question="List all monsters with their stats">
                    <i class="fas fa-dragon"></i> Monsters & Stats
                </button>
                <button class="suggestion-chip" data-question="Tell me the story of Shadowgrange">
                    <i class="fas fa-book-open"></i> Campaign Story
                </button>
                <button class="suggestion-chip" data-question="How to run the final battle">
                    <i class="fas fa-sword"></i> Battle Tips
                </button>
                <button class="suggestion-chip" data-question="What if the players befriend the villain?">
                    <i class="fas fa-lightbulb"></i> Creative Ideas
                </button>
            </div>
        `;
        
        chatMessages.appendChild(welcomeMessage);
        
        // Rebind suggestion chip events
        document.querySelectorAll('.suggestion-chip').forEach(chip => {
            chip.addEventListener('click', (e) => {
                const question = e.currentTarget.dataset.question;
                const chatInput = document.getElementById('chat-input');
                chatInput.value = question;
                this.autoResizeTextarea(chatInput);
                this.sendMessage();
            });
        });
        
        // Clear conversation history
        this.conversationHistory = [];
        
        this.updateStatus('Chat cleared');
    }

    showHistory() {
        if (this.conversationHistory.length === 0) {
            alert('No conversation history yet.');
            return;
        }
        
        let historyText = 'Conversation History:\n\n';
        this.conversationHistory.forEach((msg, index) => {
            const timestamp = msg.timestamp.toLocaleTimeString();
            const role = msg.role === 'user' ? 'You' : 'Assistant';
            const content = msg.content.substring(0, 100) + (msg.content.length > 100 ? '...' : '');
            historyText += `${index + 1}. ${role} (${timestamp}): ${content}\n\n`;
        });
        
        alert(historyText);
    }

    setLoading(loading) {
        this.isLoading = loading;
        const loadingOverlay = document.getElementById('loading-overlay');
        const sendButton = document.getElementById('send-button');
        
        if (loading) {
            loadingOverlay.classList.remove('hidden');
            sendButton.disabled = true;
            this.updateStatus('Generating response...');
        } else {
            loadingOverlay.classList.add('hidden');
            sendButton.disabled = false;
            this.updateStatus('Ready');
        }
    }

    updateStatus(status) {
        const statusText = document.getElementById('status-text');
        statusText.textContent = status;
    }
}

// Initialize the chatbot when the page loads
document.addEventListener('DOMContentLoaded', () => {
    new DMChatbot();
});