from flask import Flask, request,make_response,current_app, json, jsonify
from werkzeug.exceptions import HTTPException
from functools import update_wrapper
from datetime import timedelta
from flask_restful import Resource, Api
import sys
import os

app = Flask(__name__)
api = Api(app)
port = 5100

if sys.argv.__len__() > 1:
	port = sys.argv[1]


print("Api running on port : {} ".format(port))

# flask_app = Flask(__name__)

def _build_cors_preflight_response():
	response = make_response()
	response.headers.add("Access-Control-Allow-Origin", "*")
	response.headers.add("Access-Control-Allow-Headers", "*")
	response.headers.add("Access-Control-Allow-Methods", "*")
	return response

def _corsify_actual_response(response):
	response.headers.add("Access-Control-Allow-Origin", "*")
	return response

def humanbytes(B):
		"""Return the given bytes as a human friendly KB, MB, GB, or TB string."""
		ret = ''
		try:
			B = float(B)
			KB = float(1024)
			MB = float(KB ** 2) # 1,048,576
			GB = float(KB ** 3) # 1,073,741,824
			TB = float(KB ** 4) # 1,099,511,627,776

			if B < KB:
					return '{0} {1}'.format(B,'Bytes' if 0 == B > 1 else 'Byte')
			elif KB <= B < MB:
					return '{0:.0f} KB'.format(B / KB)
			elif MB <= B < GB:
					return '{0:.0f} MB'.format(B / MB)
			elif GB <= B < TB:
					return '{0:.0f} GB'.format(B / GB)
			elif TB <= B:
					return '{0:.0f} TB'.format(B / TB)
		except:
			return ret

# @corsapp_route('/', methods=['GET'], origin=['*'])

# @flask_app.route("/", methods=["GET", "OPTIONS"])

def getdetaillogs(qid):
	import subprocess
	s = subprocess.Popen(["logd|grep -v amavis| grep '%s' " % qid],shell=True,stdout=subprocess.PIPE).stdout
	lines = s.read().splitlines()
	return lines

def gettodaylogs():
	import subprocess
	import datetime
	s = subprocess.Popen(["logd|grep 'from=' "],shell=True,stdout=subprocess.PIPE).stdout
	lines = s.read().splitlines()
	currentlogs = []
	for l in lines:
		line = l.split()
		date = '%s %s %s %s' %(datetime.datetime.now().strftime('%Y'),line[0],line[1],line[2])
		date = datetime.datetime.strptime(date,'%Y %b %d %H:%M:%S')
		qid = line[5][:-1]
		sender = line[6][6:-2]
		size=line[7][5:-1]
		total_recipient=0
		try: total_recipient=line[8][6:]
		except: pass

		if qid == 'NOQUEUE':
			continue
		if sender == '':
			sender = line[6][5:-1] 
		if sender == '0':
			continue
		
		currentlogs.append({
			'date': date.strftime('%Y/%m/%d_%H:%M:%S'),
			'qid': qid,
			'sender': sender,
			'total_recp': total_recipient,
			'size': size
		})
		
	return currentlogs

def getmaillog(date_from,date_to):
	import pymysql
	# import socket, struct
	import ipaddress
	print(date_from,date_to)
	conn = pymysql.connect('127.0.0.1','zentyal','!@8v28972n','zentyal', cursorclass=pymysql.cursors.DictCursor)
	query = "select * from mail_message where timestamp BETWEEN '%s' AND '%s' " %( date_from, date_to)
	cursor = conn.cursor()
	ret = cursor.execute(query)
	result = cursor.fetchall()
	rs = []
	for log in result:
		# int_ip = log[u'client_host_ip']
		# print(ipaddress.ip_address(int_ip))
		qid=''
		try: qid = log[u'message'].split('queued as')[1].strip()
		except: pass
		rs.append({
			'status': log[u'status'] , 
			'client_host_ip': str(ipaddress.ip_address(int(log[u'client_host_ip']))), 
			'from_address': log[u'from_address'] ,
		  'relay': log[u'relay'], 
			'timestamp': log[u'timestamp'].strftime('%Y/%m/%d_%H:%M:%S') , 
			'client_host_name': log[u'client_host_name'], 
			'event': log[u'event'], 
			'message_size': log[u'message_size'], 
			'qid': qid,
			'to_address': log[u'to_address'], 
			'message': log[u'message'], 
			'message_type': log[u'message_type'], 
			'message_id': log[u'message_id'],

		})
	return rs	


