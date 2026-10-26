#!/usr/bin/env bash
# Cài bot đặt lệnh lên một VPS Ubuntu mới (22.04 / 24.04). Chạy bằng root, một lần:
#
#   curl -fsSLO https://raw.githubusercontent.com/leona3893/hoc-chung-khoan/main/scripts/setup_vps.sh
#   bash setup_vps.sh
#
# Làm gì:
#   • cập nhật hệ điều hành, bật tự vá bảo mật, tường lửa chỉ mở SSH
#   • tạo user "bot" (bot không chạy bằng root)
#   • lấy code về /home/bot/hoc-chung-khoan, sổ lệnh để ngoài repo ở /home/bot/botdata
#   • tạo .env mẫu (bạn tự điền khoá), lịch chạy mỗi giờ, xoay vòng log
#
# Chạy lại lần nữa cũng không sao: bước nào xong rồi thì bỏ qua, .env đã có thì giữ nguyên.
set -euo pipefail

REPO=https://github.com/leona3893/hoc-chung-khoan.git
HOME_BOT=/home/bot
APP=$HOME_BOT/hoc-chung-khoan

[ "$(id -u)" = 0 ] || { echo "Chạy bằng root (sudo -i rồi chạy lại)."; exit 1; }

echo "== 1. Cập nhật hệ điều hành"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -yq
apt-get install -yq python3 python3-pil git curl ufw unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "== 2. Tường lửa: chỉ mở SSH"
# Nhiều nhà cung cấp VN để SSH ở cổng khác 22 — mở đúng cổng đang dùng, kẻo tự khoá mình ngoài.
for p in $(sshd -T 2>/dev/null | awk '/^port /{print $2}') 22; do
  ufw allow "$p/tcp" >/dev/null
  echo "   mở cổng SSH $p"
done
ufw --force enable >/dev/null

echo "== 3. Kiểm tra Binance có chặn IP máy này không"
for u in https://api.binance.com/api/v3/ping https://testnet.binance.vision/api/v3/ping; do
  r=$(curl -s --max-time 15 "$u" || true)
  if [ "$r" = "{}" ]; then echo "   OK  $u"; else echo "   CHẶN $u → $r"; BLOCKED=1; fi
done
if [ "${BLOCKED:-0}" = 1 ]; then
  echo "Binance chặn IP của VPS này — bot sẽ không đặt lệnh được. Dừng cài đặt."
  exit 1
fi

echo "== 4. User bot, code, thư mục sổ lệnh"
id bot >/dev/null 2>&1 || useradd -m -s /bin/bash bot
sudo -u bot mkdir -p $HOME_BOT/botdata $HOME_BOT/logs
if [ -d $APP/.git ]; then
  sudo -u bot git -C $APP pull -q
else
  sudo -u bot git clone -q $REPO $APP
fi

echo "== 5. File .env (khoá API)"
if [ ! -f $APP/.env ]; then
  cat > $APP/.env <<EOF
# testnet = tiền ảo. Đổi thành live CHỈ KHI đã chạy testnet ổn và dùng key tiền thật
# (chỉ bật Spot Trading, TẮT Withdrawals, khoá IP theo VPS này).
LIVE_TRADING=testnet
BINANCE_API_KEY=
BINANCE_API_SECRET=

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
# Tin sổ giấy đã có GitHub Actions gửi — máy này chỉ nhắn chuyện lệnh trên sàn.
TG_ONLY_LIVE=1

# Sổ để ngoài repo, để cập nhật code không đụng tới.
CRYPTO_STATE=$HOME_BOT/botdata/crypto-ideas.json
TREND_STATE=$HOME_BOT/botdata/trend-ideas.json
LIVE_DIP_STATE=$HOME_BOT/botdata/live-dip.json
LIVE_STATE=$HOME_BOT/botdata/live-trend.json
EOF
  chown bot:bot $APP/.env
  chmod 600 $APP/.env
  echo "   Đã tạo $APP/.env — cần điền khoá (bước sau)."
else
  echo "   .env đã có, giữ nguyên."
fi

echo "== 6. Script chạy bot"
cat > $HOME_BOT/run.sh <<'EOF'
#!/usr/bin/env bash
# Mỗi giờ: lấy code mới nhất, chạy bot bắt đáy rồi bot xu hướng. Không chạy chồng.
# Dùng chung khoá với tg_control.py: đang đóng lệnh qua Telegram thì chờ xong mới chạy.
exec 9>/tmp/bot.lock
flock -w 600 9 || { echo "$(date -u) chờ khoá quá 10 phút, bỏ qua lần này"; exit 0; }
cd /home/bot/hoc-chung-khoan || exit 1
# Máy này không sửa file nào trong repo (sổ ở botdata/), nên luôn khớp đúng bản trên GitHub.
git fetch -q origin main && git reset -q --hard origin/main
set -a; . ./.env; set +a
export PYTHONIOENCODING=utf-8
echo "===== $(date -u '+%F %T UTC')"
python3 scripts/crypto_bot.py --no-chart
python3 scripts/trend_bot.py
# Đẩy sổ lệnh lên GitHub cho trang so-lenh.html (cần deploy key, xem bước 7b).
bash scripts/vps_push.sh
EOF
chown bot:bot $HOME_BOT/run.sh
chmod 700 $HOME_BOT/run.sh

