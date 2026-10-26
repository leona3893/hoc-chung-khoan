#!/usr/bin/env bash
# Đẩy sổ lệnh từ VPS lên GitHub để trang so-lenh.html hiển thị.
# Bên gọi (run.sh, tg_control.py) phải đang giữ /tmp/bot.lock — script này không tự khoá.
#
#   sổ giấy   botdata/crypto-ideas.json, trend-ideas.json  → data/   (chỉ khi có lệnh vào/ra)
#   lệnh thật botdata/live-dip.json, live-trend.json        → data/   (khi có thay đổi thật)
#
# Đẩy bằng deploy key của user bot (~/.ssh/config trỏ github.com tới deploy_key) — khoá đó
# chỉ có quyền ghi vào đúng repo này.
set -u
APP=/home/bot/hoc-chung-khoan
D=/home/bot/botdata
cd "$APP" || exit 1
git remote set-url --push origin git@github.com:leona3893/hoc-chung-khoan.git

for f in crypto-ideas trend-ideas live-dip live-trend; do
  [ -f "$D/$f.json" ] && cp "$D/$f.json" "data/$f.json"
done

tracked() { git ls-files --error-unmatch "$1" >/dev/null 2>&1; }

# Sổ giấy ghi lại giá mới mỗi giờ: chỉ commit khi bot vừa có lệnh vào/ra (cờ do bot đặt).
for pair in crypto-ideas:events.flag trend-ideas:trend-events.flag; do
  f=data/${pair%%:*}.json
  [ -f "$f" ] || continue
  if [ -f "data/cache/${pair##*:}" ] || ! tracked "$f"; then git add "$f"; fi
done
# Sổ lệnh thật: commit khi đổi gì đó ngoài dòng updatedAt.
for f in data/live-dip.json data/live-trend.json; do
  [ -f "$f" ] || continue
  if ! tracked "$f" || ! git diff --quiet -I '"updatedAt"' -- "$f"; then git add "$f"; fi
done

git diff --cached --quiet && exit 0
git -c user.name="VPS bot" -c user.email="vps-bot@users.noreply.github.com" \
  commit -q -m "Sổ lệnh VPS $(date -u '+%Y-%m-%d %H:%M UTC')"
for i in 1 2 3; do
  # Repo có thể vừa có commit khác (dữ liệu chứng khoán, code mới): rebase rồi đẩy lại.
  if git pull -q --rebase --autostash origin main && git push -q origin main; then
    echo "$(date -u '+%F %T') đã đẩy sổ lệnh lên GitHub"
    exit 0
  fi
  sleep 5
done
echo "$(date -u '+%F %T') LỖI: không đẩy được sổ lệnh lên GitHub" >&2
exit 1
