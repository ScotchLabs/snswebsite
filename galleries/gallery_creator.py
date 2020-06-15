# Valerie Nayak
# 6/8/2020
# Auto generate gallery pages

import os
from pathlib import Path
import re
from PIL import Image

def get_img_names(extension):
    # returns a list of all file names in path
    dirname = os.path.dirname(__file__)
    filename = os.path.join(dirname, extension)
    # p = Path(r"C:\Users\Valerie\Documents\snswebsite\galleries\images").glob('**/*')
    p = Path(filename).glob('**/*')
    file_paths = [repr(x) for x in p if x.is_file()]
    return file_paths

def get_image_data(file_paths):
    # get images list
    # images is list with each item being a tuple holding a string and a tuple: (relative path string, (img dimensions tuple))
    images = []     
    for f in file_paths:
        # trim the full path to the relative path
        rel_match = re.search('''(?<=galleries\/)[^'"()]+''', f)    # regex to match relative path
        full_match = re.search('''(?<=\(')[^'"()]+''', f)   # regex to match full file path
        if rel_match:
            rel_path = rel_match.group(0)
        if full_match:
            full_path = full_match.group(0)    
        with Image.open(full_path) as img:
            dimens = img.size
        images.append((rel_path, dimens))
    return images

def fill_file(outfile_name, top=True):
    # add the starter file code at the top and bottom
    # if top=True, add the top of the file, otherwise add the bottom
    if top:
        copy_file = os.path.dirname(__file__) + '/topfile.txt'
    else:
        copy_file = os.path.dirname(__file__) + '/bottomfile.txt'
    with open(copy_file) as f1:
        with open(outfile_name, 'a') as f2:
            for line in f1:
                f2.write(line)

def add_photos(outfile_name, images):
    with open(outfile_name, 'a') as f:
        for pic in images:
            width, height = pic[1]
            ratio = width / height
            print('ratio', ratio)
            if ratio <= .75:    # portrait
                size_class = 'col-lg-3'
            elif ratio > 1.25:  # landscape
                size_class = 'col-lg-6'
            else:   # square
                size_class = 'col-lg-4'
            # f.write("""<div class="col-6 col-md-6 col-lg-4" data-aos="fade-up" data-aos-delay="100">""")
            f.write('<div class="col-6 col-md-6 '+size_class+'" data-aos="fade-up" data-aos-delay="100">')
            f.write('   <a href="'+pic[0]+'" class="d-block photo-item" data-fancybox="gallery">')
            f.write('   <img src="'+pic[0]+'" alt="Image" class="img-fluid">')
            f.write('''<div class="photo-text-more">
              <span class="icon icon-search"></span>
                    </div>
                </a>
                </div>''')


ext = 'images/LesMisResized'
output_fname = os.path.dirname(__file__) + '/lesmis_gallery.html'
file_paths = get_img_names(ext)
# print(file_paths)
images = get_image_data(file_paths)
# print(images)

fill_file(output_fname, True)
add_photos(output_fname, images)
fill_file(output_fname, False)