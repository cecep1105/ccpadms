import asyncio
from pprint import pprint

from django.core.management.base import BaseCommand, CommandError
import os
from django.conf import settings
from django.db import connections

async def shell(reader, writer):
    rules = [
        ('Login:', 'user'),  # Mengirim username
        ('Password:', 'password'),  # Mengirim password
        ('] >', '/system identity print'),  # Perintah setelah login berhasil
        ('] >', 'quit'),  # Keluar dari session
    ]
    ruleiter = iter(rules)
    expect, send = next(ruleiter)
    while True:
        outp = await reader.read(1024)
        if not outp:
            break
        if expect in outp:
            writer.write(send)
            writer.write('\r\n')
            try:
                expect, send = next(ruleiter)
            except StopIteration:
                break
        # Tampilkan seluruh output server
        print(outp, flush=True)
    print()


class Command(BaseCommand):
    help = "ADMS Tools"

    def add_arguments(self, parser):
        parser.add_argument("cmd", nargs="+", type=str)
        parser.add_argument("params", nargs="+", type=str)

    def handle(self, *args, **options):
        cmd = options['cmd']
        params = options['params']


        if cmd[0] == "DEVS":
            from sqlalchemy import MetaData,Table,select,func,desc,create_engine
            from datetime import datetime, timedelta
            ten_days_ago = datetime.now() - timedelta(days=10)
            engine = create_engine('mysql+pymysql://adms:ad123@172.16.10.35/dbabsen')
            conn = engine.connect()
            metadata = MetaData()
            iclock = Table('absensi_iclock', metadata,autoload_with=engine)
            query = select(iclock).filter(iclock.columns.POOL.notin_(['MOBILE','TEST','TESTING']),
                                                     func.char_length(iclock.columns.SN)>10, 
                                                     func.abs(iclock.columns.LastActivity > ten_days_ago),
                                                     iclock.columns.Function.notin_(['TESTING'])).order_by(desc(iclock.columns.POOL))
            result = conn.execute(query)
            resulset = result.fetchall()
            for i,r in enumerate(resulset,start=1):
                rr = (
                    f"{i},{r._mapping[iclock.c.SN]}, "
                    f"{r._mapping[iclock.c.Name]}, {r._mapping[iclock.c.Function]}, "
                    f"{r._mapping[iclock.c.POOL]},{r._mapping[iclock.c.MAC].upper() if r._mapping[iclock.c.MAC] else  '00:00:00:00:00:00'}, "
                    f"{r._mapping[iclock.c.IPAddress]}, {r._mapping[iclock.c.Address]}"
                )
                print(rr)

        if cmd[0] == "POOLS":
            from sqlalchemy import MetaData,Table,select,func,desc,create_engine
            from datetime import datetime, timedelta
            import ipaddress

            ten_days_ago = datetime.now() - timedelta(days=10)
            engine = create_engine('mysql+pymysql://adms:ad123@172.16.10.35/dbabsen')
            conn = engine.connect()
            metadata = MetaData()
            iclock = Table('absensi_iclock', metadata,autoload_with=engine)
            query = select(iclock).filter(iclock.columns.POOL.notin_(['MOBILE','TEST','TESTING']),
                                                     func.char_length(iclock.columns.SN)>10, 
                                                     func.abs(iclock.columns.LastActivity > ten_days_ago),
                                                     iclock.columns.Function.notin_(['TESTING'])).group_by(iclock.columns.POOL)
            result = conn.execute(query)
            resulset = result.fetchall()
            for i,r in enumerate(resulset,start=1):
                base_ip_string = str(ipaddress.ip_address(r._mapping[iclock.c.IPAddress]))
                ip_octets = base_ip_string.split('.')
                ip_octets[3] = '254'

                router = '.'.join(ip_octets)
                ip_octets[3] = '0/24'
                network = '.'.join(ip_octets)
                netid = ip_octets[2]

                print(f"{i},{r._mapping[iclock.c.POOL]},{netid},{router},{network}")


        if cmd[0] == "coba":
            import sqlalchemy
            engine = sqlalchemy.create_engine('mysql+pymysql://adms:ad123@172.16.10.35/dbabsen')
            conn = engine.connect()
            metadata = sqlalchemy.MetaData()
            iclock = sqlalchemy.Table('absensi_iclock', metadata,autoload_with=engine)
            query = sqlalchemy.select(iclock).filter(iclock.columns.POOL.notin_(['MOBILE','TEST','TESTING']),sqlalchemy.func.char_length(iclock.SN)>10)
            result = conn.execute(query)
            resulset = result.fetchall()
            for r in resulset:
                # 'OID6120056120100264', 'KLDHRC1', 'KARYAWAN', 'KLENDER', 1, datetime.datetime(2024, 12, 3, 13, 41, 58,
                #                                                                               711625), '00:00;14:05', 1, '9999', '9999', None, '192.168.25.94
                row = "%s;%s;%s;%s" % (r[0], r[1], r[2], r[3])


        if cmd[0] == "coba2":
            from apps.iclock.models import department
            dname = params[0].split(';')[0]
            drouter = params[0].split(';')[1]
            dsubnet = params[0].split(';')[2]
            dparent = params[0].split(';')[3]
            dnetid = params[0].split(';')[4]
            dept = department(
                DeptName=dname,
                DeptRouter=drouter,
                DeptSubnet=dsubnet,
                parent=dparent,
                NetID=dnetid
            )
            dept.save()
        if cmd[0] == "coba3":
            with connections['old'].cursor() as cursor:
                query = """ select * from iclock_employee """
                cursor.execute(query)
                row = cursor.fetchall()
                result = row
                print(result)

        if cmd[0] == "copydata":
            from ftplib import FTP
            import pandas as pd
            ftp = FTP('172.16.10.35')
            ftp.login('absen','ab123')

            d2='01/01/2025'
            d1='01/01/2025'
            print(pd.date_range('01/01/2025','01/05/2025'))
            ftpfiles = ["%s/masterlog/%s.txt" % ('djangoapp/mysite', d.strftime('%m%Y/%d')) for d in
                        pd.date_range(d2, d1)]
            for ftpf in ftpfiles:
                print(ftpf)
                r = []
                ftp.retrlines('RETR %s' % ftpf,r.append)
                for line in r:
                    print(line)






