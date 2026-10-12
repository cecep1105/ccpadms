from django.core.management.base import BaseCommand

from django.conf import settings
from iclock.models import transaction,employee,iclock
from iclock.tasks import write_attlog_to_db
import paramiko


class Command(BaseCommand):
    help = 'copy data transaksi dari adms35'

    def add_arguments(self, parser):
        parser.add_argument('--D', default=None, help='tanggal')
        parser.add_argument('--MY', default=None, help='bulan-tahun (MMYYYY)')

    def handle(self, *args, **options):
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(settings.ADMSPROD_HOST,username=settings.ADMSPROD_USERNAME,password=settings.ADMSPROD_PASSWORD)
        sftp = ssh_client.open_sftp()
        sftp.chdir('.')
        remote_base_dir = sftp.getcwd()
        ftpfile = F"{remote_base_dir}/djangoapp/mysite/masterlog/{options['MY']}/{options['D'].zfill(2)}.txt" 

        print(ftpfile) 
        # try:
        with sftp.open(ftpfile,'r') as r:
            for line in r:
                SN, NIK, TTIME, CTYPE = line.strip().split(',')
                try:
                    dev = iclock.objects.get(SN=SN)
                    emp = employee.objects.get(PIN=NIK.zfill(9))
                    print(f"{SN:20}\t{NIK:10}\t{TTIME}\t{CTYPE}|{dev.DeviceName}\t{emp.EName}")
                except Exception as e:
                    print(NIK)

        # except Exception as e:
        #     print(e)