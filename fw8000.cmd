@echo off
netsh advfirewall firewall add rule name="chinatrip_h5_8000" dir=in action=allow protocol=TCP localport=8000 profile=any
