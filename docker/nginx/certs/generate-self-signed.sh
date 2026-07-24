#!/bin/sh
# Generate sertifikat SELF-SIGNED -- CUKUP utk testing HTTPS di lokal/LAN
# (browser akan tetap tampilkan peringatan "tidak tepercaya", itu WAJAR
# utk self-signed -- klik "Lanjutkan"/"Advanced -> Proceed" saat testing).
#
# Kalau nanti punya sertifikat ASLI (mis. Sectigo yang sama dipakai
# production, atau Let's Encrypt via domain publik sungguhan), JANGAN
# pakai script ini -- cukup taruh file itu di folder ini dgn nama PERSIS:
#   docker/nginx/certs/fullchain.pem
#   docker/nginx/certs/privkey.pem
# (gabung leaf + intermediate CA jadi 1 file fullchain.pem kalau perlu --
# lihat pembahasan kita soal UNABLE_TO_VERIFY_LEAF_SIGNATURE sebelumnya,
# kasus yang SAMA persis berlaku di sini kalau chain-nya tidak lengkap.)

set -e
cd "$(dirname "$0")"

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout privkey.pem \
  -out fullchain.pem \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

echo ""
echo "Sertifikat self-signed berhasil dibuat:"
echo "  $(pwd)/fullchain.pem"
echo "  $(pwd)/privkey.pem"
echo ""
echo "Berlaku 365 hari. Restart nginx utk memuatnya:"
echo "  docker compose restart nginx"
