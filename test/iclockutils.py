from django.conf import settings
from django.core.cache import cache

from iclock.models import transaction, employee, iclock
from iclock.hibalib.hiba_dbautils import addInOutDbtms, addtodbtms, namedba, namedbdriverhrc, namedbdriverhiba, getemp35
import datetime
import os

from iclock.ws_utils import wsinfo


def getfolderdata(dev,pin):
	folder = 'TESTING'
	group = ''
	try:
		emp = employee.objects.get(PIN="%s" % pin.zfill(9))
		group = str(emp.AccGroup)[:2]
	except:
		group = ''

	if dev.Function=='KANTIN' or dev.Function=='TESTING':
		folder = dev.Function
	elif group == '80':
		folder = 'KARYAWAN'
	else:
		for fkey in settings.DEVICEFUNCTION.keys():
			if pin[:1]  in fkey:
				folder = settings.DEVICEFUNCTION[fkey]
				break
	return folder

def getname(PIN,name):
	if (PIN[:1] == '8' or PIN[:1] == '9'):
		nama = namedba(PIN)
		if not nama:
			return name
		else:
			return nama
	elif PIN[:1] == '1':
		nama = namedbdriverhiba(PIN)
		if not nama:
			return name
		else:
			return nama

	elif PIN[:1] == '6':
		nama = namedbdriverhrc(PIN)
		if not nama:
			return name
		else:
			return nama
	else:
		return name


def createemployee(dev,pin,nama=""):
	try:
		emp = employee.objects.get(PIN=pin)
		return emp
	except:
		name = getname(pin[2:],nama)
		emp = employee(PIN=pin,EName=name,SN=dev,UTime=datetime.datetime.now())
		emp.save()

		return emp

def writeattdata(dev,data):
	currline=""
	# for line in data.split("\n"):
	for line in data:
		if line:
			if line==currline:
				# print("duplicat data")
				continue
			else:
				# print("no duplicat")
				currline=line
				# print(line)
				addtostream(dev,line)


def addtostream2(dev,data):
	ls = data.split("\t")
	print(len(ls))


def addtostream(devSN, data):
	dev = iclock.objects.get(SN=devSN)
	ls = data.split("\t")
	print(data)
	ppin = ls[0]
	lpin = "%s" % ppin.zfill(9)
	nama = ""
	try:
		nm = employee.objects.get(PIN=lpin)
		nama = nm.EName
	except:
		nama = ""

	if len(ppin) == 7 or len(ppin) == 8:
		if not nama.strip():
			if (ppin[:1] == "8" or ppin[:1] == "9"):
				try:
					nama = namedba(ppin)
					nm.EName = nama
					nm.save
				except:
					pass
			elif (ppin[:1] == "6"):
				try:
					nama = namedbdriverhrc(ppin)
					nm.EName = nama
					nm.save
				except:
					pass
			elif (ppin[:1] == "1"):
				try:
					nama = namedbdriverhiba(ppin)
					nm.EName = nama
					nm.save
				except:
					pass
			else:
				nama = ppin

			if nama == ppin:
				pass
			else:
				employee.objects.filter(PIN=lpin).update(EName=nama)

		dt = ls[1]
		eventcode = ls[2]
		verify = ls[3]
		tgl = dt.split(" ")[0]
		blnthn = tgl.split("-")[1] + tgl.split("-")[0]
		thnblntgl = tgl.split("-")[0] + tgl.split("-")[1] + tgl.split("-")[2]
		devfun = ""
		devpool = ""
		if dev.Function:
			devfun = dev.Function
		else:
			devfun = dev.SN

		if dev.DeptID:
			devpool = dev.DeptID.DeptName
		else:
			devpool = dev.SN

		data_dir =  '%s/data' % settings.BASE_DIR
		masterlog_dir = '%s/data/masterlog' % settings.BASE_DIR
		folder = "%s/%s/%s" % (data_dir, getfolderdata(dev, ppin), blnthn)
		folderhcp = "%s/%s/%s" % (data_dir, getfolderdata(dev, ppin), "mesinfinger")
		folderhcpwithsn = "%s/%s/%s" % (data_dir, getfolderdata(dev, ppin), "mesinfingerwithsn")
		foldertesting = "%s/%s/%s" % (data_dir, getfolderdata(dev, ppin), "testing")


		masterlog_folder = "%s/%s" % (masterlog_dir, blnthn)
		filename = "%s/%s.txt" % (folder, devpool)
		filename2 = "%s/%s.txt" % (folder, thnblntgl)
		filename3 = "%s/%s.txt" % (folderhcp, thnblntgl)
		filename4 = "%s/%s.txt" % (folderhcpwithsn, thnblntgl)
		logabsen = "%s/%s.txt" % (masterlog_folder, tgl.split("-")[2])
		datefilename = "%s/%s.txt" % (folder, tgl.split("-")[2])

		for fld in [masterlog_folder,folder,folderhcp,folderhcpwithsn]:
			if not os.path.exists(fld):
				os.makedirs(fld)

		dt1 = datetime.datetime.strptime(dt, "%Y-%m-%d %X")
		checktype = eventcode
		CT = 'I'
		if eventcode == '0':
			checktype = "C/In"
			CT = 'I'
		if eventcode == '1':
			checktype = "C/Out"
			CT = 'O'



		# if dev.Function ==

		writelineonce(filename,
					  "%s  %s      %s   %s" % (ppin, dt1.strftime("%d/%m/%Y"), dt1.strftime("%H:%M"), checktype))
		writelineonce(datefilename,
					  "%s  %s      %s   %s" % (ppin, dt1.strftime("%d/%m/%Y"), dt1.strftime("%H:%M"), checktype))
		writelineonce(filename2, "%s,%s,%s,%s" % (ppin, dt1.strftime("%d/%m/%Y"), dt1.strftime("%H:%M"), checktype))
		writelineonce(filename3, "%s,%s,%s,%s" % (ppin, dt1.strftime("%d/%m/%Y"), dt1.strftime("%H:%M"), checktype))
		writelineonce(filename4,
					  "%s,%s,%s,%s,%s" % (dev.SN if len(verify) == 1 else verify, ppin, dt1.strftime("%d/%m/%Y"), dt1.strftime("%H:%M"), checktype))
		writelineonce(logabsen,
					  "%s,%s,%s %s,%s" % (dev.SN if len(verify) == 1 else verify, ppin, dt1.strftime("%d/%m/%Y"), dt1.strftime("%H:%M"), eventcode))

		name = ''