def getmailq():
	import subprocess
	import sys

	cmd = subprocess.Popen(['mailq'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	stdout, stderr = cmd.communicate()
	if cmd.returncode not in (0, 69):
		print >>sys.stderr, 'Error: mailq failed: "{}"'.format(stderr.strip())

	mq = stdout.strip()
	curmsg = None
	msgs = {}
	for index, line in enumerate(mq.splitlines()):
		if not line or line[:10] == '-Queue ID-' or line[:2] == '--':
			continue
		if line[0] in '0123456789ABCDEF':
			s = line.split()
			curmsg = s[0]
			if curmsg[-1] == '*':
				status = 'active'
				curmsg = curmsg[:-1]
			else:
				status = 'deferred'
			msgs[curmsg] = {
				'size': s[1],
				'rawdate': ' '.join(s[2:6]),
				'sender': s[-1],
				'recipient': [],
				'reason': '',
				'status': status,
			}
		elif '@' in line and '<' not in line: # XXX: pretty dumb check
				# if mq.splitlines()[index] not in msgs[curmsg]['recipient']:
					# msgs[curmsg]['recipient'].append(mq.splitlines()[index])
					# print(curmsg, mq.splitlines()[index])				
				# msgs[curmsg]['recipient'].append(line.strip())
				msgs[curmsg]['recipient'].append(line.strip())
				# msgs[curmsg]['recipient'] = list(set(msgs[curmsg]['recipient']))

		elif line.lstrip(' ')[0] == '(':
				msgs[curmsg]['reason'] = line.strip()[1:-1].replace('\n', ' ')
		else:
			# print(line)
			print >> sys.stderr, 'Error: Unknown line in mailq output: %s' % line

		# print(curmsg,list(set(msgs[curmsg]['recipient']))) 

	mmq = []
	for k in msgs.keys():
		mmq.append({
			'id': k,
			'size': msgs[k]['size'],
			'rawdate': msgs[k]['rawdate'],
			'sender': msgs[k]['sender'],
			# 'recipient': " ".join(msgs[k]['recipient'][1:]),
			'recipient': " ".join(list(set(msgs[k]['recipient']))),
			'reason': msgs[k]['reason'],
			'status': msgs[k]['status']

		})

	return mmq

class MailTransport(Resource):
	def get(self):
		import subprocess

		if request.method == "OPTIONS": # CORS preflight
			return _build_cors_preflight_response()
		else:
			s = subprocess.Popen(["logd|grep \"rip=192.168\"|awk '{print $8 $10}'|sort|uniq"],shell=True,stdout=subprocess.PIPE).stdout
			mailip = s.read().splitlines()
			maildata = filter(lambda x: 'user' in x, mailip)
			maildata = list(map(lambda y: {'user': y.split(',')[0][6:-1], 'ip': y.split(',')[1][4:]},maildata))
			return {'result': maildata}
			# return _corsify_actual_response(jsonify({'result': maildata}))


class IPViaEmail(Resource):
	def get(self):
		import subprocess

		if request.method == "OPTIONS": # CORS preflight
			return _build_cors_preflight_response()
		else:
			s = subprocess.Popen(["logd|grep \"rip=192.168\"|awk '{print $8 $10}'|sort|uniq"],shell=True,stdout=subprocess.PIPE).stdout
			mailip = s.read().splitlines()
			maildata = filter(lambda x: 'user' in x, mailip)
			maildata = list(map(lambda y: {'user': y.split(',')[0][6:-1], 'ip': y.split(',')[1][4:]},maildata))
			return {'result': maildata}
			# return _corsify_actual_response(jsonify({'result': maildata}))

class POSTFIX(Resource):
	def get(self):
		import subprocess
		import datetime
		command = request.args.get('command','')
		res = ''
		if command == '':
			return {'result': res}
		
		elif command == 'today_log':
			todaylogs = gettodaylogs()
			return { 'result': todaylogs }
		
		elif command == 'detail_log':
			qid = request.args.get('qid','')
			print(qid)
			if qid == '':
				return { 'result': [] }
			detaillogs = getdetaillogs(qid)
			return { 'result': detaillogs }
		
		elif command == 'mail_log':
			date_from = request.args.get('date_from', datetime.datetime.now().strftime("%Y-%m-%d 00:00:00"))
			date_to = request.args.get('date_to',datetime.datetime.now().strftime("%Y-%m-%d 23:59:59"))
			maillog = getmaillog(date_from,date_to)
			return { 'result':  maillog }

		elif command == 'transport_map':
			ret = []
			p = subprocess.Popen(['cat /etc/postfix/acls/transport'],shell=True,stdout=subprocess.PIPE)
			out, err = p.communicate()
			lines = [x.strip() for x in out.splitlines()]
			for item in lines:
				try: domain,target = item.split('\t')
				except: continue
				status = '0' if '#' in domain else '1'
				domain = domain[1:] if '#' in domain else domain
				ret.append({
					"domain": domain,
					"target": target,
					"status": status
				})
			return jsonify({ 'result': ret})
		elif command == 'blocksenders_map':
			ret = []
			p = subprocess.Popen(['cat /etc/postfix/conf/blocksenders.regxp'],shell=True,stdout=subprocess.PIPE)
			out, err = p.communicate()

			lines = [x.strip() for x in out.splitlines()]
			print(lines)
			for item in lines:
				try: email,action = item.split('\t')
				except Exception as e:
					print(e)
					continue
				status = '0' if '#' in email else '1'
				ret.append({
					"email": email[2:-2],
					"action": action,
					"status": status
				})
			return jsonify({ 'result': ret})
		elif command == 'qheader':
			qid = request.args.get('qid','')			
			if qid == '':
				return { 'result': [] }
			
			s = subprocess.Popen(["postcat -h -q %s" % qid],shell=True,stdout=subprocess.PIPE).stdout
			lines = s.read().splitlines()
			return { 'result': lines }

		else:
			return {'result': res}			
	

		return {'result': res}
	
	def post(self):
		import subprocess
		print(request.json['command'])
		command = ''
		try: command = request.json['command']
		except: pass
		res = ''
		if command == '':
			return {'result': res}
		elif command in ['reload','flush']:
			cmd = 'postfix %s' % command
			p = subprocess.Popen([cmd],shell=True,stdout=subprocess.PIPE)
			out, err = p.communicate()
			return {'result': p.returncode }
		elif command == 'get_transport':
			ret = []
			p = subprocess.Popen(['cat /etc/postfix/acls/transport'],shell=True,stdout=subprocess.PIPE)
			out, err = p.communicate()

			lines = [x.strip() for x in out.splitlines()]
			for item in lines:
				try: domain,target = item.split('\t')
				except: continue
				status = '0' if '#' in domain else '1'
				domain = domain[1:] if '#' in domain else domain
				ret.append({
					"domain": domain,
					"target": target,
					"status": status
				})
			return jsonify({ 'result': ret})
		elif command == 'set_transport':
			ret = []
			transport_data = request.json.get('transport_data',[])
			if len(transport_data) >0:
				tempdata = ''
				for itemdata in transport_data:
					tempdata = tempdata + "%s%-30s\t%s\n" % ('#' if not itemdata['status'] else '',itemdata['domain'],itemdata['target'])
				with open('/etc/postfix/acls/transport','w') as f:
					f.write(tempdata)

				p = subprocess.Popen(['cat /etc/postfix/acls/transport'],shell=True,stdout=subprocess.PIPE)
				out, err = p.communicate()

				lines = [x.strip() for x in out.splitlines()]
				for item in lines:
					domain,target = item.split('\t')
					status = '0' if '#' in domain else '1'
					domain = domain[1:] if '#' in domain else domain
					ret.append({
						"domain": domain[0],
						"target": target,
						"status": status
					})
				p = subprocess.Popen(['postmap /etc/postfix/acls/transport'],shell=True,stdout=subprocess.PIPE)
				stdout, stderr = p.communicate()
				print('postfix-postmap :', p.returncode)
				p = subprocess.Popen(['postfix reload'],shell=True,stdout=subprocess.PIPE)
				stdout, stderr = p.communicate()
				print('postfix-reload: ', p.returncode)
				p = subprocess.Popen(['postfix flush'],shell=True,stdout=subprocess.PIPE)
				stdout, stderr = p.communicate()
				print('postfix-flush: ', p.returncode)
			return jsonify({ 'result': ret})
		elif command == 'set_blocksenders':
			ret = []
			email = request.json.get('email','')
			if email != '':
				_email = '/^%s$/\tREJECT' % email
				p = subprocess.Popen(["echo '%s' >> /etc/postfix/conf/blocksenders.regxp" %_email ],shell=True,stdout=subprocess.PIPE)
				stdout, stderr = p.communicate()
		elif command == 'add_biznet_transport':
			ret = []
			domain = request.json.get('domain','')
			if domain != '':
				p = subprocess.Popen(['bash /opt/skrip/addtransport.sh %s Y' %domain],shell=True,stdout=subprocess.PIPE)
				stdout, stderr = p.communicate()
				print(stdout)
		else:
			return {'result': res}			

class MailQ(Resource):
	def get(self):
		import json
		mmq = getmailq()
		imaplogs = []
		try:
			with open('/var/emailext/imaplog.json','r') as jsonfile:
				data = json.load(jsonfile)
				imaplogs = data['result']
		except Exception as e:
			print(e)
		return {'result': mmq, 'imaplogs': imaplogs}
	
	def post(self):
		import subprocess
		import json
		qids = request.json.get('qids',[])
		sender = request.json.get('sender','')
		if qids == [] and sender == '':
			return { 'result': 'qids harus diisi'}
		
		command = request.json.get('command', 'DELETE')

		if command == 'DELQFROMSENDER':
			cmd = "mailq | tail -n +2 | awk 'BEGIN {RS=\"\"} /%s/ {print $1}' | tr -d '*!' | postsuper -d -" % (sender)
			s = subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE).stdout
		else:
			for qid in qids:
				if command == 'DELETE':
					cmd = "postsuper -d %s" % qid
				elif command == 'REQUEUE':
					cmd = "postsuper -r %s" % qid
				s = subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE).stdout
				rs = s.read().splitlines()

		mmq = getmailq()
		return {'result': mmq}

