"""
Pagination DRF kustom -- `PageNumberPagination` BAWAAN DRF TIDAK
menghormati parameter `?page_size=` dari client SAMA SEKALI kecuali
`page_size_query_param` di-set eksplisit (defaultnya `None`). Tanpa ini,
SEMUA request `?page_size=200` dari frontend (dipakai utk isi dropdown
Pool/Device dkk yang perlu SEMUA baris, bukan cuma 1 halaman) diam-diam
DIABAIKAN, selalu balik cuma `PAGE_SIZE` (20) baris -- inilah sebabnya
dropdown Pool/Device kelihatan "tidak lengkap" di banyak halaman.

`max_page_size` TETAP dibatasi (bukan tak terbatas) supaya client nakal
tidak bisa minta SEMUA baris sekaligus (mis. 100rb employee) & membebani
server -- 500 cukup lega utk kasus dropdown (Pool/Device/dst jumlahnya
biasanya puluhan-ratusan, bukan ribuan).
"""
from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    page_size_query_param = 'page_size'
    max_page_size = 500