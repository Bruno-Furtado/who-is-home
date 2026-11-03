<p align="center">
  🇺🇸 <a href="README.md">English</a> · 🇧🇷 <a href="README_pt-BR.md">Português</a> · 🇨🇳 <b>中文</b>
</p>

# who-is-home

**家庭网络里有谁、用了多久、访问了什么。** 与 [AdGuard Home](https://github.com/AdguardTeam/AdGuardHome)（最好再加上 [down-again](https://github.com/Bruno-Furtado/down-again)）运行在同一台长期开机的电脑上，并在适合手机浏览的面板中展示一切。

## 功能

- 🟢 **实时设备**：当前谁在线、从什么时候开始、最后一次出现的时间。
- 🏷️ **真实名称**：通过 Bonjour（mDNS）、NetBIOS 和 AdGuard 客户端发现；可重命名并选择类型。
- ⏱️ **估算使用时长**：按设备、按小时、按类别（社交、视频、游戏、工作……）。
- 🌐 **访问最多**和**已拦截**的网站（广告与追踪器）。
- 🌙 **深夜使用**：零点到 6 点之间谁在上网。
- 🔔 **手机通知**（ntfy）：新设备加入，以及每周日晚上的周报。
- 📶 **互联网**：来自 down-again 的状态、断线和网速。
- 🪶 **零依赖**：只需 Python 3.8+。即使外网中断，面板也能打开。

## 安装

需要 AdGuard Home 在本机运行，并已设为网络的 DNS（在路由器的 DHCP 中）。

```bash
git clone https://github.com/Bruno-Furtado/who-is-home.git ~/who-is-home
cd ~/who-is-home
python3 who_is_home.py setup      # AdGuard 用户名和密码
python3 who_is_home.py check      # 检查 AdGuard、网络扫描和 down-again
python3 who_is_home.py install    # 每次登录 Mac 时自动启动
```

## 隐私

数据只保存在本机的 `dados/` 中（只有你的用户可以读取）。只能看到网站名称，看不到内容。如果其他人使用这个网络，请告知他们查询会被记录。

面板**没有密码**：Wi-Fi 中的任何设备都能打开。请让访客使用访客网络，或设置 `"bind": "127.0.0.1"` 只允许本机访问。切勿将端口暴露到互联网。

## 许可证

MIT
