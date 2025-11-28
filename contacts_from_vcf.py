#!/usr/bin/env python3
"""
Extract contacts from various export formats and update iMessage data.
Now saves to persistent contact_mappings.json for reuse across extractions.
"""

import json
import re
import os
import glob

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

def clean_phone_number(phone):
    """Clean and normalize phone number for matching"""
    if not phone:
        return ""
    
    # Remove all non-digit characters
    cleaned = re.sub(r'\D', '', str(phone))
    
    # Handle different lengths
    if len(cleaned) == 10:  # US number without country code
        cleaned = '1' + cleaned
    elif len(cleaned) == 11 and cleaned.startswith('1'):  # US number with country code
        pass  # Already in correct format
    
    return cleaned

def export_contacts_to_vcf():
    """Create instructions for exporting contacts to VCF format"""
    
    print("CONTACT EXPORT INSTRUCTIONS")
    print("===========================")
    print()
    print("The AddressBook database export appears to be incomplete.")
    print("Let's try a different approach:")
    print()
    print("METHOD 1: Export as VCF")
    print("1. Open the Contacts app")
    print("2. Select all contacts (Cmd+A)")
    print("3. File > Export > Export vCard...")
    print("4. Save as 'contacts.vcf' in this folder")
    print("5. Run: python3 contacts_from_vcf.py --vcf")
    print()
    print("METHOD 2: Export as CSV (if available)")
    print("1. Open Contacts app")
    print("2. Try File > Export > Export as CSV...")
    print("3. Save as 'contacts.csv' in this folder")
    print("4. Run: python3 contacts_from_vcf.py --csv")
    print()
    print("METHOD 3: Manual entry (for important contacts)")
    print("Run: python3 contacts_from_vcf.py --manual")

