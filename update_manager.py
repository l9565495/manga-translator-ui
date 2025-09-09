
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# --- 配置 ---
# PyUpdater 配置文件路径
CONFIG_PATH = Path(".pyupdater/config.pyu")
# 原始配置文件备份路径
CONFIG_BACKUP_PATH = Path(".pyupdater/config.pyu.bak")
# 客户端配置文件的基础路径
CLIENT_CONFIG_BASE_PATH = Path("desktop-ui")
# PyUpdater 需要修改的通用客户端配置文件名
CLIENT_CONFIG_TARGET = CLIENT_CONFIG_BASE_PATH / "client_config.py"
# 打包后的可执行文件名，如果你的可执行文件不叫 main.exe，请修改这里
EXE_NAME = "main.exe"
# --- 结束配置 ---

class DualVersionUpdateManager:
    """
    管理 CPU 和 GPU 双版本的 PyUpdater 更新包构建流程。
    """
    def _run_command(self, cmd, cwd=None):
        """执行一个 shell 命令并打印输出。"""
        print(f"\nExecuting: {' '.join(cmd)}")
        try:
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace'
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

    def _backup_config(self):
        """备份原始的 PyUpdater 配置文件。"""
        if CONFIG_PATH.exists() and not CONFIG_BACKUP_PATH.exists():
            shutil.copy(CONFIG_PATH, CONFIG_BACKUP_PATH)
            print(f"Backed up original config to {CONFIG_BACKUP_PATH}")

    def _restore_config(self):
        """恢复原始的 PyUpdater 配置文件。"""
        if CONFIG_BACKUP_PATH.exists():
            shutil.move(CONFIG_BACKUP_PATH, CONFIG_PATH)
            print(f"Restored original config from {CONFIG_BACKUP_PATH}")

    def _process_version(self, version_type, app_version):
        """处理指定版本（cpu 或 gpu）的更新包构建。"""
        print("-" * 60)
        print(f"Processing {version_type.upper()} version...")
        
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
        print(f"Prepared client config for {version_type.upper()}")

        # 2. 修改 PyUpdater 配置文件
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        
        update_url = f"https://raw.githubusercontent.com/hgmzhn/manga-translator-ui/main/updates/{version_type}/"
        config_data['app_config']['UPDATE_URLS'] = [update_url]
        
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2)
        print(f"Set update URL to: {update_url}")

        # 3. 运行 PyUpdater 命令
        python_exe = venv_path / "Scripts" / "python.exe" if sys.platform == "win32" else venv_path / "bin" / "python"
        
        if version_type == 'cpu':
            exe_path = Path("dist") / "manga-translator-cpu-final" / EXE_NAME
        else:  # gpu
            exe_path = Path("dist") / "manga-translator-gpu-cuda118" / EXE_NAME

        if not exe_path.exists():
            print(f"\nError: Executable not found at '{exe_path}'")
            print("Please ensure you have built the application for this version first.")
            return False

        # PyUpdater 'build' 命令
        cmd_build = [str(python_exe), "-m", "pyupdater", "build", "--app-version", app_version, str(exe_path)]
        if not self._run_command(cmd_build):
            print(f"PyUpdater 'build' command failed for {version_type.upper()}.")
            return False
        
        # PyUpdater 'pkg' 命令
        cmd_process = [str(python_exe), "-m", "pyupdater", "pkg", "--process"]
        if not self._run_command(cmd_process):
            print(f"PyUpdater 'pkg' command failed for {version_type.upper()}.")
            return False
            
        print(f"Successfully processed updates for {version_type.upper()}.")
        return True

    def build_updates(self):
        """构建双版本更新包的主函数。"""
        app_version = input("Enter the app version for the update (e.g., 2.5.2): ").strip()
        if not app_version:
            print("Error: App version cannot be empty.")
            return False

        self._backup_config()
        try:
            # 按顺序处理 CPU 和 GPU
            if not self._process_version("cpu", app_version):
                print("\nBuild failed during CPU version processing.")
                return False
            
            if not self._process_version("gpu", app_version):
                print("\nBuild failed during GPU version processing.")
                return False

        finally:
            # 无论成功与否，都恢复原始配置并清理临时文件
            self._restore_config()
            if CLIENT_CONFIG_TARGET.exists():
                os.remove(CLIENT_CONFIG_TARGET)
                print(f"Cleaned up temporary file: {CLIENT_CONFIG_TARGET}")

        print("=" * 60)
        print("Update processing complete for both CPU and GPU versions.")
        print("Please upload the contents of the 'pyu-data/deploy' directory to your update server.")
        print("=" * 60)
        return True

if __name__ == '__main__':
    # 允许直接从命令行运行此脚本
    manager = DualVersionUpdateManager()
    manager.build_updates()
