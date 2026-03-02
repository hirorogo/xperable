#!/usr/bin/env python3
"""
SOV38 Helper Toolkit
====================
Sony Xperia XZ2 Premium (SOV38 / aurora_kddi) 向けの
ブートローダーアンロック & root化 ヘルパーツール。

xperable (https://github.com/hirorogo/xperable) のラッパーとして動作し、
以下の機能を提供します:
  - TAパーティションの自動バックアップ
  - ブートローダーアンロック (BLU) のガイド付き実行
  - Magisk root化のステップバイステップガイド
  - 各種チェックと復旧ガイダンス

Usage:
    python3 sov38_helper.py           # インタラクティブメニュー
    python3 sov38_helper.py --check   # 環境チェックのみ
    python3 sov38_helper.py --backup  # TAバックアップのみ
    python3 sov38_helper.py --unlock  # BLアンロック (バックアップ込み)
    python3 sov38_helper.py --magisk  # Magisk root化ガイド

Author: hirorogo
License: GPL-3.0-or-later
"""

import subprocess
import sys
import os
import shutil
import platform
import time
import argparse
import json
import re
from pathlib import Path
from datetime import datetime

# ============================================================
# 定数
# ============================================================
VERSION = "1.1.0"
DEVICE_NAME = "Sony Xperia XZ2 Premium (SOV38)"
CODENAME = "aurora_kddi"
SOC = "SDM845"  # Tama platform

BACKUP_DIR_NAME = "sov38_backups"
TA_BACKUP_NAME = "TA_backup_{timestamp}.img"
BOOT_BACKUP_NAME = "boot_backup_{timestamp}.img"

# Magisk 関連
MAGISK_RELEASES_URL = "https://github.com/topjohnwu/Magisk/releases"
MAGISK_APK_NAME = "Magisk-v28.1.apk"  # 最新版に適宜更新

# エクスプロイト リトライ設定
DEFAULT_MAX_RETRIES = 20           # バッファサイズ変更前のリトライ回数
RETRY_DELAY_SEC = 3                # リトライ間の待機秒数
EXPLOIT_TIMEOUT_SEC = 60           # 1回の実行タイムアウト

# xperable -b オプション用バッファサイズ候補 (bytes)
# SDM845 (Tama) で有効な範囲を網羅。デフォルト → 小さめ → 大きめ の順で試す
BUFFER_SIZES = [
    None,    # デフォルト (xperable内蔵値)
    16384,   # 16KB
    8192,    # 8KB
    32768,   # 32KB
    4096,    # 4KB
    65536,   # 64KB
    2048,    # 2KB
    49152,   # 48KB
    24576,   # 24KB
    12288,   # 12KB
]

# カラー出力
class Color:
    RESET  = "\033[0m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"

def colored(text, color):
    """カラー文字列を返す (端末が対応している場合)"""
    if sys.stdout.isatty():
        return f"{color}{text}{Color.RESET}"
    return text

def print_header(text):
    print(f"\n{colored('=' * 60, Color.CYAN)}")
    print(colored(f"  {text}", Color.BOLD + Color.CYAN))
    print(colored('=' * 60, Color.CYAN))

def print_step(num, text):
    print(f"\n{colored(f'[Step {num}]', Color.GREEN + Color.BOLD)} {text}")

def print_info(text):
    print(f"  {colored('ℹ', Color.BLUE)} {text}")

def print_warn(text):
    print(f"  {colored('⚠', Color.YELLOW)} {colored(text, Color.YELLOW)}")

def print_error(text):
    print(f"  {colored('✗', Color.RED)} {colored(text, Color.RED)}")

def print_success(text):
    print(f"  {colored('✓', Color.GREEN)} {text}")

def print_danger(text):
    print(f"\n  {colored('!!! 警告 !!!', Color.RED + Color.BOLD)}")
    print(f"  {colored(text, Color.RED)}")

def ask_confirm(prompt, default=False):
    """ユーザーに確認を求める"""
    suffix = " [y/N]: " if not default else " [Y/n]: "
    while True:
        answer = input(colored(f"  → {prompt}{suffix}", Color.YELLOW)).strip().lower()
        if answer == "":
            return default
        if answer in ("y", "yes", "はい"):
            return True
        if answer in ("n", "no", "いいえ"):
            return False
        print("  y または n で答えてください")

def wait_for_enter(msg="続行するには Enter を押してください..."):
    input(colored(f"\n  → {msg}", Color.DIM))


# ============================================================
# コマンド実行ヘルパー
# ============================================================
def run_cmd(cmd, check=True, capture=True, timeout=30):
    """コマンドを実行して結果を返す"""
    try:
        result = subprocess.run(
            cmd, shell=isinstance(cmd, str),
            capture_output=capture, text=True,
            timeout=timeout
        )
        if check and result.returncode != 0:
            return None, result.stderr.strip() if capture else ""
        return result.stdout.strip() if capture else "", ""
    except subprocess.TimeoutExpired:
        return None, "タイムアウトしました"
    except FileNotFoundError:
        return None, f"コマンドが見つかりません: {cmd}"
    except Exception as e:
        return None, str(e)

def cmd_exists(name):
    """コマンドが存在するか確認"""
    return shutil.which(name) is not None


