"""
Objek pagination minimalis yang meniru interface `django.core.paginator.Page`
secukupnya supaya bisa dipakai bareng `templates/partials/pagination.html`
yang sudah ada (dipakai di semua tabel iclock) TANPA perlu duplikasi
template pagination.

Dipakai khusus untuk data dari RAW SQL (MSSQL, bukan Django QuerySet) --
pagination-nya dihitung dari `total_count` hasil `COUNT(*)` SQL terpisah
(lihat `mclock/mssql_client.py::fetch_paginated_from_sql`), BUKAN dengan
`django.core.paginator.Paginator` biasa (yang mengasumsikan queryset/list
yang bisa di-slice Python).
"""


class SimplePaginator:
    def __init__(self, count: int, per_page: int):
        self.count = count
        self.per_page = per_page
        self.num_pages = max(1, -(-count // per_page)) if per_page else 1  # ceil division


class SimplePage:
    """Duck-type `django.core.paginator.Page` -- cukup utk dipakai `partials/pagination.html`."""

    def __init__(self, object_list, number: int, total_count: int, per_page: int):
        self.object_list = object_list
        self.number = number
        self.paginator = SimplePaginator(total_count, per_page)

    def has_previous(self):
        return self.number > 1

    def has_next(self):
        return self.number < self.paginator.num_pages

    def previous_page_number(self):
        return self.number - 1

    def next_page_number(self):
        return self.number + 1

    def start_index(self):
        if self.paginator.count == 0:
            return 0
        return (self.number - 1) * self.per_page + 1

    @property
    def per_page(self):
        return self.paginator.per_page

    def __iter__(self):
        return iter(self.object_list)

    def __len__(self):
        return len(self.object_list)
