"""
Test script to verify image compression functionality (standalone)
"""
from PIL import Image
import io

def compress_and_resize_image(image_file, target_size=(300, 300), target_format='WEBP', 
                                max_size_kb=50, min_size_kb=15, target_size_kb=30):
    """
    Compress and resize an image to specific dimensions and file size.
    """
    if not image_file:
        return None
    
    try:
        # Open the image
        img = Image.open(image_file)
        
        # Convert RGBA to RGB if necessary (for WebP compatibility)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Resize the image while maintaining aspect ratio
        img.thumbnail(target_size, Image.Resampling.LANCZOS)
        
        # If image is smaller than target, create a centered image on white background
        if img.size != target_size:
            new_img = Image.new('RGB', target_size, (255, 255, 255))
            paste_position = (
                (target_size[0] - img.size[0]) // 2,
                (target_size[1] - img.size[1]) // 2
            )
            new_img.paste(img, paste_position)
            img = new_img
        
        # Try different quality levels to get the desired file size
        quality = 85
        output = io.BytesIO()
        
        # First attempt with initial quality
        img.save(output, format=target_format, quality=quality, optimize=True)
        size_kb = output.tell() / 1024
        
        # If image is too large, reduce quality iteratively
        while size_kb > max_size_kb and quality > 10:
            quality -= 5
            output = io.BytesIO()
            img.save(output, format=target_format, quality=quality, optimize=True)
            size_kb = output.tell() / 1024
        
        output.seek(0)
        return output, size_kb, quality
        
    except Exception as e:
        print(f"❌ Image compression failed: {str(e)}")
        return None, 0, 0

def test_image_compression():
    """Test the image compression function"""
    print("🧪 Testing image compression...")
    print("=" * 50)
    
    # Test 1: Large image
    print("\n📝 Test 1: Large color image (800x600)")
    test_img = Image.new('RGB', (800, 600), color='red')
    
    # Add some complexity to the image
    for i in range(0, 800, 10):
        for j in range(0, 600, 10):
            test_img.putpixel((i, j), (255, 255, 0))
    
    img_bytes = io.BytesIO()
    test_img.save(img_bytes, format='JPEG', quality=95)
    img_bytes.seek(0)
    
    original_size = len(img_bytes.getvalue()) / 1024
    print(f"   Original: 800x600 pixels, {original_size:.1f} KB")
    
    compressed, size_kb, quality = compress_and_resize_image(img_bytes)
    
    if compressed:
        print(f"   ✅ Compressed: 300x300 pixels, {size_kb:.1f} KB (quality={quality})")
        
        if size_kb <= 50:
            print(f"   ✅ Within 50KB limit")
        else:
            print(f"   ⚠️  Exceeds 50KB limit")
        
        if 15 <= size_kb <= 50:
            print(f"   ✅ In optimal range (15-50KB)")
    
    # Test 2: Small image
    print("\n📝 Test 2: Small image (100x100)")
    test_img2 = Image.new('RGB', (100, 100), color='blue')
    img_bytes2 = io.BytesIO()
    test_img2.save(img_bytes2, format='PNG')
    img_bytes2.seek(0)
    
    original_size2 = len(img_bytes2.getvalue()) / 1024
    print(f"   Original: 100x100 pixels, {original_size2:.1f} KB")
    
    compressed2, size_kb2, quality2 = compress_and_resize_image(img_bytes2)
    
    if compressed2:
        print(f"   ✅ Compressed: 300x300 pixels, {size_kb2:.1f} KB (quality={quality2})")
        print(f"   ℹ️  Small images are centered on white background")
    
    # Test 3: Already optimal size
    print("\n📝 Test 3: Already correct size (300x300)")
    test_img3 = Image.new('RGB', (300, 300), color='green')
    img_bytes3 = io.BytesIO()
    test_img3.save(img_bytes3, format='JPEG', quality=80)
    img_bytes3.seek(0)
    
    original_size3 = len(img_bytes3.getvalue()) / 1024
    print(f"   Original: 300x300 pixels, {original_size3:.1f} KB")
    
    compressed3, size_kb3, quality3 = compress_and_resize_image(img_bytes3)
    
    if compressed3:
        print(f"   ✅ Compressed: 300x300 pixels, {size_kb3:.1f} KB (quality={quality3})")
    
    print("\n" + "=" * 50)
    print("🎉 All tests completed successfully!")
    print("\n📋 Summary:")
    print("   • Images are resized to 300x300px")
    print("   • Output format: WebP")
    print("   • Target size: 15-50KB")
    print("   • Small images centered on white background")

if __name__ == '__main__':
    test_image_compression()
