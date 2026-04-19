{ config, lib, pkgs, ... }:
let
  ip = "${pkgs.iproute2}/bin/ip";
in
{
  networking = {
    hostName = "mugge";

    # US-156: Static route to dev machine subnet via gateway host.
    # Uses dhcpcd exit hook instead of networking.interfaces.end0.ipv4.routes
    # because the latter generates a systemd unit that runs BEFORE dhcpcd
    # assigns an IP, failing with "Nexthop has invalid gateway."
    dhcpcd.runHook = ''
      if [ "$interface" = "end0" ] && [ "$reason" = "BOUND" -o "$reason" = "REBOOT" -o "$reason" = "RENEW" -o "$reason" = "REBIND" ]; then
        if ! ${ip} route show 192.168.105.0/24 | grep -q .; then
          ${ip} route add 192.168.105.0/24 via 192.168.178.26 dev end0 || true
        fi
      fi
    '';

    # nftables firewall (matches US-000a hardening)
    nftables.enable = true;
    firewall = {
      enable = true;
      allowedTCPPorts = [ 22 5900 8080 ];  # SSH, wayvnc, web-ui
      allowedUDPPorts = [ 5353 ];           # mDNS
    };
  };

  # SSH hardening — key-only, no root login
  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      PermitRootLogin = "no";
    };
  };

  # mDNS via avahi — hostname resolution on local network
  services.avahi = {
    enable = true;
    nssmdns4 = true;
    publish = {
      enable = true;
      addresses = true;
    };
  };
}