class ImapLogs(Resource):
	def get(self):
		import subprocess
		import datetime
		maildata = []
		time = 'minute'
		arg = request.args.to_dict()
		try:
			time = arg['time']
		except: pass
		if time == 'day':
			filter = 'date +%b" "%e'
		elif time == 'hour':
			filter = 'date +%b" "%e" "%H:'
		else:
			filter = 'date +%b" "%e" "%H:%M'

		if request.method == "OPTIONS": # CORS preflight
			return _build_cors_preflight_response()
		else:
			# s = subprocess.Popen(['logd|grep "`date +%b" "%e" "%k:%M`"|grep imap-login|grep -v Aborted|grep failed|grep -v rip=127.0.0.1'],shell=True,stdout=subprocess.PIPE).stdout
			s = subprocess.Popen(['logd|grep "`%s`"|grep imap-login|grep -v Aborted|grep failed|grep -v rip=127.0.0.1' % filter],shell=True,stdout=subprocess.PIPE).stdout

			logs = s.read().splitlines()
			# print(logs)
			logdata=[]
			for y in logs:
				try:
					logdata.append({
						'notes': y.split(':')[4],
						'email': y.split(',')[1].split('=')[1][1:-1], 
						'date': y.split('mail')[0],
						'ip': y.split(',')[3].split('=')[1]
					})
				except Exception as e:
					logdata.append({
						'notes': y.split(':')[4],
						'email': '', 
						'date': y.split('mail')[0],
						'ip': y.split(',')[0].split('=')[1]
					})
					# print(y)
			logdata = sorted(logdata, key=lambda d: d['date']) 
			return {'result': logdata}

