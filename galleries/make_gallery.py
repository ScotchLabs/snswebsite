# Build a gallery page from a folder of photos.
#
# usage: python3 make_gallery.py "<photo folder>"   (folder named "Show Name (month year)")
#
# - the show name, month (optional) and year come from the folder name,
#   e.g. "Eurydice (February 2022)" or "Eurydice (2022)"
# - checks that every file in the folder is a readable image
# - converts anything that isn't a JPG to .jpg
# - converts and strips the photos, then uploads them to s3://sns-photos-static/images/<slug>/
#   (photos are NOT kept in the repo; they are served from https://static.snstheatre.org/images/...)
# - writes galleries/<slug>.html using topfile.txt and bottomfile.txt
# - adds a card for the new gallery at the top of the grid in all_galleries.html
#   (skipped if a card linking to the page already exists)
#
# needs the AWS CLI logged in (`aws login`) with write access to the bucket

import argparse
import calendar
import html
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

GALLERIES = Path(__file__).resolve().parent
ALL_GALLERIES = GALLERIES.parent / 'all_galleries.html'
GRID_START = '<div class="row gtr-150">'

BUCKET = 'sns-photos-static'
PUBLIC_IMAGE_URL = 'https://static.snstheatre.org/images'
# photos never change once uploaded, so browsers and CloudFront may cache them for a year
CACHE_CONTROL = 'public, max-age=31536000, immutable'

# photos are never re-encoded when they are already JPEGs: the pixels are copied byte for byte
# and only the metadata is removed. Non-JPEG photos are converted to JPEG at this quality.
CONVERT_QUALITY = 95

MONTHS = {name.lower(): name for name in calendar.month_name[1:]}
MONTHS.update({name.lower(): full for name, full in zip(calendar.month_abbr[1:], calendar.month_name[1:])})


def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def parse_folder_name(name):
    """Return (title, year, month) from "Show Name (month year)" or "Show Name (year)".

    month is the full month name (e.g. "February") or None when the folder has no month.
    Returns None if the name doesn't match either form.
    """
    match = re.fullmatch(r'(.+?)\s*\((?:([A-Za-z]+)\s+)?(\d{4})\)', name)
    if not match:
        return None
    title, month_word, year = match.group(1).strip(), match.group(2), match.group(3)
    if month_word is None:
        return title, year, None
    month = MONTHS.get(month_word.lower())
    if month is None:
        return None
    return title, year, month


def date_text(year, month):
    return f'{month} {year}' if month else year


def s3_prefix_has_objects(prefix):
    """True if anything already exists under s3://BUCKET/<prefix>/ (so we never overwrite a gallery)."""
    result = subprocess.run(['aws', 's3', 'ls', f's3://{BUCKET}/{prefix}/'],
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f'aws s3 ls failed (are you logged in with `aws login`?):\n{result.stderr}')
    return bool(result.stdout.strip())


def upload_images(local_dir, prefix):
    """Copy every JPG in local_dir to s3://BUCKET/images/<prefix>/ with web-friendly headers."""
    result = subprocess.run([
        'aws', 's3', 'cp', str(local_dir), f's3://{BUCKET}/images/{prefix}/',
        '--recursive', '--exclude', '*', '--include', '*.jpg',
        '--content-type', 'image/jpeg', '--cache-control', CACHE_CONTROL,
    ])
    if result.returncode != 0:
        sys.exit('Upload to S3 failed; no gallery page or card was written.')


def check_photos(sources):
    bad = []
    for src in sources:
        try:
            with Image.open(src) as img:
                img.verify()
        except OSError:
            bad.append(src.name)
    return bad


def _jpeg_orientation(data):
    """Return the EXIF orientation (1-8) of a JPEG's bytes, or None if it has none."""
    try:
        i = 2
        while data[i] == 0xFF and data[i + 1] != 0xDA:
            seglen = struct.unpack('>H', data[i + 2:i + 4])[0]
            if data[i + 1] == 0xE1 and data[i + 4:i + 10] == b'Exif\x00\x00':
                tiff = i + 10
                order = '<' if data[tiff:tiff + 2] == b'II' else '>'
                ifd = tiff + struct.unpack(order + 'I', data[tiff + 4:tiff + 8])[0]
                count = struct.unpack(order + 'H', data[ifd:ifd + 2])[0]
                for n in range(count):
                    entry = ifd + 2 + 12 * n
                    if struct.unpack(order + 'H', data[entry:entry + 2])[0] == 0x0112:
                        return struct.unpack(order + 'H', data[entry + 8:entry + 10])[0]
                return None
            i += 2 + seglen
    except (IndexError, struct.error):
        pass
    return None