def parse_vcf_file():
    """Parse VCF file and extract contacts"""
    
    vcf_files = glob.glob("*.vcf") + glob.glob("contacts.*")
    
    if not vcf_files:
        print("No VCF files found. Please export your contacts as described above.")
        return {}
    
    vcf_file = vcf_files[0]
    print(f"Reading contacts from: {vcf_file}")
    
    contacts_map = {}
    
    try:
        with open(vcf_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Split into individual contact cards
        cards = content.split('BEGIN:VCARD')
        
        for card in cards[1:]:  # Skip the first empty split
            if 'END:VCARD' not in card:
                continue
                
            name = ""
            phones = []
            
            lines = card.split('\n')
            for line in lines:
                line = line.strip()
                
                # Extract name
                if line.startswith('FN:'):
                    name = line[3:].strip()
                elif line.startswith('N:'):
                    # Format: N:Last;First;Middle;Prefix;Suffix
                    parts = line[2:].split(';')
                    if len(parts) >= 2:
                        last = parts[0].strip()
                        first = parts[1].strip()
                        if first and last:
                            name = f"{first} {last}"
                        elif first:
                            name = first
                        elif last:
                            name = last
                
                # Extract phone numbers
                if line.startswith('TEL'):
                    # Extract phone number from various formats
                    if ':' in line:
                        phone = line.split(':', 1)[1].strip()
                        phones.append(phone)
            
            # Store mappings
            if name and phones:
                for phone in phones:
                    cleaned = clean_phone_number(phone)
                    original = phone.strip()
                    
                    # Store multiple formats
                    phone_variants = [
                        original,
                        cleaned,
                        f"+{cleaned}",
                        f"+1{cleaned[-10:]}" if len(cleaned) >= 10 else None,
                    ]
                    
                    for variant in phone_variants:
                        if variant:
                            contacts_map[variant] = name
                    
                    print(f"  {name}: {original}")
        
        print(f"\nExtracted {len(contacts_map)} phone-to-name mappings")
        
    except Exception as e:
        print(f"Error reading VCF file: {e}")
    
    return contacts_map

def parse_csv_file():
    """Parse CSV file and extract contacts"""
    
    csv_files = glob.glob("*.csv") + glob.glob("contacts.*")
    csv_files = [f for f in csv_files if f.endswith('.csv')]
    
    if not csv_files:
        print("No CSV files found.")
        return {}
    
    csv_file = csv_files[0]
    print(f"Reading contacts from: {csv_file}")
    
    contacts_map = {}
    
    try:
        import csv
        
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # Try to find name columns
                name = ""
                phones = []
                
                # Common name column variations
                name_fields = ['Name', 'Full Name', 'First Name', 'Given Name', 'Display Name']
                for field in name_fields:
                    if field in row and row[field]:
                        name = row[field].strip()
                        break
                
                # If no single name field, try combining first and last
                if not name:
                    first = row.get('First Name', '') or row.get('Given Name', '')
                    last = row.get('Last Name', '') or row.get('Family Name', '')
                    if first and last:
                        name = f"{first.strip()} {last.strip()}"
                    elif first:
                        name = first.strip()
                    elif last:
                        name = last.strip()
                
                # Find phone columns
                phone_fields = [k for k in row.keys() if 'phone' in k.lower() or 'mobile' in k.lower() or 'cell' in k.lower()]
                for field in phone_fields:
                    if row[field]:
                        phones.append(row[field].strip())
                
                # Store mappings
                if name and phones:
                    for phone in phones:
                        cleaned = clean_phone_number(phone)
                        original = phone.strip()
                        
                        phone_variants = [
                            original,
                            cleaned,
                            f"+{cleaned}",
                            f"+1{cleaned[-10:]}" if len(cleaned) >= 10 else None,
                        ]
                        
                        for variant in phone_variants:
                            if variant:
                                contacts_map[variant] = name
                        
                        print(f"  {name}: {original}")
        
        print(f"\nExtracted {len(contacts_map)} phone-to-name mappings")
        
    except Exception as e:
        print(f"Error reading CSV file: {e}")
    
    return contacts_map

def manual_entry():
    """Manual entry of important contacts"""
    
    print("Manual Contact Entry")
    print("===================")
    print("Enter contact names for your most important phone numbers.")
    print("Press Enter without typing anything to finish.")
    print()
    
    # Load current data to show what needs updating
    with open('imessage_data.json', 'r') as f:
        data = json.load(f)
    
    # Find contacts that need names
    unresolved = []
    for contact in data.get('contacts', []):
        phone = contact.get('phone', '')
        name = contact.get('name', '')
        
        # Skip if already has a proper name
        if name and not name.startswith('+') and not name.startswith('chat') and '@' not in name:
            continue
        
        # Skip group chats
        if phone.startswith('chat') or phone.startswith('urn:'):
            continue
        
        message_count = contact.get('messageCount', 0)
        unresolved.append((phone, message_count))
    
    # Sort by message count (most active first)
    unresolved.sort(key=lambda x: x[1], reverse=True)
    
    contacts_map = {}
    
    print(f"Found {len(unresolved)} contacts that need names.")
    print("Starting with most active contacts:\n")
    
    for phone, msg_count in unresolved:
        # Format phone for display
        display = phone
        if phone.startswith('+1') and len(phone) == 12:
            cleaned = phone[2:]
            display = f"({cleaned[:3]}) {cleaned[3:6]}-{cleaned[6:]}"
        
        name = input(f"{display} ({msg_count} messages): ").strip()
        if not name:
            break
        
        contacts_map[phone] = name
    
    return contacts_map

def update_contacts_with_mapping(contacts_map):
    """Update the JSON data with the contact mapping and save to persistent mappings"""

    if not contacts_map:
        print("No contact mappings to apply.")
        return

    # First, save to persistent mappings file
    print(f"\n📇 Saving {len(contacts_map)} mappings to persistent file...")
    mappings = load_mappings()
    mappings["phone_to_name"].update(contacts_map)
    save_mappings(mappings)

    # Load the JSON data
    with open('imessage_data.json', 'r') as f:
        data = json.load(f)

    updated_count = 0

    for contact in data['contacts']:
        phone = contact.get('phone', '')
        current_name = contact.get('name', '')

        # Skip if already has a proper name
        if current_name and not current_name.startswith('+') and not current_name.startswith('chat') and '@' not in current_name:
            continue

        # Try to find a match
        new_name = None

        if phone in contacts_map:
            new_name = contacts_map[phone]
        else:
            # Try partial matching
            cleaned = clean_phone_number(phone)
            test_variants = [
                cleaned,
                f"+{cleaned}",
                f"+1{cleaned[-10:]}" if len(cleaned) >= 10 else None,
                cleaned[-10:] if len(cleaned) >= 10 else None,
            ]

            for variant in test_variants:
                if variant and variant in contacts_map:
                    new_name = contacts_map[variant]
                    break

        if new_name:
            print(f"  {current_name} -> {new_name}")
            contact['name'] = new_name
            updated_count += 1

    if updated_count > 0:
        # Backup and save
        with open('imessage_data_before_contact_update.json', 'w') as f:
            with open('imessage_data.json', 'r') as original:
                f.write(original.read())

        with open('imessage_data.json', 'w') as f:
            json.dump(data, f, indent=2)

        print(f"\nUpdated {updated_count} contacts in JSON!")
        print("Backup saved to imessage_data_before_contact_update.json")
        print("💾 Mappings saved - these will persist across future extractions!")
        print("Refresh your browser to see the changes.")
    else:
        print("\nNo contacts were updated in JSON, but mappings were saved for future use.")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--vcf':
            contacts_map = parse_vcf_file()
            update_contacts_with_mapping(contacts_map)
        elif sys.argv[1] == '--csv':
            contacts_map = parse_csv_file()
            update_contacts_with_mapping(contacts_map)
        elif sys.argv[1] == '--manual':
            contacts_map = manual_entry()
            update_contacts_with_mapping(contacts_map)
        else:
            export_contacts_to_vcf()
    else:
        export_contacts_to_vcf()