class SASLLogs(Resource):
	def get(self):
		import subprocess
		import datetime
		maildata = []
		time = 'minute'
		arg = request.args.to_dict()
		try:
			time = arg['time']
		except: pass
		if time == 'day':
			filter = 'date +%b" "%e'
		elif time == 'hour':
			filter = 'date +%b" "%e" "%H:'
		else:
			filter = 'date +%b" "%e" "%H:%M'


		if request.method == "OPTIONS": # CORS preflight
			return _build_cors_preflight_response()
		else:
			s = subprocess.Popen(['logd|grep "`%s`"|grep -E "SASL (LOGIN|PLAIN) authentication failed"' % filter],shell=True,stdout=subprocess.PIPE).stdout
			logs = s.read().splitlines()
			logdata=[]
			for y in logs:
				try:
					notes = y.split(':')[5]
					date = y.split('mail')[0]
					ip = y.split(':')[4].split('[')[1][0:-1]
					count = 1
					if not any(d['ip'] == ip for d in logdata):			
						logdata.append({
							'notes': notes,
							'date': date,
							'ip': ip,
							'count': count
						})
					else:
						_cnt = next(item for item in logdata if item["ip"] == ip)['count']
						next(item for item in logdata if item["ip"] == ip)['count'] = _cnt +1
				except Exception as e:
					# logdata.append({
					# 	'notes': y.split()[7],
					# 	'email': '', 
					# 	'date': y.split('mail')[0],
					# 	'ip': y.split(',')[0].split('=')[1]
					# })
					print(y)
			logdata = sorted(logdata, key=lambda d: d['date']) 
			return {'result': logdata}


api.add_resource(IPViaEmail, '/ipviaemail')
api.add_resource(MailQ, '/mailq')
api.add_resource(ImapLogs, '/imaplogs')
api.add_resource(SASLLogs, '/sasllogs')
api.add_resource(POSTFIX, '/postfix')


# api.add_resource(TaskListAPI, '/todo/api/v1.0/tasks', endpoint = 'tasks')
# api.add_resource(UserAPI, '/users/<int:id>', endpoint = 'user')

if __name__ == '__main__':
		app.run(debug=True,host="0.0.0.0", port=port)

