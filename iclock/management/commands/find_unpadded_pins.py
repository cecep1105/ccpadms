"""
Diagnostik: cari record Employee yang PIN-nya numerik tapi BELUM 9-digit
zero-padded -- kemungkinan besar hasil dari bug SEBELUM perbaikan
`normalize_pin()` (Backup Data Finger dulu menyimpan PIN mentah dari device
fisik apa adanya, tanpa zero-pad, sehingga bisa menghasilkan Employee
duplikat kalau versi zero-padded-nya sudah ada duluan di database).

Command ini CUMA melaporkan, TIDAK mengubah/menghapus data apapun -- keputusan
menggabungkan/menghapus duplikat diserahkan ke Anda (perlu hati-hati, cek dulu
referensi ke tabel Fingerprint Template & Transaction sebelum hapus).

Jalankan:
    python manage.py find_unpadded_pins
"""
from django.core.management.base import BaseCommand

from iclock.models import employee, fptemp, transaction
from iclock.services import PIN_ZERO_PAD_LENGTH


class Command(BaseCommand):
    help = (
        'Cari Employee dengan PIN numerik yang belum 9 digit zero-padded -- kemungkinan data lama '
        'dari sebelum perbaikan normalize_pin() di fitur Backup Data Finger.'
    )

    def handle(self, *args, **options):
        candidates = [
            emp for emp in employee.objects.all()
            if emp.PIN and emp.PIN.strip().isdigit() and len(emp.PIN.strip()) < PIN_ZERO_PAD_LENGTH
        ]

        if not candidates:
            self.stdout.write(self.style.SUCCESS(
                'Tidak ada Employee dengan PIN numerik yang belum 9 digit. Aman, tidak perlu tindakan apapun.'
            ))
            return

        self.stdout.write(self.style.WARNING(
            f'Ditemukan {len(candidates)} Employee dengan PIN numerik BELUM 9-digit zero-padded:'
        ))
        self.stdout.write('')

        for emp in candidates:
            padded_pin = emp.PIN.strip().zfill(PIN_ZERO_PAD_LENGTH)
            existing_padded = employee.objects.filter(PIN=padded_pin).exclude(pk=emp.pk).first()

            tpl_count = fptemp.objects.filter(UserID=emp).count()
            trx_count = transaction.objects.filter(UserID=emp).count()

            self.stdout.write(f"PIN={emp.PIN!r} (pk={emp.pk}, nama={emp.EName!r})")
            self.stdout.write(f'  Fingerprint Template terkait: {tpl_count} | Transaction terkait: {trx_count}')
            if existing_padded:
                self.stdout.write(self.style.ERROR(
                    f"  KEMUNGKINAN DUPLIKAT dari Employee PIN={padded_pin!r} (pk={existing_padded.pk}, "
                    f"nama={existing_padded.EName!r}) -- kemungkinan besar ini akibat bug lama sebelum "
                    f"normalize_pin(), keduanya merujuk ke orang yang sama."
                ))
            else:
                self.stdout.write(
                    f"  Tidak ada Employee lain dengan PIN={padded_pin!r} -- kemungkinan aman di-rename "
                    f"manual jadi zero-padded kalau memang perlu, tidak akan bentrok."
                )
            self.stdout.write('')

        self.stdout.write(self.style.NOTICE(
            'Command ini CUMA melaporkan, TIDAK mengubah/menghapus data apapun. Kalau ada yang perlu '
            'digabung (mis. pindahkan Fingerprint Template & Transaction dari PIN lama ke PIN '
            'zero-padded yang benar, lalu hapus record duplikatnya), lakukan manual & hati-hati.'
        ))