###
		if 'nikNames' in cache:
			niknames = cache.get('nikNames')
		else:
			niknames = getemp35('')
			cache.set('nikNames', niknames)

		try: name = list(filter(lambda x: x['badgenumber'] == ppin.zfill(9), niknames))[0]['name']
		except: pass
###

		wsinfo('iclock', 'device_attlog', { 
			'sn': dev.SN, 
			'la': dev.LastActivity.strftime("%Y-%m-%d %H:%M:%S"), 
			'nik':  ppin,
			'name': name,
			'date': dt1.strftime("%d/%m/%Y"),
			'time': dt1.strftime("%H:%M:%S"),
			'type': checktype,
			'source': verify
		})

		try:
			datasend = "1,%s,%s,%s,%s %s,%s" % (
			dev.DeviceName, ppin, nama, dt1.strftime("%d/%m/%Y"), dt1.strftime("%H.%M"), eventcode)
			if settings.LOGATTLOG:
				logevent( 'attlog', datasend)
		except Exception as e:
			print(e)

		try:
			if len(verify)>1:
				_dev = iclock.objects.get(sn=verify)
				emp = createemployee(_dev, lpin)

			else:
				emp = createemployee(dev, lpin)
		except Exception as e:
			print(e)

		try:
			Function = 0

			if dev.Function == 'KANTIN' or dev.Function == 'TESTING':
				Function = dict(map(reversed, settings.DEVICEFUNCTION.items()))[dev.Function]

			elif len(str(emp.AccGroup)) > 1 and str(emp.AccGroup)[:2] == '80':
				Function = '89'

			else:
				Function = ppin[:1]
				for fkey in settings.DEVICEFUNCTION.keys():
					if Function in fkey:
						Function = fkey
						break
			try:
				tr = transaction(UserID=emp, TTime=dt1.strftime("%Y-%m-%d %H:%M"), State=CT, SN=dev, Function=Function)
				tr.save()
			except Exception as e:
				print(e)

			if Function=='1' and settings.MIRROR_ATT_LOG_MOBILE:
				_data = "%s,%s,%s,%s,%s" % (dev.SN,ppin,dt1.strftime("%d/%m/%Y"),dt1.strftime("%H:%M"),checktype)
				_data2 = "%s,%s,%s,%s,%s" % (dev.SN,ppin,dt1.strftime("%m/%d/%Y"),dt1.strftime("%H:%M"),checktype)
				if len(dev.SN) > 7: 
					addtodbtms(_data2)

			if Function == 'X' and settings.MIRROR_ATT_LOG_MOBILE:
				_data2 = "%s,%s,%s,%s,%s" % (dev.SN,ppin,dt1.strftime("%m/%d/%Y"),dt1.strftime("%H:%M"),checktype)
				addInOutDbtms(_data2,'dbGeneral','HRD_AbsenKantin')		


		except Exception as e:
			print(e)
	else:
		dt = ls[1]
		dt1 = datetime.datetime.strptime(dt, "%Y-%m-%d %X")
		eventcode = ls[2]
		verify = ls[3]
		tgl = dt.split(" ")[0]
		blnthn = tgl.split("-")[1] + tgl.split("-")[0]
		thnblntgl = tgl.split("-")[0] + tgl.split("-")[1] + tgl.split("-")[2]
		masterlog_dir = settings.BASE_DIR / "masterlogother"
		masterlog_folder = masterlog_dir / f"{blnthn}"
		# "%s/%s" % (masterlog_dir, blnthn)
		if not os.path.exists(masterlog_folder):
			os.makedirs(masterlog_folder)

		logabsen = "%s/%s.txt" % (masterlog_folder, tgl.split("-")[2])
		writelineonce(logabsen,
					  "%s,%s,%s %s,%s" % (dev.SN, ppin, dt1.strftime("%d/%m/%Y"), dt1.strftime("%H:%M"), eventcode))

def writelineonce(filename, data):
	os.makedirs(os.path.dirname(filename), exist_ok=True)
	try:
		with open(filename, 'r+') as f:
			for line in f:
				line.rstrip()
				if data in line:
					# print("duplicat")
					break
			else:
				f.write("%s\r\n" % data)
	except:
		with open(filename, 'a+') as f:
			f.write("%s\r\n" % data)



def logevent(room,data):
	pass
	return
	# from websocket import create_connection
	# ws = create_connection("ws://localhost:%s/ws/monitoring/%s/" %(request.META['SERVER_PORT'],room))
	# _data = json.dumps({'message': data},separators=(',',':'))
	# ws.send(_data)
	# ws.close()