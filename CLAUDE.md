# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

**iMessage Explorer** - A macOS application that extracts, processes, and visualizes iMessage conversation data through a beautiful web interface. The project consists of a unified Python CLI tool and an interactive HTML/CSS/JS dashboard.

## Quick Start

```bash
# Full export - extracts messages, contacts, attachments (first time use)
python3 imessage_export.py --full

# Update with new messages only (daily use)
python3 imessage_export.py --update

# Start web server to view
python3 imessage_export.py --serve
# Then open http://localhost:8000
```

**Requires**: macOS with Full Disk Access permission for Terminal

## Project Structure

```
├── imessage_export.py          # Main unified CLI (use this!)
├── index.html                   # Web dashboard (single-file app)
├── imessage_data.json          # Extracted data (generated)
├── contact_mappings.json       # Persistent contact names (generated)
├── web_ready_images/           # Processed images (generated)
│
├── # Legacy scripts (still functional but use CLI instead):
├── extract_messages_final_correct.py
├── save_contact_mappings.py
├── update_contact_names.py
├── contacts_from_vcf.py
├── extract_attachments.py
└── convert_all_heic.py
```

## Key Commands

| Command | Description |
|---------|-------------|
| `python3 imessage_export.py` | Full export (same as --full) |
| `python3 imessage_export.py --full` | Complete extraction from scratch |
| `python3 imessage_export.py --update` | Incremental update (new messages only) |
| `python3 imessage_export.py --contacts` | Resolve unresolved contact names via macOS Contacts |
| `python3 imessage_export.py --attachments` | Extract/convert image attachments only |
| `python3 imessage_export.py --serve` | Start local web server on port 8000 |

## Architecture

### Data Flow
1. **Extraction**: Read from `~/Library/Messages/chat.db` (SQLite)
2. **Processing**: Resolve contacts, decode messages, calculate statistics
3. **Image Processing**: Copy attachments, convert HEIC→JPEG via `sips`
4. **Storage**: Save to `imessage_data.json` with automatic backups
5. **Visualization**: Web interface loads JSON, renders interactive dashboard

### Core Components

#### imessage_export.py (1090 lines)
The unified CLI with these key functions:
- `extract_messages()` - Query chat.db, decode attributedBody, resolve contacts
- `extract_attachments()` - Find image attachments, copy and convert
- `resolve_contacts_via_applescript()` - Use macOS Contacts app for name lookup
- `cmd_update()` - Incremental update with proper contact ID remapping
- `cmd_full_export()` - 7-step complete extraction pipeline

#### index.html (2474 lines)
Single-file web application with:
- Contact list with search and message counts
- Conversation viewer with inline images
- Attachments gallery with contact/date filters
- Statistics dashboard with hourly activity chart
- Network visualization (D3.js)

### Data Structure

**imessage_data.json**:
```json
{
  "contacts": [
    {"id": 1, "name": "John Doe", "phone": "+1234567890", "messageCount": 150, "isGroupChat": false}
  ],
  "messages": [
    {"id": 12345, "contactId": 1, "content": "Hello!", "date": "2025-01-01 10:30:00", "isFromMe": true}
  ],
  "images": [
    {"url": "web_ready_images/IMG_1234.jpg", "messageId": 12345, "contactName": "John Doe", "date": "..."}
  ],
  "statistics": {
    "totalMessages": 237639,
    "uniqueContacts": 2134,
    "hourlyDistribution": [...]
  }
}
```

**contact_mappings.json**:
```json
{
  "version": 1,
  "phone_to_name": {"+1234567890": "John Doe"},
  "group_chats": {"chat123456": {"participants": [...], "resolved_display_name": "..."}}
}
```

## Important Implementation Details

### Message Decoding
- Messages may have `text` field (plain) or `attributedBody` (binary plist with styling)
- `decode_attributed_body()` handles NSAttributedString extraction
- Unicode object replacement character (U+FFFC) indicates inline attachments

### Contact Resolution
1. First, use existing mappings from `contact_mappings.json`
2. Then, query group chat participants from `chat_handle_join` table
3. Finally, use AppleScript to query macOS Contacts app
4. Mappings persist across extractions

### Update Merge Logic (Critical!)
When merging new messages in `--update`:
1. Extract new messages with temporary contact IDs (starting from 1)
2. Build lookup from phone/chat_identifier → existing contact ID
3. **Remap** new message contactIds to existing IDs (or create new contacts)
4. Must save `original_id` before modifying to create correct mapping

### Image Handling
- HEIC images converted to JPEG using macOS `sips` command
- Images linked to messages via `messageId` for inline display
- Some old attachments may be deleted by macOS - these are skipped

### Group Chats
- Identified by `chat_identifier` starting with "chat"
- Participants resolved from `chat_handle_join` table
- Display names generated from first 4 participant names + count

## Common Issues & Solutions

### "Permission denied" accessing chat.db
Grant **Full Disk Access** to Terminal in System Preferences → Security & Privacy → Privacy

### Images not loading in browser
1. Check `web_ready_images/` directory exists and has files
2. Run `python3 imessage_export.py --attachments` to re-extract
3. Some files may show as HEIC with .jpeg extension - the CLI fixes these

### Contact showing as phone number
1. Check if contact exists in macOS Contacts app
2. Run `python3 imessage_export.py --contacts` to resolve
3. New contacts are automatically resolved on `--update`

### Messages assigned to wrong contact (after update)
This was a bug fixed in commit `11d9f92`. If you see this, update to latest code.

## Configuration

In `imessage_export.py`:
```python
MESSAGE_LIMIT = 500000    # Max messages to extract (covers most users)
ATTACHMENT_LIMIT = 20000  # Max images to process
```

## Dependencies

- Python 3.x (built-in: sqlite3, json, subprocess, re, pathlib)
- macOS `sips` command (built-in) for HEIC conversion
- Modern browser for web interface
- Optional: `pillow`, `pillow-heif` for legacy scripts

## Privacy

All data stays local. The `.gitignore` excludes:
- `imessage_data.json` (your messages)
- `contact_mappings.json` (your contacts)
- `*.vcf` (contact exports)
- Image directories
