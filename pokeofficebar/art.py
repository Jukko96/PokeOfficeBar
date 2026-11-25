"""Draw fallback item icons with Pillow."""

from PIL import Image, ImageDraw

INK = "#333044"
HIGHLIGHT = "#fff8e7"


def item_art(key: str) -> Image.Image | None:
    image = Image.new("RGBA", (40, 40))
    draw = ImageDraw.Draw(image)
    if key == "gift_box":
        draw.rounded_rectangle((4, 15, 35, 37), radius=4, fill="#ecc388", outline=INK, width=2)
        draw.rounded_rectangle((3, 12, 36, 20), radius=3, fill="#fbdb9a", outline=INK, width=2)
        draw.rectangle((17, 12, 22, 35), fill="#ce7a77")
        draw.ellipse((10, 5, 20, 13), fill="#ce7a77", outline=INK)
        draw.ellipse((20, 5, 30, 13), fill="#ce7a77", outline=INK)
    elif key == "rare_candy":
        draw.polygon(((3, 9), (15, 15), (27, 13), (35, 6), (35, 31),
                      (26, 25), (14, 27), (5, 34)), fill="#a3bce8", outline=INK, width=2)
        draw.ellipse((12, 10, 29, 28), fill="#edaa97", outline=INK, width=2)
        draw.arc((15, 13, 25, 24), 190, 288, fill=HIGHLIGHT, width=2)
    elif key == "mint":
        draw.ellipse((8, 5, 33, 33), fill="#9fd3ad", outline=INK, width=2)
        draw.line((8, 34, 27, 12), fill="#509c79", width=3)
        draw.line((18, 23, 13, 16), fill="#509c79", width=2)
    elif key == "shiny_charm":
        draw.ellipse((16, 3, 24, 12), outline=INK, width=2)
        draw.polygon(((20, 9), (24, 17), (34, 18), (27, 25), (29, 35), (20, 30),
                      (11, 35), (13, 25), (6, 18), (16, 17)),
                     fill="#e9bb6b", outline=INK, width=2)
        draw.line((21, 15, 20, 25), fill=HIGHLIGHT, width=2)
    elif key == "soothe_bell":
        draw.ellipse((17, 5, 23, 11), outline=INK, width=2)
        draw.rounded_rectangle((10, 9, 30, 31), radius=8, fill="#e8b570", outline=INK, width=2)
        draw.ellipse((7, 25, 33, 32), fill="#f5d494", outline=INK, width=2)
        draw.ellipse((17, 31, 23, 37), fill="#b6815f", outline=INK, width=2)
    elif key == "incense":
        draw.arc((16, 2, 29, 19), 122, 280, fill="#9ac6c4", width=3)
        draw.line((20, 28, 23, 12), fill="#ac7770", width=3)
        draw.ellipse((4, 26, 36, 36), fill="#bd8eb0", outline=INK, width=2)
        draw.arc((7, 26, 33, 32), 180, 355, fill=HIGHLIGHT, width=2)
    else:
        return None
    bounds = image.getbbox()
    return image.crop(bounds) if bounds else None
