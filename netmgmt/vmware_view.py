"""
Detail per-VM VMware vCenter -- SOAP API (pyVmomi), BUKAN REST.

KENAPA SOAP UTK INI (BEDA dari List Host/VM Guest yang TETAP di Next.js
via REST, lihat nextadms/src/lib/vsphere-client.ts): REST API vCenter
`/rest/vcenter/vm/{vm}` cuma kasih 1 kategori info per-request (hardware
summary SENDIRI, guest identity SENDIRI, disk SENDIRI, dst) -- utk detail
lengkap 1 VM perlu 4-5+ request TERPISAH (N+1 problem). SOAP API py
`PropertyCollector` yang bisa ambil BANYAK property SEKALIGUS dlm SATU
round-trip -- itu SEBABNYA modul ini pakai pyVmomi (SDK resmi VMware utk
Python), bukan menambah lebih banyak call REST dari Next.js.

Scope detail yang diambil (sesuai kebutuhan yang diminta): guest OS/IP/
hostname/tools status + disk & datastore usage -- BUKAN network adapter/
port group (di luar scope saat ini, gampang ditambah nanti kalau perlu).
"""
import ssl  # noqa: F401 -- TIDAK dipakai lagi saat ini (lihat catatan di get_vmware_connection() -- sslContext eksplisit sempat dicoba, TIDAK membantu, dikembalikan ke disableSslCertValidation saja), disimpan sbg referensi kalau nanti perlu didiagnosis lagi

from django.conf import settings
from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim, vmodl
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole
from netmgmt.crypto_utils import NetmgmtCryptoError, decrypt_vmware_password


class VMwareConnectionError(Exception):
    """Gagal terhubung/autentikasi ke vCenter (SOAP)."""


def get_vmware_connection():
    """
    Buka koneksi SOAP ke vCenter -- return `ServiceInstance` (si). WAJIB
    panggil `Disconnect(si)` setelah selesai (lihat pola pemakaian di
    VMwareVmDetailView.get(), pakai try/finally).
    """
    if not settings.VMWARE_HOST:
        raise VMwareConnectionError('VMWARE_HOST belum diisi di .env.')
    if not settings.VMWARE_PASSWORD_ENCRYPTED:
        raise VMwareConnectionError(
            'Password VMware belum diisi (VMWARE_PASSWORD_ENCRYPTED di .env) -- lihat '
            'netmgmt/crypto_utils.py & management command generate_vmware_key/encrypt_vmware_password.'
        )
    try:
        password = decrypt_vmware_password(settings.VMWARE_PASSWORD_ENCRYPTED)
    except NetmgmtCryptoError as exc:
        raise VMwareConnectionError(str(exc)) from exc

    # CATATAN (koreksi LAGI dari percobaan sebelumnya): sempat dicoba
    # bangun ssl.SSLContext EKSPLISIT & teruskan lewat parameter
    # `sslContext` (dugaan disableSslCertValidation saja tidak cukup) --
    # TERNYATA itu TIDAK MEMPERBAIKI apa pun, error SSL yang SAMA tetap
    # muncul. Dikonfirmasi LANGSUNG lewat testing produksi: meneruskan
    # `disableSslCertValidation=True` SAJA (TANPA parameter `sslContext`
    # sama sekali) TERBUKTI BEKERJA -- kemungkinan besar akar masalah
    # SEBENARNYA ada di nilai `settings.VMWARE_ALLOW_SELF_SIGNED_CERT`
    # yang tidak ter-set True spt yg diharapkan (BUKAN soal API pyVmomi-
    # nya) -- kalau masih gagal lagi SETELAH ini, cek dgn:
    #     python manage.py shell -c "from django.conf import settings; print(settings.VMWARE_ALLOW_SELF_SIGNED_CERT)"
    # WAJIB tercetak True.
    try:
        si = SmartConnect(
            host=settings.VMWARE_HOST,
            user=settings.VMWARE_USER,
            pwd=password,
            disableSslCertValidation=settings.VMWARE_ALLOW_SELF_SIGNED_CERT,
        )
    except Exception as exc:  # noqa: BLE001
        raise VMwareConnectionError(f'Gagal terhubung ke vCenter: {exc}') from exc

    return si


def _collect_vm_properties(si, vm_moref, prop_paths):
    """
    Ambil BANYAK property SEKALIGUS (1 round-trip) via PropertyCollector
    -- INILAH keunggulan SOAP API drpd REST (yang perlu request terpisah
    per jenis detail). `prop_paths` -- list path property vSphere API,
    mis. ['guest.ipAddress', 'guest.hostName', 'runtime.powerState'].
    """
    content = si.RetrieveContent()
    collector = content.propertyCollector

    obj_spec = vmodl.query.PropertyCollector.ObjectSpec(obj=vm_moref)
    prop_spec = vmodl.query.PropertyCollector.PropertySpec(type=vim.VirtualMachine, pathSet=prop_paths)
    filter_spec = vmodl.query.PropertyCollector.FilterSpec(objectSet=[obj_spec], propSet=[prop_spec])

    result = collector.RetrieveContents([filter_spec])
    if not result:
        return None
    props = {}
    for prop in result[0].propSet:
        props[prop.name] = prop.val
    return props


