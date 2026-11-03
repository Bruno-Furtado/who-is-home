<p align="center">
  🇺🇸 <b>English</b> · 🇧🇷 <a href="README_pt-BR.md">Português</a> · 🇨🇳 <a href="README_zh-CN.md">中文</a>
</p>

# who-is-home

**Who's on your home network, how much they use it and what they access.** Runs on the same always-on computer as [AdGuard Home](https://github.com/AdguardTeam/AdGuardHome) (and, ideally, [down-again](https://github.com/Bruno-Furtado/down-again)) and shows everything on a phone-friendly dashboard.

## Features

- 🟢 **Live devices**: who's on right now, since when, and when each was last seen.
- 🏷️ **Real names**: found via Bonjour (mDNS), NetBIOS and AdGuard clients; rename devices and pick a type.
- ⏱️ **Estimated time in use** per device, per hour and per category (social, video, games, work…).
- 🌐 **Most visited** and **blocked** sites (ads and trackers), per device and overall.
- 🌙 **Late-night use**: who was online between midnight and 6 am.
- 🔔 **Phone alerts** (ntfy): new device on the network and a weekly summary on Sunday evening.
- 📶 **Internet**: status, outages and speed from down-again.
- 🪶 **Zero dependencies**: just Python 3.8+. The dashboard works even with the internet down.

## How it works

1. **Scan**: every minute it pings the network and reads the ARP table to see who's on.
2. **AdGuard Home**: reads the query log through the API and ties each lookup to a device (by MAC).
3. **Time in use**: a minute counts as "in use" when the device looked up sites that aren't automatic system traffic (updates, iCloud, ads…).
4. **Dashboard**: `http://<machine-name>.local:8080`.

Only **site names** are visible, never content, messages or pages (HTTPS hides the rest).

## Install

Requires AdGuard Home running on this machine and set as the network DNS (in the router's DHCP).

```bash
git clone https://github.com/Bruno-Furtado/who-is-home.git ~/who-is-home
cd ~/who-is-home
python3 who_is_home.py setup      # AdGuard user and password; offers down-again's alerts topic
python3 who_is_home.py check      # tests AdGuard, the scan and down-again
python3 who_is_home.py install    # starts by itself whenever you log in to the Mac
```

Settings live in `dados/config.json`; see the Portuguese README for the full table.

## Limitations

Time in use is estimated from DNS lookups. A secondary DNS server, private MAC addresses, per-device encrypted DNS and IPv6 DNS can all hide part of the traffic.

## Privacy

Data stays on this machine, in `dados/` (readable only by your user). If other people use the network, let them know their lookups are recorded.

The dashboard has **no password**: any device on your Wi-Fi can open it. Keep guests on a guest network, or set `"bind": "127.0.0.1"` to open it only on the machine itself. Never expose the port to the internet.

## License

MIT
