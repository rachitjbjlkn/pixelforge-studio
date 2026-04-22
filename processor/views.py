import os
import uuid
import json
from io import BytesIO
from pathlib import Path

from django.shortcuts import render
from django.http import JsonResponse, FileResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import PIL.Image


def index(request):
    return render(request, 'processor/index.html')


@csrf_exempt
def process_image(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    uploaded = request.FILES.get('image')
    if not uploaded:
        return JsonResponse({'error': 'No image uploaded'}, status=400)

    try:
        img = Image.open(uploaded)
        original_format = img.format or 'PNG'
        original_mode = img.mode
        orig_w, orig_h = img.size

        # Convert to RGBA for processing
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

        ops = request.POST

        # ── 1. RESIZE / WIDTH / HEIGHT ───────────────────────────────────────
        new_w = int(ops.get('width', orig_w) or orig_w)
        new_h = int(ops.get('height', orig_h) or orig_h)
        maintain_aspect = ops.get('maintain_aspect', 'false') == 'true'

        if maintain_aspect and (new_w != orig_w or new_h != orig_h):
            img.thumbnail((new_w, new_h), Image.LANCZOS)
        elif new_w != orig_w or new_h != orig_h:
            img = img.resize((new_w, new_h), Image.LANCZOS)

        # ── 2. ROTATION ────────────────────────────────────────────────────────
        rotation = int(ops.get('rotation', 0) or 0)
        if rotation:
            img = img.rotate(-rotation, expand=True)

        # ── 3. FLIP ───────────────────────────────────────────────────────────
        flip_h = ops.get('flip_horizontal', 'false') == 'true'
        flip_v = ops.get('flip_vertical', 'false') == 'true'
        if flip_h:
            img = ImageOps.mirror(img)
        if flip_v:
            img = ImageOps.flip(img)

        # ── 4. COLOR ADJUSTMENTS ──────────────────────────────────────────────
        brightness = float(ops.get('brightness', 1.0) or 1.0)
        contrast = float(ops.get('contrast', 1.0) or 1.0)
        saturation = float(ops.get('saturation', 1.0) or 1.0)
        sharpness = float(ops.get('sharpness', 1.0) or 1.0)

        if brightness != 1.0:
            img = ImageEnhance.Brightness(img).enhance(brightness)
        if contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(contrast)
        if saturation != 1.0:
            img = ImageEnhance.Color(img).enhance(saturation)
        if sharpness != 1.0:
            img = ImageEnhance.Sharpness(img).enhance(sharpness)

        # ── 5. COLOR FILTERS ──────────────────────────────────────────────────
        color_filter = ops.get('color_filter', 'none')
        if color_filter == 'grayscale':
            img = ImageOps.grayscale(img).convert('RGB')
        elif color_filter == 'sepia':
            gray = ImageOps.grayscale(img)
            sepia = Image.new('RGB', gray.size)
            px = gray.load()
            sp = sepia.load()
            for y in range(gray.height):
                for x in range(gray.width):
                    v = px[x, y]
                    sp[x, y] = (
                        min(255, int(v * 1.08)),
                        min(255, int(v * 0.85)),
                        min(255, int(v * 0.66)),
                    )
            img = sepia
        elif color_filter == 'invert':
            if img.mode == 'RGBA':
                r, g, b, a = img.split()
                rgb = Image.merge('RGB', (r, g, b))
                rgb = ImageOps.invert(rgb)
                r, g, b = rgb.split()
                img = Image.merge('RGBA', (r, g, b, a))
            else:
                img = ImageOps.invert(img)
        elif color_filter == 'red_channel':
            r, g, b = img.convert('RGB').split()
            img = Image.merge('RGB', (r, Image.new('L', r.size, 0), Image.new('L', r.size, 0)))
        elif color_filter == 'green_channel':
            r, g, b = img.convert('RGB').split()
            img = Image.merge('RGB', (Image.new('L', g.size, 0), g, Image.new('L', g.size, 0)))
        elif color_filter == 'blue_channel':
            r, g, b = img.convert('RGB').split()
            img = Image.merge('RGB', (Image.new('L', b.size, 0), Image.new('L', b.size, 0), b))
        elif color_filter == 'cool':
            r, g, b = img.convert('RGB').split()
            r = r.point(lambda i: max(0, i - 30))
            b = b.point(lambda i: min(255, i + 30))
            img = Image.merge('RGB', (r, g, b))
        elif color_filter == 'warm':
            r, g, b = img.convert('RGB').split()
            r = r.point(lambda i: min(255, i + 30))
            b = b.point(lambda i: max(0, i - 30))
            img = Image.merge('RGB', (r, g, b))

        # ── 6. PIXEL EFFECTS ──────────────────────────────────────────────────
        pixelate = int(ops.get('pixelate', 0) or 0)
        if pixelate > 1:
            small = img.resize(
                (max(1, img.width // pixelate), max(1, img.height // pixelate)),
                Image.BOX
            )
            img = small.resize(img.size, Image.NEAREST)

        # ── 7. BLUR / SHARPEN ─────────────────────────────────────────────────
        blur_radius = float(ops.get('blur', 0) or 0)
        if blur_radius > 0:
            img = img.filter(ImageFilter.GaussianBlur(blur_radius))

        edge_enhance = ops.get('edge_enhance', 'false') == 'true'
        if edge_enhance:
            img = img.filter(ImageFilter.EDGE_ENHANCE_MORE)

        emboss = ops.get('emboss', 'false') == 'true'
        if emboss:
            img = img.filter(ImageFilter.EMBOSS)

        # ── 8. OUTPUT FORMAT & QUALITY ────────────────────────────────────────
        out_format = ops.get('format', 'JPEG').upper()
        if out_format not in ('JPEG', 'PNG', 'WEBP', 'BMP', 'GIF'):
            out_format = 'JPEG'

        quality = int(ops.get('quality', 85) or 85)
        quality = max(1, min(100, quality))

        # ── DPI / RESOLUTION ─────────────────────────────────────────────────
        dpi_val = int(ops.get('dpi', 72) or 72)

        # Fix mode for JPEG
        if out_format == 'JPEG' and img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # Save to memory (no disk needed)
        import base64
        buffer = BytesIO()

        save_kwargs = {'dpi': (dpi_val, dpi_val)}
        if out_format in ('JPEG', 'WEBP'):
            save_kwargs['quality'] = quality
            save_kwargs['optimize'] = True
        elif out_format == 'PNG':
            save_kwargs['optimize'] = True

        img.save(buffer, format=out_format, **save_kwargs)
        buffer.seek(0)
        img_bytes = buffer.getvalue()

        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
        mime = 'image/jpeg' if out_format == 'JPEG' else f'image/{out_format.lower()}'
        final_w, final_h = img.size
        file_size = len(img_bytes)

        return JsonResponse({
            'success': True,
            'image_data': f'data:{mime};base64,{img_base64}',
            'width': final_w,
            'height': final_h,
            'format': out_format,
            'quality': quality,
            'dpi': dpi_val,
            'file_size': _human_size(file_size),
            'original_width': orig_w,
            'original_height': orig_h,
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def download_image(request, filename):
    path = Path(settings.MEDIA_ROOT) / 'processed' / filename
    if not path.exists():
        raise Http404
    return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


def _human_size(size):
    for unit in ['B', 'KB', 'MB']:
        if size < 1024:
            return f'{size:.1f} {unit}'
        size /= 1024
    return f'{size:.1f} GB'