# ============================================================
# 環境チェック
# ============================================================
def check_environment():
    """必要なツールがインストールされているか確認"""
    print_header("環境チェック")

    checks = {
        "adb": "Android Debug Bridge",
        "fastboot": "Android Fastboot",
        "python3": "Python 3",
    }

    all_ok = True
    for cmd, desc in checks.items():
        if cmd_exists(cmd):
            out, _ = run_cmd([cmd, "--version"] if cmd != "python3" else ["python3", "--version"])
            version = out.split("\n")[0] if out else "?"
            print_success(f"{desc}: {version}")
        else:
            print_error(f"{desc}: 見つかりません")
            all_ok = False

    # xperable バイナリの確認
    script_dir = Path(__file__).parent
    xperable_bin = None
    for name in ["xperable", "xperable.exe"]:
        p = script_dir / name
        if p.exists():
            xperable_bin = p
            break

    if xperable_bin:
        print_success(f"xperable: {xperable_bin}")
    else:
        print_warn("xperable バイナリが見つかりません")
        print_info("先に make でビルドするか、リリースからダウンロードしてください")
        print_info(f"  cd {script_dir} && make")
        all_ok = False

    # OS情報
    print_info(f"OS: {platform.system()} {platform.machine()}")

    # USBドライバ (Windowsのみ)
    if platform.system() == "Windows":
        print_warn("Windows: Sony USB ドライバがインストールされているか確認してください")
        print_info("  https://developer.sony.com/open-source/aosp-on-xperia-open-devices")

    return all_ok


# ============================================================
# デバイス接続チェック
# ============================================================
def check_adb_device():
    """ADBでデバイスが接続されているか確認"""
    out, err = run_cmd(["adb", "devices"])
    if out is None:
        print_error(f"adb devices 失敗: {err}")
        return False

    lines = out.strip().split("\n")
    devices = [l for l in lines[1:] if l.strip() and "device" in l and "unauthorized" not in l]

    if not devices:
        # unauthorizedチェック
        unauth = [l for l in lines[1:] if "unauthorized" in l]
        if unauth:
            print_warn("デバイスが unauthorized 状態です")
            print_info("スマホ画面の「USBデバッグを許可」ダイアログを承認してください")
        else:
            print_error("ADBデバイスが見つかりません")
            print_info("USBケーブルで接続し、USBデバッグを有効にしてください")
        return False

    serial = devices[0].split("\t")[0]
    print_success(f"デバイス接続済み: {serial}")
    return True


def check_fastboot_device():
    """fastbootでデバイスが接続されているか確認"""
    out, err = run_cmd(["fastboot", "devices"], timeout=5)
    if out is None or out.strip() == "":
        return False
    return True


# ============================================================
# バックアップ機能
# ============================================================
def get_backup_dir():
    """バックアップディレクトリを取得・作成"""
    backup_dir = Path(__file__).parent / BACKUP_DIR_NAME
    backup_dir.mkdir(exist_ok=True)
    return backup_dir


def backup_ta_partition():
    """TAパーティションをadb経由でバックアップ"""
    print_header("TA パーティション バックアップ")

    print_info("TAパーティションはSony端末固有の重要データを含みます:")
    print_info("  - DRMキー (Suntory/CKB)")
    print_info("  - Widevine キー")
    print_info("  - デバイス固有のシリアル番号")
    print_info("  - ブートローダーアンロック状態")
    print()
    print_danger("TAパーティションのバックアップは必ず取ってください！\n  バックアップなしでTAが破損すると修理不可能になります。")

    if not check_adb_device():
        return False

    # root確認
    out, _ = run_cmd(["adb", "shell", "id"])
    is_root = out and "uid=0" in out
    if not is_root:
        out, _ = run_cmd(["adb", "shell", "su", "-c", "id"])
        is_root = out and "uid=0" in out

    if not is_root:
        print_warn("root権限がありません。TAバックアップにはroot権限が必要です。")
        print_info("root化済みの場合: Magiskアプリでadb shellにroot権限を付与してください")
        print_info("root化前の場合: xperableが自動的にTAバックアップを作成します")

        if ask_confirm("xperableのTAバックアップに任せますか？"):
            print_info("BLアンロック時にxperableが自動的にTA.imgを作成します")
            return True
        return False

    backup_dir = get_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # TAパーティションのパスを確認
    ta_paths = [
        "/dev/block/bootdevice/by-name/TA",
        "/dev/block/platform/soc/1d84000.ufshc/by-name/TA",
    ]

    ta_path = None
    for p in ta_paths:
        out, _ = run_cmd(["adb", "shell", "su", "-c", f"ls {p}"])
        if out and "No such file" not in out:
            ta_path = p
            break

    if not ta_path:
        # lsで探す
        out, _ = run_cmd(["adb", "shell", "su", "-c",
                          "ls /dev/block/bootdevice/by-name/ | grep -i ta"])
        if out:
            ta_path = f"/dev/block/bootdevice/by-name/{out.strip().split()[0]}"

    if not ta_path:
        print_error("TAパーティションが見つかりません")
        return False

    print_info(f"TAパーティション: {ta_path}")

    # バックアップ実行
    backup_file = backup_dir / f"TA_backup_{timestamp}.img"
    print_info(f"バックアップ先: {backup_file}")
    print_info("バックアップ中... (数分かかる場合があります)")

    # ddでダンプしてpull
    _, err = run_cmd(
        ["adb", "shell", "su", "-c",
         f"dd if={ta_path} of=/sdcard/TA_backup.img bs=4096"],
        timeout=120
    )

    out, err = run_cmd(["adb", "pull", "/sdcard/TA_backup.img", str(backup_file)], timeout=120)
    if out is None:
        print_error(f"バックアップ失敗: {err}")
        return False

    # 後片付け
    run_cmd(["adb", "shell", "rm", "/sdcard/TA_backup.img"])

    # ファイルサイズ確認
    size = backup_file.stat().st_size
    if size < 1024:
        print_error(f"バックアップファイルが小さすぎます ({size} bytes)")
        return False

    size_mb = size / (1024 * 1024)
    print_success(f"TAバックアップ完了: {backup_file} ({size_mb:.1f} MB)")
    print_warn("このファイルは絶対に消さないでください！複数の場所にコピーを保存してください。")
    return True