def _orientation_segment(orientation):
    """A minimal EXIF block that holds only the orientation tag (no GPS, camera, or date)."""
    tiff = (b'II*\x00' + struct.pack('<I', 8) + struct.pack('<H', 1)
            + struct.pack('<HHI', 0x0112, 3, 1) + struct.pack('<H', orientation) + b'\x00\x00'
            + struct.pack('<I', 0))
    body = b'Exif\x00\x00' + tiff
    return b'\xff\xe1' + struct.pack('>H', len(body) + 2) + body


def strip_jpeg_metadata(data):
    """Return the JPEG bytes with metadata removed and the image data left untouched.

    Dropped: EXIF (including GPS and camera details), XMP, IPTC, comments, thumbnails.
    Kept: JFIF, the color profile (ICC), Adobe color info, and the image itself.
    The camera rotation is kept as a one-tag EXIF block so photos still display upright.
    No pixels are decoded or re-encoded.
    """
    if data[:2] != b'\xff\xd8':
        raise ValueError('not a JPEG')
    orientation = _jpeg_orientation(data)
    out = bytearray(b'\xff\xd8')
    if orientation not in (None, 1):
        out += _orientation_segment(orientation)
    i = 2
    while True:
        if data[i] != 0xFF:
            raise ValueError('corrupt JPEG header')
        marker = data[i + 1]
        if marker == 0xFF:  # padding byte
            i += 1
            continue
        if marker == 0xDA or marker == 0xD9:  # start of scan or end of image: the rest is image data
            out += data[i:]
            return bytes(out)
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # markers with no length field
            i += 2
            continue
        seglen = struct.unpack('>H', data[i + 2:i + 4])[0]
        seg = data[i:i + 2 + seglen]
        is_metadata = (0xE1 <= marker <= 0xEF and marker != 0xEE) or marker == 0xFE  # APP1-APP15 except Adobe, and COM
        if marker == 0xE2 and seg[4:16].startswith(b'ICC_PROFILE'):  # color profile: keep
            is_metadata = False
        if not is_metadata:  # everything else (JFIF, quantization/Huffman tables, frame info, etc.) is needed
            out += seg
        i += 2 + seglen


