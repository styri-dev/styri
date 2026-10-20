#!/usr/bin/env bash
# No-egress guard for Styri (Linux, root). Styri runs as uid 10001, so a
# firewall rule matched on that uid sees exactly its traffic, even with
# --network host:
#   allowed  loopback, private LAN ranges, link-local, multicast (DDS discovery)
#   refused  everything else, and DNS to any server (including the local resolver)
#
#   sudo ci/egress-guard.sh start <image>   install rules, prove they block, zero counters
#   sudo ci/egress-guard.sh check           fail if Styri tried to reach anything outside
#   sudo ci/egress-guard.sh stop
set -euo pipefail

UID_STYRI=10001
CHAIN=STYRI_EGRESS

v4_allow=(127.0.0.0/8 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 224.0.0.0/4 255.255.255.255/32)
v6_allow=(::1/128 fe80::/10 fc00::/7 ff00::/8)

rules() {  # $1 = iptables|ip6tables, rest = allowed ranges
  local ipt=$1; shift
  $ipt -N $CHAIN 2>/dev/null || $ipt -F $CHAIN
  for proto in udp tcp; do
    $ipt -A $CHAIN -p $proto --dport 53 -j LOG --log-prefix "STYRI-EGRESS-DNS " --log-uid
    $ipt -A $CHAIN -p $proto --dport 53 -j REJECT
  done
  for net in "$@"; do
    $ipt -A $CHAIN -d "$net" -j ACCEPT
  done
  $ipt -A $CHAIN -j LOG --log-prefix "STYRI-EGRESS " --log-uid
  $ipt -A $CHAIN -j REJECT
  $ipt -C OUTPUT -m owner --uid-owner $UID_STYRI -j $CHAIN 2>/dev/null \
    || $ipt -I OUTPUT 1 -m owner --uid-owner $UID_STYRI -j $CHAIN
}

refused() {  # packets that hit a REJECT rule
  { iptables -L $CHAIN -v -n -x; ip6tables -L $CHAIN -v -n -x; } 2>/dev/null \
    | awk '$3 == "REJECT" { n += $1 } END { print n + 0 }'
}

case "${1:-}" in
  start)
    image=${2:?usage: $0 start <styri image>}
    rules iptables "${v4_allow[@]}"
    rules ip6tables "${v6_allow[@]}"
    # Canaries, as uid 10001: an internet connection and a DNS lookup must both fail.
    canary() {
      docker run --rm --network host --user $UID_STYRI --entrypoint python3 "$image" -c "$1" >/dev/null 2>&1
    }
    if canary "import socket; socket.create_connection(('1.1.1.1', 443), 5)"; then
      echo "guard is not blocking outbound connections"; exit 1
    fi
    if canary "import socket; socket.getaddrinfo('example.com', 443)"; then
      echo "guard is not blocking DNS"; exit 1
    fi
    echo "guard proven: outbound and DNS from uid $UID_STYRI are refused ($(refused) canary packets)"
    iptables -Z $CHAIN && ip6tables -Z $CHAIN
    ;;
  check)
    n=$(refused)
    if [ "$n" -ne 0 ]; then
      echo "::error::Styri tried to reach outside the LAN: $n packet(s) refused"
      { iptables -L $CHAIN -v -n -x; ip6tables -L $CHAIN -v -n -x; } || true
      dmesg 2>/dev/null | grep STYRI-EGRESS | tail -20 || true
      exit 1
    fi
    echo "no egress: Styri sent nothing outside loopback, LAN and multicast"
    ;;
  stop)
    for ipt in iptables ip6tables; do
      $ipt -D OUTPUT -m owner --uid-owner $UID_STYRI -j $CHAIN 2>/dev/null || true
      $ipt -F $CHAIN 2>/dev/null || true
      $ipt -X $CHAIN 2>/dev/null || true
    done
    ;;
  *)
    echo "usage: $0 start <image> | check | stop"; exit 2
    ;;
esac
