import subprocess
import sys
import os
import json
import argparse
from pathlib import Path
import shutil
import io

# Force stdout and stderr to use UTF-8 encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Try to import tufup, and provide a helpful error message if it's not installed.
try:
    from tufup.repo import Repository
except ImportError:
    print("Error: tufup library not found. Please install it with: pip install tufup")
    sys.exit(1)

# --- configuration ---
APP_NAME = "MangaTranslatorUI"
REPO_DIR = 'update_repository'
KEYS_DIR = 'keys'
APP_VERSION_ATTR = '__version__'

def run_command_realtime(cmd, cwd=None):
    """实时执行一个 shell 命令并打印输出。"""
    use_shell = isinstance(cmd, str)
    print(f"\nExecuting: {cmd}")
    try:
        # Set PYTHONUTF8 environment variable to ensure UTF-8 is used by subprocesses
        env = os.environ.copy()
        env['PYTHONUTF8'] = '1'
        
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            shell=use_shell,
            env=env
        )
        
        # Real-time output
        for line in process.stdout:
            print(line.strip())
        
        returncode = process.wait()
        print(f"Exit code: {returncode}")
        return returncode == 0
    except Exception as e:
        # Try to print the exception, but be prepared for encoding errors
        try:
            print(f"Error executing command: {e}")
        except UnicodeEncodeError:
            print(f"Error executing command (ascii representation): {repr(e)}")
        return False




class Builder:
    """封装了构建和打包逻辑的类"""

    def __init__(self, app_version=None, is_creating_keys=False):
        self.app_version = app_version
        self.version_file = Path("VERSION")
        
        repo_path = Path(REPO_DIR)
        (repo_path / 'targets').mkdir(parents=True, exist_ok=True)
        
        self.repo = Repository(
            repo_dir=repo_path,
            keys_dir=Path(KEYS_DIR),
            app_name=APP_NAME,
            app_version_attr=APP_VERSION_ATTR
        )

        # If creating keys, the `builder.create_keys()` method will handle loading.
        # Otherwise, we need to explicitly load the existing repository data.
        if not is_creating_keys:
            print("Loading existing repository...")
            # NOTE: This is a private method, but required for now based on source code analysis.
            self.repo._load_keys_and_roles(create_keys=False)

        # Now, the check for self.repo.roles should pass.
        if not is_creating_keys and self.repo.roles is None:
            print("Error: Repository metadata is missing or corrupt, and could not be loaded.")
            print("Please ensure the 'update_repository/metadata' directory is valid or run with --create-keys to start fresh.")
            sys.exit(1)

    def create_keys(self):
        """Create new keys if they don't exist."""
        keys_path = Path(KEYS_DIR)
        if not keys_path.exists():
            keys_path.mkdir()
        print("Creating new keys...")
        self.repo.initialize()
        print("Keys created. Please securely back up the 'keys' directory and do NOT commit it to git.")

    def build_executables(self, version_type):
        """使用 PyInstaller 构建指定版本 (cpu 或 gpu)"""
        print("=" * 60)
        print(f"Building {version_type.upper()} Executable")
        print("=" * 60)

        venv_path = Path(f".venv_{version_type}")
        req_file = f"requirements_{version_type}.txt"
        spec_file = f"manga-translator-{version_type}.spec"

        # Prefer local venv python if it exists, otherwise use the python running this script
        python_exe_in_venv = venv_path / 'Scripts' / 'python.exe' if sys.platform == 'win32' else venv_path / 'bin' / 'python'
        if os.path.exists(python_exe_in_venv):
            python_exe = str(python_exe_in_venv)
            print(f"Using python from venv: {python_exe}")
        else:
            python_exe = sys.executable
            print(f"Venv python not found. Using system python: {python_exe}")

        if not Path(spec_file).exists():
            print(f"Error: Spec file '{spec_file}' not found.")
            return False
        
        # In a CI environment, we assume dependencies are pre-installed by the workflow.
        print(f"Running PyInstaller for {version_type.upper()}...")
        cmd_pyinstaller = [python_exe, "-m", "PyInstaller", spec_file]
        if not run_command_realtime(cmd_pyinstaller):
            print(f"PyInstaller build failed for {version_type.upper()}.")
            return False

        print(f"\nRunning PyInstaller for Updater...")
        updater_spec_file = 'updater.spec'
        # Use the same python for consistency
        cmd_pyinstaller_updater = [str(python_exe), "-m", "PyInstaller", updater_spec_file, "--distpath", "dist", "--workpath", f"build/updater_{version_type}"]
        if not run_command_realtime(cmd_pyinstaller_updater):
            print(f"PyInstaller build failed for Updater.")
            return False

        print(f"\nCopying updater to dist folder...")
        dist_dir = Path("dist") / f"manga-translator-{version_type}"
        updater_exe_src = Path("dist") / "updater" / "updater.exe"
        updater_exe_dest = dist_dir / "updater.exe"
        
        try:
            shutil.copy2(updater_exe_src, updater_exe_dest)
            print(f"Copied updater to {updater_exe_dest}")
        except Exception as e:
            print(f"Failed to copy updater: {e}")
            return False
        
        # Create build_info.json
        dist_dir = Path("dist") / f"manga-translator-{version_type}"
        build_info_path = dist_dir / "build_info.json"
        print(f"Creating build info file at: {build_info_path}")
        with open(build_info_path, "w", encoding="utf-8") as f:
            json.dump({"variant": version_type}, f, indent=2)

        print(f"{version_type.upper()} build completed!")
        return True

    def package_updates(self, version_type):
        """
        Adds an update package to the TUF repository.
        It only adds patches as client-facing update targets.
        The full bundle archive is always created to serve as a base for future patches,
        but it is NEVER registered in the client-facing metadata.
        """
        print("=" * 60)
        print(f"Adding update package for {version_type.upper()}")
        print("=" * 60)

        # For GPU, we skip the auto-update process entirely as per user decision
        if version_type == 'gpu':
            print("Skipping TUF packaging for GPU version.")
            return True

        self.version_file.write_text(self.app_version, encoding='utf-8')
        dist_dir = Path("dist") / f"manga-translator-{version_type}"

        if not dist_dir.exists():
            print(f"\nError: Bundle directory not found at '{dist_dir}'")
            return False

        print(f"Creating full archive from: {dist_dir} to serve as a future base package.")
        # Step 1: Always create the full archive. This places it in the `targets`
        # directory, making it the "Base Package" for the next workflow run.
        # It will NOT be registered as a client-facing target.
        archive_path = self.repo.create_archive(
            bundle_dir=dist_dir,
            version=self.app_version,
            custom_metadata={'variant': version_type}
        )

        print("Attempting to create patches...")
        # Step 2: Try to create patches. `tufup` automatically adds them to metadata if successful.
        patch_paths = self.repo.create_patches()

        if patch_paths:
            print(f'Created {len(patch_paths)} patch(es). These will be the only update targets registered in metadata.')
        else:
            print('No patches created (first release). No client-facing update targets will be added to metadata for this version.')

        return True

    def publish_updates(self):
        """
        Signs and publishes all changes to the repository.
        """
        print("=" * 60)
        print("Publishing changes to repository...")
        print("=" * 60)
        self.repo.publish_changes(private_key_dirs=[KEYS_DIR])
        print("Repository update complete.")
        return True

