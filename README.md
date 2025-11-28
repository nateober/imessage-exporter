# iMessage Explorer

A beautiful, warm-themed web interface to explore and visualize your iMessage history on macOS.

## Features

- **Contact List** - View all contacts sorted by message count with resolved names
- **Conversation Viewer** - Read conversations in elegant message bubbles
- **Search** - Search contacts and messages instantly
- **Image Gallery** - Browse shared images in polaroid-style frames with lightbox viewer
- **Statistics** - View message statistics, hourly activity charts, and network visualization
- **Group Chats** - Automatically resolves group chat participants to show names
- **Persistent Contacts** - Contact name mappings are saved and reused across extractions

## Screenshots

The interface features a warm, personal aesthetic with:
- Cream and terracotta color palette
- Elegant serif typography (Lora, Nunito, Caveat fonts)
- Polaroid-style image frames
- Smooth animations and transitions

## Quick Start

### 1. Extract your iMessage data

```bash
python3 extract_messages_final_correct.py
```

*Note: Requires Full Disk Access permission on macOS*

### 2. Resolve contact names (optional but recommended)

```bash
# Save current contact mappings and group chat participants
python3 save_contact_mappings.py

# Resolve more contacts via macOS Contacts app
python3 update_contact_names.py

# Or import from VCF export
python3 contacts_from_vcf.py --vcf
```

### 3. View in browser

```bash
# Start a local server
python3 -m http.server 8000

# Open in browser
open http://localhost:8000
```

## Project Structure

```
├── index.html                    # Web interface
├── extract_messages_final_correct.py  # Main extraction script
├── save_contact_mappings.py      # Save contact & group chat mappings
├── update_contact_names.py       # Resolve contacts via macOS Contacts
├── contacts_from_vcf.py          # Import contacts from VCF/CSV
├── extract_attachments.py        # Extract message attachments
├── convert_all_heic.py           # Convert HEIC images to JPEG
├── contact_mappings.json         # Persistent contact mappings (generated)
├── imessage_data.json            # Extracted message data (generated)
└── web_ready_images/             # Processed images (generated)
```

## Persistent Contact Mappings

Contact names and group chat participants are stored in `contact_mappings.json`:

- **Phone → Name mappings**: Resolved contact names persist across extractions
- **Group chat info**: Participant lists and resolved display names for unnamed group chats

This means you only need to resolve contacts once - future extractions will automatically use saved mappings.

## Scripts

| Script | Description |
|--------|-------------|
| `extract_messages_final_correct.py` | Extract messages from iMessage database with proper UTF-8 handling |
| `save_contact_mappings.py` | Save current contacts and query group chat participants |
| `update_contact_names.py` | Resolve contacts via macOS Contacts app (AppleScript) |
| `contacts_from_vcf.py` | Import contacts from VCF or CSV exports |
| `extract_attachments.py` | Extract image attachments from messages |
| `convert_all_heic.py` | Convert HEIC images to web-compatible JPEG |

## Requirements

- macOS (for iMessage database access)
- Python 3.x with:
  - `pillow` (for image processing)
  - `pillow_heif` (for HEIC support)
- Modern web browser

Install dependencies:
```bash
pip install pillow pillow-heif
```

## Privacy Note

This tool processes your personal message data **locally**. No data is sent to external servers. All processing happens on your machine.

The `.gitignore` excludes all personal data files:
- Message data (`imessage_data.json`)
- Contact mappings (`contact_mappings.json`)
- VCF exports (`*.vcf`)
- Image directories

## Troubleshooting

### Permission denied
Grant **Full Disk Access** to Terminal in System Preferences → Security & Privacy → Privacy → Full Disk Access

### Images not loading
1. Run `python3 extract_attachments.py` to extract attachments
2. Run `python3 convert_all_heic.py` to convert HEIC to JPEG

### Contacts showing as phone numbers
1. Run `python3 update_contact_names.py` to resolve via Contacts app
2. Or export contacts as VCF and run `python3 contacts_from_vcf.py --vcf`

### Group chats showing as IDs
Run `python3 save_contact_mappings.py` to query participant info from iMessage database

## License

MIT