rm -f $HOME_BOT/tgctl.sh     # bản cũ chạy mỗi phút, nay thay bằng dịch vụ chạy liên tục

echo "== 6b. Điều khiển Telegram: dịch vụ chạy liên tục, phản hồi tức thì"
cat > /etc/systemd/system/bot-tg.service <<'EOF'
[Unit]
Description=Dieu khien bot qua Telegram (nut Dong, /lenh)
After=network-online.target
Wants=network-online.target

[Service]
User=bot
WorkingDirectory=/home/bot/hoc-chung-khoan
EnvironmentFile=/home/bot/hoc-chung-khoan/.env
Environment=PYTHONIOENCODING=utf-8
ExecStart=/usr/bin/python3 scripts/tg_control.py --loop
Restart=always
RestartSec=5
# Khởi động lại mỗi giờ để nạp code mới mà run.sh vừa kéo về.
RuntimeMaxSec=3600
StandardOutput=append:/home/bot/logs/tg.log
StandardError=append:/home/bot/logs/tg.log

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable bot-tg >/dev/null 2>&1
systemctl restart bot-tg
sleep 3
systemctl is-active --quiet bot-tg && echo "   bot-tg đang chạy" || echo "   bot-tg CHƯA chạy — xem: journalctl -u bot-tg -n 30"

echo "== 7. Lịch chạy: bot phút 05 mỗi giờ"
echo "5 * * * * /home/bot/run.sh >> /home/bot/logs/bot.log 2>&1" | crontab -u bot -

cat > /etc/logrotate.d/bot <<'EOF'
/home/bot/logs/*.log {
  weekly
  rotate 8
  compress
  missingok
  notifempty
  copytruncate
}
EOF

echo "== 7b. Khoá đẩy sổ lệnh lên GitHub (deploy key, chỉ ghi được vào repo này)"
if [ ! -f $HOME_BOT/.ssh/deploy_key ]; then
  sudo -u bot mkdir -p $HOME_BOT/.ssh
  sudo -u bot chmod 700 $HOME_BOT/.ssh
  sudo -u bot ssh-keygen -q -t ed25519 -N "" -f $HOME_BOT/.ssh/deploy_key -C "vps-bot@hoc-chung-khoan"
fi
sudo -u bot tee $HOME_BOT/.ssh/config >/dev/null <<'EOF'
Host github.com
  IdentityFile /home/bot/.ssh/deploy_key
  IdentitiesOnly yes
EOF
sudo -u bot chmod 600 $HOME_BOT/.ssh/config
grep -q github.com $HOME_BOT/.ssh/known_hosts 2>/dev/null || \
  sudo -u bot bash -c "ssh-keyscan -t ed25519 github.com >> $HOME_BOT/.ssh/known_hosts 2>/dev/null"
if sudo -u bot ssh -o BatchMode=yes -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
  echo "   GitHub đã nhận khoá — VPS đẩy được sổ lệnh."
else
  echo "   CHƯA đẩy được lên GitHub. Thêm dòng sau vào repo → Settings → Deploy keys"
  echo "   (tick 'Allow write access'):"
  echo "   $(cat $HOME_BOT/.ssh/deploy_key.pub)"
fi

echo "== 8. Đăng nhập SSH"
if [ -s /root/.ssh/authorized_keys ]; then
  # File 00- được đọc trước, nên thắng cả 50-cloud-init.conf (vốn bật mật khẩu trên Ubuntu 24.04).
  mkdir -p /etc/ssh/sshd_config.d
  echo "PasswordAuthentication no" > /etc/ssh/sshd_config.d/00-bot.conf
  systemctl restart ssh 2>/dev/null || systemctl restart sshd
  echo "   Đã tắt đăng nhập bằng mật khẩu (chỉ còn khoá SSH)."
else
  echo "   CHƯA có khoá SSH cho root — vẫn đang cho đăng nhập bằng mật khẩu."
  echo "   Nên thêm khoá SSH rồi chạy lại script này để tắt mật khẩu."
fi

cat <<EOF

=========================================================
Xong. Việc còn lại:
  1) Điền khoá:   nano $APP/.env      (Ctrl+O Enter để lưu, Ctrl+X để thoát)
  2) Kiểm tra:    sudo -u bot bash -c 'cd $APP && set -a && . ./.env && python3 scripts/exchange.py check'
  3) Chạy thử:    sudo -u bot /home/bot/run.sh
  4) Xem log:     tail -f /home/bot/logs/bot.log
=========================================================
EOF
