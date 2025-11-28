#!/usr/bin/env python3
"""
Save contact mappings to a persistent file.
This extracts resolved contact names from the current JSON and
queries group chat participants from the iMessage database.

These mappings are then applied during extraction so you don't
have to re-resolve contacts every time.
"""

import json
import sqlite3
import os
import re
from pathlib import Path
from collections import defaultdict

MAPPINGS_FILE = 'contact_mappings.json'
DATA_FILE = 'imessage_data.json'

def load_mappings():
    """Load existing mappings or create default"""
    if os.path.exists(MAPPINGS_FILE):
        with open(MAPPINGS_FILE, 'r') as f:
            return json.load(f)
    return {
        "version": 1,
        "description": "Persistent contact and group chat mappings",
        "phone_to_name": {},
        "group_chats": {}
    }

def save_mappings(mappings):
    """Save mappings to file"""
    with open(MAPPINGS_FILE, 'w') as f:
        json.dump(mappings, f, indent=2)
    print(f"✅ Saved mappings to {MAPPINGS_FILE}")

def clean_phone_number(phone):
    """Normalize phone number for consistent matching"""
    if not phone:
        return ""
    cleaned = re.sub(r'\D', '', str(phone))
    if len(cleaned) == 10:
        cleaned = '1' + cleaned
    return cleaned

def extract_contacts_from_json():
    """Extract resolved contact names from current JSON"""
    if not os.path.exists(DATA_FILE):
        print(f"❌ {DATA_FILE} not found")
        return {}

    with open(DATA_FILE, 'r') as f:
        data = json.load(f)

    phone_to_name = {}

    for contact in data.get('contacts', []):
        phone = contact.get('phone', '')
        name = contact.get('name', '')

        # Skip if name is just a phone number or chat ID
        if not name or name.startswith('+') or name.startswith('chat') or '@' in name:
            continue

        # Skip group chats for phone mapping
        if contact.get('isGroupChat') or phone.startswith('chat'):
            continue

        # Store mapping with normalized phone
        if phone:
            # Store original format
            phone_to_name[phone] = name

            # Also store normalized format for matching
            cleaned = clean_phone_number(phone)
            if cleaned:
                phone_to_name[f"+{cleaned}"] = name
                phone_to_name[cleaned] = name
                # Last 10 digits
                if len(cleaned) >= 10:
                    phone_to_name[cleaned[-10:]] = name

    return phone_to_name

def query_group_chat_participants():
    """Query iMessage database for group chat participants"""
    db_path = Path.home() / "Library/Messages/chat.db"

    if not db_path.exists():
        print(f"❌ iMessage database not found at {db_path}")
        return {}

    print(f"📖 Reading group chat participants from {db_path}")

    group_chats = {}

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Find all group chats (chat_identifier starts with 'chat')
        cursor.execute("""
            SELECT ROWID, chat_identifier, display_name
            FROM chat
            WHERE chat_identifier LIKE 'chat%'
        """)

        chats = cursor.fetchall()
        print(f"Found {len(chats)} group chats")

        for chat_rowid, chat_id, display_name in chats:
            # Get participants for this chat
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

        conn.close()

        print(f"✅ Found participants for {len(group_chats)} group chats")

    except Exception as e:
        print(f"❌ Error querying database: {e}")

    return group_chats

def resolve_participant_names(group_chats, phone_to_name):
    """Resolve participant phone numbers to names where possible"""
    for chat_id, chat_info in group_chats.items():
        if chat_info.get("display_name"):
            # Already has a display name set in iMessage
            continue

        # Try to resolve participant names
        resolved_names = []
        for participant in chat_info.get("participants", []):
            # Try direct match
            name = phone_to_name.get(participant)

            # Try normalized match
            if not name:
                cleaned = clean_phone_number(participant)
                name = phone_to_name.get(cleaned) or phone_to_name.get(f"+{cleaned}")
                if not name and len(cleaned) >= 10:
                    name = phone_to_name.get(cleaned[-10:])

            if name:
                resolved_names.append(name)

        # Create display name from resolved participants
        if resolved_names:
            chat_info["resolved_display_name"] = ", ".join(resolved_names[:4])
            if len(resolved_names) > 4:
                chat_info["resolved_display_name"] += f" +{len(resolved_names) - 4} more"

def main():
    print("=" * 60)
    print("📇 Contact Mappings Saver")
    print("=" * 60)
    print()

    # Load existing mappings
    mappings = load_mappings()

    # Extract contact names from current JSON
    print("📖 Extracting resolved contact names from JSON...")
    new_phone_mappings = extract_contacts_from_json()

    # Merge with existing (new values override old)
    existing_count = len(mappings.get("phone_to_name", {}))
    mappings["phone_to_name"].update(new_phone_mappings)
    new_count = len(mappings["phone_to_name"])

    print(f"   Phone mappings: {existing_count} existing + {len(new_phone_mappings)} from JSON = {new_count} total")

    # Query group chat participants
    print()
    print("📖 Querying group chat participants from iMessage database...")
    group_chats = query_group_chat_participants()

    # Resolve participant names
    resolve_participant_names(group_chats, mappings["phone_to_name"])

    # Merge with existing
    existing_groups = len(mappings.get("group_chats", {}))
    mappings["group_chats"].update(group_chats)

    print(f"   Group chats: {existing_groups} existing + {len(group_chats)} from database")

    # Save
    print()
    save_mappings(mappings)

    # Summary
    print()
    print("=" * 60)
    print("📊 Summary")
    print("=" * 60)
    print(f"Phone → Name mappings: {len(mappings['phone_to_name'])}")
    print(f"Group chat mappings:   {len(mappings['group_chats'])}")

    # Show some examples
    print()
    print("Sample phone mappings:")
    sample_phones = list(mappings["phone_to_name"].items())[:5]
    for phone, name in sample_phones:
        if phone.startswith('+'):
            print(f"  {phone} → {name}")

    print()
    print("Sample group chats with resolved names:")
    for chat_id, info in list(mappings["group_chats"].items())[:5]:
        display = info.get("display_name") or info.get("resolved_display_name") or "No name"
        participant_count = len(info.get("participants", []))
        print(f"  {chat_id[:30]}... → {display} ({participant_count} participants)")

    print()
    print("✅ Done! These mappings will be used by the extraction script.")

if __name__ == "__main__":
    main()
