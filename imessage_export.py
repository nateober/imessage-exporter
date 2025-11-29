#!/usr/bin/env python3
"""
iMessage Export - Unified CLI Application

A single command to extract, process, and export your iMessage data.

Usage:
    python3 imessage_export.py                 # Full export (default)
    python3 imessage_export.py --full          # Full export (reset everything)
    python3 imessage_export.py --update        # Update with new messages only
    python3 imessage_export.py --contacts      # Update contact names only
    python3 imessage_export.py --attachments   # Extract attachments only
    python3 imessage_export.py --serve         # Start web server
"""

import os
import sys
import json
import sqlite3
import shutil
import subprocess
import argparse
import re
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ============================================================================
# Configuration
# ============================================================================

DATA_FILE = 'imessage_data.json'
MAPPINGS_FILE = 'contact_mappings.json'
ATTACHMENTS_DIR = 'imessage_attachments'
WEB_IMAGES_DIR = 'web_ready_images'
MESSAGE_LIMIT = 500000  # 500k to get all messages (most people have <300k)
ATTACHMENT_LIMIT = 20000  # Get all attachments (historical data has ~15k)

# ============================================================================
# Utility Functions
# ============================================================================

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

def load_mappings():
    """Load persistent contact mappings"""
    if os.path.exists(MAPPINGS_FILE):
        try:
            with open(MAPPINGS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"version": 1, "phone_to_name": {}, "group_chats": {}}

def save_mappings(mappings):
    """Save contact mappings"""
    with open(MAPPINGS_FILE, 'w') as f:
        json.dump(mappings, f, indent=2)

