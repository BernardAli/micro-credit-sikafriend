"""Readable workspace colors for optional company brand overrides."""
import re


def _rgb(value):
    if not re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", value or ""):
        return None
    digits = value[1:]
    if len(digits) == 3:
        digits = "".join(char * 2 for char in digits)
    return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4))


def _luminance(rgb):
    channels = [channel / 255 for channel in rgb]
    linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4 for channel in channels]
    return sum(channel * weight for channel, weight in zip(linear, (.2126, .7152, .0722)))


def _readable(rgb, background, lighten=False):
    """Keep the brand hue, blending only as far as needed for readable text."""
    target = 255 if lighten else 0
    for step in range(101):
        color = tuple(round(channel + (target - channel) * step / 100) for channel in rgb)
        luminances = sorted((_luminance(color), _luminance(background)))
        if (luminances[1] + .05) / (luminances[0] + .05) >= 5.5:
            return "#" + "".join(f"{channel:02x}" for channel in color)


def dashboard_brand_css(primary, secondary):
    rules = []
    primary_rgb = _rgb(primary)
    secondary_rgb = _rgb(secondary)
    if primary_rgb:
        light = _readable(primary_rgb, (237, 242, 239))
        dark = _readable(primary_rgb, (29, 44, 48), lighten=True)
        action = _readable(primary_rgb, (255, 255, 255))
        rules.extend((f"--accent-light:{light};", f"--accent-dark:{dark};", f"--action:{action};"))
        for variable, fraction in (("action-hover", .8), ("hero-start", .5), ("hero-end", .75)):
            rgb = _rgb(action)
            shade = "#" + "".join(f"{round(channel * fraction):02x}" for channel in rgb)
            rules.append(f"--{variable}:{shade};")
    if secondary_rgb:
        rules.extend((f"--gold-light:{_readable(secondary_rgb, (237, 242, 239))};",
                      f"--gold-dark:{_readable(secondary_rgb, (29, 44, 48), lighten=True)};"))
    return " ".join(rules)
