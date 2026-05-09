import os
import re
from PIL import Image
from rembg import remove
from scipy import ndimage
import numpy as np

INPUT_DIR = 'charA'
OUTPUT_DIR = '.'


def get_output_name(filename):
    base = os.path.splitext(filename)[0]
    match = re.match(r'^(\d+)(?:_(\d+))?$', base)
    if not match:
        return None
    expr_id = match.group(1)
    variant = match.group(2) if match.group(2) else '1'
    return f'A_{expr_id}_{variant}.png'


def process_image(input_path, output_path):
    img = Image.open(input_path)
    out = remove(img)
    arr = np.array(out).astype(np.float32)
    h, w = arr.shape[:2]

    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]
    y_coords = np.arange(h)[:, None]

    # 1. Green desk
    green_global = (g > r + 50) & (g > b + 30) & (g > 100)
    green_y = (y_coords > 880) & (g > r + 10) & (g > b + 5)
    green_mask = green_global | green_y

    # 2. Brown edge
    brown_mask = (y_coords > 850) & (r > g) & (g > b) & (r > 45) & (g > 25) & (b > 15) & (r < 180) & (g < 150) & (b < 130)

    # 3. Poker card white background
    white_mask = (y_coords > 850) & (r + g + b > 500) & (r > 170) & (g > 160) & (b > 155)

    # 4. Grayish fragments in bottom area (spades/clubs/shadows)
    # Low saturation gray/brown in y > 920
    gray_mask = (y_coords > 920) & (r + g + b > 80) & (r + g + b < 450) & \
                (np.abs(r - g) < 50) & (np.abs(g - b) < 50) & (np.abs(r - b) < 50)

    # Preserve chips
    chip_mask = (
        ((r > 120) & (g < 130) & (b < 130) & (r - np.maximum(g, b) > 30)) |      # red
        ((b > 70) & (r < 110) & (g < 140) & (b - np.maximum(r, g) > 20)) |        # blue
        ((g > 70) & (r < 100) & (b < 100) & (g - np.maximum(r, b) > 15)) |        # green chip
        ((r < 70) & (g < 70) & (b < 70) & (r + g + b < 180))                       # black
    )

    remove_mask = (green_mask | brown_mask | white_mask | gray_mask) & (~chip_mask)
    arr[remove_mask, 3] = 0

    result = Image.fromarray(arr.astype(np.uint8))
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
