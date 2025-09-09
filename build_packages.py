#!/usr/bin/env python3
"""
Manga Translator Package Builder
Builds both GPU and CPU versions of the application
"""
import subprocess
import sys
import os
import shutil
import json
import argparse
from pathlib import Path

# --- PyUpdater 配置 ---
CONFIG_PATH = Path(".pyupdater/config.pyu")
CONFIG_BACKUP_PATH = Path(".pyupdater/config.pyu.bak")
CLIENT_CONFIG_BASE_PATH = Path("desktop-ui")
CLIENT_CONFIG_TARGET = CLIENT_CONFIG_BASE_PATH / "client_config.py"
EXE_NAME = "main.exe"  # 如果你的可执行文件不叫 main.exe，请修改这里
# --- 结束配置 ---

def run_command_realtime(cmd, cwd=None):
    """实时执行一个 shell 命令并打印输出。"""
    print(f"\nExecuting: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    try:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            shell=True
        )
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                print(output.strip())
        
        returncode = process.poll()
        print(f"Exit code: {returncode}")
        return returncode == 0
    except Exception as e:
        print(f"Error executing command: {e}")
        return False

class PackageBuilder:
    """封装了构建和打包逻辑的类"""

    def __init__(self, app_version):
        self.app_version = app_version

    def build_version(self, version_type):
        """构建指定版本 (cpu 或 gpu)"""
        print("=" * 60)
        print(f"Building {version_type.upper()} Version")
        print("=" * 60)

        venv_path = Path(f".venv_{version_type}")
        req_file = f"requirements_{version_type}.txt"
        spec_file = f"manga-translator-{version_type}.spec"
        dist_dir = Path("dist") / f"manga-translator-{version_type}-final"
        if version_type == 'gpu':
            dist_dir = Path("dist") / "manga-translator-gpu-cuda118"

        # 1. 设置虚拟环境
        if not venv_path.exists():
            print(f"Creating virtual environment for {version_type.upper()} build...")
            if not run_command_realtime(f'{sys.executable} -m venv {venv_path}'):
                return False
        else:
            print(f"Using existing {version_type.upper()} virtual environment...")

        # 激活命令和Python可执行文件路径
        if sys.platform == 'win32':
            activate_cmd = f'{venv_path}\Scripts\activate && '
            python_cmd = f'{venv_path}\Scripts\python.exe'
        else:
            activate_cmd = f'source {venv_path}/bin/activate && '
            python_cmd = f'{venv_path}/bin/python3'

        # 2. 安装依赖
        print("Upgrading pip...")
        if not run_command_realtime(f'{activate_cmd}{python_cmd} -m pip install --upgrade pip'): return False
        
        if version_type == 'gpu':
            print("Installing PyTorch with CUDA 11.8...")
            torch_cmd = f'{activate_cmd}pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118'
            if not run_command_realtime(torch_cmd): return False

        print(f"Installing {version_type.upper()} dependencies...")
        if not run_command_realtime(f'{activate_cmd}pip install -r {req_file}'): return False
        if not run_command_realtime(f'{activate_cmd}pip install pyinstaller'): return False

        # 3. 清理旧的构建
        if dist_dir.exists():
            print(f"Cleaning previous build: {dist_dir}")
            shutil.rmtree(dist_dir)

        # 4. 使用 PyInstaller 构建
        print(f"Building {version_type.upper()} application...")
        if not run_command_realtime(f'{activate_cmd}pyinstaller {spec_file}'):
            return False

        # 5. 重命名输出文件夹
        temp_dist_dir = Path("dist") / f"manga-translator-{version_type}"
        if temp_dist_dir.exists():
            if dist_dir.exists(): shutil.rmtree(dist_dir)
            os.rename(temp_dist_dir, dist_dir)
            print(f"{version_type.upper()} build completed! Output in {dist_dir}")
            return True
        else:
            print(f"{version_type.upper()} build failed - output directory not found!")
            return False

    def package_updates(self, version_type):
        """为指定版本创建PyUpdater更新包"""
        print("-" * 60)
        print(f"Processing PyUpdater packages for {version_type.upper()} version...")
        
        venv_path = Path(f".venv_{version_type}")
        if not venv_path.exists():
            print(f"Error: Virtual environment not found at {venv_path}")
            return False

        # 1. 准备客户端配置文件
        source_client_config = CLIENT_CONFIG_BASE_PATH / f"client_config_{version_type}.py"
        if not source_client_config.exists():
            print(f"Error: Source client config not found at {source_client_config}")
            return False
        shutil.copy(source_client_config, CLIENT_CONFIG_TARGET)

        # 2. 修改 PyUpdater 配置文件
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        update_url = f"https://raw.githubusercontent.com/hgmzhn/manga-translator-ui/main/updates/{version_type}/"
        config_data['app_config']['UPDATE_URLS'] = [update_url]
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2)

        # 3. 运行 PyUpdater 命令
        python_exe = venv_path / "Scripts" / "python.exe" if sys.platform == "win32" else venv_path / "bin" / "python"
        
        if version_type == 'cpu':
            exe_path = Path("dist") / "manga-translator-cpu-final" / EXE_NAME
        else:
            exe_path = Path("dist") / "manga-translator-gpu-cuda118" / EXE_NAME

        if not exe_path.exists():
            print(f"\nError: Executable not found at '{exe_path}'")
            return False

        cmd_build = [str(python_exe), "-m", "pyupdater", "build", "--app-version", self.app_version, str(exe_path)]
        if not run_command_realtime(cmd_build): return False
        
        cmd_process = [str(python_exe), "-m", "pyupdater", "pkg", "--process"]
        if not run_command_realtime(cmd_process): return False
            
        print(f"Successfully processed updates for {version_type.upper()}.")
        return True

    def backup_config(self):
        if CONFIG_PATH.exists() and not CONFIG_BACKUP_PATH.exists():
            shutil.copy(CONFIG_PATH, CONFIG_BACKUP_PATH)

    def restore_config(self):
        if CONFIG_BACKUP_PATH.exists():
            shutil.move(CONFIG_BACKUP_PATH, CONFIG_PATH)
        if CLIENT_CONFIG_TARGET.exists():
            os.remove(CLIENT_CONFIG_TARGET)