def main():
    # Ensure the keys directory exists to prevent interactive prompts in CI
    if not os.path.exists(KEYS_DIR):
        print(f"'{KEYS_DIR}' directory not found. Creating it to avoid interactive prompts.")
        os.makedirs(KEYS_DIR)

    parser = argparse.ArgumentParser(description="Manga Translator UI Builder and Updater")
    parser.add_argument("version", nargs='?', default=None, help="The application version to build (e.g., 1.4.0)")
    parser.add_argument("--build", choices=['cpu', 'gpu', 'both'], default='both', help="Which version(s) to build.")
    parser.add_argument("--skip-build", action='store_true', help="Skip building executables.")
    parser.add_argument("--update-repo", action='store_true', help="Update the TUF repository with the built packages.")
    parser.add_argument("--create-keys", action='store_true', help="Create new TUF keys if they don't exist.")
    args = parser.parse_args()

    builder = Builder(args.version, is_creating_keys=args.create_keys)

    if args.create_keys:
        builder.create_keys()
        sys.exit(0)

    if not args.version:
        parser.error("the following arguments are required: version")

    print(f"--- Starting process for version {args.version} ---")

    versions_to_process = []
    if args.build in ['cpu', 'both']:
        versions_to_process.append('cpu')
    if args.build in ['gpu', 'both']:
        versions_to_process.append('gpu')

    for v_type in versions_to_process:
        if not args.skip_build:
            if not builder.build_executables(v_type):
                print(f"\nFATAL: Build failed for {v_type.upper()}. Halting.")
                sys.exit(1)
        
        if args.update_repo:
            if not builder.package_updates(v_type):
                print(f"\nFATAL: Update packaging failed for {v_type.upper()}. Halting.")
                sys.exit(1)

    if args.update_repo:
        builder.publish_updates()

    print("\n" + "=" * 60)
    print("ALL TASKS COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    if args.update_repo:
        print("Next steps:")
        print("1. Commit and push the 'update_repository/' directory to your git repository.")
        print("2. The GitHub Actions workflow should handle the rest.")

if __name__ == "__main__":
    main()
