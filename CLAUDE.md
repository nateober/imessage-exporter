# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an iMessage data processing and visualization project that extracts, processes, and displays iMessage conversation data on macOS. It consists of Python data extraction/processing tools and a web-based visualization interface.

## Key Components

1. **imessage-data-explorer.py** - Extracts data directly from macOS iMessage database
2. **data-processor.py** - Processes CSV exports into clean JSON format
3. **index.html** - Interactive web dashboard for viewing messages and statistics
4. **extracted_images/** - Directory containing extracted message attachments

## Common Commands

### Extract messages from iMessage database (requires Full Disk Access):
```bash
python imessage-data-explorer.py
```

### Process CSV message exports:
```bash
# Process all CSV files in current directory
python data-processor.py

# Process specific CSV file
python data-processor.py --input messages.csv --output processed_data.json
```

### View data in browser:
```bash
# Open index.html in default browser
open index.html
```

## Architecture

### Data Flow
1. **Extraction**: Either direct from chat.db (imessage-data-explorer.py) or from CSV exports
2. **Processing**: Clean contact names, deduplicate messages, convert HEIC images, calculate statistics
3. **Storage**: JSON format with contacts, messages, images, and statistics
4. **Visualization**: Web interface loads JSON and displays interactive dashboard

### Key Dependencies
- pandas - Data manipulation
- PIL/Pillow - Image processing
- pillow_heif - HEIC image support
- sqlite3 - Database access
- numpy - Numerical operations

### Data Structure
The processed JSON contains:
- `contacts`: Array of contact objects with id, name, phone, messageCount
- `messages`: Array of message objects with id, contactId, content, date, isFromMe
- `images`: Array of image metadata with paths and contact associations
- `statistics`: Overall metrics including hourly distribution

### Important Implementation Details
- Contact name cleaning handles phone numbers, emails, and various chat ID formats
- Image processing includes HEIC to JPEG conversion for web compatibility
- Messages are deduplicated to avoid repeated entries
- Full Disk Access permission required for direct database extraction on macOS
- Encoding detection and fallback for handling various text encodings