def backup_boot_image():
    """現在のboot imageをバックアップ"""
    print_header("Boot Image バックアップ")

    if not check_adb_device():
        return False

    # root確認
    out, _ = run_cmd(["adb", "shell", "su", "-c", "id"])
    is_root = out and "uid=0" in out
    if not is_root:
        print_warn("root権限がないため、boot imageのバックアップができません")
        print_info("代替方法: fastbootモードで boot パーティションをダンプできます")
        return False

    backup_dir = get_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # A/Bスロット確認
    out, _ = run_cmd(["adb", "shell", "getprop", "ro.boot.slot_suffix"])
    slot = out.strip() if out else "_a"
    print_info(f"現在のスロット: {slot}")

    boot_path = f"/dev/block/bootdevice/by-name/boot{slot}"
    backup_file = backup_dir / f"boot{slot}_backup_{timestamp}.img"

    print_info(f"boot パーティション: {boot_path}")
    print_info("バックアップ中...")

    _, _ = run_cmd(
        ["adb", "shell", "su", "-c",
         f"dd if={boot_path} of=/sdcard/boot_backup.img bs=4096"],
        timeout=120
    )

    out, err = run_cmd(["adb", "pull", "/sdcard/boot_backup.img", str(backup_file)], timeout=120)
    if out is None:
        print_error(f"バックアップ失敗: {err}")
        return False

    run_cmd(["adb", "shell", "rm", "/sdcard/boot_backup.img"])

    size = backup_file.stat().st_size
    size_mb = size / (1024 * 1024)
    print_success(f"boot imageバックアップ完了: {backup_file} ({size_mb:.1f} MB)")
    return True


# ============================================================
# エクスプロイト リトライエンジン
# ============================================================
def parse_xperable_output(stdout, stderr):
    """xperableの出力を解析して成功/失敗/エラー種別を判定"""
    combined = (stdout or "") + (stderr or "")
    result = {
        "success": False,
        "connected": False,
        "error_type": None,  # "usb", "overflow", "timeout", "unknown"
        "raw": combined,
    }

    # 接続成功の判定
    if "bootloader" in combined.lower() or "OKAY" in combined:
        result["connected"] = True

    # 成功パターン
    if any(kw in combined for kw in ["OKAY", "unlock success", "patch applied"]):
        result["success"] = True

    # returncode 0 でエラーメッセージがなければ成功とみなす
    # (xperable は成功時に特定のメッセージを出さない場合もある)

    # エラーパターン判定
    if "usb" in combined.lower() and ("error" in combined.lower() or "fail" in combined.lower()):
        result["error_type"] = "usb"
    elif "overflow" in combined.lower() or "buffer" in combined.lower():
        result["error_type"] = "overflow"
    elif "timeout" in combined.lower():
        result["error_type"] = "timeout"
    elif "FAIL" in combined or "error" in combined.lower():
        result["error_type"] = "unknown"

    return result


