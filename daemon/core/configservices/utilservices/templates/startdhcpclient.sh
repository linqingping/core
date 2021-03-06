#!/bin/sh
# auto-generated by DHCPClient service (utility.py)
# uncomment this mkdir line and symlink line to enable client-side DNS\n# resolution based on the DHCP server response.
#mkdir -p /var/run/resolvconf/interface
% for ifname in ifnames:
#ln -s /var/run/resolvconf/interface/${ifname}.dhclient /var/run/resolvconf/resolv.conf
dhclient -nw -pf /var/run/dhclient-${ifname}.pid -lf /var/run/dhclient-${ifname}.lease ${ifname}
% endfor
