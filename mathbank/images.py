"""Remove only completely white outer margins; never resample source pixels."""
import pymupdf


def trim_white_margin(pixmap, padding=12):
    if pixmap.alpha or pixmap.n != 3:
        return pixmap
    samples = pixmap.samples
    left, top, right, bottom = pixmap.width, pixmap.height, 0, 0
    for y in range(pixmap.height):
        row = samples[y * pixmap.stride:y * pixmap.stride + pixmap.width * 3]
        leading = len(row) - len(row.lstrip(b'\xff'))
        if leading == len(row):
            continue
        trailing = len(row.rstrip(b'\xff'))
        left, right = min(left, leading // 3), max(right, (trailing + 2) // 3)
        top, bottom = min(top, y), y + 1
    if not right:
        return pixmap
    box = pymupdf.IRect(max(0, left-padding), max(0, top-padding),
                       min(pixmap.width, right+padding), min(pixmap.height, bottom+padding))
    if box.width == pixmap.width and box.height == pixmap.height:
        return pixmap
    box += (pixmap.x, pixmap.y, pixmap.x, pixmap.y)
    result = pymupdf.Pixmap(pixmap.colorspace, box, 0)
    result.copy(pixmap, box)
    result.set_origin(0, 0)
    result.set_dpi(pixmap.xres, pixmap.yres)
    return result
