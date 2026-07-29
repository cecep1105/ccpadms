#!/bin/bash
# Tampilkan baris /var/log/mail.log utk 1 hari tertentu (default: hari ini).
# Dipanggil sbg "logd" (symlink/alias) oleh zentyalmail.py.
#
# Pemakaian: logd [jumlah_hari_ke_belakang]
#   logd        -> hari ini
#   logd 1      -> kemarin
#   logd 2      -> 2 hari lalu
#
# CATATAN: logic pencocokan tanggal (`date +%b" "%e`) SUDAH diverifikasi
# benar -- padding spasi utk tanggal 1 digit (mis. "Jul  5", 2 spasi)
# PERSIS cocok dgn format timestamp syslog standar, jadi grep-nya akurat.

dd="$1"
if [ -z "$dd" ]; then
    dd=0
fi

# Validasi input -- WAJIB angka bulat non-negatif, TOLAK apa pun selain
# itu (defense in depth -- script ini bisa dipanggil dari proses lain yg
# meneruskan input dari luar, jangan asumsikan selalu dipanggil aman).
case "$dd" in
    ''|*[!0-9]*)
        echo "Error: argumen harus angka bulat non-negatif (jumlah hari ke belakang)." >&2
        exit 1
        ;;
esac

cat /var/log/mail.log | grep "`date +%b" "%e -d "-$dd day"`"