def _collect_datastore_summaries(si, datastore_morefs):
    """SAMA prinsipnya spt _collect_vm_properties, TAPI utk BANYAK objek datastore SEKALIGUS (1 round-trip juga, bukan 1 request per datastore)."""
    if not datastore_morefs:
        return {}
    content = si.RetrieveContent()
    collector = content.propertyCollector

    object_specs = [vmodl.query.PropertyCollector.ObjectSpec(obj=ds) for ds in datastore_morefs]
    prop_spec = vmodl.query.PropertyCollector.PropertySpec(type=vim.Datastore, pathSet=['summary'])
    filter_spec = vmodl.query.PropertyCollector.FilterSpec(objectSet=object_specs, propSet=[prop_spec])

    result = collector.RetrieveContents([filter_spec])
    summaries = {}
    for obj_content in result:
        for prop in obj_content.propSet:
            if prop.name == 'summary':
                summaries[obj_content.obj] = prop.val
    return summaries


class VMwareVmDetailView(APIView):
    """
    GET /api/v1/netmgmt/vmware/vm-detail/?vm=<moref id, mis. "vm-100">

    `vm` = ID internal vCenter, SAMA PERSIS dgn field `vm` yang sudah
    dikembalikan REST API (`GET /rest/vcenter/vm`, dipakai halaman List
    VM Guest di Next.js) -- frontend cukup teruskan ID itu apa adanya,
    TIDAK perlu tahu bedanya REST vs SOAP.
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        vm_id = request.query_params.get('vm', '')
        if not vm_id:
            return Response({'error': "Parameter 'vm' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            si = get_vmware_connection()
        except VMwareConnectionError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            vm_moref = vim.VirtualMachine(vm_id, si._stub)

            props = _collect_vm_properties(si, vm_moref, [
                'name',
                'runtime.powerState',
                'guest.guestFullName',
                'guest.hostName',
                'guest.ipAddress',
                'guest.toolsStatus',
                'guest.toolsRunningStatus',
                'config.hardware.numCPU',
                'config.hardware.memoryMB',
                'config.hardware.device',
                'datastore',
            ])
            if props is None or 'name' not in props:
                return Response({'error': f"VM dengan id '{vm_id}' tidak ditemukan di vCenter."}, status=status.HTTP_404_NOT_FOUND)

            disks = []
            for device in props.get('config.hardware.device') or []:
                if isinstance(device, vim.vm.device.VirtualDisk):
                    backing = device.backing
                    disks.append({
                        'label': device.deviceInfo.label if device.deviceInfo else '',
                        'capacity_gb': round(device.capacityInKB / 1024 / 1024, 2),
                        'thin_provisioned': getattr(backing, 'thinProvisioned', None),
                        'datastore_name': backing.datastore.name if getattr(backing, 'datastore', None) else None,
                    })

            datastore_morefs = props.get('datastore') or []
            datastore_summaries = _collect_datastore_summaries(si, datastore_morefs)
            datastores = []
            for ds_moref in datastore_morefs:
                summary = datastore_summaries.get(ds_moref)
                if summary is None:
                    continue
                datastores.append({
                    'name': summary.name,
                    'type': summary.type,
                    'capacity_gb': round(summary.capacity / 1024 ** 3, 2),
                    'free_space_gb': round(summary.freeSpace / 1024 ** 3, 2),
                })

            data = {
                'vm': vm_id,
                'name': props.get('name'),
                'power_state': props.get('runtime.powerState'),
                'guest_full_name': props.get('guest.guestFullName'),
                'guest_hostname': props.get('guest.hostName'),
                'guest_ip_address': props.get('guest.ipAddress'),
                'tools_status': props.get('guest.toolsStatus'),
                'tools_running_status': props.get('guest.toolsRunningStatus'),
                'num_cpu': props.get('config.hardware.numCPU'),
                'memory_mb': props.get('config.hardware.memoryMB'),
                'disks': disks,
                'datastores': datastores,
            }
        except vim.fault.NotFound:
            return Response({'error': f"VM dengan id '{vm_id}' tidak ditemukan di vCenter."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            return Response({'error': f'Gagal mengambil detail VM: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
        finally:
            Disconnect(si)

        return Response(data, status=status.HTTP_200_OK)