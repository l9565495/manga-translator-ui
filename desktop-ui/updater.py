import sys
import os
import subprocess
import logging
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import shutil
import json

# --- Dependency Check ---
try:
    import psutil
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'psutil'])
    import psutil

# --- Basic Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("updater.log"),
        logging.StreamHandler()
    ]
)

# --- Configuration ---
APP_NAME = "MangaTranslatorUI"
MAIN_APP_EXE = "app.exe"
UPDATER_EXE = "updater.exe"
CURRENT_VERSION = "0.0.0" # This will be read from version file

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def get_app_variant():
    try:
        build_info_path = resource_path('build_info.json')
        with open(build_info_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            variant = data.get('variant', 'cpu').lower()
            logging.info(f"Detected app variant: {variant}")
            return variant
    except Exception as e:
        logging.warning(f"build_info.json not found, defaulting to 'cpu'. Error: {e}")
        return 'cpu'

def get_current_version():
    try:
        version_path = resource_path('VERSION')
        with open(version_path, 'r', encoding='utf-8') as f:
            version = f.read().strip()
            logging.info(f"Current version from file: {version}")
            return version
    except Exception as e:
        logging.error(f"Could not read version file: {e}")
        return CURRENT_VERSION

def show_message(title, message, is_error=False):
    root = tk.Tk()
    root.withdraw()
    if is_error:
        messagebox.showerror(title, message)
    else:
        messagebox.showinfo(title, message)
    root.destroy()

def is_main_app_running():
    """Check if the main application is currently running."""
    for proc in psutil.process_iter(['name', 'exe']):
        try:
            # sys.executable is the path to updater.exe when frozen
            if proc.name() == MAIN_APP_EXE and proc.exe() and Path(proc.exe()).parent == Path(sys.executable).parent:
                logging.info(f"Main app process found: {proc}")
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def main():
    logging.info("Updater started.")

    if is_main_app_running():
        show_message("请关闭主程序", f"为了继续更新，请先手动关闭正在运行的 {MAIN_APP_EXE}，然后再点击此对话框的“确定”按钮。")
        # After user clicks OK, we check again
        if is_main_app_running():
            show_message("更新取消", f"主程序 {MAIN_APP_EXE} 仍在运行。更新已取消。", is_error=True)
            sys.exit(1)

    try:
        from tufup.client import Client
        from packaging.version import parse as parse_version

        app_variant = get_app_variant()
        current_version = get_current_version()

        app_install_dir = Path(os.path.dirname(sys.executable))
        cache_dir = app_install_dir / 'cache_tufup'
        metadata_dir = cache_dir / 'metadata'
        target_dir = cache_dir / 'targets'
        metadata_dir.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=True)

        source_root_json_path = resource_path(os.path.join('update_repository', 'metadata', 'root.json'))
        dest_root_json_path = metadata_dir / 'root.json'
        if not dest_root_json_path.exists() and os.path.exists(source_root_json_path):
            shutil.copy(source_root_json_path, dest_root_json_path)

        client = Client(
            app_name=APP_NAME,
            app_install_dir=app_install_dir,
            current_version=current_version,
            metadata_dir=metadata_dir,
            metadata_base_url=f'https://hgmzhn.github.io/manga-translator-ui-package/',
            target_dir=target_dir,
            target_base_url=f'https://github.com/hgmzhn/manga-translator-ui-package/releases/download/'
        )

        logging.info("Refreshing TUF metadata...")
        client.refresh()
        
        logging.info("Searching for updates...")
        latest_update = None
        current_v = parse_version(client.current_version)

        for target_meta in client.trusted_target_metas:
            if target_meta.version > current_v:
                if target_meta.custom.get('variant') == app_variant:
                    if latest_update is None or target_meta.version > latest_update.version:
                        latest_update = target_meta
        
        if latest_update:
            logging.info(f"Update found: {latest_update.version}")
            if messagebox.askyesno("发现新版本", f"检测到新版本 {latest_update.version} ({app_variant})。是否要下载并安装？"):
                client._trusted_target_metas = [latest_update]
                client.download_and_apply_update()
                logging.info("Update applied successfully.")
                show_message("更新成功", f"已成功更新到版本 {latest_update.version}。请重新启动程序。")
            else:
                logging.info("User declined the update.")
        else:
            logging.info("No new updates found.")
            show_message("无更新", "您使用的已是最新版本。")

    except Exception as e:
        logging.error(f"An error occurred during the update process: {e}")
        show_message("更新失败", f"检查更新时发生错误: {e}", is_error=True)
    
    sys.exit(0)

if __name__ == "__main__":
    main()