def run_xperable_with_retry(xperable_bin, script_dir, xperable_args=None,
                             max_retries=DEFAULT_MAX_RETRIES,
                             auto_reconnect=True):
    """
    xperable をリトライ付きで実行する。

    動作フロー:
    1. デフォルトのバッファサイズで最大 max_retries 回試行
    2. 全て失敗 → バッファサイズを変更して再度 max_retries 回ずつ試行
    3. 各バッファサイズで試し、成功したサイズと回数を記録
    4. 全サイズで失敗した場合は結果レポートを表示

    Returns:
        (success: bool, stats: dict)
    """
    if xperable_args is None:
        xperable_args = ["-B", "-4"]

    log_dir = get_backup_dir() / "exploit_logs"
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"exploit_log_{timestamp}.json"

    stats = {
        "start_time": datetime.now().isoformat(),
        "total_attempts": 0,
        "buffer_sizes_tried": [],
        "success": False,
        "success_buffer_size": None,
        "success_attempt": None,
        "attempts": [],
    }

    print_info(f"リトライモード: 最大 {max_retries}回/サイズ × {len(BUFFER_SIZES)}サイズ")
    print_info(f"ログ保存先: {log_file}")
    print()

    for size_idx, buf_size in enumerate(BUFFER_SIZES):
        size_label = f"{buf_size} bytes" if buf_size else "デフォルト"

        if size_idx > 0:
            print()
            print_header(f"バッファサイズ変更: {size_label} ({size_idx + 1}/{len(BUFFER_SIZES)})")
            print_info("USBケーブルを抜き差しして S1モード に再度入ってください")
            print_info("  1. ケーブルを抜く")
            print_info("  2. 10秒待つ")
            print_info("  3. ボリュームDOWN + USB接続 → 緑LED")
            wait_for_enter("S1モード（緑LED）になったら Enter...")

        stats["buffer_sizes_tried"].append(size_label)

        for attempt in range(1, max_retries + 1):
            stats["total_attempts"] += 1
            global_attempt = stats["total_attempts"]

            # プログレスバー
            bar_width = 30
            filled = int(bar_width * attempt / max_retries)
            bar = colored("█" * filled, Color.GREEN) + colored("░" * (bar_width - filled), Color.DIM)
            print(f"\r  [{bar}] {colored(f'#{global_attempt}', Color.BOLD)} "
                  f"サイズ={size_label} 試行 {attempt}/{max_retries}", end="", flush=True)

            # xperable コマンド構築
            cmd = [str(xperable_bin)]
            if buf_size is not None:
                cmd.extend(["-b", str(buf_size)])
            cmd.extend(xperable_args)

            attempt_info = {
                "global_attempt": global_attempt,
                "buffer_size": size_label,
                "local_attempt": attempt,
                "command": " ".join(cmd),
                "timestamp": datetime.now().isoformat(),
            }

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True, text=True,
                    timeout=EXPLOIT_TIMEOUT_SEC,
                    cwd=str(script_dir)
                )

                parsed = parse_xperable_output(result.stdout, result.stderr)
                attempt_info["returncode"] = result.returncode
                attempt_info["parsed"] = {
                    "success": parsed["success"],
                    "connected": parsed["connected"],
                    "error_type": parsed["error_type"],
                }
                # 出力の最後の数行をログに保存
                output_lines = parsed["raw"].strip().split("\n")
                attempt_info["output_tail"] = output_lines[-5:] if output_lines else []

                if result.returncode == 0:
                    # 成功！
                    print()  # 改行
                    print_success(f"成功！ (試行 #{global_attempt}, サイズ={size_label})")

                    stats["success"] = True
                    stats["success_buffer_size"] = size_label
                    stats["success_attempt"] = global_attempt
                    attempt_info["result"] = "SUCCESS"
                    stats["attempts"].append(attempt_info)

                    # ログ保存
                    stats["end_time"] = datetime.now().isoformat()
                    _save_exploit_log(log_file, stats)

                    return True, stats

                else:
                    attempt_info["result"] = "FAIL"
                    error_hint = parsed["error_type"] or "unknown"
                    print(f" → {colored('✗', Color.RED)} ({error_hint})", flush=True)

            except subprocess.TimeoutExpired:
                attempt_info["result"] = "TIMEOUT"
                attempt_info["returncode"] = -1
                print(f" → {colored('⏱ タイムアウト', Color.YELLOW)}", flush=True)

            except Exception as e:
                attempt_info["result"] = "ERROR"
                attempt_info["error"] = str(e)
                print(f" → {colored(f'✗ {e}', Color.RED)}", flush=True)

            stats["attempts"].append(attempt_info)

            # リトライ間のクールダウン
            if attempt < max_retries:
                # USB再接続が必要な場合
                if auto_reconnect and attempt % 5 == 0:
                    print()
                    print_warn(f"5回連続失敗。USBを再接続してください")
                    print_info("  ケーブルを抜く → 5秒待つ → ボリュームDOWN + USB接続")
                    wait_for_enter("再接続したら Enter...")
                else:
                    time.sleep(RETRY_DELAY_SEC)

        # このバッファサイズでは全滅
        print()
        print_warn(f"サイズ {size_label}: {max_retries}回全て失敗")

    # 全バッファサイズで失敗
    print()
    stats["end_time"] = datetime.now().isoformat()
    _save_exploit_log(log_file, stats)
    _print_exploit_report(stats, log_file)

    return False, stats


def _save_exploit_log(log_file, stats):
    """エクスプロイトログをJSONで保存"""
    try:
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
    except Exception:
        pass  # ログ保存失敗は無視


def _print_exploit_report(stats, log_file):
    """エクスプロイト結果レポートを表示"""
    print_header("エクスプロイト結果レポート")
    print()
    print_info(f"総試行回数: {stats['total_attempts']}")
    print_info(f"試したバッファサイズ: {', '.join(stats['buffer_sizes_tried'])}")

    if stats["success"]:
        print_success(f"成功: 試行 #{stats['success_attempt']} "
                      f"(サイズ: {stats['success_buffer_size']})")
    else:
        print_error("全て失敗しました")
        print()
        print_info("考えられる原因:")
        print_info("  1. USBケーブル/ポートの相性が悪い → 別のケーブルやポートを試す")
        print_info("  2. USB HUBを経由している → 直接接続する")
        print_info("  3. OSのUSBドライバの問題 → 再起動して試す")
        print_info("  4. デバイスのファームウェアバージョンが非対応")
        print()

        # エラー種別の集計
        error_counts = {}
        for a in stats["attempts"]:
            result = a.get("result", "unknown")
            parsed = a.get("parsed", {})
            error_type = parsed.get("error_type", result)
            error_counts[error_type] = error_counts.get(error_type, 0) + 1

        if error_counts:
            print_info("エラー内訳:")
            for err_type, count in sorted(error_counts.items(), key=lambda x: -x[1]):
                print_info(f"  {err_type}: {count}回")

    print()
    print_info(f"詳細ログ: {log_file}")


