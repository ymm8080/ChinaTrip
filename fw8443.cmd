@echo off
netsh advfirewall firewall add rule name="chinatrip_h5_8443" dir=in action=allow protocol=TCP localport=8443 profile=any