def main():
    parser = argparse.ArgumentParser(description="Manga Translator UI Package Builder")
    parser.add_argument("--version", required=True, help="The application version to build (e.g., 2.6.0)")
    parser.add_argument("--build", choices=['cpu', 'gpu', 'both'], default='both', help="Which version to build.")
    parser.add_argument("--skip-build", action='store_true', help="Skip the application build and only package updates.")
    parser.add_argument("--skip-updates", action='store_true', help="Skip packaging updates and only build the application.")
    args = parser.parse_args()

    print(f"Starting build process for version {args.version}")
    builder = PackageBuilder(args.version)

    build_ok = True
    if not args.skip_build:
        if args.build in ['cpu', 'both']:
            if not builder.build_version('cpu'):
                build_ok = False
        if args.build in ['gpu', 'both'] and build_ok:
            if not builder.build_version('gpu'):
                build_ok = False
    
    if not build_ok:
        print("\n" + "=" * 60)
        print("BUILD FAILED!")
        print("=" * 60)
        sys.exit(1)
    elif not args.skip_updates:
        print("\n" + "=" * 60)
        print("BUILD COMPLETED SUCCESSFULLY! NOW PACKAGING UPDATES...")
        print("=" * 60)

    if not args.skip_updates:
        builder.backup_config()
        updates_ok = True
        try:
            if args.build in ['cpu', 'both']:
                if not builder.package_updates('cpu'):
                    updates_ok = False
            if args.build in ['gpu', 'both'] and updates_ok:
                if not builder.package_updates('gpu'):
                    updates_ok = False
        finally:
            builder.restore_config()
        
        if not updates_ok:
            print("\n" + "=" * 60)
            print("UPDATE PACKAGING FAILED!")
            print("=" * 60)
            sys.exit(1)

    print("\n" + "=" * 60)
    print("ALL TASKS COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    if not args.skip_updates:
        print("Please upload the contents of the 'pyu-data/deploy' directory to your update server.")

if __name__ == "__main__":
    main()
