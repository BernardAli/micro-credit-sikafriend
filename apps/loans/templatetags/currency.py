from django import template
from django.contrib.humanize.templatetags.humanize import intcomma

register = template.Library()


def _get_symbol():
    """Return currency symbol from CompanyProfile, fallback to GHS."""
    try:
        from apps.company.models import CompanyProfile
        return CompanyProfile.get_solo().formatted_currency
    except Exception:
        return "GHS"


@register.filter(name="ghs")
def ghs(value):
    """Format a value as currency using the configured company currency symbol."""
    if value is None:
        symbol = _get_symbol()
        return f"{symbol} 0.00"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return value
    symbol = _get_symbol()
    return f"{symbol} {intcomma(f'{value:,.2f}')}"


@register.filter(name="currency")
def currency(value):
    """Alias for the shared currency formatter used across templates."""
    return ghs(value)


@register.simple_tag(takes_context=True)
def currency_symbol(context):
    """Return just the currency symbol/prefix for use in templates."""
    return _get_symbol()