def load_data():
    """Load existing data file"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return None

def save_data(data):
    """Save data with backup"""
    # Backup existing file
    if os.path.exists(DATA_FILE):
        backup = f"imessage_data_backup_{int(datetime.now().timestamp())}.json"
        shutil.copy2(DATA_FILE, backup)
        print(f"  📦 Backed up to {backup}")

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ============================================================================
# Message Decoding
# ============================================================================

def decode_attributed_body(blob):
    """Decode NSAttributedString with proper UTF-8 byte handling"""
    if not blob:
        return None

    try:
        nsstring_pos = blob.find(b'NSString')
        if nsstring_pos == -1:
            return None

        patterns = [
            (bytes([0x67, 0x01, 0x94, 0x84, 0x01, 0x2b]), 0),
            (bytes([0x84, 0x01, 0x2b]), 0),
            (bytes([0x01, 0x94, 0x84, 0x01, 0x2b]), 0),
            (bytes([0x01, 0x95, 0x84, 0x01, 0x2b]), 0),
        ]

        for pattern, length_offset in patterns:
            pattern_pos = blob.find(pattern, nsstring_pos)
            if pattern_pos != -1:
                length_pos = pattern_pos + len(pattern) + length_offset

                if length_pos < len(blob):
                    length_byte = blob[length_pos]

                    if length_byte >= 0x80:
                        num_length_bytes = length_byte & 0x7F
                        if num_length_bytes == 1 and length_pos + 2 < len(blob):
                            text_length = blob[length_pos + 1]
                            text_start = length_pos + 3
                        elif num_length_bytes == 2 and length_pos + 3 < len(blob):
                            text_length = blob[length_pos + 1] | (blob[length_pos + 2] << 8)
                            text_start = length_pos + 4
                        else:
                            continue
                    else:
                        text_length = length_byte
                        text_start = length_pos + 1

                    if 1 <= text_length <= 10000 and text_start + text_length <= len(blob):
                        try:
                            text_bytes = blob[text_start:text_start + text_length]
                            text = text_bytes.decode('utf-8', errors='strict')

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

        # Fallback scan
        search_start = nsstring_pos + 8
        for i in range(search_start, min(search_start + 100, len(blob) - 10)):
            potential_length = blob[i]
            if 2 <= potential_length <= 200:
                text_start = i + 1
                if text_start + potential_length <= len(blob):
                    try:
                        text_bytes = blob[text_start:text_start + potential_length]
                        text = text_bytes.decode('utf-8', errors='strict')

                        if (any(c.isalnum() for c in text) and
                            not text.startswith('NS') and
                            not text.startswith('__')):

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
                        continue

    except Exception:
        pass

    return None

# ============================================================================
# Contact Resolution
# ============================================================================

def resolve_contact_name(phone, mappings):
    """Look up contact name from mappings"""
    phone_to_name = mappings.get("phone_to_name", {})

    if phone in phone_to_name:
        return phone_to_name[phone]

    cleaned = re.sub(r'\D', '', str(phone))
    if len(cleaned) == 10:
        cleaned = '1' + cleaned

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

def query_group_chat_participants(cursor):
    """Query group chat participants from database"""
    group_chats = {}

    cursor.execute("""
        SELECT ROWID, chat_identifier, display_name
        FROM chat
        WHERE chat_identifier LIKE 'chat%'
    """)

    chats = cursor.fetchall()

    for chat_rowid, chat_id, display_name in chats:
        cursor.execute("""
            SELECT h.id
            FROM handle h
            JOIN chat_handle_join chj ON h.ROWID = chj.handle_id
            WHERE chj.chat_id = ?
        """, (chat_rowid,))

        participants = [row[0] for row in cursor.fetchall()]

        if participants:
            group_chats[chat_id] = {
                "display_name": display_name or "",
                "participants": participants
            }

    return group_chats

def resolve_participant_names(group_chats, phone_to_name):
    """Resolve participant phone numbers to names"""
    for chat_id, chat_info in group_chats.items():
        if chat_info.get("display_name"):
            continue

        resolved_names = []
        for participant in chat_info.get("participants", []):
            name = phone_to_name.get(participant)

            if not name:
                cleaned = re.sub(r'\D', '', str(participant))
                if len(cleaned) == 10:
                    cleaned = '1' + cleaned
                name = phone_to_name.get(cleaned) or phone_to_name.get(f"+{cleaned}")
                if not name and len(cleaned) >= 10:
                    name = phone_to_name.get(cleaned[-10:])

            if name:
                resolved_names.append(name)

        if resolved_names:
            chat_info["resolved_display_name"] = ", ".join(resolved_names[:4])
            if len(resolved_names) > 4:
                chat_info["resolved_display_name"] += f" +{len(resolved_names) - 4} more"

def resolve_contacts_via_applescript(phones_to_resolve, limit=50):
    """Resolve contacts using AppleScript (slower but more accurate)"""
    resolved = {}

    for i, phone in enumerate(phones_to_resolve[:limit]):
        if i % 10 == 0 and i > 0:
            print(f"    Resolving contacts: {i}/{min(len(phones_to_resolve), limit)}")

        try:
            script = f'''
            on run
                tell application "Contacts"
                    set foundPeople to {{}}
                    try
                        set foundPeople to foundPeople & (every person whose value of every phone contains "{phone}")
                    end try
                    try
                        set foundPeople to foundPeople & (every person whose value of every email contains "{phone}")
                    end try
                    if (count of foundPeople) > 0 then
                        set thePerson to item 1 of foundPeople
                        set firstName to first name of thePerson
                        set lastName to last name of thePerson
                        if firstName is missing value then set firstName to ""
                        if lastName is missing value then set lastName to ""
                        if firstName is not "" and lastName is not "" then
                            return firstName & " " & lastName
                        else if firstName is not "" then
                            return firstName
                        else if lastName is not "" then
                            return lastName
                        else
                            return ""
                        end if
                    else
                        return ""
                    end if
                end tell
            end run
            '''

            result = subprocess.run(['osascript', '-e', script],
                                  capture_output=True, text=True, timeout=5)

            if result.returncode == 0 and result.stdout.strip():
                resolved[phone] = result.stdout.strip()
        except:
            pass

    return resolved


def resolve_unresolved_contacts(data, mappings, limit=100):
    """Find and resolve unresolved contacts via AppleScript"""
    # Find contacts that still show as phone numbers or emails
    unresolved = []
    for contact in data.get('contacts', []):
        if contact.get('isGroupChat'):
            continue
        name = contact.get('name', '')
        phone = contact.get('phone', '')
        # Check if name is unresolved (phone number, email, or chat ID)
        if name.startswith('+') or '@' in name or name.startswith('chat'):
            if phone and phone not in unresolved:
                unresolved.append(phone)

    if not unresolved:
        return 0

    print(f"  Found {len(unresolved)} unresolved contacts")

    # Resolve via AppleScript
    resolved = resolve_contacts_via_applescript(unresolved, limit=limit)

    if not resolved:
        print(f"  ⚠️  Could not resolve any contacts")
        return 0

    # Update mappings
    for phone, name in resolved.items():
        mappings['phone_to_name'][phone] = name
        cleaned = re.sub(r'\D', '', phone)
        if cleaned:
            mappings['phone_to_name'][cleaned] = name
            mappings['phone_to_name'][f"+{cleaned}"] = name

    save_mappings(mappings)

    # Update contact names in data
    updated = 0
    for contact in data.get('contacts', []):
        phone = contact.get('phone', '')
        if phone in resolved:
            contact['name'] = resolved[phone]
            updated += 1
        else:
            # Try normalized phone
            cleaned = re.sub(r'\D', '', phone)
            for orig_phone, name in resolved.items():
                if re.sub(r'\D', '', orig_phone) == cleaned:
                    contact['name'] = name
                    updated += 1
                    break

    print(f"  ✅ Resolved {len(resolved)} contacts, updated {updated} in data")
    return len(resolved)


# ============================================================================
# Message Extraction
# ============================================================================

def extract_messages(mappings, limit=MESSAGE_LIMIT, since_date=None):
    """Extract messages from iMessage database"""
    db_path = find_chat_db()
    if not db_path:
        print("❌ No iMessage database found")
        return None

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Build query
    date_filter = ""
    params = [limit]

    if since_date:
        # Convert datetime to Apple's epoch
        apple_epoch = (since_date - datetime(2001, 1, 1)).total_seconds() * 1000000000
        date_filter = "AND m.date > ?"
        params = [apple_epoch, limit]

    query = f"""
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
    WHERE 1=1 {date_filter}
    ORDER BY m.date DESC
    LIMIT ?
    """

    cursor.execute(query, params)
    results = cursor.fetchall()

    print(f"  Found {len(results)} messages")

    # Process messages
    contacts = {}
    messages = []
    contact_id_counter = 1
    messages_with_text = 0

    for row in results:
        message_id, text, attributed_body, is_from_me, date, contact_identifier, chat_identifier, chat_display_name, service = row

        # Extract message content
        message_content = text
        if not message_content and attributed_body:
            message_content = decode_attributed_body(attributed_body)

        if message_content:
            messages_with_text += 1

            # Determine contact
            is_group_chat = chat_identifier and chat_identifier.startswith('chat')

            if is_group_chat:
                contact_key = chat_identifier
            elif contact_identifier:
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
                    mapped_display_name, participants = get_group_chat_info(chat_identifier, mappings)
                    if chat_display_name:
                        name = chat_display_name
                    elif mapped_display_name:
                        display_name = mapped_display_name
                        name = chat_identifier
                else:
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

                if display_name:
                    contact_data['displayName'] = display_name
                if participants:
                    contact_data['participants'] = participants

                contacts[contact_key] = contact_data
                contact_id_counter += 1

            contacts[contact_key]['messageCount'] += 1

            messages.append({
                'id': message_id,
                'contactId': contacts[contact_key]['id'],
                'content': message_content,
                'date': date,
                'isFromMe': bool(is_from_me)
            })

    conn.close()

    print(f"  ✅ Extracted {messages_with_text} messages with content")

    # Calculate statistics
    contacts_list = list(contacts.values())
    contacts_list.sort(key=lambda x: x['messageCount'], reverse=True)

    stats = calculate_statistics(messages, contacts_list)

    return {
        'contacts': contacts_list,
        'messages': messages,
        'images': [],
        'statistics': stats
    }

def calculate_statistics(messages, contacts):
    """Calculate message statistics"""
    total_messages = len(messages)
    messages_sent = sum(1 for m in messages if m['isFromMe'])
    messages_received = total_messages - messages_sent

    hourly_dist = [0] * 24
    for message in messages:
        try:
            hour = datetime.fromisoformat(message['date']).hour
            hourly_dist[hour] += 1
        except:
            pass

    dates = [m['date'] for m in messages if m['date']]
    date_range = {
        'start': min(dates) if dates else '',
        'end': max(dates) if dates else ''
    }

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

# ============================================================================
# Attachment Extraction
# ============================================================================

def extract_attachments(limit=ATTACHMENT_LIMIT):
    """Extract attachments from iMessage database"""
    db_path = find_chat_db()
    if not db_path:
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = """
    SELECT DISTINCT
        a.filename,
        a.mime_type,
        a.transfer_name,
        datetime(m.date/1000000000 + 978307200, 'unixepoch') as message_date,
        m.is_from_me,
        COALESCE(h.id, c.chat_identifier) as contact_identifier,
        c.display_name as chat_display_name,
        m.ROWID as message_id
    FROM attachment a
    JOIN message_attachment_join maj ON a.ROWID = maj.attachment_id
    JOIN message m ON maj.message_id = m.ROWID
    LEFT JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
    LEFT JOIN chat c ON cmj.chat_id = c.ROWID
    LEFT JOIN handle h ON m.handle_id = h.ROWID
    WHERE a.filename IS NOT NULL
        AND (a.mime_type LIKE 'image/%'
             OR a.filename LIKE '%.heic'
             OR a.filename LIKE '%.HEIC'
             OR a.filename LIKE '%.jpeg'
             OR a.filename LIKE '%.jpg'
             OR a.filename LIKE '%.png'
             OR a.filename LIKE '%.gif')
    ORDER BY m.date DESC
    LIMIT ?
    """

    cursor.execute(query, (limit,))
    results = cursor.fetchall()
    conn.close()

    print(f"  Found {len(results)} image attachments")

    attachments = []
    for row in results:
        filename, mime_type, transfer_name, date, is_from_me, contact_id, display_name, message_id = row
        contact_name = display_name or contact_id
        if contact_id and not display_name:
            if contact_id.startswith('+'):
                contact_name = clean_phone_number(contact_id)

        attachments.append({
            'filename': filename,
            'mimeType': mime_type,
            'transferName': transfer_name,
            'date': date,
            'isFromMe': bool(is_from_me),
            'contactId': contact_id,
            'contactName': contact_name,
            'messageId': message_id
        })

    return attachments

def copy_and_convert_attachments(attachments, mappings):
    """Copy attachments and convert HEIC to JPEG"""
    output_path = Path(ATTACHMENTS_DIR)
    output_path.mkdir(exist_ok=True)

    web_path = Path(WEB_IMAGES_DIR)
    web_path.mkdir(exist_ok=True)

    processed = []
    copied = 0
    converted = 0
    skipped = 0

    print(f"  Processing {len(attachments)} attachments...")

    for i, att in enumerate(attachments):
        if i % 50 == 0 and i > 0:
            print(f"    Progress: {i}/{len(attachments)}")

        source = att['filename']
        if not source:
            skipped += 1
            continue

        source = os.path.expanduser(source)
        if not os.path.exists(source):
            skipped += 1
            continue

        # Determine destination filename
        dest_name = att['transferName'] or os.path.basename(source)

        # Copy to attachments dir
        dest_path = output_path / dest_name
        counter = 1
        base_name = dest_name
        while dest_path.exists():
            name_parts = base_name.rsplit('.', 1)
            if len(name_parts) == 2:
                dest_name = f"{name_parts[0]}_{counter}.{name_parts[1]}"
            else:
                dest_name = f"{base_name}_{counter}"
            dest_path = output_path / dest_name
            counter += 1

        try:
            shutil.copy2(source, dest_path)
            copied += 1
        except:
            skipped += 1
            continue

        # Convert to web-ready format
        if dest_name.lower().endswith(('.heic', '.heif')):
            jpeg_name = dest_name.rsplit('.', 1)[0] + '.jpg'
            web_dest = web_path / jpeg_name

            if not web_dest.exists():
                try:
                    result = subprocess.run(
                        ['sips', '-s', 'format', 'jpeg', str(dest_path), '--out', str(web_dest)],
                        capture_output=True, timeout=10
                    )
                    if result.returncode == 0:
                        converted += 1
                except:
                    pass

            url = f"{WEB_IMAGES_DIR}/{jpeg_name}"
        else:
            # Copy directly to web dir
            web_dest = web_path / dest_name
            if not web_dest.exists():
                try:
                    shutil.copy2(dest_path, web_dest)
                except:
                    pass
            url = f"{WEB_IMAGES_DIR}/{dest_name}"

        # Resolve contact name from mappings
        contact_name = att['contactName']
        resolved = resolve_contact_name(att['contactId'], mappings)
        if resolved:
            contact_name = resolved

        processed.append({
            'url': url,
            'filename': dest_name,
            'date': att['date'],
            'contactName': contact_name,
            'isFromMe': att['isFromMe'],
            'mimeType': att.get('mimeType', 'image/jpeg'),
            'messageId': att.get('messageId')
        })

    print(f"  ✅ Copied {copied} files, converted {converted} HEIC images")
    if skipped:
        print(f"  ⚠️  Skipped {skipped} (not found)")

    return processed

# ============================================================================
# Main Commands
# ============================================================================

def cmd_full_export():
    """Full export - extract everything from scratch"""
    print("\n" + "=" * 60)
    print("📱 iMessage Full Export")
    print("=" * 60)

    # Step 1: Load or create mappings
    print("\n📇 Step 1: Loading contact mappings...")
    mappings = load_mappings()
    print(f"  Loaded {len(mappings.get('phone_to_name', {}))} phone mappings")
    print(f"  Loaded {len(mappings.get('group_chats', {}))} group chat mappings")

    # Step 2: Query group chat participants
    print("\n👥 Step 2: Querying group chat participants...")
    db_path = find_chat_db()
    if db_path:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        group_chats = query_group_chat_participants(cursor)
        conn.close()

        # Resolve participant names
        resolve_participant_names(group_chats, mappings.get('phone_to_name', {}))
        mappings['group_chats'] = group_chats
        save_mappings(mappings)
        print(f"  ✅ Found {len(group_chats)} group chats")

    # Step 3: Extract messages
    print("\n💬 Step 3: Extracting messages...")
    data = extract_messages(mappings, limit=MESSAGE_LIMIT)
    if not data:
        print("❌ Failed to extract messages")
        return 1

    # Step 4: Save contact mappings from extracted data
    print("\n💾 Step 4: Saving new contact mappings...")
    new_mappings = 0
    for contact in data['contacts']:
        if not contact.get('isGroupChat'):
            phone = contact.get('phone', '')
            name = contact.get('name', '')
            if name and not name.startswith('+') and not name.startswith('chat') and '@' not in name:
                if phone and phone not in mappings['phone_to_name']:
                    mappings['phone_to_name'][phone] = name
                    cleaned = re.sub(r'\D', '', phone)
                    if cleaned:
                        mappings['phone_to_name'][cleaned] = name
                        mappings['phone_to_name'][f"+{cleaned}"] = name
                    new_mappings += 1

    if new_mappings:
        save_mappings(mappings)
        print(f"  ✅ Added {new_mappings} new contact mappings")

    # Step 5: Resolve unresolved contacts via AppleScript
    print("\n🔍 Step 5: Resolving contacts via macOS Contacts...")
    resolved_count = resolve_unresolved_contacts(data, mappings, limit=100)
    if resolved_count == 0:
        print("  ✅ All contacts already resolved")

    # Step 6: Extract attachments
    print("\n📎 Step 6: Extracting attachments...")
    attachments = extract_attachments(limit=ATTACHMENT_LIMIT)
    if attachments:
        images = copy_and_convert_attachments(attachments, mappings)
        data['images'] = images
        data['statistics']['totalImages'] = len(images)

    # Step 7: Save data
    print("\n💾 Step 7: Saving data...")
    save_data(data)
    print(f"  ✅ Saved to {DATA_FILE}")

    # Summary
    print("\n" + "=" * 60)
    print("✨ Export Complete!")
    print("=" * 60)
    stats = data['statistics']
    print(f"  📊 Messages: {stats['totalMessages']:,}")
    print(f"  👤 Contacts: {stats['uniqueContacts']}")
    print(f"  📷 Images: {stats.get('totalImages', 0)}")
    print(f"  📅 Date Range: {stats['dateRange']['start'][:10]} to {stats['dateRange']['end'][:10]}")

    print("\n🌐 To view: python3 imessage_export.py --serve")
    return 0

def cmd_update():
    """Update with new messages only"""
    print("\n" + "=" * 60)
    print("🔄 iMessage Update")
    print("=" * 60)

    # Load existing data
    existing = load_data()
    if not existing:
        print("⚠️  No existing data found. Running full export instead.")
        return cmd_full_export()

    # Get last message date
    last_date = None
    if existing.get('messages'):
        dates = [m['date'] for m in existing['messages'] if m.get('date')]
        if dates:
            last_date = datetime.fromisoformat(max(dates))
            print(f"  Last message date: {last_date}")

    # Load mappings
    mappings = load_mappings()

    # Extract new messages
    print("\n💬 Extracting new messages...")
    new_data = extract_messages(mappings, limit=10000, since_date=last_date)

    if not new_data or not new_data['messages']:
        print("  ℹ️  No new messages found")
        return 0

    # Merge messages
    print(f"\n📝 Merging {len(new_data['messages'])} new messages...")
    existing_ids = {m['id'] for m in existing['messages']}
    new_messages = [m for m in new_data['messages'] if m['id'] not in existing_ids]

    if new_messages:
        existing['messages'] = new_messages + existing['messages']

        # Update contacts
        existing_contact_ids = {c['id'] for c in existing['contacts']}
        new_contacts_added = 0
        for contact in new_data['contacts']:
            if contact['id'] not in existing_contact_ids:
                existing['contacts'].append(contact)
                new_contacts_added += 1

        # Resolve any new unresolved contacts via AppleScript
        if new_contacts_added > 0:
            print(f"\n🔍 Resolving {new_contacts_added} new contacts...")
            resolve_unresolved_contacts(existing, mappings, limit=50)

        # Recalculate statistics
        existing['statistics'] = calculate_statistics(existing['messages'], existing['contacts'])

        # Save
        save_data(existing)
        print(f"  ✅ Added {len(new_messages)} new messages")
    else:
        print("  ℹ️  All messages already in database")

    return 0

def cmd_contacts():
    """Update contact names"""
    print("\n" + "=" * 60)
    print("📇 Contact Name Resolution")
    print("=" * 60)

    # Load data and mappings
    data = load_data()
    mappings = load_mappings()

    if not data:
        print("❌ No data file found. Run --full first.")
        return 1

    # Find unresolved contacts
    unresolved = []
    for contact in data['contacts']:
        if contact.get('isGroupChat'):
            continue
        name = contact.get('name', '')
        phone = contact.get('phone', '')
        if name.startswith('+') or '@' in name:
            unresolved.append(phone)

    print(f"  Found {len(unresolved)} unresolved contacts")

    if not unresolved:
        print("  ✅ All contacts already resolved")
        return 0

    # Try to resolve via AppleScript
    print("\n🔍 Resolving via macOS Contacts...")
    resolved = resolve_contacts_via_applescript(unresolved, limit=100)

    if resolved:
        # Update mappings
        for phone, name in resolved.items():
            mappings['phone_to_name'][phone] = name
            cleaned = re.sub(r'\D', '', phone)
            if cleaned:
                mappings['phone_to_name'][cleaned] = name
                mappings['phone_to_name'][f"+{cleaned}"] = name

        save_mappings(mappings)
        print(f"  ✅ Resolved {len(resolved)} contacts")

        # Update data file
        updated = 0
        for contact in data['contacts']:
            phone = contact.get('phone', '')
            if phone in resolved:
                contact['name'] = resolved[phone]
                updated += 1

        if updated:
            save_data(data)
            print(f"  ✅ Updated {updated} contacts in data file")
    else:
        print("  ⚠️  Could not resolve any contacts")

    return 0

def cmd_attachments():
    """Extract attachments only"""
    print("\n" + "=" * 60)
    print("📎 Attachment Extraction")
    print("=" * 60)

    data = load_data()
    mappings = load_mappings()

    if not data:
        print("❌ No data file found. Run --full first.")
        return 1

    print("\n📎 Extracting attachments...")
    attachments = extract_attachments(limit=ATTACHMENT_LIMIT)

    if attachments:
        images = copy_and_convert_attachments(attachments, mappings)
        data['images'] = images
        data['statistics']['totalImages'] = len(images)
        save_data(data)
        print(f"\n✅ Extracted {len(images)} images")
    else:
        print("  ⚠️  No attachments found")

    return 0

def cmd_serve():
    """Start web server"""
    print("\n🌐 Starting web server...")
    print("   Open http://localhost:8000 in your browser")
    print("   Press Ctrl+C to stop\n")

    os.system("python3 -m http.server 8000")
    return 0

# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='iMessage Export - Extract and visualize your iMessage data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 imessage_export.py              # Full export (default)
  python3 imessage_export.py --update     # Update with new messages
  python3 imessage_export.py --contacts   # Resolve contact names
  python3 imessage_export.py --serve      # Start web server
        """
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--full', action='store_true', help='Full export (reset everything)')
    group.add_argument('--update', action='store_true', help='Update with new messages only')
    group.add_argument('--contacts', action='store_true', help='Update contact names only')
    group.add_argument('--attachments', action='store_true', help='Extract attachments only')
    group.add_argument('--serve', action='store_true', help='Start web server')

    args = parser.parse_args()

    # Check for iMessage database
    if not args.serve and not find_chat_db():
        print("❌ iMessage database not found!")
        print("   Make sure you have Full Disk Access enabled for Terminal")
        print("   System Preferences → Security & Privacy → Privacy → Full Disk Access")
        return 1

    # Run appropriate command
    if args.update:
        return cmd_update()
    elif args.contacts:
        return cmd_contacts()
    elif args.attachments:
        return cmd_attachments()
    elif args.serve:
        return cmd_serve()
    else:
        return cmd_full_export()

if __name__ == "__main__":
    sys.exit(main())
