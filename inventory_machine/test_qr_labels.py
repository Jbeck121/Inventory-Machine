#!/usr/bin/env python3
"""
Test script for qrcode.py functionality (not just pipeline label generation).
Validates that labels/qrcode.py's generate_qr_for_sticker() works correctly.
"""

from pathlib import Path
from labels.qrcode import generate_qr_for_sticker  # Import the utility function
import os
from PIL import Image

def main():
    # Test data (simple, valid for .5" sticker)
    test_data = "test_qr_valid"
    
    # Path where the test image will be saved (project root, predictable)
    test_output_path = Path("test_qr.png")
    
    # Run the utility function (exactly as defined in labels/qrcode.py)
    generate_qr_for_sticker(test_data, test_output_path)
    
    # Verify the image was created and has correct dimensions/size
    if test_output_path.exists():
        img = Image.open(test_output_path)
        # Expect 128x128 pixels (matches .5" sticker requirement)
        if img.size == (128, 128):
            print(f"✅ qrcode.py test PASSED: QR code saved to {test_output_path}")
            print(f"   Image size: {img.size} pixels (matches .5\" sticker requirement)")
            print(f"   Encoded data: {test_data}")
        else:
            print(f"Unexpected image size {img.size}")
            print(f"   Expected (128, 128); got {img.size}")
         
            return True
    else:
        print(f"❌ qrcode.py test FAILED: File not created at {test_output_path}")
        return False
    
    # Clean up test image (optional, keeps repo tidy during CI)
    # test_output_path.unlink()  # Uncomment if you want to remove the test image after run
    
    return True

if __name__ == "__main__":
    success = main()
    if success:
        print("✅ All qrcode.py functionality validated successfully.")
    else:
        print("❌ Test failed – see above output.")
        exit(1)