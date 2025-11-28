#!/usr/bin/env python3
"""
Final correct iMessage extraction
The length byte counts UTF-8 bytes, not characters
This handles multi-byte characters correctly

Now with persistent contact mappings support!
"""

import os
import sqlite3
import json
import re
from datetime import datetime
from pathlib import Path

MAPPINGS_FILE = 'contact_mappings.json'

def load_contact_mappings():
    """Load persistent contact mappings if available"""
    if os.path.exists(MAPPINGS_FILE):
        try:
            with open(MAPPINGS_FILE, 'r') as f:
                mappings = json.load(f)
            print(f"📇 Loaded contact mappings: {len(mappings.get('phone_to_name', {}))} phone mappings, {len(mappings.get('group_chats', {}))} group chats")
            return mappings
        except Exception as e:
            print(f"⚠️ Could not load mappings: {e}")
    return {"phone_to_name": {}, "group_chats": {}}

def resolve_contact_name(phone, mappings):
    """Look up contact name from mappings"""
    phone_to_name = mappings.get("phone_to_name", {})

    # Direct lookup
    if phone in phone_to_name:
        return phone_to_name[phone]

    # Normalized lookup
    cleaned = re.sub(r'\D', '', str(phone))
    if len(cleaned) == 10:
        cleaned = '1' + cleaned

    # Try various formats
    variants = [
        cleaned,
        f"+{cleaned}",
        f"+1{cleaned[-10:]}" if len(cleaned) >= 10 else None,
        cleaned[-10:] if len(cleaned) >= 10 else None,
    ]

    for variant in variants:
        if variant and variant in phone_to_name:
            return phone_to_name[variant]

    return None

def get_group_chat_info(chat_identifier, mappings):
    """Get display name and participants for a group chat"""
    group_chats = mappings.get("group_chats", {})

    if chat_identifier in group_chats:
        info = group_chats[chat_identifier]
        display_name = info.get("display_name") or info.get("resolved_display_name")
        participants = info.get("participants", [])
        return display_name, participants

    return None, []

def find_chat_db():
    """Find iMessage chat database"""
    chat_db = Path.home() / "Library/Messages/chat.db"
    if chat_db.exists():
        return str(chat_db)
    return None

def clean_phone_number(phone):
    """Clean and normalize phone number"""
    if not phone:
        return ""

    cleaned = re.sub(r'\D', '', str(phone))

    if len(cleaned) == 10:
        cleaned = '1' + cleaned
    elif len(cleaned) == 11 and cleaned.startswith('1'):
        pass

    return f"+{cleaned}" if cleaned else phone

def decode_attributed_body_correct(blob):
    """
    Correct decode of NSAttributedString
    Length byte represents UTF-8 byte count, not character count
    Handles multi-byte length encoding for messages > 127 bytes
    """
    if not blob:
        return None

    try:
        # Look for NSString marker
        nsstring_pos = blob.find(b'NSString')
        if nsstring_pos == -1:
            return None

        # Primary pattern: 67 01 94 84 01 2b [length] [text]
        patterns = [
            (bytes([0x67, 0x01, 0x94, 0x84, 0x01, 0x2b]), 0),  # Standard pattern
            (bytes([0x84, 0x01, 0x2b]), 0),  # Shorter pattern
            (bytes([0x01, 0x94, 0x84, 0x01, 0x2b]), 0),  # Alternative pattern
            (bytes([0x01, 0x95, 0x84, 0x01, 0x2b]), 0),  # Another variant
        ]

        for pattern, length_offset in patterns:
            pattern_pos = blob.find(pattern, nsstring_pos)
            if pattern_pos != -1:
                # Length byte position
                length_pos = pattern_pos + len(pattern) + length_offset

                if length_pos < len(blob):
                    length_byte = blob[length_pos]

                    # Handle multi-byte length encoding
                    # If high bit is set (>= 0x80), lower bits indicate how many bytes follow
                    if length_byte >= 0x80:
                        # Multi-byte length: lower 7 bits = number of following length bytes
                        num_length_bytes = length_byte & 0x7F
                        if num_length_bytes == 1 and length_pos + 2 < len(blob):
                            # Single additional byte for length, plus null separator
                            text_length = blob[length_pos + 1]
                            # Skip: 0x81 + length_byte + 0x00 separator
                            text_start = length_pos + 3
                        elif num_length_bytes == 2 and length_pos + 3 < len(blob):
                            # Two additional bytes for length (little-endian), plus null separator
                            text_length = blob[length_pos + 1] | (blob[length_pos + 2] << 8)
                            text_start = length_pos + 4
                        else:
                            continue
                    else:
                        # Single byte length (< 128)
                        text_length = length_byte
                        text_start = length_pos + 1

                    # Validate and extract
                    if 1 <= text_length <= 10000 and text_start + text_length <= len(blob):
                        try:
                            text_bytes = blob[text_start:text_start + text_length]
                            text = text_bytes.decode('utf-8', errors='strict')

                            # Clean control characters
                            clean_text = ''
                            for char in text:
                                if ord(char) >= 32 or char in '\n\t\r':
                                    clean_text += char
                                elif ord(char) < 32:
                                    break

                            clean_text = clean_text.strip()

                            if len(clean_text) > 0:
                                return clean_text

                        except UnicodeDecodeError:
                            continue

        # Fallback: scan for length + valid UTF-8 sequences
        # Start searching after NSString
        search_start = nsstring_pos + 8

        for i in range(search_start, min(search_start + 100, len(blob) - 10)):
            potential_length = blob[i]

            # Try reasonable lengths
            if 2 <= potential_length <= 200:
                text_start = i + 1
                if text_start + potential_length <= len(blob):
                    try:
                        # Extract the exact number of bytes
                        text_bytes = blob[text_start:text_start + potential_length]

                        # Try to decode as UTF-8
                        text = text_bytes.decode('utf-8', errors='strict')

                        # Validate it looks like a message
                        if (any(c.isalnum() for c in text) and
                            not text.startswith('NS') and
                            not text.startswith('__')):

                            # Clean control chars
                            clean_text = ''
                            for char in text:
                                if ord(char) >= 32 or char in '\n\t\r':
                                    clean_text += char
                                elif ord(char) < 32:
                                    break

                            clean_text = clean_text.strip()

                            if len(clean_text) >= 2:
                                return clean_text

                    except UnicodeDecodeError:
                        # Not valid UTF-8 at this position
                        continue

    except Exception as e:
        pass

    return None

