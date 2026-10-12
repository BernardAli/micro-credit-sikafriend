"""Serialize chart data without allowing HTML to terminate an inline script."""
import json

from django import template
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.safestring import mark_safe

register = template.Library()
SCRIPT_ESCAPES = {
    ord("<"): "\\u003C", ord(">"): "\\u003E", ord("&"): "\\u0026",
    ord("\u2028"): "\\u2028", ord("\u2029"): "\\u2029",
}


@register.filter
def json_js(value):
    """Accept existing JSON strings as well as native lists/dicts/numbers."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            pass
    return mark_safe(json.dumps(value, cls=DjangoJSONEncoder).translate(SCRIPT_ESCAPES))
