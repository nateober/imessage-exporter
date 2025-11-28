#!/usr/bin/env python3
"""
Update contact names by resolving them from macOS Contacts.
Now saves to persistent contact_mappings.json for reuse across extractions.
"""

import json
import sqlite3
import os
import subprocess
import re
from pathlib import Path

MAPPINGS_FILE = 'contact_mappings.json'

def load_mappings():
    """Load existing mappings"""
    if os.path.exists(MAPPINGS_FILE):
        with open(MAPPINGS_FILE, 'r') as f:
            return json.load(f)
    return {"version": 1, "phone_to_name": {}, "group_chats": {}}

def save_mappings(mappings):
    """Save mappings to file"""
    with open(MAPPINGS_FILE, 'w') as f:
        json.dump(mappings, f, indent=2)
    print(f"✅ Saved mappings to {MAPPINGS_FILE}")

def find_contacts_database():
    """Find the macOS Contacts database"""
    possible_paths = [
        # Modern macOS paths
        Path.home() / "Library/Application Support/AddressBook/AddressBook-v22.abcddb",
        Path.home() / "Library/Application Support/ContactsAgent/Contacts.sqlite",
        Path.home() / "Library/Application Support/Contacts/AddressBook-v22.abcddb",
        # iCloud synced contacts
        Path.home() / "Library/Application Support/CloudDocs/session/db/AddressBook-v22.abcddb",
    ]
    
    # Also search for any AddressBook databases
    search_paths = [
        Path.home() / "Library/Application Support/AddressBook",
        Path.home() / "Library/Application Support/Contacts",
        Path.home() / "Library/Containers/com.apple.Contacts",
    ]
    
    for search_path in search_paths:
        if search_path.exists():
            for db_file in search_path.rglob("*.abcddb"):
                possible_paths.append(db_file)
            for db_file in search_path.rglob("*.sqlite"):
                if "contacts" in db_file.name.lower():
                    possible_paths.append(db_file)
    
    # Return the first existing database
    for path in possible_paths:
        if path.exists():
            print(f"Found Contacts database at: {path}")
            return str(path)
    
    return None

def clean_phone_number(phone):
    """Clean and normalize phone number"""
    # Remove all non-digit characters
    cleaned = re.sub(r'\D', '', phone)
    
    # Handle different lengths
    if len(cleaned) == 10:  # US number without country code
        cleaned = '1' + cleaned
    elif len(cleaned) == 11 and cleaned.startswith('1'):  # US number with country code
        pass  # Already in correct format
    
    return cleaned

