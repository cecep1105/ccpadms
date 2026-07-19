import os,time, datetime

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from redis import Redis
from rq import Queue

# from apps.iclock.devview import lineToLog
from iclock.models import getDevice


def parseLogDataInFile(conn,cursor):
    start_time=time.time()
    i=0
    lc=0
    tmp_dir='%s/tmp' % settings.BASE_DIR



    while True:
        if time.time()-start_time>0.1*60: #max live 0.1 minutes
            break
        fcount=0
        files=os.listdir(tmp_dir+"/read")

        lines = None

        for file_name in files:
            if file_name[-4:]==".txt":
                tmp_file="%s/read/%s"%(tmp_dir, file_name)
                print("read data file: ", tmp_file)
                try:
                    lines=open(tmp_file, "r").read()
                except Exception as e:
                    # appendFile(e + 'step 1')

                    continue

                if lines:
                    # lcc, okc=parseATransData(conn, cursor, lines.decode("utf-8").splitlines())
                    lcc, okc = parseATransData(conn,cursor,lines.splitlines())
                    lc += lcc
                    i += okc
                now = datetime.datetime.now()
                new_file = "%s/write/%s/%s" % (tmp_dir, now.strftime("%Y%m%d"), file_name)
                try:
                    import shutil
                    shutil.copy(tmp_file, new_file)
                    os.remove(tmp_file)
                    # os.renames(tmp_file, new_file)
                except Exception as e:
                    print(e)
                    try:
                        os.remove(tmp_file)
                    except Exception as e:
                        # appendFile(e)
                        pass
                fcount += 1

        if fcount == 0:
            print("no transactions in the directory")
            time.sleep(10)

        if lc > 50000:  # Too many records, exit and continue next time
            break
        print("lines: %s, valid: %s, seconds: %s" % (lc, i, int(time.time() - start_time)))
        return i









# def appendFile(s):
#     f=open("%s/info_%s.txt"%(tmpDir(),datetime.datetime.now().strftime("%Y%m%d")), "a+") #ccp
#     try:
#         f.write(s)
#     except:
#         try:
#             f.write(s.encode("utf-8"))
#         except: pass
#     f.write("\n")



def parseATransData(conn, cursor, lines):
    # print(lines)
    l=lines[0]
    try:
        sn=l.split("SN=")[1].split("\t")[0]
        print(sn)
        device=getDevice(sn)
    except:
        device=None
    if device is None:
        print("UNKOWN Device",lines)
    elif ":TRANSACTIONS:" in l:
        return parseATransLogData(device, conn, cursor, lines[1:])

    elif ":OPLOG:" in l:
        print(lines[1:])
        # return parseAOpLogData(device, conn, cursor, lines[1:])
    else:
        print("UNKOWN DATA", lines)
    return (len(lines), 0)


def parseATransLogData(device, conn, cursor, lines):
    print("trans lines count:", len(lines))
    okc=0
    errorLogs=[]  #解析出错、不正确数据的行
    errorLines=[] #发生保存错误的记录
    cacheLines=[] #本次提交的行
    sqls=[]
    lc=0
    for l in lines:
        if not l:
            break
        lc+=1
        eMsg=""; alog=""
        try:
            log=lineToLog(device, l)
        except Exception as e:
            eMsg=u"%s"%e
            errorLogs.append("%s\t--%s"%(l, eMsg))
            log=None
        if log:
            sqls.append(log)
            cacheLines.append(l) #先记住还没有提交数据，commit不成功的话可以知道哪些数据没有提交成功
            print("len cache lines count : %s"%len(cacheLines))
            if len(cacheLines)>=700: #达到700行就提交一次
                try:
                    cursor=commitLog(conn, cursor, sqls)
                    okc+=len(cacheLines)
                    print("\tcommit ", len(cacheLines))
                    alog=cacheLines[0]
                except:
                    errorLines+=cacheLines
                cacheLines=[]
                sqls=[]
#            else:
#                 errorLogs.append("%s\t--%s"%(l, eMsg and eMsg or "Invalid Data"))
    #数据分析已经完成
    if cacheLines: #有还没有提交的数据
        try:
            cursor=commitLog(conn, cursor, sqls)
            okc+=len(cacheLines)
            print("\tcommit last:", len(cacheLines))
            if not alog:
                alog=cacheLines[0]
        except:
            print_exc()
            errorLines+=cacheLines
    if errorLines: #重新保存上面提交失败的数据，每条记录提交一次，最小化失败记录数
        cacheLines=errorLines
        errorLines=[]
        for line in cacheLines:
            if line not in errorLogs:
                try:
                    log=lineToLog(device, line)
                    cursor=commitLog(conn, cursor, log)
                    okc+=1
                    print("\tcommit last error:", line)
                except Exception as e:
                    eMsg=u"%s"%e
                    if "Duplicate" not in eMsg:
                        errorLines.append("%s\t--%s"%(line, eMsg))
    errorLines+=errorLogs
    dlogObj=""
    try:
        if okc==1:
            dlogObj=alog
        elif okc>1:
            dlogObj=alog + ", ..."
    except Exception as e:
            eMsg=u"%s"%e
            errorLines.append("%s\t--%s"%(line, eMsg))
            pass
    log=devlog(SN_id=device.SN, Cnt=okc, ECnt=len(errorLines), Object=dlogObj[:20], OpTime=datetime.datetime.now())
    try:
        log.save()
    except:
        try:
            device.save()
            log.save()
        except Exception as e:
            eMsg=u"%s"%e
            errorLines.append("%s\t--%s"%(line, eMsg))
            pass
    if errorLines:
        tmpFile("transaction_%s_%s.txt"%(device.SN, log.id), "\n".join(errorLines))
    return lc, okc




















def run_writedata(index=0):
    from django.db import connection
    q = Queue(connection=Redis())
    cursor = connection.cursor()
    print("-----------------------Start Writedata %s" % index)
    # if AutoDelTmp:
    #     try:
    #         ret = auto_del()
    #     except Exception as e:
    #         print("--Auto Check&Delete failed!(%s):" % e)
    #         pass
    parseLogDataInFile(connection, cursor)
    try:
        cursor.close()
        connection.close()
    except:
        pass
    q.connection.close()
    print("-----------------------End Writedata %s" % index)


def performPostDataFile(count=10):
    #print"----start?"
    run_writedata(0)