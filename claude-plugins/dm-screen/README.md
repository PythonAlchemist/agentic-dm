# DM Screen Plugin

Generate printable DM screen reference PDFs from D&D adventures.

## Commands

### `/dm-screen`

Reads an adventure from D&D Beyond (or provided content), extracts all key reference material, and generates a dense, landscape PDF optimized for printing and inserting into a DM screen.

**What it produces:**
- NPC table with locations, attitudes, and key info
- Room-by-room key with enemies, hazards, and treasure
- Quick monster stat reference table
- Full stat blocks for bosses and unique creatures
- Special mechanics, passwords, secrets
- Finale encounter reference with win conditions
- Conclusion and reward outcomes

**Usage:**
```
/dm-screen The Murkmire Malevolence from Keys from the Golden Vault
/dm-screen Curse of Strahd chapter Death House
/dm-screen [paste adventure content here]
```

**Output:**
- `dm-screen-<adventure>.html` — editable source file
- `dm-screen-<adventure>.pdf` — print-ready landscape PDF

**Requirements:**
- Google Chrome (for headless PDF conversion)
- D&D Beyond MCP server (for reading owned sourcebooks)

## Installation

From your project directory:
```
claude plugins install ./claude-plugins/dm-screen
```

Or copy the plugin to `~/.claude/plugins/cache/local/dm-screen/` manually.
