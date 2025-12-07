#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
漫画翻译器启动脚本
Manga Translator UI Launcher
"""

import os
import sys
import argparse
import subprocess
import importlib.util
from pathlib import Path

# 项目配置
BRANCH = 'main'
VERSION = '1.7.6'
PYTHON_VERSION_MIN = (3, 12)
PYTHON_VERSION_MAX = (3, 12)  # 仅支持Python 3.12,不支持3.13+

# 路径配置
PATH_ROOT = Path(__file__).parent.parent
stored_commit_hash = None

# 获取环境变量
python = sys.executable

# Git路径配置 (优先使用便携版)
portable_git = PATH_ROOT / "PortableGit" / "cmd" / "git.exe"
if portable_git.exists():
    git = str(portable_git)
else:
    git = os.environ.get('GIT', "git")

skip_install = False
index_url = os.environ.get('INDEX_URL', "")


def is_python_version_valid():
    """检查Python版本是否符合要求"""
    if sys.version_info < PYTHON_VERSION_MIN:
        print(f'错误: 需要 Python {PYTHON_VERSION_MIN[0]}.{PYTHON_VERSION_MIN[1]}+ ')
        print(f'当前版本: Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')
        return False
    if sys.version_info[:2] > PYTHON_VERSION_MAX:
        print(f'错误: 仅支持 Python {PYTHON_VERSION_MAX[0]}.{PYTHON_VERSION_MAX[1]},不支持更高版本')
        print(f'当前版本: Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')
        print(f'请使用 Python {PYTHON_VERSION_MAX[0]}.{PYTHON_VERSION_MAX[1]} 版本')
        return False
    return True


def is_installed(package):
    """检查Python包是否已安装"""
    try:
        spec = importlib.util.find_spec(package)
    except ModuleNotFoundError:
        return False
    return spec is not None


def run(command, desc=None, errdesc=None, custom_env=None, live=False):
    """执行系统命令"""
    if desc is not None:
        print(desc)

    if live:
        result = subprocess.run(command, shell=True, env=os.environ if custom_env is None else custom_env)
        if result.returncode != 0:
            raise RuntimeError(f"""{errdesc or '命令执行错误'}.
命令: {command}
错误代码: {result.returncode}""")
        return ""

    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True,
                            env=os.environ if custom_env is None else custom_env,
                            encoding='gbk', errors='ignore')

    if result.returncode != 0:
        message = f"""{errdesc or '命令执行错误'}.
