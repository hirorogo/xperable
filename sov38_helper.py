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
from pathlib import Path
from datetime import datetime

# ============================================================
# 定数
# ============================================================
VERSION = "1.0.0"
DEVICE_NAME = "Sony Xperia XZ2 Premium (SOV38)"
CODENAME = "aurora_kddi"
SOC = "SDM845"  # Tama platform

BACKUP_DIR_NAME = "sov38_backups"
TA_BACKUP_NAME = "TA_backup_{timestamp}.img"
BOOT_BACKUP_NAME = "boot_backup_{timestamp}.img"

# Magisk 関連
MAGISK_RELEASES_URL = "https://github.com/topjohnwu/Magisk/releases"
MAGISK_APK_NAME = "Magisk-v28.1.apk"  # 最新版に適宜更新

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

    # Step 2: xperable実行
    print_step(2, "xperable を実行してBLアンロック")
    print_info(f"実行: {xperable_bin} -4")
    print_info("TAパーティションの rooting_status を書き換えます...")
    print()

    # バックアップディレクトリ作成
    backup_dir = get_backup_dir()

    try:
        # xperableは -4 オプションでBLアンロックパッチを実行
        # -B でブートローダーバージョン確認、-4 でパッチ実行
        result = subprocess.run(
            [str(xperable_bin), "-B", "-4"],
            timeout=120,
            cwd=str(script_dir)
        )

        if result.returncode != 0:
            print_error("xperableの実行に失敗しました")
            print_info("エラーを確認して再試行してください")
            print_info("トラブルシューティング:")
            print_info("  - USBケーブルを抜き差しして S1モード に再度入る")
            print_info("  - 別のUSBポートを試す")
            print_info("  - sudo で実行を試す (Linux/macOS)")
            return False

    except subprocess.TimeoutExpired:
        print_error("タイムアウトしました。USBの接続を確認してください。")
        return False
    except Exception as e:
        print_error(f"実行エラー: {e}")
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