def resolve_contact_via_applescript(identifier):
    """Resolve contact name using AppleScript"""
    try:
        # Clean the identifier
        identifier = identifier.strip()
        
        # AppleScript to search contacts
        script = f'''
        on run
            tell application "Contacts"
                set foundPeople to {{}}
                
                -- Search by phone number
                try
                    set foundPeople to foundPeople & (every person whose value of every phone contains "{identifier}")
                end try
                
                -- Search by email
                try
                    set foundPeople to foundPeople & (every person whose value of every email contains "{identifier}")
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
        
        # Run the AppleScript
        result = subprocess.run(['osascript', '-e', script], 
                              capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    
    except Exception as e:
        print(f"AppleScript error for {identifier}: {e}")
    
    return None

def resolve_contacts_from_database(db_path, phone_numbers):
    """Resolve multiple contacts from the database"""
    resolved = {}
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Query to get contact names - try different matching strategies
        for phone in phone_numbers:
            cleaned = clean_phone_number(phone)
            
            # Try multiple matching strategies
            queries = [
                # Exact match on cleaned number
                f"""
                SELECT DISTINCT 
                    COALESCE(p.ZFIRSTNAME, '') || ' ' || COALESCE(p.ZLASTNAME, '') as name
                FROM ZABCDPHONENUMBER pn
                JOIN ZABCDRECORD p ON pn.ZOWNER = p.Z_PK
                WHERE REPLACE(REPLACE(REPLACE(REPLACE(pn.ZFULLNUMBER, ' ', ''), '-', ''), '(', ''), ')', '') LIKE '%{cleaned}%'
                """,
                # Last 10 digits match
                f"""
                SELECT DISTINCT 
                    COALESCE(p.ZFIRSTNAME, '') || ' ' || COALESCE(p.ZLASTNAME, '') as name
                FROM ZABCDPHONENUMBER pn
                JOIN ZABCDRECORD p ON pn.ZOWNER = p.Z_PK
                WHERE REPLACE(REPLACE(REPLACE(REPLACE(pn.ZFULLNUMBER, ' ', ''), '-', ''), '(', ''), ')', '') LIKE '%{cleaned[-10:]}%'
                """ if len(cleaned) >= 10 else None,
                # Last 7 digits match
                f"""
                SELECT DISTINCT 
                    COALESCE(p.ZFIRSTNAME, '') || ' ' || COALESCE(p.ZLASTNAME, '') as name
                FROM ZABCDPHONENUMBER pn
                JOIN ZABCDRECORD p ON pn.ZOWNER = p.Z_PK
                WHERE REPLACE(REPLACE(REPLACE(REPLACE(pn.ZFULLNUMBER, ' ', ''), '-', ''), '(', ''), ')', '') LIKE '%{cleaned[-7:]}%'
                """ if len(cleaned) >= 7 else None,
            ]
            
            for query in queries:
                if query:
                    try:
                        cursor.execute(query)
                        result = cursor.fetchone()
                        if result and result[0].strip():
                            resolved[phone] = result[0].strip()
                            break
                    except:
                        continue
        
        conn.close()
        
    except Exception as e:
        print(f"Database error: {e}")
    
    return resolved

def update_contact_names():
    """Update contact names in imessage_data.json"""
    
    # Load the JSON data
    print("Loading imessage_data.json...")
    with open('imessage_data.json', 'r') as f:
        data = json.load(f)
    
    if not data.get('contacts'):
        print("No contacts found in data")
        return
    
    print(f"Found {len(data['contacts'])} contacts to process")
    
    # Find contacts database
    db_path = find_contacts_database()
    
    # Collect all phone numbers that need resolution
    phones_to_resolve = {}
    for contact in data['contacts']:
        phone = contact.get('phone', '')
        name = contact.get('name', '')
        
        # Skip if already has a proper name (not just a phone number or chat ID)
        if name and not name.startswith('+') and not name.startswith('chat') and '@' not in name:
            continue
        
        # Skip group chats
        if phone.startswith('chat'):
            continue
        
        phones_to_resolve[phone] = contact
    
    print(f"Need to resolve {len(phones_to_resolve)} phone numbers")
    
    # Try database resolution first
    resolved_names = {}
    if db_path:
        print("Attempting database resolution...")
        resolved_names = resolve_contacts_from_database(db_path, list(phones_to_resolve.keys()))
        print(f"Resolved {len(resolved_names)} contacts from database")
    
    # For any unresolved, try AppleScript
    unresolved = [p for p in phones_to_resolve if p not in resolved_names]
    if unresolved:
        print(f"Attempting AppleScript resolution for {len(unresolved)} remaining contacts...")
        for i, phone in enumerate(unresolved):
            if i % 10 == 0:
                print(f"  Processing {i}/{len(unresolved)}...")
            
            name = resolve_contact_via_applescript(phone)
            if name:
                resolved_names[phone] = name
    
    # Save resolved names to persistent mappings
    if resolved_names:
        print(f"\n📇 Saving {len(resolved_names)} resolved names to persistent mappings...")
        mappings = load_mappings()

        # Add normalized variants for each resolved name
        for phone, name in resolved_names.items():
            mappings["phone_to_name"][phone] = name
            # Also store normalized versions
            cleaned = clean_phone_number(phone)
            if cleaned:
                mappings["phone_to_name"][cleaned] = name
                mappings["phone_to_name"][f"+{cleaned}"] = name
                if len(cleaned) >= 10:
                    mappings["phone_to_name"][cleaned[-10:]] = name

        save_mappings(mappings)

    # Update the contacts in current JSON
    updated_count = 0
    for contact in data['contacts']:
        phone = contact.get('phone', '')
        if phone in resolved_names:
            old_name = contact.get('name', '')
            new_name = resolved_names[phone]
            if old_name != new_name:
                print(f"  {old_name} -> {new_name}")
                contact['name'] = new_name
                updated_count += 1

    print(f"\nUpdated {updated_count} contact names in JSON")

    # Save the updated data
    if updated_count > 0:
        # Backup original
        print("Creating backup...")
        with open('imessage_data_backup.json', 'w') as f:
            with open('imessage_data.json', 'r') as original:
                f.write(original.read())

        # Save updated data
        print("Saving updated data...")
        with open('imessage_data.json', 'w') as f:
            json.dump(data, f, indent=2)

        print("Done! Refresh your browser to see the updated contact names.")
        print("💾 Mappings saved - these will persist across future extractions!")
    else:
        print("No contacts were updated.")
    
    # Show summary of remaining unresolved contacts
    still_unresolved = []
    for contact in data['contacts']:
        name = contact.get('name', '')
        if name.startswith('+') or '@' in name:
            still_unresolved.append(name)
    
    if still_unresolved:
        print(f"\nStill unresolved ({len(still_unresolved)} contacts):")
        for name in still_unresolved[:10]:
            print(f"  {name}")
        if len(still_unresolved) > 10:
            print(f"  ... and {len(still_unresolved) - 10} more")

if __name__ == "__main__":
    print("iMessage Contact Name Resolver")
    print("==============================")
    print("This script will update contact names in your imessage_data.json")
    print("by looking them up in your macOS Contacts app.")
    print()
    
    # Check for required permissions
    print("Note: This script requires access to your Contacts.")
    print("You may be prompted to grant permission.")
    print()
    
    update_contact_names()