"""
配置管理服务
负责应用程序的配置加载、保存、验证和环境变量管理
"""
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dotenv import dotenv_values, set_key, load_dotenv

from core.config_models import AppSettings


@dataclass
class TranslatorConfig:
    """翻译器配置信息"""
    name: str
    display_name: str
    required_env_vars: List[str]
    optional_env_vars: List[str] = field(default_factory=list)
    validation_rules: Dict[str, str] = field(default_factory=dict)

from PyQt6.QtCore import QObject, pyqtSignal


class ConfigService(QObject):
    """配置管理服务"""

    config_changed = pyqtSignal(dict)
    
    def __init__(self, root_dir: str):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.root_dir = root_dir
        # .env文件应该在exe所在目录（root_dir的上一级，与exe同级）
        # 打包后：root_dir = _internal，.env在_internal的上一级
        # 开发时：root_dir = 项目根目录，.env也在项目根目录
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            self.env_path = os.path.join(self.root_dir, "..", ".env")
        else:
            self.env_path = os.path.join(self.root_dir, ".env")

        # Use get_default_config_path() for PyInstaller compatibility
        # Temporarily set a placeholder, will be properly set after initialization
        self.default_config_path = None

        self.config_path = None # This will hold the path of a loaded file
        self.current_config: AppSettings = AppSettings()

        # Set the correct default config path
        self.default_config_path = self.get_default_config_path()
        self.logger.info(f"默认配置文件路径: {self.default_config_path}")
        self.logger.info(f"配置文件是否存在: {os.path.exists(self.default_config_path)}")
        if hasattr(sys, '_MEIPASS'):
            self.logger.info(f"打包环境，sys._MEIPASS = {sys._MEIPASS}")

        # Try to load the default config on startup
        if os.path.exists(self.default_config_path):
            self.logger.info(f"正在加载配置文件: {self.default_config_path}")
            success = self.load_config_file(self.default_config_path)
            if success:
                self.logger.info("配置文件加载成功")
            else:
                self.logger.error("配置文件加载失败")
        else:
            self.logger.warning(f"Default config file not found at: {self.default_config_path}")
        
        self._translator_configs = None
        self._env_cache = None
        self._config_cache = None

    @property
    def translator_configs(self):
        """延迟加载翻译器配置"""
        if self._translator_configs is None:
            self._translator_configs = self._init_translator_configs()
        return self._translator_configs
        
    def _init_translator_configs(self) -> Dict[str, TranslatorConfig]:
        """从JSON文件初始化翻译器配置注册表"""
        configs = {}
        
        if hasattr(sys, '_MEIPASS'):
            # Packaged environment
            config_path = os.path.join(sys._MEIPASS, "examples", "config", "translators.json")
        else:
            # Development environment
            config_path = os.path.join(self.root_dir, "examples", "config", "translators.json")

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for name, config_data in data.items():
                configs[name] = TranslatorConfig(**config_data)
        except FileNotFoundError:
            self.logger.error(f"Translator config file not found at: {config_path}")
        except Exception as e:
            self.logger.error(f"Failed to load translator configs: {e}")
        return configs
    
    def get_translator_configs(self) -> Dict[str, TranslatorConfig]:
        """获取所有翻译器配置"""
        return self.translator_configs
    
    def get_translator_config(self, translator_name: str) -> Optional[TranslatorConfig]:
        """获取特定翻译器配置"""
        return self.translator_configs.get(translator_name)
    
    def get_required_env_vars(self, translator_name: str) -> List[str]:
        """获取翻译器必需的环境变量"""
        config = self.get_translator_config(translator_name)
        return config.required_env_vars if config else []
    
    def get_all_env_vars(self, translator_name: str) -> List[str]:
        """获取翻译器所有相关环境变量"""
        config = self.get_translator_config(translator_name)
        if not config:
            return []
        return config.required_env_vars + config.optional_env_vars
    
    def validate_api_key(self, key: str, var_name: str, translator_name: str) -> bool:
        """验证API密钥格式"""
        config = self.get_translator_config(translator_name)
        if not config or var_name not in config.validation_rules:
            return True  # 如果没有验证规则，则认为有效
            
        pattern = config.validation_rules[var_name]
        return bool(re.match(pattern, key))
    
    def load_config_file(self, config_path: str) -> bool:
        """加载JSON配置文件并与默认设置合并"""
        try:
            if not os.path.exists(config_path):
                self.logger.error(f"配置文件不存在: {config_path}")
                return False

            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # 预处理以处理不规范的JSON，例如尾随逗号
                # content = re.sub(r',(\s*[\]})', r'\1', content) # Temporarily disabled for debugging
                loaded_data = json.loads(content)

            # 深层合并加载的数据和现有配置
            new_config_dict = self.current_config.dict()
            
            def deep_update(target, source):
                for key, value in source.items():
                    if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                        deep_update(target[key], value)
                    else:
                        target[key] = value
            
            deep_update(new_config_dict, loaded_data)
            
            self.current_config = AppSettings.parse_obj(new_config_dict)
            
            self.config_path = config_path
            self.logger.info(f"成功加载配置文件: {config_path}")
            self.config_changed.emit(self.current_config.dict())
            return True
            
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            return False
    
    def save_config_file(self, config_path: Optional[str] = None) -> bool:
        """保存JSON配置文件"""
        try:
            save_path = config_path or self.config_path or self.default_config_path
            if not save_path:
                self.logger.error("没有指定保存路径，且无默认路径")
                return False
                
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(self.current_config.dict(), f, indent=2, ensure_ascii=False)
                
            self.config_path = save_path
            self.logger.info(f"成功保存配置文件: {save_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"保存配置文件失败: {e}")
            return False

    def reload_config(self):
        """
        强制从 .env 和 JSON 文件完全重新加载配置。
        这能确保外部对文件的任何修改都能在程序中生效。
        """
        self.logger.info("正在强制重新加载配置...")
        
        # 1. 重新加载 .env 文件到 os.environ。翻译引擎会自动从此读取。
        load_dotenv(self.env_path, override=True)
        self.logger.info(f".env 文件已从 {self.env_path} 重新加载，环境变量已更新。")

        # 2. 重新创建 AppSettings 对象 (用于UI设置)
        self.current_config = AppSettings()

        # 3. 在新创建的 AppSettings 对象之上，重新应用 JSON 配置文件中的设置
        config_file_to_load = self.config_path or self.default_config_path
        if config_file_to_load and os.path.exists(config_file_to_load):
            self.load_config_file(config_file_to_load)

        # 4. 通知所有监听者配置已更改
        self.config_changed.emit(self.current_config.dict())
        self.logger.info("配置重载完成。")

    def reload_from_disk(self):
        """
        强制从当前设置的 config_path 重新加载配置, 并通知所有监听者。
        """
        if self.config_path and os.path.exists(self.config_path):
            self.logger.info(f"正在从 {self.config_path} 强制重载配置...")
            self.load_config_file(self.config_path)
        else:
            self.logger.warning("无法重载配置：config_path 未设置或文件不存在。")
    
    def get_config(self) -> AppSettings:
        """获取当前配置模型的深拷贝副本"""
        return self.current_config.copy(deep=True)

    def get_config_reference(self) -> AppSettings:
        """获取对当前配置模型的直接引用，谨慎使用。"""
        return self.current_config
    
    def set_config(self, config: AppSettings) -> None:
        """设置配置并通知监听者"""
        self.current_config = config.copy(deep=True)
        self.logger.info("配置已更新，正在通知监听者...")
        self.config_changed.emit(self.current_config.dict())
    
    def update_config(self, updates: Dict[str, Any]) -> None:
        """更新配置的部分内容"""
        new_config_dict = self.current_config.dict()

        def deep_update(target, source):
            for key, value in source.items():
                if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                    deep_update(target[key], value)
                else:
                    target[key] = value
        
        deep_update(new_config_dict, updates)

        self.current_config = AppSettings.parse_obj(new_config_dict)
        self.logger.info("配置已更新，正在通知监听者...")
        self.config_changed.emit(self.current_config.dict())

    def load_env_vars(self) -> Dict[str, str]:
        """加载环境变量"""
        try:
            if os.path.exists(self.env_path):
                return dotenv_values(self.env_path)
            return {}
        except Exception as e:
            self.logger.error(f"加载环境变量失败: {e}")
            return {}
    
    def save_env_var(self, key: str, value: str) -> bool:
        """保存单个环境变量 - 使用手动处理避免set_key的自动引号"""
        try:
            # 去除首尾空格
            value = value.strip()
            
            if not os.path.exists(self.env_path):
                os.makedirs(os.path.dirname(self.env_path), exist_ok=True)
                with open(self.env_path, 'w', encoding='utf-8') as f:
                    f.write(f"{key}={value}\n")
            else:
                # 手动读取、更新、写入，避免set_key的自动处理
                lines = []
                key_found = False
                with open(self.env_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                # 更新或添加键值对
                with open(self.env_path, 'w', encoding='utf-8') as f:
                    for line in lines:
                        stripped = line.strip()
                        if stripped and not stripped.startswith('#'):
                            if '=' in stripped:
                                existing_key = stripped.split('=', 1)[0].strip()
                                if existing_key == key:
                                    f.write(f"{key}={value}\n")
                                    key_found = True
                                    continue
                        f.write(line)
                    
                    # 如果键不存在，追加到文件末尾
                    if not key_found:
                        f.write(f"{key}={value}\n")
            
            # 重新加载环境变量到os.environ，使其立即生效
            load_dotenv(self.env_path, override=True)
            self.logger.info(f"保存环境变量: {key}={value}")
            return True

        except Exception as e:
            self.logger.error(f"保存环境变量失败: {e}")
            return False
    
    def save_env_vars(self, env_vars: Dict[str, str]) -> bool:
        """批量保存环境变量"""
        try:
            for key, value in env_vars.items():
                if not self.save_env_var(key, value):
                    return False
            return True
        except Exception as e:
            self.logger.error(f"批量保存环境变量失败: {e}")
            return False
    
    def validate_translator_env_vars(self, translator_name: str) -> Dict[str, bool]:
        """验证翻译器的环境变量是否完整"""
        env_vars = self.load_env_vars()
        required_vars = self.get_required_env_vars(translator_name)
        
        validation_result = {}
        for var in required_vars:
            value = env_vars.get(var, "")
            is_present = bool(value.strip())
            is_valid_format = self.validate_api_key(value, var, translator_name) if is_present else True
            validation_result[var] = is_present and is_valid_format
            
        return validation_result
    
    def get_missing_env_vars(self, translator_name: str) -> List[str]:
        """获取缺失的环境变量"""
        validation_result = self.validate_translator_env_vars(translator_name)
        return [var for var, is_valid in validation_result.items() if not is_valid]
    
    def is_translator_configured(self, translator_name: str) -> bool:
        """检查翻译器是否已完整配置"""
        missing_vars = self.get_missing_env_vars(translator_name)
        return len(missing_vars) == 0
    
    def get_default_config_path(self) -> str:
        """
        获取默认配置文件路径

        打包后配置文件在 _internal/examples/config-example.json
        开发时在 项目根目录/examples/config-example.json
        """
        if hasattr(sys, '_MEIPASS'):
            # 打包环境：sys._MEIPASS 指向 _internal 目录
            return os.path.join(sys._MEIPASS, 'examples', 'config-example.json')
        else:
            # 开发环境
            return os.path.join(self.root_dir, "examples", "config-example.json")
    
    def load_default_config(self) -> bool:
        """加载默认配置"""
        default_path = self.get_default_config_path()
        return self.load_config_file(default_path)