def strip_png_metadata(data):
    """Return the PNG bytes with text, time, and EXIF chunks removed. Image and color chunks are kept."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG')
    drop = {b'tEXt', b'zTXt', b'iTXt', b'eXIf', b'tIME'}
    out = bytearray(data[:8])
    i = 8
    while i + 8 <= len(data):
        length = struct.unpack('>I', data[i:i + 4])[0]
        kind = data[i + 4:i + 8]
        chunk = data[i:i + 12 + length]
        if kind not in drop:
            out += chunk
        i += 12 + length
        if kind == b'IEND':
            break
    return bytes(out)


def to_jpg(src, image_dir):
    """Copy a photo into image_dir as a JPG with its metadata removed.

    A JPEG is copied byte for byte (only its metadata is stripped), so its quality is
    exactly the original. Any other format is converted to JPEG at CONVERT_QUALITY.
    Returns (file name, size as shown on the page, whether the source was not already a JPEG).
    """
    dest = image_dir / (src.stem + '.jpg')
    with Image.open(src) as img:
        was_converted = img.format != 'JPEG'
        if not was_converted:
            dest.write_bytes(strip_jpeg_metadata(src.read_bytes()))
            size = ImageOps.exif_transpose(img).size  # size after the camera rotation, for the layout
            return dest.name, size, False
        img = ImageOps.exif_transpose(img)
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGBA')
            background = Image.new('RGB', img.size, 'white')
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert('RGB')
        img.save(dest, 'JPEG', quality=CONVERT_QUALITY, subsampling=0)  # no metadata written
        return dest.name, img.size, True


def photo_html(rel_path, size, delay):
    width, height = size
    ratio = width / height
    if ratio <= .75:   
        size_class = 'col-lg-3'
    elif ratio > 1.25:  
        size_class = 'col-lg-6'
    else:              
        size_class = 'col-lg-4'
    return f'''        <div class="col-6 col-md-6 {size_class}" data-aos="fade-up" data-aos-delay="{delay}">
          <a href="{rel_path}" class="d-block photo-item" data-fancybox="gallery">
            <img src="{rel_path}" alt="Image" class="img-fluid">
            <div class="photo-text-more">
              <span class="icon icon-search"></span>
            </div>
          </a>
        </div>
'''


def gallery_card(slug, title, date_text, cover_src, blurb):
    blurb_html = f'\n                                        <p>{html.escape(blurb)}</p>' if blurb else ''
    return f'''                                <div class="col-4 col-12-narrower">
                                    <section>
                                        <a href="galleries/{slug}" class="image featured"><img src="{cover_src}" alt="" /></a>
                                        <header>
                                            <h3>
                                                <strong><a href="galleries/{slug}">{html.escape(title)}</a></strong>
                                                <br>{html.escape(date_text)}
                                            </h3>
                                        </header>{blurb_html}
                                    </section>
                                </div>
'''


def add_gallery_card(slug, card):
    text = ALL_GALLERIES.read_text()
    if f'href="galleries/{slug}"' in text:
        print(f'{ALL_GALLERIES.name} already links to galleries/{slug}; card not added')
        return
    if text.count(GRID_START) != 1:
        sys.exit(f'Expected exactly one "{GRID_START}" in {ALL_GALLERIES.name}; card not added.')
    pos = text.index(GRID_START) + len(GRID_START)
    text = text[:pos] + '\n' + card.rstrip('\n') + text[pos:]
    ALL_GALLERIES.write_text(text)
    print(f'card -> {ALL_GALLERIES}')


def main():
    parser = argparse.ArgumentParser(description='Build a gallery page from a folder named "Show Name (month year)".')
    parser.add_argument('folder', type=Path, help='folder containing the photos, named "Show Name (month year)"')
    parser.add_argument('--slug', help='page name, e.g. 201910-showname (default: year and show name)')
    parser.add_argument('--date', help='date shown on the all_galleries card and the page, e.g. "February 2020" (default: month and year from the folder name)')
    parser.add_argument('--blurb', default='', help='description shown on the all_galleries card (optional)')
    args = parser.parse_args()

    if not args.folder.is_dir():
        parser.error(f'{args.folder} is not a folder')

    parsed = parse_folder_name(args.folder.resolve().name)
    if not parsed:
        parser.error(f'folder must be named "Show Name (month year)" or "Show Name (year)", got "{args.folder.name}"')
    title, year, month = parsed
    shown_date = args.date or date_text(year, month)

    slug = args.slug or f'{year}-{slugify(title)}'
    page = GALLERIES / f'{slug}.html'
    prefix = slug.replace('-', '_')  # folder name in the bucket, e.g. 2025_alice_by_heart
    if page.exists():
        parser.error(f'{page.name} already exists; pick another --slug')
    if s3_prefix_has_objects(f'images/{prefix}'):
        parser.error(f's3://{BUCKET}/images/{prefix}/ already has photos; pick another --slug')

    sources = sorted(p for p in args.folder.iterdir() if p.is_file() and not p.name.startswith('.'))
    if not sources:
        parser.error(f'no photos found in {args.folder}')

    bad = check_photos(sources)
    if bad:
        sys.exit('These files are not readable images, so nothing was built:\n  ' + '\n  '.join(bad))

    jpg_names = [src.stem + '.jpg' for src in sources]
    if len(set(jpg_names)) != len(jpg_names):
        sys.exit('Two photos would get the same .jpg name (for example IMG.png and IMG.jpg); rename one and try again.')

    photos = []
    converted = 0
    with tempfile.TemporaryDirectory() as staging:  # converted copies live here only until they are uploaded
        staging = Path(staging)
        for src in sources:
            name, size, was_converted = to_jpg(src, staging)
            converted += was_converted
            photos.append((f'{PUBLIC_IMAGE_URL}/{prefix}/{name}', size))
        upload_images(staging, prefix)

    top = (GALLERIES / 'topfile.txt').read_text()
    top = top.replace('<title>Gallery</title>', f'<title>{html.escape(title)} | Scotch\'n\'Soda Theatre</title>')
    top = top.replace('<h2 class="text-white mb-4">SHOW NAME HERE</h2>',
                      f'<h2 class="text-white mb-4">{html.escape(title)}</h2>\n'
                      f'          <p class="text-white">{html.escape(shown_date)}</p>')
    bottom = (GALLERIES / 'bottomfile.txt').read_text()

    with open(page, 'w') as f:
        f.write(top + '\n')
        for i, (rel_path, size) in enumerate(photos):
            # delays cycle 0, 100, 200 so neighboring photos fade in one after another
            f.write(photo_html(rel_path, size, (i % 3) * 100))
        f.write(bottom)

    print(f'{len(photos)} photos ({converted} converted to JPG) -> s3://{BUCKET}/images/{prefix}/')
    print(f'page -> {page}')

    cover_src = photos[0][0]
    card = gallery_card(slug, title, shown_date, cover_src, args.blurb)
    add_gallery_card(slug, card)


if __name__ == '__main__':
    main()