命令: {command}
错误代码: {result.returncode}
stdout: {result.stdout if len(result.stdout) > 0 else '<empty>'}
stderr: {result.stderr if len(result.stderr) > 0 else '<empty>'}
"""
        raise RuntimeError(message)

    return result.stdout


def run_pip(args, desc=None):
    """使用pip安装包"""
    if skip_install:
        return
    
    index_url_line = f' --index-url {index_url}' if index_url != '' else ''
    
    # ✅ 添加 --trusted-host 参数以解决SSL证书问题
    # 需要为主索引和PyTorch官方源都添加trusted-host
    trusted_host_line = ''
    if index_url:
        import urllib.parse
        # 主索引（清华源等）
        parsed = urllib.parse.urlparse(index_url)
        if parsed.hostname:
            trusted_host_line += f' --trusted-host {parsed.hostname}'
        
        # PyTorch官方源（如果在requirements中使用了--extra-index-url）
        # 添加常用的PyTorch源
        trusted_host_line += ' --trusted-host download.pytorch.org'
    
    return run(f'"{python}" -m pip {args} --prefer-binary{index_url_line}{trusted_host_line} --disable-pip-version-check --no-warn-script-location',
               desc=f"正在安装 {desc}", errdesc=f"无法安装 {desc}", live=True)


def commit_hash():
    """获取当前Git commit hash"""
    global stored_commit_hash
    if stored_commit_hash is not None:
        return stored_commit_hash

    try:
        stored_commit_hash = run(f"{git} rev-parse HEAD").strip()
    except Exception:
        stored_commit_hash = "<none>"

    return stored_commit_hash


def restart():
    """重启应用"""
    print('正在重启应用...\n')
    os.execv(sys.executable, ['python'] + sys.argv)


def detect_gpu():
    """检测GPU类型 - 使用多种方法以提高兼容性"""
    
    def check_gpu_keywords(output):
        """检查输出中的GPU关键词，返回 (GPU类型, 显卡名称)"""
        if not output:
            return None, None
        output_upper = output.upper()
        
        # 提取显卡名称（取第一行非空的）
        gpu_name = ""
        for line in output.strip().split('\n'):
            line = line.strip()
            if line and not line.startswith('NAME') and not line.startswith('---'):
                gpu_name = line
                break
        
        if any(keyword in output_upper for keyword in ["NVIDIA", "GEFORCE", "GTX", "RTX", "QUADRO", "TESLA"]):
            return "NVIDIA", gpu_name
        elif any(keyword in output_upper for keyword in ["AMD", "RADEON", "ATI"]):
            return "AMD", gpu_name
        elif "INTEL" in output_upper and any(keyword in output_upper for keyword in ["HD GRAPHICS", "UHD GRAPHICS", "IRIS", "ARC"]):
            return "Intel", gpu_name
        return None, None
    
    def check_nvidia_cuda_version():
        """检查 NVIDIA CUDA 驱动版本"""
        try:
            # 尝试运行 nvidia-smi 获取驱动版本
            cmd = 'nvidia-smi --query-gpu=driver_version --format=csv,noheader'
            output = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL, timeout=5, encoding='gbk', errors='ignore')
            driver_version = output.strip().split('\n')[0].strip()
            
            # 尝试从nvidia-smi直接输出获取CUDA版本
            # nvidia-smi输出的第一行通常包含CUDA版本信息
            try:
                cmd_full = 'nvidia-smi'
                full_output = subprocess.check_output(cmd_full, shell=True, text=True, stderr=subprocess.DEVNULL, timeout=5, encoding='gbk', errors='ignore')
                # 解析 "CUDA Version: X.Y" 格式
                import re
                cuda_match = re.search(r'CUDA Version:\s*(\d+\.\d+)', full_output)
                if cuda_match:
                    cuda_version = cuda_match.group(1)
                    cuda_major = int(cuda_version.split('.')[0])
                    return cuda_major, cuda_version, driver_version
            except:
                pass
            
            # 如果无法获取CUDA版本，返回驱动版本
            return None, None, driver_version
        except Exception:
            return None, None, None
    
    try:
        if sys.platform == 'win32':
            # Windows 系统：尝试多种检测方式（优先使用无需安装的方法）
            
            # 方法1: 尝试 PowerShell Get-CimInstance（Windows 8+，无需额外工具）
            try:
                cmd = 'powershell -NoProfile -Command "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"'
                output = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL, timeout=5, encoding='gbk', errors='ignore')
                gpu_type, gpu_name = check_gpu_keywords(output)
                if gpu_type:
                    # 如果是 NVIDIA，检查 CUDA 版本
                    if gpu_type == "NVIDIA":
                        cuda_major, cuda_version, driver_version = check_nvidia_cuda_version()
                        return gpu_type, gpu_name, cuda_major, cuda_version, driver_version
                    return gpu_type, gpu_name, None, None, None
            except Exception:
                pass
            
            # 方法2: 尝试 wmic（经典方法，兼容老系统）
            try:
                cmd = 'wmic path win32_VideoController get name'
                output = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL, timeout=5, encoding='gbk', errors='ignore')
                gpu_type, gpu_name = check_gpu_keywords(output)
                if gpu_type:
                    # 如果是 NVIDIA，检查 CUDA 版本
                    if gpu_type == "NVIDIA":
                        cuda_major, cuda_version, driver_version = check_nvidia_cuda_version()
                        return gpu_type, gpu_name, cuda_major, cuda_version, driver_version
                    return gpu_type, gpu_name, None, None, None
            except Exception:
                pass
            
            # 方法3: 尝试 PowerShell Get-WmiObject（更老的 PowerShell）
            try:
                cmd = 'powershell -NoProfile -Command "Get-WmiObject Win32_VideoController | Select-Object -ExpandProperty Name"'
                output = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL, timeout=5, encoding='gbk', errors='ignore')
                gpu_type, gpu_name = check_gpu_keywords(output)
                if gpu_type:
                    # 如果是 NVIDIA，检查 CUDA 版本
                    if gpu_type == "NVIDIA":
                        cuda_major, cuda_version, driver_version = check_nvidia_cuda_version()
                        return gpu_type, gpu_name, cuda_major, cuda_version, driver_version
                    return gpu_type, gpu_name, None, None, None
            except Exception:
                pass
            
            # 方法4: 尝试读取注册表（最底层的方法）
            try:
                cmd = 'reg query "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0000" /v DriverDesc'
                output = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL, timeout=5, encoding='gbk', errors='ignore')
                gpu_type, gpu_name = check_gpu_keywords(output)
                if gpu_type:
                    # 如果是 NVIDIA，检查 CUDA 版本
                    if gpu_type == "NVIDIA":
                        cuda_major, cuda_version, driver_version = check_nvidia_cuda_version()
                        return gpu_type, gpu_name, cuda_major, cuda_version, driver_version
                    return gpu_type, gpu_name, None, None, None
            except Exception:
                pass
            
            # 方法5: 尝试使用 wmi Python 库（需要额外安装，作为最后备选）
            try:
                # 先尝试导入，如果失败则尝试安装
                try:
                    import wmi
                except ImportError:
                    # 库不存在，尝试安装
                    try:
                        import subprocess as sp
                        print('正在安装 wmi 库以进行显卡检测...')
                        sp.run([python, '-m', 'pip', 'install', 'wmi', '--quiet'], check=True, timeout=30)
                        import wmi
                        print('wmi 库安装成功')
                    except Exception:
                        # 安装失败，跳过
                        raise ImportError('wmi 库安装失败')
                
                # 使用 wmi 检测
                c = wmi.WMI()
                for gpu in c.Win32_VideoController():
                    gpu_type, gpu_name = check_gpu_keywords(gpu.Name)
                    if gpu_type:
                        # 如果是 NVIDIA，检查 CUDA 版本
                        if gpu_type == "NVIDIA":
                            cuda_major, cuda_version, driver_version = check_nvidia_cuda_version()
                            return gpu_type, gpu_name, cuda_major, cuda_version, driver_version
                        return gpu_type, gpu_name, None, None, None
            except (ImportError, Exception):
                pass
                
        else:
            # Linux/Mac: 使用lspci或其他工具
            try:
                output = subprocess.check_output("lspci | grep -i vga", shell=True, text=True, stderr=subprocess.DEVNULL, timeout=5, encoding='gbk', errors='ignore')
                gpu_type, gpu_name = check_gpu_keywords(output)
                if gpu_type:
                    # 如果是 NVIDIA，检查 CUDA 版本
                    if gpu_type == "NVIDIA":
                        cuda_major, cuda_version, driver_version = check_nvidia_cuda_version()
                        return gpu_type, gpu_name, cuda_major, cuda_version, driver_version
                    return gpu_type, gpu_name, None, None, None
            except:
                pass
            
            # 尝试使用 lshw
            try:
                output = subprocess.check_output("lshw -C display 2>/dev/null | grep 'product:'", shell=True, text=True, stderr=subprocess.DEVNULL, timeout=5, encoding='gbk', errors='ignore')
                gpu_type, gpu_name = check_gpu_keywords(output)
                if gpu_type:
                    # 如果是 NVIDIA，检查 CUDA 版本
                    if gpu_type == "NVIDIA":
                        cuda_major, cuda_version, driver_version = check_nvidia_cuda_version()
                        return gpu_type, gpu_name, cuda_major, cuda_version, driver_version
                    return gpu_type, gpu_name, None, None, None
            except:
                pass
                
    except Exception:
        pass
    
    return "CPU", "", None, None, None


def detect_amd_gfx_version(gpu_name):
    """根据 AMD 显卡名称检测对应的 gfx 版本
    
    返回: (gfx_version, architecture_name) 或 (None, None)
    """
    if not gpu_name:
        return None, None
    
    gpu_name_upper = gpu_name.upper()
    
    # AMD 显卡型号到 gfx 版本的映射
    # 参考: https://github.com/ROCm/ROCm
    amd_gpu_mapping = {
        # RDNA 3 架构 (RX 7000 系列)
        'gfx1150': {
            'keywords': ['7900 XTX', '7900 XT', '7950'],
            'name': 'RDNA 3 (Navi 31)'
        },
        'gfx1151': {
            'keywords': ['7800 XT', '7700 XT', '7600'],
            'name': 'RDNA 3 (Navi 32/33)'
        },
        'gfx110X-all': {
            'keywords': ['RX 7'],  # 通用 RX 7000 系列
            'name': 'RDNA 3 (RX 7000 系列)'
        },
        
        # RDNA 2 架构 (RX 6000 系列) - 不支持，使用CPU
        # 'gfx103X-dgpu': {
        #     'keywords': ['RX 6', '6900', '6800', '6700', '6600', '6500', '6400'],
        #     'name': 'RDNA 2 (RX 6000 系列) - 不支持，请使用CPU版本'
        # },
        
        # RDNA 1 架构 (RX 5000 系列) - 不支持，使用CPU
        # 'gfx101X-dgpu': {
        #     'keywords': ['RX 5', '5700', '5600', '5500'],
        #     'name': 'RDNA 1 (RX 5000 系列) - 不支持，请使用CPU版本'
        # },
        
        # Vega 架构
        'gfx90X-dcgpu': {
            'keywords': ['VEGA', 'RADEON VII', 'MI25', 'MI50', 'MI60'],
            'name': 'Vega (Radeon VII / MI50/60)'
        },
        
        # CDNA 2 (数据中心)
        'gfx94X-dcgpu': {
            'keywords': ['MI200', 'MI210', 'MI250', 'MI260'],
            'name': 'CDNA 2 (MI200 系列)'
        },
        
        # CDNA 3 (数据中心)
        'gfx950-dcgpu': {
            'keywords': ['MI300'],
            'name': 'CDNA 3 (MI300 系列)'
        },
        
        # RDNA 4 架构 (RX 9000 系列)
        'gfx120X-all': {
            'keywords': ['RX 9', '9070 XT', '9070', '9060 XT', '9060', '9050'],
            'name': 'RDNA 4 (RX 9000 系列)'
        },
    }
    
    # 尝试匹配
    for gfx_version, info in amd_gpu_mapping.items():
        for keyword in info['keywords']:
            if keyword in gpu_name_upper:
                return gfx_version, info['name']
    
    return None, None


def detect_installed_pytorch_version():
    """检测当前安装的PyTorch版本类型(CPU/GPU)"""
    try:
        import torch
        if torch.cuda.is_available():
            # 检查CUDA版本
            cuda_version = torch.version.cuda
            if cuda_version:
                return "GPU", f"CUDA {cuda_version}"
        return "CPU", "CPU-only"
    except (ImportError, AttributeError):
        return None, "未安装"


def get_requirements_file_from_env():
    """从当前虚拟环境检测应该使用哪个requirements文件"""
    pytorch_type, detail = detect_installed_pytorch_version()
    
    if pytorch_type == "GPU":
        return 'requirements_gpu.txt', pytorch_type, detail
    elif pytorch_type == "CPU":
        return 'requirements_cpu.txt', pytorch_type, detail
    else:
        # 未安装PyTorch,返回None让后续逻辑自动检测
        return None, None, detail


def prepare_environment(args):
    """准备运行环境
    
    返回: (use_amd_pytorch, amd_gfx_version) - 是否使用AMD PyTorch及其gfx版本
    """
    
    if args.frozen:
        print('frozen模式: 跳过依赖安装')
        return False, None

    # 确保 packaging 已安装 (需要 < 25.0 版本)
    try:
        import packaging
        import packaging.version
        import packaging.utils
        # 检查是否有 packaging.requirements (在 25.0 中已移除)
        try:
            from packaging.requirements import Requirement
        except (ImportError, AttributeError):
            # packaging 版本过高,需要降级
            print('检测到 packaging 版本不兼容,正在安装兼容版本...')
            run_pip("install 'packaging<25.0'", "packaging")
            import packaging
            import packaging.version
            import packaging.utils
            print('✓ packaging 安装成功')
    except (ModuleNotFoundError, ImportError):
        print('正在安装 packaging 模块...')
        run_pip("install 'packaging<25.0'", "packaging")
        try:
            import packaging
            import packaging.version
            import packaging.utils
            print('✓ packaging 安装成功')
        except (ModuleNotFoundError, ImportError):
            print('✗ 警告: packaging 安装失败')

    print('\n正在检查依赖...\n')
    
    # 将项目根目录添加到 Python 路径，以便导入 build_utils
    if str(PATH_ROOT) not in sys.path:
        sys.path.insert(0, str(PATH_ROOT))
    
    # 导入依赖检查工具
    try:
        from build_utils.package_checker import check_req_file
        print('✓ 依赖检查工具加载成功')
    except ImportError as e:
        print(f'✗ 警告: 无法导入依赖检查工具')
        print(f'   原因: {e}')
        print('   将跳过增量检查,强制重新安装所有依赖')
        check_req_file = lambda x: False

    # 检测GPU并选择对应的依赖文件
    gpu_type, gpu_name, cuda_major, cuda_version, driver_version = detect_gpu()
    print(f'\n检测到的计算设备: {gpu_type}')
    if gpu_name:
        print(f'显卡型号: {gpu_name}')
    if cuda_version:
        print(f'CUDA 版本: {cuda_version}')
        if driver_version:
            print(f'驱动版本: {driver_version}')
    print()
    
    # 根据GPU类型选择requirements文件
    use_amd_pytorch = False  # 初始化AMD PyTorch标志
    amd_gfx_version = None    # 初始化gfx版本
    
    if args.requirements != 'auto':
        # 用户手动指定,尊重用户选择
        requirements_file = args.requirements
        # 如果手动指定了 requirements_amd.txt，需要检测 gfx 版本并安装 AMD PyTorch
        if requirements_file == 'requirements_amd.txt':
            use_amd_pytorch = True
            # 尝试从环境中检测已安装的 AMD PyTorch 版本
            try:
                import torch
                if hasattr(torch.version, 'hip') and torch.version.hip:
                    # 已安装 AMD ROCm PyTorch，获取版本信息
                    print(f'\n检测到已安装 AMD ROCm PyTorch')
                    print(f'ROCm 版本: {torch.version.hip}')
                    print('')
                    
                    # 询问是否更新
                    update_choice = input('是否更新 AMD ROCm PyTorch? (y/n, 默认n): ').strip().lower()
                    if update_choice in ['y', 'yes']:
                        # 自动检测 gfx 版本
                        detected_gfx, arch_name = detect_amd_gfx_version(gpu_name) if gpu_name else (None, None)
                        
                        if detected_gfx:
                            print(f'\n自动识别架构: {arch_name}')
                            print(f'对应 gfx 版本: {detected_gfx}')
                            use_detected = input(f'使用检测到的 {detected_gfx}? (y/n, 默认y): ').strip().lower()
                            if use_detected in ['', 'y', 'yes']:
                                amd_gfx_version = detected_gfx
                            else:
                                amd_gfx_version = input('请输入您的 gfx 版本: ').strip()
                        else:
                            print('\n无法自动检测 gfx 版本')
                            amd_gfx_version = input('请输入您的 gfx 版本 (如 gfx103X-dgpu): ').strip()
                        
                        if not amd_gfx_version:
                            print('[INFO] 未输入 gfx 版本，跳过 AMD PyTorch 更新')
                            use_amd_pytorch = False
                    else:
                        use_amd_pytorch = False
                else:
                    # 未安装或非 AMD PyTorch
                    print('\n未检测到 AMD ROCm PyTorch')
                    print('[INFO] 手动指定了 requirements_amd.txt，但未安装 AMD PyTorch')
                    print('[INFO] 如需安装 AMD PyTorch，请运行 步骤1-首次安装.bat')
                    use_amd_pytorch = False
            except ImportError:
                # PyTorch 未安装
                print('\n未检测到 PyTorch')
                print('[INFO] 手动指定了 requirements_amd.txt，但未安装 PyTorch')
                print('[INFO] 如需安装 AMD PyTorch，请运行 步骤1-首次安装.bat')
                use_amd_pytorch = False
        else:
            pass  # 不是AMD，use_amd_pytorch已在开头初始化为False
    else:
        # 自动选择
        if gpu_type == "NVIDIA":
            print('=' * 50)
            print('检测到 NVIDIA GPU')
            print('=' * 50)
            print('')
            
            # 检查 CUDA 版本
            if cuda_major is not None:
                if cuda_major < 12:
                    print('⚠️  警告: 检测到 CUDA 版本低于 12')
                    print(f'   当前 CUDA 版本: {cuda_version}')
                    print(f'   GPU 版本需要: CUDA 12.x')
                    print(f'   驱动版本要求: >= 525.60.13')
                    print('')
                    print('您的 CUDA 版本过低，无法使用 GPU 版本。')
                    print('请选择:')
                    print('  [1] 更新 NVIDIA 驱动后重新运行安装')
                    print('  [2] 使用 CPU 版本')
                    print('')
                    
                    while True:
                        choice = input('请选择 (1/2, 默认2): ').strip()
                        if choice == '1':
                            print('\n请访问 NVIDIA 官网下载最新驱动:')
                            print('https://www.nvidia.com/Download/index.aspx')
                            print('\n安装驱动后请重新运行此脚本')
                            sys.exit(0)
                        elif choice in ['', '2']:
                            requirements_file = 'requirements_cpu.txt'
                            print(f'✓ 使用: {requirements_file} (CPU版本)')
                            break
                        else:
                            print('无效输入,请输入 1 或 2')
                else:
                    # CUDA 版本符合要求
                    print('GPU 版本需要:')
                    print('  - NVIDIA 显卡支持 CUDA 12.x')
                    print('  - 显卡驱动版本 >= 525.60.13')
                    print('')
                    print(f'✓ 您的 CUDA 版本 {cuda_version} 符合要求')
                    print('')
                    print('如果不确定,可以选择 CPU 版本(速度较慢但兼容性好)')
                    print('')
                    
                    while True:
                        choice = input('使用 GPU 版本? (y/n, 默认y): ').strip().lower()
                        if choice in ['', 'y', 'yes']:
                            requirements_file = 'requirements_gpu.txt'
                            print(f'✓ 使用: {requirements_file} (NVIDIA CUDA)')
                            break
                        elif choice in ['n', 'no']:
                            requirements_file = 'requirements_cpu.txt'
                            print(f'✓ 使用: {requirements_file} (CPU版本)')
                            break
                        else:
                            print('无效输入,请输入 y 或 n')
            else:
                # 无法检测 CUDA 版本
                print('⚠️  无法检测 CUDA 版本 (可能未安装 nvidia-smi)')
                print('')
                print('GPU 版本需要:')
                print('  - NVIDIA 显卡支持 CUDA 12.x')
                print('  - 显卡驱动版本 >= 525.60.13')
                print('')
                print('如果不确定,可以选择 CPU 版本(速度较慢但兼容性好)')
                print('')
                
                while True:
                    choice = input('使用 GPU 版本? (y/n, 默认y): ').strip().lower()
                    if choice in ['', 'y', 'yes']:
                        requirements_file = 'requirements_gpu.txt'
                        print(f'✓ 使用: {requirements_file} (NVIDIA CUDA)')
                        break
                    elif choice in ['n', 'no']:
                        requirements_file = 'requirements_cpu.txt'
                        print(f'✓ 使用: {requirements_file} (CPU版本)')
                        break
                    else:
                        print('无效输入,请输入 y 或 n')
                    
        elif gpu_type == "AMD":
            # 检测 AMD GPU 的 gfx 版本
            detected_gfx, arch_name = detect_amd_gfx_version(gpu_name)
            
            print('=' * 50)
            print('检测到 AMD GPU')
            print('=' * 50)
            print('')
            
            if detected_gfx:
                print(f'自动识别架构: {arch_name}')
                print(f'对应 gfx 版本: {detected_gfx}')
            else:
                print('⚠️  无法自动识别 AMD GPU 架构')
            
            print('')
            print('AMD GPU 支持选项:')
            print('  [1] AMD ROCm GPU 版本 (实验性,需要兼容的 AMD 显卡)')
            print('  [2] CPU 版本 (推荐,兼容性好)')
            print('')
            
            if detected_gfx:
                print(f'建议: 选择 [1] 并使用检测到的 {detected_gfx}')
            else:
                print('建议: 选择 [2] CPU 版本,或查询您的显卡对应的 gfx 版本')
            print('')
            
            while True:
                choice = input('请选择 (1/2, 默认2): ').strip()
                if choice == '1':
                    # 用户选择 AMD GPU
                    print('')
                    print('支持的 AMD gfx 版本:')
                    print('  - gfx101X-dgpu: RX 5000 系列 (RDNA 1)')
                    print('  - gfx103X-dgpu: RX 6000 系列 (RDNA 2)')
                    print('  - gfx110X-all:  RX 7000 系列 (RDNA 3)')
                    print('  - gfx1150:      RX 7900 XTX/XT (Navi 31)')
                    print('  - gfx1151:      RX 7800/7700/7600 (Navi 32/33)')
                    print('  - gfx120X-all:  RX 9070 XT/9070/9060 XT (RDNA 4)')
                    print('  - gfx90X-dcgpu: Vega / Radeon VII')
                    print('  - gfx94X-dcgpu: MI200 系列')
                    print('  - gfx950-dcgpu: MI300 系列')
                    print('')
                    
                    if detected_gfx:
                        default_gfx = detected_gfx
                        gfx_input = input(f'请输入您的 gfx 版本 (默认 {detected_gfx}): ').strip()
                        if not gfx_input:
                            amd_gfx_version = default_gfx
                        else:
                            amd_gfx_version = gfx_input
                    else:
                        gfx_input = input('请输入您的 gfx 版本 (如 gfx103X-dgpu): ').strip()
                        if gfx_input:
                            amd_gfx_version = gfx_input
                        else:
                            print('未输入 gfx 版本,将使用 CPU 版本')
                            requirements_file = 'requirements_cpu.txt'
                            break
                    
                    # 使用 AMD ROCm PyTorch
                    requirements_file = 'requirements_amd.txt'  # 使用专用的 AMD 依赖文件
                    use_amd_pytorch = True
                    print(f'✓ 将使用 AMD ROCm PyTorch ({amd_gfx_version})')
                    print(f'✓ 依赖文件: {requirements_file}')
                    break
                    
                elif choice in ['', '2']:
                    requirements_file = 'requirements_cpu.txt'
                    print(f'✓ 使用: {requirements_file} (CPU版本)')
                    break
                else:
                    print('无效输入,请输入 1 或 2')
                    
        elif gpu_type == "CPU":
            # 自动检测失败,让用户手动选择
            print('=' * 50)
            print('⚠️  无法自动检测显卡类型')
            print('=' * 50)
            print('')
            print('请手动选择安装版本:')
            print('  [1] NVIDIA GPU 版本 (CUDA) - 需要 NVIDIA 显卡')
            print('  [2] AMD GPU 版本 (ROCm) - 需要兼容的 AMD 显卡')
            print('  [3] CPU 版本 - 兼容所有电脑')
            print('')
            
            while True:
                choice = input('请选择 (1/2/3, 默认3): ').strip()
                if choice == '1':
                    requirements_file = 'requirements_gpu.txt'
                    print(f'✓ 使用: {requirements_file} (NVIDIA CUDA)')
                    break
                elif choice == '2':
                    # AMD GPU 手动输入
                    print('')
                    print('支持的 AMD gfx 版本:')
                    print('  - gfx103X-dgpu: RX 6000 系列')
                    print('  - gfx110X-all:  RX 7000 系列')
                    print('  - gfx1150:      RX 7900 XTX/XT')
                    print('  (更多版本见上方 AMD 选项说明)')
                    print('')
                    gfx_input = input('请输入您的 gfx 版本: ').strip()
                    if gfx_input:
                        amd_gfx_version = gfx_input
                        requirements_file = 'requirements_amd.txt'
                        use_amd_pytorch = True
                        print(f'✓ 将使用 AMD ROCm PyTorch ({amd_gfx_version})')
                        print(f'✓ 依赖文件: {requirements_file}')
                        break
                    else:
                        print('未输入 gfx 版本')
                        continue
                elif choice in ['', '3']:
                    requirements_file = 'requirements_cpu.txt'
                    print(f'✓ 使用: {requirements_file} (CPU版本)')
                    break
                else:
                    print('无效输入,请输入 1, 2 或 3')
                    
        else:
            # Intel GPU - 在 Windows 上支持有限,推荐使用 CPU 版本
            print('=' * 50)
            print('检测到 Intel GPU')
            print('=' * 50)
            print('')
            print('⚠️  Intel GPU 在 PyTorch 上的支持有限')
            print('推荐使用 CPU 版本以获得最佳兼容性')
            print('')
            print('请选择:')
            print('  [1] NVIDIA GPU 版本 (如果有独立显卡)')
            print('  [2] CPU 版本 (推荐)')
            print('')
            
            while True:
                choice = input('请选择 (1/2, 默认2): ').strip()
                if choice == '1':
                    requirements_file = 'requirements_gpu.txt'
                    print(f'✓ 使用: {requirements_file} (NVIDIA CUDA)')
                    break
                elif choice in ['', '2']:
                    requirements_file = 'requirements_cpu.txt'
                    print(f'✓ 使用: {requirements_file} (CPU版本)')
                    break
                else:
                    print('无效输入,请输入 1 或 2')
    
    # 选择对应的PyTorch版本 (根据requirements_gpu.txt中的版本)
    # 注意: 不再单独安装 PyTorch，而是通过 requirements 文件统一安装
    # 这样可以避免版本冲突和 DLL 损坏问题
    
    # 检查是否需要卸载不匹配的 PyTorch 版本
    need_reinstall = args.reinstall_torch
    
    if not need_reinstall:
        # 检测当前安装的 PyTorch 类型
        installed_pytorch_type, installed_detail = detect_installed_pytorch_version()
        target_type = "GPU" if "gpu" in requirements_file.lower() else "CPU"
        
        if installed_pytorch_type is not None and installed_pytorch_type != target_type:
            print('\n' + '=' * 50)
            print('⚠️  警告: 检测到 PyTorch 版本不匹配')
            print('=' * 50)
            print(f'当前安装: {installed_pytorch_type} 版本 ({installed_detail})')
            print(f'目标版本: {target_type} 版本')
            print('')
            print('不同版本的 PyTorch 会导致 DLL 冲突和加载失败')
            print('建议卸载旧版本后重新安装')
            print('')
            need_reinstall = True
    
    # 如果需要重装 PyTorch，先卸载
    if need_reinstall or use_amd_pytorch:
        print('正在卸载现有的 PyTorch...')
        run(f'"{python}" -m pip uninstall torch torchvision torchaudio -y', "卸载 PyTorch", "无法卸载 PyTorch", live=True)
        # 强制清理 pip 缓存，避免使用缓存的错误版本
        print('正在清理 pip 缓存...')
        run(f'"{python}" -m pip cache purge', "清理缓存", "无法清理缓存")
    
    # 如果用户选择了 AMD ROCm PyTorch，先安装它
    if use_amd_pytorch and amd_gfx_version:
        print('\n' + '=' * 50)
        print('正在安装 AMD ROCm PyTorch')
        print('=' * 50)
        print(f'gfx 版本: {amd_gfx_version}')
        print('')

        # AMD ROCm PyTorch 的 index URL
        amd_index_url = f"https://d2awnip2yjpvqn.cloudfront.net/v2/{amd_gfx_version}/"

        # 根据是否为更新模式决定版本要求
        # 如果是首次安装（install-deps-only），锁定具体版本
        # 如果是更新依赖（update-deps），安装最新版本
        if args and hasattr(args, 'update_deps') and args.update_deps:
            # 步骤4：更新到最新版本
            torch_version = "torch>=2.9.0"
            torchvision_version = "torchvision>=0.24.0"
            torchaudio_version = "torchaudio>=2.9.0"
            print('模式: 更新到最新版本')
        else:
            # 步骤1：首次安装，锁定完整版本（包含ROCm版本号）
            torch_version = "torch==2.9.0+rocm7.10.0a20251031"
            torchvision_version = "torchvision==0.24.0+rocm7.10.0a20251031"
            torchaudio_version = "torchaudio==2.9.0+rocm7.10.0a20251031"
            print('模式: 首次安装，锁定版本 2.9.0+rocm7.10.0a20251031')

        # 安装 AMD ROCm PyTorch
        print(f'正在从 AMD ROCm 源安装 PyTorch...')
        print(f'Index URL: {amd_index_url}')
        print('这可能需要几分钟时间...\n')

        try:
            # 直接使用 run() 而不是 run_pip() 以完全控制参数顺序
            amd_pytorch_cmd = f'"{python}" -m pip install "{torch_version}" "{torchvision_version}" "{torchaudio_version}" --index-url {amd_index_url} --no-cache-dir'
            run(amd_pytorch_cmd, "正在安装 AMD ROCm PyTorch", "AMD ROCm PyTorch 安装失败", live=True)
            print('\n✓ AMD ROCm PyTorch 安装完成')
            print('\n⚠️  注意:')
            print('  - AMD ROCm PyTorch 是实验性功能')
            print('  - 首次运行可能需要编译某些操作')
            print('  - 如果遇到问题,请使用 CPU 版本')
        except Exception as e:
            print(f'\n✗ AMD ROCm PyTorch 安装失败: {e}')
            print('\n建议:')
            print('  1. 检查您的 gfx 版本是否正确')
            print('  2. 检查网络连接')
            print('  3. 如果仍有问题,请使用 CPU 版本重新安装')
            # 安装失败，返回失败状态
            return False, None

    # 检查并安装其他依赖
    if not os.path.exists(requirements_file):
        print(f'警告: 未找到 {requirements_file}')
        return False, None

    print(f'\n正在检查依赖: {requirements_file}')
    if not check_req_file(requirements_file) or need_reinstall:
        if need_reinstall:
            print(f'强制重新安装所有依赖...')
        else:
            print(f'发现缺失依赖,正在安装...')
        run_pip(f"install -r {requirements_file}", f"{requirements_file} 中的依赖")
    else:
        print(f'依赖已满足 ✓')
    
    # 返回 AMD PyTorch 相关信息
    return use_amd_pytorch, amd_gfx_version


def update_repository(args):
    """更新代码库"""
    if getattr(sys, 'frozen', False):
        print('打包版本,跳过更新检查')
        return False

    if not args.update:
        return False

    print('正在检查更新...')
    try:
        current_commit = commit_hash()
        run(f"{git} fetch origin {BRANCH}", desc="正在从远程拉取更新...", errdesc="拉取更新失败")
        latest_commit = run(f"{git} rev-parse origin/{BRANCH}").strip()

        if current_commit != latest_commit:
            print("发现新版本,正在更新...")
            run(f"{git} pull origin {BRANCH}", desc="正在更新代码库...", errdesc="更新失败")
            print("更新完成,正在重启应用...")
            restart()
            return True
        else:
            print("已是最新版本")
    except Exception as e:
        print(f"更新检查失败: {e}")
        print("继续使用当前版本")
    
    return False


def check_version_info():
    """检查版本信息"""
    print()
    print("正在检查版本...")
    print("=" * 40)
    
    # 获取当前版本
    version_file = PATH_ROOT / "packaging" / "VERSION"
    try:
        if version_file.exists():
            current_version = version_file.read_text(encoding='utf-8').strip()
        else:
            current_version = "unknown"
    except Exception:
        current_version = "unknown"
    
    # fetch远程
    try:
        subprocess.run([git, 'fetch', 'origin'], capture_output=True, check=False)
    except Exception:
        pass
    
    # 获取远程版本
    try:
        result = subprocess.run(
            [git, 'show', 'origin/main:packaging/VERSION'],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            remote_version = result.stdout.strip()
        else:
            remote_version = "unknown"
    except Exception:
        remote_version = "unknown"
    
    print(f"当前版本 - {current_version}")
    print(f"远程版本 - {remote_version}")
    
    if current_version == remote_version:
        print()
        print("[信息] 当前已是最新版本")
    elif remote_version == "unknown":
        print()
        print("[警告] 无法获取远程版本信息")
    else:
        print()
        print("[发现新版本]")
    
    print("=" * 40)
    return current_version, remote_version


def update_code_force():
    """强制更新代码（同步到远程）"""
    print()
    print("=" * 40)
    print("更新代码 (强制同步)")
    print("=" * 40)
    print()
    
    print("[警告] 将强制同步到远程分支,本地修改将被覆盖")
    confirm = input("是否继续更新? (y/n): ").strip().lower()
    if confirm not in ['y', 'yes']:
        print("取消更新")
        return False
    
    print()
    print("获取远程更新...")
    try:
        subprocess.run([git, 'fetch', 'origin'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] 获取远程更新失败: {e}")
        return False
    
    print()
    print("正在强制同步到远程分支...")
    try:
        subprocess.run([git, 'reset', '--hard', 'origin/main'], check=True)
        print("[OK] 代码更新完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] 代码更新失败: {e}")
        return False


def update_dependencies(args):
    """更新依赖"""
    print()
    print("=" * 40)
    print("更新/安装依赖")
    print("=" * 40)
    print()
    
    # 设置参数，让 prepare_environment 处理所有逻辑
    args.update_deps = True
    args.frozen = False
    args.reinstall_torch = False
    
    # 检测已安装的 PyTorch 类型来决定 requirements 文件
    req_file, pytorch_type, detail = get_requirements_file_from_env()
    if req_file:
        args.requirements = req_file
        print(f"检测到 PyTorch 类型: {pytorch_type} ({detail})")
        print(f"使用: {req_file}")
    else:
        args.requirements = 'auto'
        print("未检测到 PyTorch,将进行首次安装...")
    
    print()
    
    try:
        prepare_environment(args)
        print()
        print("[OK] 依赖更新完成")
        return True
    except Exception as e:
        print(f"[ERROR] 依赖更新失败: {e}")
        return False


def maintenance_menu():
    """维护菜单"""
    print()
    print("=" * 40)
    print("漫画翻译器 - 更新维护工具")
    print("Manga Translator UI - Update Tool")
    print("=" * 40)
    
    # 创建一个简单的 args 对象用于依赖更新
    class Args:
        def __init__(self):
            self.frozen = False
            self.requirements = 'auto'
            self.reinstall_torch = False
            self.update_deps = False
    
    args = Args()
    
    # 首次显示版本信息
    check_version_info()
    
    while True:
        print()
        print("请选择操作:")
        print("[1] 更新代码 (强制同步)")
        print("[2] 更新/安装依赖")
        print("[3] 完整更新 (代码+依赖)")
        print("[4] 重新检查版本")
        print("[5] 退出")
        print()
        
        choice = input("请选择 (1/2/3/4/5): ").strip()
        
        if choice == '1':
            update_code_force()
            input("\n按回车键继续...")
            
        elif choice == '2':
            update_dependencies(args)
            input("\n按回车键继续...")
            
        elif choice == '3':
            print()
            print("=" * 40)
            print("完整更新 (代码+依赖)")
            print("=" * 40)
            print()
            
            print("[1/2] 更新代码 (强制同步)...")
            if update_code_force():
                print()
                print("[2/2] 更新依赖...")
                update_dependencies(args)
            
            input("\n按回车键继续...")
            
        elif choice == '4':
            check_version_info()
            
        elif choice == '5':
            print()
            print("退出更新工具")
            break
            
        else:
            print("无效选项")


def launch_ui(args):
    """启动UI界面"""
    if args.ui == 'qt':
        # 新版 Qt UI (推荐)
        from desktop_qt_ui.main import main as qt_main
        qt_main()
    elif args.ui == 'customtkinter':
        # 旧版 CustomTkinter UI
        import importlib
        desktop_ui = importlib.import_module('desktop-ui.main')
        desktop_ui.main_ui()
    else:
        # 默认使用新版 Qt UI
        from desktop_qt_ui.main import main as qt_main
        qt_main()


def launch_cli(args):
    """启动命令行版本"""
    import manga_translator.__main__ as cli_main
    # 传递参数给命令行版本
    cli_main.main()


def main():
    """主函数"""
    # 检查Python版本
    if not is_python_version_valid():
        sys.exit(1)

    # 解析命令行参数
    parser = argparse.ArgumentParser(description='漫画翻译器启动脚本')
    parser.add_argument("--update", action='store_true', help="启动前检查并自动更新")
    parser.add_argument("--frozen", action='store_true', help="跳过依赖检查(打包版本)")
    parser.add_argument("--install-deps-only", action='store_true', help="仅安装依赖,不启动UI")
    parser.add_argument("--reinstall-torch", action='store_true', help="重新安装PyTorch")
    parser.add_argument("--update-deps", action='store_true', help="更新依赖到最新版本(步骤4使用)")
    parser.add_argument("--requirements", default='auto', help="依赖文件路径 (auto=自动选择, 或指定 requirements_gpu.txt/requirements_cpu.txt)")
    parser.add_argument("--ui", choices=['qt', 'tk'], default='tk', help="选择UI框架: qt(PyQt6) 或 tk(CustomTkinter)")
    parser.add_argument("--cli", action='store_true', help="使用命令行模式")
    parser.add_argument("--verbose", action='store_true', help="显示详细日志")
    parser.add_argument("--maintenance", action='store_true', help="启动更新维护菜单")
    
    args, unknown = parser.parse_known_args()
    
    # 如果是维护模式，直接进入维护菜单
    if args.maintenance:
        # 切换到项目根目录
        os.chdir(PATH_ROOT)
        maintenance_menu()
        return

    # 显示版本信息
    commit = commit_hash()
    print('=' * 60)
    print('漫画翻译器 Manga Translator UI')
    print('=' * 60)
    print(f'版本: {VERSION}')
    print(f'分支: {BRANCH}')
    print(f'提交: {commit[:8]}')
    print(f'Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')
    print(f'Python路径: {sys.executable}')
    print('=' * 60)

    # 切换到项目根目录 (launch.py 在 packaging/ 下,需要切换到父目录)
    APP_DIR = PATH_ROOT
    os.chdir(APP_DIR)

    # 更新检查
    if update_repository(args):
        return  # 更新后会自动重启

    # 准备环境
    print('\n正在检查依赖...')
    use_amd_pytorch, amd_gfx_version = prepare_environment(args)

    # 如果只是安装依赖,则退出
    if args.install_deps_only:
        print('\n依赖安装完成!')
        
        # 如果是 AMD GPU 且安装了 requirements_amd.txt，提示 PyTorch 状态
        if use_amd_pytorch and amd_gfx_version:
            print('\n✓ AMD ROCm PyTorch 已安装/更新')
            print(f'  gfx 版本: {amd_gfx_version}')
        
        return

    # 启动应用
    print('\n正在启动应用...\n')
    try:
        if args.cli:
            launch_cli(args)
        else:
            launch_ui(args)
    except KeyboardInterrupt:
        print('\n\n用户取消')
        sys.exit(0)
    except Exception as e:
        print(f'\n错误: {e}')
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()


