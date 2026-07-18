"""
Template tag kecil untuk bikin link pagination yang mempertahankan semua
query param yang sedang aktif (filter, sort, dll), cuma ganti nilai `page`.

Dipakai lewat partial templates/partials/pagination.html, di-include di
semua halaman list yang punya pagination.
"""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """
    Kembalikan querystring dari request saat ini dengan key-key di kwargs
    di-override. Contoh pemakaian: ?{% url_replace page=3 %}
    """
    request = context.get('request')
    if request is None:
        return ''
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()