# ============================================================
# ブートローダーアンロック
# ============================================================
def bootloader_unlock():
    """xperableを使用してBLアンロックを実行"""
    print_header("ブートローダーアンロック (BLU)")

    print_danger(
        "BLアンロックを行うと以下の影響があります:\n"
        "  - メーカー保証が無効になる\n"
        "  - カメラDRM (Suntory/CKB) が消失 → 画質低下\n"
        "  - Widevine L1 → L3 → Netflix等のHD/4K再生不可\n"
        "  - おサイフケータイが使えなくなる場合がある\n"
        "  - 端末が初期化（ファクトリーリセット）される"
    )

    if not ask_confirm("リスクを理解した上で続行しますか？"):
        print_info("中断しました")
        return False

    # xperableバイナリ確認
    script_dir = Path(__file__).parent
    xperable_bin = None
    for name in ["xperable", "xperable.exe"]:
        p = script_dir / name
        if p.exists() and os.access(str(p), os.X_OK):
            xperable_bin = p
            break
        elif p.exists():
            # 実行権限を付与
            os.chmod(str(p), 0o755)
            xperable_bin = p
            break

    if not xperable_bin:
        print_error("xperable バイナリが見つかりません")
        print_info("先にビルドしてください: make")
        return False

    # Step 1: S1モードへの誘導
    print_step(1, "SOV38をS1モード（緑LED）にする")
    print()
    print_info("以下の手順で S1モード に入ってください:")
    print_info("  1. SOV38の電源を 完全にオフ にする")
    print_info("  2. ボリュームDOWNボタンを押しながら USBケーブルをPCに接続")
    print_info("  3. 緑色のLED が点灯すれば成功")
    print()
    print_warn("うまくいかない場合:")
    print_info("  - ケーブルを抜き、10秒待ってから再試行")
    print_info("  - 別のUSBケーブルやポートを試す")

    wait_for_enter("S1モード（緑LED点灯）になったら Enter を押してください...")

    # Step 2: xperable実行 (自動リトライ付き)
    print_step(2, "xperable を実行してBLアンロック")
    print_info("TAパーティションの rooting_status を書き換えます...")
    print()

    # リトライ設定の確認
    print_info("エクスプロイトはUSBタイミングに依存するため、失敗は正常です。")
    print_info(f"デフォルト: {DEFAULT_MAX_RETRIES}回リトライ → 失敗時にバッファサイズ変更")
    print()

    # カスタムリトライ回数の設定
    custom_retries = input(colored(
        f"  → リトライ回数 (Enter={DEFAULT_MAX_RETRIES}): ", Color.YELLOW
    )).strip()
    max_retries = int(custom_retries) if custom_retries.isdigit() else DEFAULT_MAX_RETRIES

    # バックアップディレクトリ作成
    backup_dir = get_backup_dir()

    # リトライエンジンで実行
    success, stats = run_xperable_with_retry(
        xperable_bin, script_dir,
        xperable_args=["-B", "-4"],
        max_retries=max_retries,
        auto_reconnect=True
    )

    if not success:
        print_error("xperableの実行に失敗しました")
        print_info("トラブルシューティング:")
        print_info("  - 別のUSBケーブルを試す (短くて太いケーブルが良い)")
        print_info("  - USB HUBを外して直接接続する")
        print_info("  - sudo で実行を試す (Linux/macOS)")
        print_info("  - PCを再起動してから再試行")
        return False

    print_success("xperable の実行が完了しました")

    # TA.imgバックアップの確認
    ta_img = script_dir / "TA.img"
    if ta_img.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"TA_xperable_{timestamp}.img"
        shutil.copy2(str(ta_img), str(backup_path))
        print_success(f"TAバックアップをコピー: {backup_path}")
        print_warn("このファイルは絶対に消さないでください！")
    else:
        print_warn("TA.img が見つかりません。xperableが正常に動作したか確認してください。")

    # Step 3: 再起動と確認
    print_step(3, "再起動")
    print_info("USBケーブルを抜いて、電源ボタンで起動してください")
    print()
    print_info("初回起動時の挙動:")
    print_info("  1. 「ブートローダーがアンロックされています」警告が表示される")
    print_info("  2. 端末が初期化（ファクトリーリセット）される")
    print_info("  3. 初期設定画面が表示される")
    print()
    print_info("これは正常な動作です。初期設定を済ませてください。")

    wait_for_enter("初期設定が完了したら Enter を押してください...")

    # Step 4: アンロック確認
    print_step(4, "アンロック状態の確認")
    print_info("USBデバッグを再度有効にしてPCと接続してください:")
    print_info("  設定 → システム → 開発者向けオプション → USBデバッグ ON")

    wait_for_enter("USBデバッグを有効にして接続したら Enter を押してください...")

    if check_adb_device():
        print_info("fastbootモードに再起動します...")
        run_cmd(["adb", "reboot", "bootloader"])
        time.sleep(5)

        out, _ = run_cmd(["fastboot", "oem", "device-info"], timeout=10)
        if out and "Device unlocked: true" in out:
            print_success("ブートローダーのアンロックが確認されました！")
        elif out:
            print_warn(f"確認結果: {out}")
        else:
            print_warn("fastbootでの確認ができませんでした")

        run_cmd(["fastboot", "reboot"])
        print_info("Androidに再起動します...")
    else:
        print_info("ADB接続ができなくても、次のステップに進めます")
        print_info("手動で確認: adb reboot bootloader → fastboot oem device-info")

    print_success("BLアンロック完了！")
    return True


