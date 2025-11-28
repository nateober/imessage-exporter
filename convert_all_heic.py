#!/usr/bin/env python3
"""
Convert all HEIC images to JPEG and update JSON paths
"""

import json
import os
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import time

def convert_heic_file(args):
    """Convert a single HEIC file to JPEG"""
    heic_path, jpeg_path = args

    try:
        # Use macOS sips command for conversion
        result = subprocess.run(
            ['sips', '-s', 'format', 'jpeg', str(heic_path), '--out', str(jpeg_path)],
            capture_output=True,
            timeout=10
        )
        return result.returncode == 0
    except:
        return False

def convert_all_heic():
    """Convert all HEIC files to web-compatible JPEG"""

    print("🔄 Converting all HEIC files to JPEG for web compatibility...")

    # Create web-ready directory
    web_dir = Path('web_ready_images')
    web_dir.mkdir(exist_ok=True)

    # Load current data
    with open('imessage_data.json', 'r') as f:
        data = json.load(f)

    # Find all HEIC files
    heic_images = []
    other_images = []

    for img in data['images']:
        # Handle both 'url' and 'path' field names for compatibility
        url = img.get('url') or img.get('path') or img.get('filename', '')
        if url.lower().endswith(('.heic', '.heif')):
            heic_images.append(img)
        else:
            other_images.append(img)

    print(f"Found {len(heic_images)} HEIC files to convert")
    print(f"Found {len(other_images)} already compatible files")

    # Prepare conversion tasks
    conversion_tasks = []
    updated_images = []

    for img in heic_images:
        current_path = img.get('url') or img.get('path') or img.get('filename', '')
        # Expand home directory if needed
        current_path = os.path.expanduser(current_path)
        if os.path.exists(current_path):
            # Create JPEG filename
            original_name = Path(current_path).stem
            jpeg_name = f"{original_name}.jpg"
            jpeg_path = web_dir / jpeg_name

            # Add to conversion queue if not already exists
            if not jpeg_path.exists():
                conversion_tasks.append((current_path, jpeg_path))

            # Update image data to point to JPEG
            img_copy = img.copy()
            img_copy['url'] = f"web_ready_images/{jpeg_name}"
            img_copy['mimeType'] = 'image/jpeg'
            updated_images.append(img_copy)
        else:
            # File doesn't exist, skip
            print(f"⚠️  File not found: {current_path}")

    # Convert HEIC files in parallel
    if conversion_tasks:
        print(f"Converting {len(conversion_tasks)} HEIC files...")

        converted = 0
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(convert_heic_file, conversion_tasks))
            converted = sum(results)

        print(f"✅ Successfully converted {converted}/{len(conversion_tasks)} files")

    # Copy other compatible files to web directory
    print("📁 Copying other image files...")
    copied = 0

    for img in other_images:
        current_path = img.get('url') or img.get('path') or img.get('filename', '')
        # Expand home directory if needed
        current_path = os.path.expanduser(current_path)
        if os.path.exists(current_path):
            filename = Path(current_path).name
            dest_path = web_dir / filename

            if not dest_path.exists():
                try:
                    import shutil
                    shutil.copy2(current_path, dest_path)
                    copied += 1
                except:
                    pass

            # Update path to web directory
            img_copy = img.copy()
            img_copy['url'] = f"web_ready_images/{filename}"
            updated_images.append(img_copy)
        else:
            print(f"⚠️  File not found: {current_path}")

    print(f"✅ Copied {copied} other image files")

    # Update JSON with new paths
    data['images'] = updated_images

    # Save updated data
    with open('imessage_data.json', 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Final verification
    web_compatible = 0
    for img in data['images']:
        url = img.get('url', '')
        if url.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')) and os.path.exists(url):
            web_compatible += 1

    print(f"\n🎉 Conversion complete!")
    print(f"📊 Summary:")
    print(f"  • Total images: {len(data['images'])}")
    print(f"  • Web-compatible: {web_compatible}")
    print(f"  • Success rate: {web_compatible/len(data['images'])*100:.1f}%")
    print(f"  • Files saved to: web_ready_images/")

    return web_compatible

if __name__ == "__main__":
    start_time = time.time()
    result = convert_all_heic()
    duration = time.time() - start_time

    print(f"\n⏱️  Completed in {duration:.1f} seconds")
    print("🌐 Refresh your browser to see all images!")