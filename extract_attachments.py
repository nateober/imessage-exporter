#!/usr/bin/env python3
"""
Extract and process iMessage attachments/media
Copies files, converts HEIC to JPEG, and updates JSON
"""

import os
import sqlite3
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

def find_chat_db():
    """Find iMessage chat database"""
    chat_db = Path.home() / "Library/Messages/chat.db"
    if chat_db.exists():
        return str(chat_db)
    return None

def clean_phone_number(phone):
    """Clean and normalize phone number for matching"""
    if not phone:
        return ""
    import re
    cleaned = re.sub(r'\D', '', str(phone))
    if len(cleaned) == 10:
        cleaned = '1' + cleaned
    elif len(cleaned) == 11 and cleaned.startswith('1'):
        pass
    return f"+{cleaned}" if cleaned else phone

def extract_attachments(limit=500):
    """Extract attachments from iMessage database"""

    db_path = find_chat_db()
    if not db_path:
        print("❌ No iMessage database found")
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print(f"📎 Extracting up to {limit} recent attachments...")

    # Query for attachments with contact info
    query = """
    SELECT DISTINCT
        a.filename,
        a.mime_type,
        a.transfer_name,
        datetime(m.date/1000000000 + 978307200, 'unixepoch') as message_date,
        m.is_from_me,
        COALESCE(h.id, c.chat_identifier) as contact_identifier,
        c.display_name as chat_display_name
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

    print(f"Found {len(results)} image attachments")

    attachments = []
    for row in results:
        filename, mime_type, transfer_name, date, is_from_me, contact_id, display_name = row

        # Resolve contact name
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
            'contactName': contact_name
        })

    conn.close()
    return attachments

def copy_attachments(attachments, output_dir="imessage_attachments"):
    """Copy attachment files to local directory"""

    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    copied_files = []
    skipped = 0
    errors = 0

    print(f"\n📁 Copying files to {output_dir}/...")

    for i, att in enumerate(attachments):
        if i % 50 == 0 and i > 0:
            print(f"  Progress: {i}/{len(attachments)}")

        source = att['filename']
        if not source:
            skipped += 1
            continue

        # Expand home directory path
        source = os.path.expanduser(source)

        if not os.path.exists(source):
            skipped += 1
            continue

        # Use transfer name or extract from path
        if att['transferName']:
            dest_name = att['transferName']
        else:
            dest_name = os.path.basename(source)

        # Ensure unique filename
        dest_path = output_path / dest_name
        counter = 1
        while dest_path.exists():
            name_parts = dest_name.rsplit('.', 1)
            if len(name_parts) == 2:
                dest_name = f"{name_parts[0]}_{counter}.{name_parts[1]}"
            else:
                dest_name = f"{dest_name}_{counter}"
            dest_path = output_path / dest_name
            counter += 1

        try:
            shutil.copy2(source, dest_path)
            # Note: spread att first, then override filename with the actual destination name
            copied_files.append({
                **att,
                'original': source,
                'copied': str(dest_path),
                'filename': dest_name,  # Override att['filename'] with actual destination name
            })
        except Exception as e:
            errors += 1

    print(f"✅ Copied {len(copied_files)} files")
    if skipped:
        print(f"⚠️  Skipped {skipped} (file not found)")
    if errors:
        print(f"❌ Errors: {errors}")

    return copied_files

def convert_heic_images(copied_files, output_dir="web_ready_images"):
    """Convert HEIC images to JPEG and copy all images to web_ready_images"""

    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    heic_files = [f for f in copied_files if f['filename'].lower().endswith(('.heic', '.heif'))]
    other_images = [f for f in copied_files if not f['filename'].lower().endswith(('.heic', '.heif'))]

    print(f"\n🖼️  Processing images for web...")
    print(f"   HEIC files to convert: {len(heic_files)}")
    print(f"   Other images to copy: {len(other_images)}")

    # Convert HEIC files
    converted = 0
    for i, file_info in enumerate(heic_files):
        if i % 20 == 0 and i > 0:
            print(f"  Converting HEIC: {i}/{len(heic_files)}")

        source = file_info['copied']
        jpeg_name = file_info['filename'].rsplit('.', 1)[0] + '.jpg'
        dest_path = output_path / jpeg_name

        if dest_path.exists():
            file_info['webPath'] = f"web_ready_images/{jpeg_name}"
            converted += 1
            continue

        try:
            # Use macOS sips command
            result = subprocess.run(
                ['sips', '-s', 'format', 'jpeg', source, '--out', str(dest_path)],
                capture_output=True,
                timeout=10
            )
            if result.returncode == 0:
                file_info['webPath'] = f"web_ready_images/{jpeg_name}"
                converted += 1
        except:
            pass

    # Copy non-HEIC images to web_ready_images
    copied = 0
    for file_info in other_images:
        source = Path(file_info['copied'])
        dest_path = output_path / file_info['filename']

        if not dest_path.exists():
            try:
                shutil.copy2(source, dest_path)
                copied += 1
            except:
                pass
        else:
            copied += 1

        file_info['webPath'] = f"web_ready_images/{file_info['filename']}"

    print(f"✅ Converted {converted} HEIC images to JPEG")
    print(f"✅ Copied {copied} other images")

    return copied_files

def update_json_with_images(image_files, json_file="imessage_data.json"):
    """Update the main JSON file with image references"""

    print(f"\n📝 Updating {json_file} with image data...")

    # Load existing data
    with open(json_file, 'r') as f:
        data = json.load(f)

    # Prepare image data for JSON
    images = []
    for img in image_files:
        # Use web-accessible path - prefer webPath, then construct from filename
        if 'webPath' in img:
            url = img['webPath']
        elif img['filename'].lower().endswith(('.heic', '.heif')):
            # HEIC files should be converted to jpg
            jpeg_name = img['filename'].rsplit('.', 1)[0] + '.jpg'
            url = f"web_ready_images/{jpeg_name}"
        else:
            url = f"web_ready_images/{img['filename']}"

        images.append({
            'url': url,  # Changed from 'path' to 'url' for index.html compatibility
            'filename': img['filename'],
            'date': img['date'],
            'contactName': img['contactName'],
            'isFromMe': img['isFromMe'],
            'mimeType': img.get('mimeType', 'image/jpeg')
        })

    # Update data
    data['images'] = images

    # Update statistics
    if 'statistics' in data:
        data['statistics']['totalImages'] = len(images)

    # Save updated data
    with open(json_file, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✅ Added {len(images)} images to JSON")

    return len(images)

def main():
    """Main execution"""
    print("=" * 60)
    print("🎨 iMessage Media Extraction Tool")
    print("=" * 60)

    # Step 1: Extract attachment metadata from database
    attachments = extract_attachments(limit=500)

    if not attachments:
        print("No attachments found")
        return 1

    # Step 2: Copy files locally
    copied_files = copy_attachments(attachments)

    # Step 3: Convert HEIC images
    processed_files = convert_heic_images(copied_files)

    # Step 4: Update JSON
    image_count = update_json_with_images(processed_files)

    # Summary
    print("\n" + "=" * 60)
    print("✨ Media Extraction Complete!")
    print("=" * 60)
    print(f"📸 {image_count} images added to dashboard")
    print(f"📁 Files saved to:")
    print(f"   - imessage_attachments/ (original files)")
    print(f"   - extracted_images/ (web-ready images)")
    print(f"\n🌐 Refresh your browser to see the images!")

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())