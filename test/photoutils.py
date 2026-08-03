
from django.conf import settings
import pyodbc


def kbagetphotodriver(nip):
    try:
        data = ''
        cnxn = pyodbc.connect(settings.KBAPHOTO_CONNECTION_STRING, autocommit=True
        )
        ccursor = cnxn.cursor()
        sql = "SET TEXTSIZE 2147483647;"
        sql += f"SELECT id_absen, namapengemudi,Photo,Photo3 FROM dbo.MSDriverKBA WHERE id_absen='{nip}'"
        ccursor.execute(sql)
        fields = map(lambda x:x[0], ccursor.description)
        result = [dict(zip(fields,row)) for row in ccursor.fetchall()]
        for a in result:
            data = a['Photo']

        return data
    except:
        return None


def ftpdir(ftploc, path, NIK):
    from storages.backends.ftp import FTPStorage
    import ftplib

    fs = FTPStorage(location=ftploc)
    config = fs._config
    ftp = ftplib.FTP(config['host'])
    lsphoto = []

    try:
        ftp.login(config['user'],config['passwd'])
        ls = []
        ftp.retrlines(f"LIST {path}", ls.append)
        for l in ls:
            if NIK in l:
                inik = l.find(NIK)
                lsphoto.append(l[inik:])
    except Exception as e:
        print(ftploc)
        print(e)
    return lsphoto

def getphoto(NIK, template=None):
    from storages.backends.ftp import FTPStorage
    import base64
    resp = ''

    fnames = []
    images = []
    if template == "DRIVER-HU":
        ftploc = settings.FTP2
        counter = 0
        for dir in ['dataphotosopir/newphoto', 'dataphotosopir/originazise']:
            flist = ftpdir(ftploc, dir, NIK)
            for fn in flist:
                imagedet = {}
                fnames.append("%s/%s" % (dir, fn))
                fs = FTPStorage(location=f"{ftploc}{dir}/")
                image = fs._open(f"{fn}").read()
                strimage = "data:image/jpeg;base64,%s" % (base64.b64encode(image).decode())
                imagedet['counter'] = counter
                imagedet['path'] = fn
                imagedet['data'] = strimage
                imagedet['nik'] = NIK
                imagedet['source'] = 'FTP2'
                images.append(imagedet)
                counter += 1
    elif template == "DRIVER-KBA":
        counter = 0
        photo = kbagetphotodriver(NIK)
        fn = photo
        imagedet = {}
        fnames.append("%s" % (fn))
        strimage = "data:image/jpeg;base64,%s" % fn
        imagedet['counter'] = counter
        imagedet['path'] = ''
        imagedet['data'] = strimage
        imagedet['nik'] = NIK
        imagedet['source'] = 'FTP2'
        images.append(imagedet)
    elif template == "DRIVERONLINE":
        ftploc = settings.FTP1
        counter = 0
        for dir in ['photoinput']:
            flist = ftpdir(ftploc, dir, NIK)
            for fn in flist:
                imagedet = {}
                fnames.append("%s/%s" % (dir, fn))
                fs = FTPStorage(location=f"{ftploc}{dir}/")
                image = fs._open(f"{fn}").read()
                strimage = "data:image/jpeg;base64,%s" % (base64.b64encode(image).decode())
                imagedet['counter'] = counter
                imagedet['path'] = fn[:5] + '|' + fn[6:-4].replace('_', ' ').upper()
                imagedet['data'] = strimage
                imagedet['nik'] = NIK
                imagedet['source'] = 'FTP1'
                images.append(imagedet)
                counter += 1
    else:
        ftploc = settings.FTP1
        counter = 0
        for dir in ['photo', 'photoinput', 'phototemp', 'photocrop']:
            flist = ftpdir(ftploc, dir, NIK)

            for fn in flist:
                imagedet = {}
                fnames.append("%s/%s" % (dir, fn))
                fs = FTPStorage(location=f"{ftploc}{dir}/")
                image = fs._open(f"{fn}").read()

                imgformat = fn[-3:].upper()
                if imgformat == 'PNG':
                    strimage = "data:image/png;base64,%s" % (base64.b64encode(image).decode())
                else:
                    strimage = "data:image/jpeg;base64,%s" % (base64.b64encode(image).decode())

                imagedet['counter'] = counter
                imagedet['dir'] = dir
                imagedet['path'] = fn
                imagedet['data'] = strimage
                imagedet['nik'] = NIK
                imagedet['source'] = 'FTP1'
                images.append(imagedet)
                counter += 1

    if len(images) == 0:
        ftploc = settings.FTP3
        counter = 0
        dir = ''
        if NIK[:1] in '4': dir = 'DRIVERKBA'
        flist = ftpdir(ftploc, dir, NIK)
        for fn in flist:
            imagedet = {}
            fnames.append("%s/%s" % (dir, fn))
            fs = FTPStorage(location=f"{ftploc}{dir}/")
            try:
                image = fs._open(f"{fn}").read()
                strimage = "data:image/jpeg;base64,%s" % (base64.b64encode(image).decode())
                imagedet['counter'] = counter
                imagedet['path'] = fn
                imagedet['data'] = strimage
                imagedet['nik'] = NIK
                imagedet['source'] = 'FTP3'
                images.append(imagedet)
            except Exception as e:
                strimage = ''
    return images