# ============================================================
# Magisk root化
# ============================================================
def magisk_root():
    """Magiskでroot化するガイド"""
    print_header("Magisk root化 ガイド")

    print_info("Magiskは、systemパーティションを書き換えずにroot権限を取得するツールです。")
    print_info("SafetyNet/Play Integrity の回避も可能です。")
    print()

    if not check_adb_device():
        print_error("デバイスを接続してから再試行してください")
        return False

    # Step 1: 現在のboot imageを取得
    print_step(1, "boot imageの取得")
    print()

    # A/Bスロット確認
    out, _ = run_cmd(["adb", "shell", "getprop", "ro.boot.slot_suffix"])
    slot = out.strip() if out else "_a"
    print_info(f"現在のスロット: {slot}")

    backup_dir = get_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    boot_file = backup_dir / f"boot{slot}_{timestamp}.img"

    print_info("boot imageの取得方法を選択してください:")
    print(f"  {colored('1', Color.CYAN)}) adb + root権限でダンプ (root済みの場合)")
    print(f"  {colored('2', Color.CYAN)}) ファームウェアから手動で取得済み")
    print()

    choice = input(colored("  → 選択 (1/2): ", Color.YELLOW)).strip()

    if choice == "1":
        # root権限でboot imageダンプ
        out, _ = run_cmd(["adb", "shell", "su", "-c", "id"])
        if not (out and "uid=0" in out):
            print_error("root権限がありません")
            print_info("初回root化の場合は、ファームウェアからboot.imgを取得してください")
            print_info("Sony公式ファームウェアからsxflasherで展開できます")
            return False

        boot_path = f"/dev/block/bootdevice/by-name/boot{slot}"
        print_info(f"ダンプ中: {boot_path}")

        run_cmd(
            ["adb", "shell", "su", "-c",
             f"dd if={boot_path} of=/sdcard/boot.img bs=4096"],
            timeout=120
        )
        out, err = run_cmd(
            ["adb", "pull", "/sdcard/boot.img", str(boot_file)],
            timeout=120
        )
        if out is None:
            print_error(f"boot imageの取得に失敗: {err}")
            return False

        run_cmd(["adb", "shell", "rm", "/sdcard/boot.img"])
        print_success(f"boot image取得完了: {boot_file}")

    elif choice == "2":
        print_info("boot.img のパスを入力してください:")
        path = input(colored("  → パス: ", Color.YELLOW)).strip()
        if not Path(path).exists():
            print_error(f"ファイルが見つかりません: {path}")
            return False
        shutil.copy2(path, str(boot_file))
        print_success(f"コピー完了: {boot_file}")
    else:
        print_error("無効な選択です")
        return False

    # Step 2: Magiskでパッチ
    print_step(2, "Magiskアプリでboot imageをパッチ")
    print()
    print_info(f"Magisk最新版: {MAGISK_RELEASES_URL}")
    print()
    print_info("手順:")
    print_info(f"  1. MagiskアプリをSOV38にインストール")
    print_info(f"     adb install Magisk-*.apk")
    print_info(f"  2. boot imageをSOV38に転送:")
    print_info(f"     adb push {boot_file} /sdcard/boot.img")
    print()

    # boot imageをデバイスに転送
    if ask_confirm("boot imageをデバイスに転送しますか？"):
        out, err = run_cmd(
            ["adb", "push", str(boot_file), "/sdcard/boot.img"],
            timeout=120
        )
        if out is not None:
            print_success("転送完了: /sdcard/boot.img")
        else:
            print_error(f"転送失敗: {err}")

    print()
    print_info("  3. Magiskアプリを開く → 「インストール」")
    print_info("  4. 「パッチするファイルを選択」→ /sdcard/boot.img を選択")
    print_info("  5. パッチが完了するまで待つ")
    print_info("  6. パッチ済みファイル: /sdcard/Download/magisk_patched-*.img")

    wait_for_enter("Magiskでのパッチが完了したら Enter を押してください...")

    # Step 3: パッチ済みboot imageを取得
    print_step(3, "パッチ済みboot imageをPCに取得")

    out, _ = run_cmd(
        ["adb", "shell", "ls", "/sdcard/Download/magisk_patched-*.img"],
        timeout=10
    )

    patched_files = []
    if out:
        patched_files = [f.strip() for f in out.split("\n") if f.strip()]

    if not patched_files:
        print_warn("パッチ済みファイルが見つかりません")
        print_info("手動でパスを指定してください")
        path = input(colored("  → デバイス上のパス: ", Color.YELLOW)).strip()
        if path:
            patched_files = [path]
        else:
            return False

    # 最新のパッチファイルを使用
    patched_device_path = patched_files[-1]
    patched_local = backup_dir / f"magisk_patched_{timestamp}.img"

    print_info(f"取得中: {patched_device_path}")
    out, err = run_cmd(
        ["adb", "pull", patched_device_path, str(patched_local)],
        timeout=120
    )
    if out is None:
        print_error(f"取得失敗: {err}")
        return False

    print_success(f"取得完了: {patched_local}")

    # Step 4: fastbootでフラッシュ
    print_step(4, "パッチ済みboot imageを書き込み")
    print()
    print_warn("この操作でboot パーティションが上書きされます")

    if not ask_confirm("パッチ済みboot imageを書き込みますか？"):
        print_info("中断しました。手動で以下を実行してください:")
        print_info(f"  adb reboot bootloader")
        print_info(f"  fastboot flash boot{slot} {patched_local}")
        print_info(f"  fastboot reboot")
        return False

    # fastbootに再起動
    print_info("fastbootモードに再起動中...")
    run_cmd(["adb", "reboot", "bootloader"])

    # fastbootデバイス待機
    print_info("fastbootデバイスを待機中...")
    for i in range(15):
        time.sleep(2)
        if check_fastboot_device():
            break
    else:
        print_error("fastbootデバイスが見つかりません")
        print_info("青色LEDが点灯しているか確認してください")
        return False

    print_success("fastbootデバイス検出")

    # フラッシュ実行
    print_info(f"書き込み中: fastboot flash boot{slot} ...")
    result = subprocess.run(
        ["fastboot", "flash", f"boot{slot}", str(patched_local)],
        capture_output=True, text=True, timeout=60
    )

    if result.returncode != 0:
        print_error(f"書き込み失敗: {result.stderr}")
        print_info("fastboot reboot で再起動してやり直してください")
        return False

    print_success("書き込み完了！")

    # 再起動
    print_info("再起動します...")
    run_cmd(["fastboot", "reboot"])

    print()
    print_success("Magisk root化が完了しました！")
    print()
    print_info("起動後の確認:")
    print_info("  1. Magiskアプリを開く → バージョンが表示されればOK")
    print_info("  2. 「Superuser」タブでroot権限を管理")
    print()
    print_info("トラブルシューティング:")
    print_info("  起動しない場合 → 音量DOWNを押しながら起動でセーフモード")
    print_info("  セーフモードでMagiskモジュールが全て無効化されます")

    return True


