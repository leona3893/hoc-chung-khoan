#!/usr/bin/env python3
"""
Kích hoạt một workflow GitHub qua API — đúng việc cron-job.org sẽ làm mỗi giờ.

Dùng để kiểm tra token GitHub chạy được TRƯỚC khi dán nó vào cron-job.org.
Token đọc từ biến môi trường GH_TOKEN, không bao giờ ghi vào file.

    # PowerShell
    $env:GH_TOKEN="github_pat_..."
    python scripts/dispatch.py crypto-bot.yml
    python scripts/dispatch.py crypto-bot.yml --test BTC    # gửi tin thử

Thành công: HTTP 204, và trong tab Actions xuất hiện một lần chạy mới.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

REPO = "leona3893/hoc-chung-khoan"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow", help="vd crypto-bot.yml, trend-bot.yml, morning.yml")
    ap.add_argument("--test", help="mã gửi thử (chỉ crypto-bot / trend-bot)")
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        print("Chưa có GH_TOKEN. Trong PowerShell: $env:GH_TOKEN=\"github_pat_...\"")
        return 1

    body = {"ref": "main"}
    if args.test:
        body["inputs"] = {"test": args.test}
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{args.workflow}/dispatches"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "dispatch-check",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"HTTP {r.status} — đã kích hoạt {args.workflow}. Xem tab Actions trên GitHub.")
            return 0
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:200]
        hint = {401: "token sai hoặc đã hết hạn",
                403: "token thiếu quyền Actions: Read and write",
                404: "sai tên file workflow, hoặc token không được cấp quyền vào repo này",
                422: "workflow không nhận input này"}.get(e.code, "")
        print(f"HTTP {e.code} — {hint}\n{msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
