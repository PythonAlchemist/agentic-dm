---
allowed-tools: Bash, Write, Read, Edit, Agent, mcp__dndbeyond__ddb_read_book, mcp__dndbeyond__ddb_navigate, mcp__dndbeyond__ddb_interact, mcp__dndbeyond__ddb_list_library
description: Generate a printable DM screen PDF from a D&D adventure
---

## Your Task

Create a dense, printable DM screen reference PDF for a D&D adventure. The user will specify an adventure (by name, book, or chapter). Your job is to:

1. **Read the full adventure** from D&D Beyond (or from provided content)
2. **Extract and organize** the key reference material
3. **Generate a tightly packed HTML file** styled for print
4. **Convert to PDF** using headless Chrome

## Step 1: Read the Adventure

Use the `mcp__dndbeyond__ddb_read_book` tool to get the table of contents, then the specific chapter. If content is truncated, use the Agent tool to spawn subagents that read different sections in parallel (e.g., one for early rooms, one for later rooms + conclusion + stat blocks). Each subagent should use `mcp__dndbeyond__ddb_navigate` and `mcp__dndbeyond__ddb_interact` (action: "screenshot") to capture truncated content.

## Step 2: Extract Reference Material

Pull out ALL of the following (where applicable):

- **NPC Table**: Name, location, creature type, attitude, key info (what they know, what they want, what they trade)
- **Room/Location Key Table**: Room ID, floor/area, enemies (with bold creature names), hazards/traps, treasure (bold magic items)
- **Monster Quick Stats Table**: Every unique creature type in the adventure — AC, HP, best attack, key ability/note
- **Stat Blocks**: Full stat blocks for unique/boss creatures (name, type, CR, AC, HP, speed, ability scores, saves, skills, immunities, senses, languages, all actions/bonus actions/reactions)
- **Encounter Tables**: Random encounter tables, complication tables, etc.
- **Special Mechanics**: Any adventure-specific rules (e.g., eldritch surges, lair actions, chase rules, environmental hazards)
- **Passwords & Secrets**: Hidden doors, passwords, DCs, trap solutions
- **Key Items**: Magic items, quest items, books, keys — what they do and where they are
- **Finale/Boss Encounter**: Setup, win conditions, timer mechanics, consequences
- **Conclusion & Rewards**: All outcome branches and their rewards
- **Read-Aloud Text**: Do NOT include — this is a reference sheet, not a script

## Step 3: Generate HTML

Create a single HTML file optimized for landscape Letter printing. Follow these layout rules strictly:

### Layout Architecture
- Use `@page { size: letter landscape; margin: 0.3in; }`
- Use **CSS Grid** with 3 columns: `grid-template-columns: 1fr 1fr 1fr; gap: 6pt;`
- Do NOT use CSS `columns` property (it creates gaps from break-inside: avoid)
- Manually distribute content across `<div class="col">` elements for optimal packing
- Balance columns by eye — the goal is ZERO wasted whitespace

### Typography & Sizing
- Body: 6.5pt, line-height 1.2
- Section headers (h2): 7.5pt, small-caps, `color: #58180D`, 1px bottom border
- Subsection headers (h3): 6.5pt
- Table body: 6pt
- Table headers: 5.5pt uppercase
- Stat block text: 6pt
- Footnotes/annotations: 5pt in #666

### Table Styling
```css
table { width: 100%; border-collapse: collapse; font-size: 6pt; page-break-inside: avoid; break-inside: avoid; }
th { background: #58180D; color: #fff; padding: 1.5pt 2pt; text-align: left; font-size: 5.5pt; text-transform: uppercase; }
td { padding: 1pt 2pt; border-bottom: 0.5px solid #ddd; vertical-align: top; }
tr:nth-child(even) { background: #f9f3f0; }
```

### Stat Block Styling
```css
.stat-block { background: #fdf1dc; border: 1px solid #deb887; padding: 3pt 4pt; margin: 1pt 0; break-inside: avoid; page-break-inside: avoid; }
```
- Stat block headers: 7pt bold `#58180D`
- Subtitle: 5.5pt italic `#58180D`
- Ability scores in a flex row, 5.5pt
- Trait names: bold italic

### Color Palette
- Primary: `#58180D` (D&D dark red)
- Accent: `#7A200D`
- Stat block bg: `#fdf1dc`
- Stat block border: `#deb887`
- Even row: `#f9f3f0`
- Text: `#1a1a1a`

### Packing Rules
- **Abbreviate aggressively** in tables: "Perc" not "Perception", "Inv" not "Investigation", "imm" not "immune", "disadv" not "disadvantage", "atk" not "attack", "pot." not "potion", etc.
- Use symbols: arrows (↑↓), multiplication (×), dashes (—)
- Combine related small sections into one column block
- Put the largest tables (room key, monster stats) in the widest available column space
- Keep stat blocks compact — single line for AC/HP/Speed, flex row for scores
- Footnotes for spell scroll lists, item details that don't fit in tables
- Every table MUST have `page-break-inside: avoid; break-inside: avoid;`
- If content exceeds one page, use `page-break-after: always` between page divs

### Page Title
- Span all columns: `grid-column: 1 / -1`
- Adventure name in small-caps, #58180D, 11pt, centered, 2px bottom border

## Step 4: Convert to PDF

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --disable-gpu \
  --print-to-pdf="<output_path>.pdf" \
  --no-margins --print-to-pdf-no-header \
  "file://<html_path>"
```

If Chrome is not at that path, try:
- `which google-chrome`
- `which chromium`
- `/usr/bin/google-chrome`
- As fallback, tell the user to open the HTML file and print to PDF from the browser

Then open the PDF for the user: `open <output_path>.pdf`

## Output Files

Save both files next to each other:
- `dm-screen-<adventure-slug>.html` — editable source
- `dm-screen-<adventure-slug>.pdf` — printable output

## Quality Checklist

Before delivering, verify:
- [ ] No table splits across pages
- [ ] No large empty whitespace gaps
- [ ] All unique creatures have stat references
- [ ] All rooms/locations are accounted for
- [ ] Boss encounter has clear win conditions listed
- [ ] Passwords/secrets are consolidated in one place
- [ ] Magic items are bolded in treasure columns