# ============================================================
# フルガイド (全ステップ)
# ============================================================
def full_guide():
    """BLアンロックからroot化まで全ステップをガイド"""
    print_header(f"{DEVICE_NAME} 改造ガイド")
    print()
    print_info("このガイドでは以下を順番に実行します:")
    print_info("  1. 環境チェック")
    print_info("  2. ブートローダーアンロック (BLU)")
    print_info("  3. Magisk root化")
    print()

    if not ask_confirm("フルガイドを開始しますか？"):
        return

    # 環境チェック
    if not check_environment():
        print_error("環境チェックに失敗しました。不足しているツールをインストールしてください。")
        return

    wait_for_enter()

    # BLアンロック
    if ask_confirm("BLアンロックを実行しますか？ (既にアンロック済みならスキップ)"):
        if not bootloader_unlock():
            if not ask_confirm("エラーがありましたが続行しますか？"):
                return
    else:
        print_info("BLアンロックをスキップ")

    wait_for_enter()

    # Magisk root化
    if ask_confirm("Magisk root化を実行しますか？"):
        magisk_root()
    else:
        print_info("Magisk root化をスキップ")

    print_header("完了！")
    print_success(f"{DEVICE_NAME} の改造が完了しました")
    print()
    print_info("バックアップファイル:")
    backup_dir = get_backup_dir()
    for f in sorted(backup_dir.iterdir()):
        size_mb = f.stat().st_size / (1024 * 1024)
        print_info(f"  {f.name} ({size_mb:.1f} MB)")
    print()
    print_warn("バックアップは複数の場所にコピーしておいてください！")


# ============================================================
# ステータス確認
# ============================================================
def check_status():
    """デバイスの現在の状態を確認"""
    print_header("デバイスステータス確認")

    if not check_adb_device():
        print_info("ADBが使えない場合:")
        print_info("  - S1モード(緑LED): ファームウェアフラッシュのみ")
        print_info("  - fastboot(青LED): fastboot oem device-info で確認")
        return

    # デバイス情報
    checks = [
        ("モデル", "ro.product.model"),
        ("コードネーム", "ro.product.device"),
        ("Androidバージョン", "ro.build.version.release"),
        ("ビルド番号", "ro.build.display.id"),
        ("セキュリティパッチ", "ro.build.version.security_patch"),
        ("スロット", "ro.boot.slot_suffix"),
    ]

    print()
    for label, prop in checks:
        out, _ = run_cmd(["adb", "shell", "getprop", prop])
        if out:
            print_info(f"{label}: {out}")

    # root確認
    out, _ = run_cmd(["adb", "shell", "su", "-c", "id"])
    if out and "uid=0" in out:
        print_success("root: あり (Magisk)")
    else:
        print_info("root: なし")

    # Magisk確認
    out, _ = run_cmd(["adb", "shell", "magisk", "-v"])
    if out:
        print_success(f"Magisk: {out}")

    # BL状態確認（rootがあればgetpropで）
    out, _ = run_cmd(["adb", "shell", "getprop", "ro.boot.verifiedbootstate"])
    if out:
        state = "アンロック済み" if out.strip() == "orange" else out.strip()
        print_info(f"ブートローダー: {state}")


