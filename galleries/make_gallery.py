# Build a gallery page from a folder of photos.
#
# usage: python3 make_gallery.py "<photo folder>"   (folder named "Show Name (month year)")
#
# - the show name, month (optional) and year come from the folder name,
#   e.g. "Eurydice (February 2022)" or "Eurydice (2022)"
# - checks that every file in the folder is a readable image
# - converts anything that isn't a JPG to .jpg
# - copies the photos to galleries/images/<slug>/
# - writes galleries/<slug>.html using topfile.txt and bottomfile.txt
# - adds a card for the new gallery at the top of the grid in all_galleries.html
#   (skipped if a card linking to the page already exists)

import argparse
import calendar
import html
import re
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageOps

GALLERIES = Path(__file__).resolve().parent
ALL_GALLERIES = GALLERIES.parent / 'all_galleries.html'
GRID_START = '<div class="row gtr-150">'

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


def check_photos(sources):
    bad = []
    for src in sources:
        try:
            with Image.open(src) as img:
                img.verify()
        except OSError:
            bad.append(src.name)
    return bad


def to_jpg(src, image_dir):
    dest = image_dir / (src.stem + '.jpg')
    with Image.open(src) as img:
        is_jpeg = img.format == 'JPEG'
        if is_jpeg:
            shutil.copy2(src, dest)    
            size = ImageOps.exif_transpose(img).size
            return dest.name, size, False
        img = ImageOps.exif_transpose(img)
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGBA')
            background = Image.new('RGB', img.size, 'white')
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert('RGB')
        img.save(dest, 'JPEG', quality=92)
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
    image_dir = GALLERIES / 'images' / slug.replace('-', '_')
    if page.exists() or image_dir.exists():
        parser.error(f'{page.name} or {image_dir.name} already exists; pick another --slug')

    sources = sorted(p for p in args.folder.iterdir() if p.is_file() and not p.name.startswith('.'))
    if not sources:
        parser.error(f'no photos found in {args.folder}')

    bad = check_photos(sources)
    if bad:
        sys.exit('These files are not readable images, so nothing was built:\n  ' + '\n  '.join(bad))

    jpg_names = [src.stem + '.jpg' for src in sources]
    if len(set(jpg_names)) != len(jpg_names):
        sys.exit('Two photos would get the same .jpg name (for example IMG.png and IMG.jpg); rename one and try again.')

    image_dir.mkdir(parents=True)
    photos = []
    converted = 0
    for src in sources:
        name, size, was_converted = to_jpg(src, image_dir)
        converted += was_converted
        photos.append((f'images/{image_dir.name}/{name}', size))

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

    print(f'{len(photos)} photos ({converted} converted to JPG) -> {image_dir}')
    print(f'page -> {page}')

    cover_src = f'galleries/{photos[0][0]}'
    card = gallery_card(slug, title, shown_date, cover_src, args.blurb)
    add_gallery_card(slug, card)


if __name__ == '__main__':
    main()
