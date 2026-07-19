
1. Koneksi device ke server menggunakan cache. jadi di table iclock perlu dibuat function save yang 'cache-aware'

2. Untuk options berikut dibuatkan fieldnya di table iclock
Stamp=9999
OpStamp=9999
PhotoStamp=9999
ErrorDelay=60
Delay=30
TransTimes=00:00;14:05
TransInterval=1
TransFlag=1111000000
Realtime=1
Encrypt=0

jadi saat respon pertama, server mengirimkan options sesuai yang ada di database untuk sn yang bersangkutan.

2a. Device yang konek server akan dicheck dulu apakah SN-nya ada di table iclock (activedevice), bila tidak, buat atau update ke table RegisteredDevice dengan DeptID=0, dan tidak dilanjutkan ke proses berikutnya (dengan info SN,Alias (sepertinya ambil dari IPAddress),lastactivity dan field lain yang ada). Jika ada di iclock, make dilanjutkan ke proses berikutnya.

3. Jumlah PIN dari device =7 atau 8 (tidak termasuk prefix '0')

4. 'DB Write Policy' => server menulis log/attlog ke textfile, untuk nulis ke db-nya dilempar ke celery task. Untuk format text yang ditulis seperti file yang ada di folder test/062026.zip. nama filenya: {base_dir}/masterattlog/{MMYYYY}/{DD}.txt (dibuat pathnya tergantu OS => bisa / atau \. 

masteroplog => untuk 'OPLOG'  {base_dir}/masteroplog/{MMYYYY}/{DD}.txt
masterfplog => untuk 'TEMPLATE' jari/face  {base_dir}/masterfplog/{MMYYYY}/{DD}.txt

Untuk attlog yang PIN-nya tidak sesuai nomor 3, logtextnya di {base_dir}/masterattlog_other/{MMYYYY}/{DD}.txt dan tidak dibuatkan task di celery (tidak ditulis ke database). Text 'other' juga berlaku untuk oplog dan fplog (juga tidak ditulis ke database)

5. **UDP notification (port 4374)* => ini perlu (perlu dicoba)
6. **Encryption** => Penasaran dengan option ini, sepertinya perlu dicoba untuk 'security'. Soalanya kalua tidak pake enkripsi gampang dimasukkan data 'fake' kalua menurut saya.
