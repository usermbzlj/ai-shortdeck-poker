import os
import re
from PIL import Image
from rembg import remove
from scipy import ndimage
import numpy as np

INPUT_DIR = 'charA'
OUTPUT_DIR = '.'
CROP_Y = 820


def get_output_name(filename):
    """Convert charA filename to A_X_Y.png format."""
    # e.g., '1.png' -> 'A_1_1.png', '1_2.png' -> 'A_1_2.png'
    base = os.path.splitext(filename)[0]
    match = re.match(r'^(\d+)(?:_(\d+))?$', base)
    if not match:
        return None
    expr_id = match.group(1)
    variant = match.group(2) if match.group(2) else '1'
    return f'A_{expr_id}_{variant}.png'


def process_image(input_path, output_path):
    img = Image.open(input_path)
    
    # Step 1: rembg remove background
    out = remove(img)
    arr = np.array(out)
    
    # Step 2: Keep only largest connected component
    alpha = arr[:, :, 3]
    labeled, num_features = ndimage.label(alpha > 50)
    if num_features > 0:
        sizes = ndimage.sum(alpha > 50, labeled, range(1, num_features + 1))
        largest_label = np.argmax(sizes) + 1
        mask = labeled == largest_label
        new_arr = np.zeros_like(arr)
        new_arr[mask] = arr[mask]
        arr = new_arr
    
    # Step 3: Crop at y=CROP_Y
    arr[CROP_Y:, :, 3] = 0
    
    result = Image.fromarray(arr)
    result.save(output_path)
    print(f'Saved: {output_path}')


def main():
    files = sorted([f for f in os.listdir(INPUT_DIR) if f.endswith('.png')])
    for fname in files:
        out_name = get_output_name(fname)
        if not out_name:
            print(f'Skip: {fname}')
            continue
        input_path = os.path.join(INPUT_DIR, fname)
        output_path = os.path.join(OUTPUT_DIR, out_name)
        process_image(input_path, output_path)


if __name__ == '__main__':
    main()
