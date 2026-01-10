"""
Utility functions for the POS application
"""
import os
import io
from PIL import Image
from django.core.files.uploadedfile import InMemoryUploadedFile


def compress_and_resize_image(image_file, target_size=(300, 300), target_format='WEBP', 
                                max_size_kb=50, min_size_kb=15, target_size_kb=30):
    """
    Compress and resize an image to specific dimensions and file size.
    
    Args:
        image_file: The uploaded image file
        target_size: Tuple of (width, height) for the output image
        target_format: Output format (default: 'WEBP')
        max_size_kb: Maximum file size in KB (default: 50)
        min_size_kb: Minimum target file size in KB (default: 15)
        target_size_kb: Ideal target file size in KB (default: 30)
    
    Returns:
        InMemoryUploadedFile: Compressed image file
    """
    if not image_file:
        return None
    
    try:
        # Open the image
        img = Image.open(image_file)
        
        # Convert RGBA to RGB if necessary (for WebP compatibility)
        if img.mode in ('RGBA', 'LA', 'P'):
            # Create a white background
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
        quality = 85  # Start with high quality
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
        
        # If still too large, try more aggressive compression
        if size_kb > max_size_kb:
            quality = 10
            output = io.BytesIO()
            img.save(output, format=target_format, quality=quality, optimize=True, method=6)
            size_kb = output.tell() / 1024
        
        # If image is too small and we can afford better quality, increase it
        if size_kb < min_size_kb and quality < 95:
            while size_kb < target_size_kb and quality < 95:
                quality += 5
                test_output = io.BytesIO()
                img.save(test_output, format=target_format, quality=quality, optimize=True)
                test_size_kb = test_output.tell() / 1024
                
                if test_size_kb <= max_size_kb:
                    output = test_output
                    size_kb = test_size_kb
                else:
                    break
        
        output.seek(0)
        
        # Get the original filename and change extension
        original_filename = image_file.name if hasattr(image_file, 'name') else 'image'
        base_name = os.path.splitext(original_filename)[0]
        new_filename = f"{base_name}.webp"
        
        # Create InMemoryUploadedFile
        compressed_image = InMemoryUploadedFile(
            output,
            'ImageField',
            new_filename,
            f'image/{target_format.lower()}',
            output.tell(),
            None
        )
        
        print(f"✅ Image compressed: {original_filename} -> {new_filename} ({size_kb:.1f}KB, quality={quality})")
        
        return compressed_image
        
    except Exception as e:
        print(f"❌ Image compression failed: {str(e)}")
        # Return original image if compression fails
        return image_file