# ============================================================
# メインメニュー
# ============================================================
def exploit_retry_standalone():
    """エクスプロイトのリトライテスト (単体実行)"""
    print_header("エクスプロイト リトライテスト")
    print()
    print_info("xperableエクスプロイトを自動リトライで実行します。")
    print_info("BLアンロック以外のテスト (-0 や -2 など) にも使えます。")
    print()

    # xperableバイナリ確認
    script_dir = Path(__file__).parent
    xperable_bin = None
    for name in ["xperable", "xperable.exe"]:
        p = script_dir / name
        if p.exists():
            if not os.access(str(p), os.X_OK):
                os.chmod(str(p), 0o755)
            xperable_bin = p
            break

    if not xperable_bin:
        print_error("xperable バイナリが見つかりません")
        return

    # テストケース選択
    print_info("テストケース:")
    print(f"  {colored('0', Color.CYAN)}) -0  基本クラッシュテスト")
    print(f"  {colored('2', Color.CYAN)}) -2  バッファオフセット距離テスト")
    print(f"  {colored('4', Color.CYAN)}) -4  BLアンロックパッチ (デフォルト)")
    print(f"  {colored('5', Color.CYAN)}) -5  BLアンロックパッチ (代替)")
    print(f"  {colored('c', Color.CYAN)}) カスタムオプション指定")
    print()

    choice = input(colored("  → 選択 (0/2/4/5/c) [4]: ", Color.YELLOW)).strip()

    if choice == "0":
        args = ["-0"]
    elif choice == "2":
        args = ["-2"]
    elif choice == "5":
        args = ["-B", "-5"]
    elif choice == "c":
        custom = input(colored("  → xperable オプション: ", Color.YELLOW)).strip()
        args = custom.split()
    else:
        args = ["-B", "-4"]

    # リトライ回数
    retries_input = input(colored(
        f"  → リトライ回数/サイズ [Enter={DEFAULT_MAX_RETRIES}]: ", Color.YELLOW
    )).strip()
    max_retries = int(retries_input) if retries_input.isdigit() else DEFAULT_MAX_RETRIES

    print()
    print_info("SOV38をS1モード（緑LED）にして接続してください")
    wait_for_enter("準備できたら Enter...")

    success, stats = run_xperable_with_retry(
        xperable_bin, script_dir,
        xperable_args=args,
        max_retries=max_retries,
        auto_reconnect=True
    )

    if success:
        print_success("エクスプロイト成功！")
        if stats.get("success_buffer_size"):
            print_info(f"最適バッファサイズ: {stats['success_buffer_size']}")
            print_info(f"成功までの試行回数: {stats['success_attempt']}")
    else:
        print_error("全試行が失敗しました。ログを確認してください。")


def main_menu():
    """インタラクティブメニュー"""
    while True:
        print_header(f"SOV38 Helper Toolkit v{VERSION}")
        print()
        print(f"  {colored('1', Color.CYAN)}) 環境チェック")
        print(f"  {colored('2', Color.CYAN)}) デバイスステータス確認")
        print(f"  {colored('3', Color.CYAN)}) TAパーティション バックアップ")
        print(f"  {colored('4', Color.CYAN)}) boot image バックアップ")
        print(f"  {colored('5', Color.CYAN)}) ブートローダーアンロック (BLU)")
        print(f"  {colored('6', Color.CYAN)}) Magisk root化")
        print(f"  {colored('7', Color.CYAN)}) フルガイド (1→5→6 を順番に実行)")
        print(f"  {colored('8', Color.CYAN)}) エクスプロイト リトライテスト")
        print(f"  {colored('q', Color.RED)}) 終了")
        print()

        choice = input(colored("  → 選択: ", Color.YELLOW)).strip().lower()

        if choice == "1":
            check_environment()
        elif choice == "2":
            check_status()
        elif choice == "3":
            backup_ta_partition()
        elif choice == "4":
            backup_boot_image()
        elif choice == "5":
            bootloader_unlock()
        elif choice == "6":
            magisk_root()
        elif choice == "7":
            full_guide()
        elif choice == "8":
            exploit_retry_standalone()
        elif choice in ("q", "quit", "exit"):
            print_info("終了します")
            break
        else:
            print_error("無効な選択です")

        wait_for_enter()


# ============================================================
# エントリーポイント
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description=f"SOV38 Helper Toolkit v{VERSION} - {DEVICE_NAME} 改造支援ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python3 sov38_helper.py             # インタラクティブメニュー
  python3 sov38_helper.py --check     # 環境チェック
  python3 sov38_helper.py --status    # デバイスステータス確認
  python3 sov38_helper.py --backup    # TA + boot バックアップ
  python3 sov38_helper.py --unlock    # BLアンロック
  python3 sov38_helper.py --magisk    # Magisk root化

詳細: https://github.com/hirorogo/xperable
        """
    )

    parser.add_argument("--check", action="store_true", help="環境チェックのみ実行")
    parser.add_argument("--status", action="store_true", help="デバイスステータス確認")
    parser.add_argument("--backup", action="store_true", help="TAとbootのバックアップ")
    parser.add_argument("--unlock", action="store_true", help="BLアンロック実行")
    parser.add_argument("--magisk", action="store_true", help="Magisk root化ガイド")
    parser.add_argument("--version", action="version", version=f"SOV38 Helper v{VERSION}")

    args = parser.parse_args()

    print(colored(f"""
  ╔══════════════════════════════════════════╗
  ║   SOV38 Helper Toolkit v{VERSION}           ║
  ║   {DEVICE_NAME}   ║
  ╚══════════════════════════════════════════╝
    """, Color.CYAN))

    if args.check:
        check_environment()
    elif args.status:
        check_status()
    elif args.backup:
        backup_ta_partition()
        backup_boot_image()
    elif args.unlock:
        bootloader_unlock()
    elif args.magisk:
        magisk_root()
    else:
        main_menu()


if __name__ == "__main__":
    main()
