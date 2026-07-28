dd=$1
if [ -z "$dd" ]; then
    dd=0
fi
cat /var/log/mail.log|grep "`date +%b" "%e -d "-$dd day"`"