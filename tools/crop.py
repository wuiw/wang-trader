"""Crop a region from a book photo at full resolution.

Usage: tools/.venv/bin/python tools/crop.py IMG_8340 x0 y0 x1 y1 out.jpg [--rot DEG]
Coordinates are in the reference/book-jpg/<IMG>.jpg pixel space (2400x1800 landscape,
already rotated). --rot applies an extra rotation (e.g. 180) if that JPG was upside down.
"""
import sys
import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()
args = sys.argv[1:]
rot = 0
if "--rot" in args:
    i = args.index("--rot"); rot = int(args[i + 1]); del args[i:i + 2]
name, x0, y0, x1, y1, out = args[0], *map(float, args[1:5]), args[5]
im = ImageOps.exif_transpose(Image.open(f"reference/book/{name}.HEIC")).convert("RGB")
im = im.rotate(90, expand=True)
if rot:
    im = im.rotate(rot, expand=True)
s = im.width / 2400
c = im.crop((int(x0 * s), int(y0 * s), int(x1 * s), int(y1 * s)))
c.thumbnail((2000, 2000))
c.save(out, quality=88)
print(out, im.width, im.height)