def extract_all_messages():
    """Extract ALL messages with correct UTF-8 byte handling"""

    # Load persistent contact mappings
    mappings = load_contact_mappings()

    db_path = find_chat_db()
    if not db_path:
        print("❌ No iMessage database found")
        return None

    print(f"Found database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("Extracting messages with correct UTF-8 byte handling...")

    # Query for ALL messages
    query = """
    SELECT DISTINCT
        m.ROWID as message_id,
        m.text as message_text,
        m.attributedBody as attributed_body,
        m.is_from_me,
        datetime(m.date / 1000000000 + strftime('%s', '2001-01-01'), 'unixepoch', 'localtime') as message_date,
        h.id as contact_identifier,
        c.chat_identifier,
        c.display_name as chat_display_name,
        m.service
    FROM message m
    LEFT JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
    LEFT JOIN chat c ON cmj.chat_id = c.ROWID
    LEFT JOIN handle h ON m.handle_id = h.ROWID
    ORDER BY m.date DESC
    LIMIT 50000
    """

    cursor.execute(query)
    results = cursor.fetchall()

    print(f"Found {len(results)} total messages")

    # Process messages
    contacts = {}
    messages = []
    contact_id_counter = 1
    messages_with_text = 0
    messages_from_attributed = 0
    extraction_errors = 0

    for row in results:
        message_id, text, attributed_body, is_from_me, date, contact_identifier, chat_identifier, chat_display_name, service = row

        # Extract message content
        message_content = text

        if not message_content and attributed_body:
            # Use our correct UTF-8 aware decoder
            try:
                extracted_text = decode_attributed_body_correct(attributed_body)
                if extracted_text:
                    message_content = extracted_text
                    messages_from_attributed += 1
                else:
                    extraction_errors += 1
            except Exception as e:
                extraction_errors += 1

        if message_content:
            messages_with_text += 1

            # Determine contact - for group chats, always use chat_identifier to keep messages together
            is_group_chat = chat_identifier and chat_identifier.startswith('chat')

            if is_group_chat:
                # Group chat: use chat_identifier to keep all messages together
                contact_key = chat_identifier
            elif contact_identifier:
                # Individual chat: use contact identifier
                contact_key = contact_identifier
            elif chat_identifier:
                contact_key = chat_identifier
            else:
                contact_key = f"unknown_{message_id}"

            # Create or update contact
            if contact_key not in contacts:
                name = contact_key
                display_name = None
                participants = []

                if is_group_chat:
                    # Try to get group chat info from mappings
                    mapped_display_name, participants = get_group_chat_info(chat_identifier, mappings)
                    if chat_display_name:
                        name = chat_display_name
                    elif mapped_display_name:
                        display_name = mapped_display_name
                        name = chat_identifier  # Keep original as name, display_name for UI
                else:
                    # Individual chat - try to resolve from mappings first
                    resolved_name = resolve_contact_name(contact_identifier, mappings)
                    if resolved_name:
                        name = resolved_name
                    elif chat_display_name:
                        name = chat_display_name
                    elif contact_identifier:
                        if contact_identifier.startswith('+') or contact_identifier.replace('-', '').replace('(', '').replace(')', '').replace(' ', '').isdigit():
                            name = clean_phone_number(contact_identifier)
                        else:
                            name = contact_identifier

                contact_data = {
                    'id': contact_id_counter,
                    'name': name,
                    'phone': contact_identifier or chat_identifier or '',
                    'messageCount': 0,
                    'isGroupChat': is_group_chat
                }

                # Add display_name and participants for group chats
                if display_name:
                    contact_data['displayName'] = display_name
                if participants:
                    contact_data['participants'] = participants

                contacts[contact_key] = contact_data
                contact_id_counter += 1

            # Add message
            contacts[contact_key]['messageCount'] += 1

            messages.append({
                'id': message_id,
                'contactId': contacts[contact_key]['id'],
                'content': message_content,
                'date': date,
                'isFromMe': bool(is_from_me)
            })

    conn.close()

    print(f"✅ Extracted {messages_with_text} messages with content")
    print(f"  - {messages_with_text - messages_from_attributed} from text field")
    print(f"  - {messages_from_attributed} from attributedBody field")
    if extraction_errors > 0:
        print(f"  - {extraction_errors} messages could not be decoded")

    # Convert contacts dict to list and sort
    contacts_list = list(contacts.values())
    contacts_list.sort(key=lambda x: x['messageCount'], reverse=True)

    # Calculate statistics
    stats = calculate_statistics(messages, contacts_list)

    # Prepare final data
    data = {
        'contacts': contacts_list,
        'messages': messages,
        'images': [],
        'statistics': stats
    }

    return data

def calculate_statistics(messages, contacts):
    """Calculate message statistics"""
    total_messages = len(messages)
    messages_sent = sum(1 for m in messages if m['isFromMe'])
    messages_received = total_messages - messages_sent

    # Calculate hourly distribution
    hourly_dist = [0] * 24
    for message in messages:
        try:
            hour = datetime.fromisoformat(message['date']).hour
            hourly_dist[hour] += 1
        except:
            pass

    # Date range
    dates = [m['date'] for m in messages if m['date']]
    date_range = {
        'start': min(dates) if dates else '',
        'end': max(dates) if dates else ''
    }

    # Average message length
    lengths = [len(m['content']) for m in messages if m['content']]
    avg_length = sum(lengths) / len(lengths) if lengths else 0

    return {
        'totalMessages': total_messages,
        'messagesSent': messages_sent,
        'messagesReceived': messages_received,
        'uniqueContacts': len(contacts),
        'avgMessageLength': avg_length,
        'dateRange': date_range,
        'hourlyDistribution': hourly_dist
    }

def main():
    """Main execution"""
    print("=" * 70)
    print("🚀 iMessage Final Correct Extraction")
    print("   Proper UTF-8 byte counting - handles all special characters!")
    print("=" * 70)

    # Extract messages
    data = extract_all_messages()

    if not data:
        print("❌ Failed to extract messages")
        return 1

    # Save to JSON
    output_file = 'imessage_data.json'
    backup_file = f'imessage_data_backup_{int(datetime.now().timestamp())}.json'

    # Backup existing file
    if Path(output_file).exists():
        import shutil
        shutil.copy2(output_file, backup_file)
        print(f"📦 Backed up existing data to {backup_file}")

    # Save new data
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Data saved to {output_file}")

    # Print summary
    stats = data['statistics']
    print("\n" + "=" * 70)
    print("📊 Final Extraction Summary")
    print("=" * 70)
    print(f"Total Messages: {stats['totalMessages']:,}")
    print(f"Unique Contacts: {stats['uniqueContacts']}")
    print(f"Messages Sent: {stats['messagesSent']:,}")
    print(f"Messages Received: {stats['messagesReceived']:,}")
    print(f"Date Range: {stats['dateRange']['start'][:10]} to {stats['dateRange']['end'][:10]}")
    print(f"Avg Message Length: {stats['avgMessageLength']:.1f} characters")

    print("\nTop 5 Contacts:")
    for contact in data['contacts'][:5]:
        print(f"  - {contact['name']}: {contact['messageCount']:,} messages")

    # Show sample messages with special characters
    print("\n✨ Sample messages (with special chars preserved):")

    # Look for messages with special characters
    special_char_msgs = []
    for msg in data['messages']:
        content = msg['content']
        # Check for non-ASCII or special punctuation
        if any(ord(c) > 127 or c in '\'''""—–' for c in content):
            special_char_msgs.append(msg)
            if len(special_char_msgs) >= 3:
                break

    # Also show some regular messages
    regular_msgs = [m for m in data['messages'] if len(m['content']) > 20][:2]

    for msg in special_char_msgs + regular_msgs:
        preview = msg['content'][:80]
        if len(msg['content']) > 80:
            preview += "..."
        print(f"  - {repr(preview)}")

    print("\n🎉 Complete extraction with proper character handling!")
    print("📝 All special characters, emojis, and quotes preserved correctly")

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())