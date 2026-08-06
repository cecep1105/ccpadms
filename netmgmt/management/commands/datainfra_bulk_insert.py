"""
Bulk insert data itinfra (lihat netmgmt/models.py::ITInfraEntry) dari file CSV. Gunakan
perintah ini kalau ingin mengimpor data IT-Infra dalam jumlah banyak sekaligus, mis
format data:
kategori,nama,catatan,is_staff_only,data
internet,Indihome,langganan internet rumah,0,"sid=1234567890;username=abc;password=xyz"

Jalankan:
    python manage.py datainfra_bulk_insert {file_csv}
"""
from django.core.management.base import BaseCommand
from django.shortcuts import get_object_or_404
from netmgmt.models import ITInfraCategory, ITInfraEntry

def parse_data(text):
    result = {}
    for item in text.split(";"):
        if not item:
            continue
        k, v = item.split("=", 1)
        result[k] = v
    return result
def to_bool(value):
    return value.strip().lower() in ("true", "1", "yes", "y")

class Command(BaseCommand):
    help = 'Bulk insert data itinfra dari file CSV.'

    def add_arguments(self, parser):
        parser.add_argument('file_csv', type=str, help='Path ke file CSV')

    def handle(self, *args, **options):
        file_csv = options['file_csv']
        import csv
        with open(file_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                nama = row["nama"]
                kategori = row["kategori"]
                catatan = row["catatan"]
                is_staff_only = to_bool(row["is_staff_only"])
                data = row["data"]
                data_dict = parse_data(data)
                category_id = ITInfraCategory.objects.filter(name=kategori).values_list('id', flat=True).first()
                category = get_object_or_404(ITInfraCategory, id=category_id)
                try:
                    entry = ITInfraEntry(category=category, name=nama, notes=catatan, is_staff_only=is_staff_only)
                    entry.set_data(data_dict)
                    entry.save()
                    print(f"Insert: kategori={kategori}, nama={nama}")
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error|duplikat: {kategori} - {nama}"))
