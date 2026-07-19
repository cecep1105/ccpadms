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
            from iclock.models import department
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
                pool = r._mapping[iclock.c.POOL]

                try:
                    dept = department.objects.get(DeptName=pool)
                except Exception as e:
                    print(e)
                    dept = department(
                        DeptID = i,
                        DeptName = pool,
                        NetID = netid,
                        DeptRouter = router,
                        DeptSubnet = network
                    )
                    dept.save()

                    print(f"{i},{pool},{netid},{router},{network}")









