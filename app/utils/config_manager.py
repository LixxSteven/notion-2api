"""
配置持久化管理模块
使用 JSON 格式存储配置，支持自动加载和保存
"""
import json
from pathlib import Path
from typing import Dict, Any

# 配置目录和文件
CONFIG_DIR = Path.home() / ".notion-ai-proxy"
CONFIG_FILE = CONFIG_DIR / "config.json"

# 默认配置
DEFAULT_CONFIG = {
    "token_v2": "",
    "space_id": "",
    "user_id": "",
    "port": "8088",
    "auto_start": False,
    "log_level": "INFO"
}


class ConfigManager:
    """配置管理器"""
    
    def __init__(self):
        """初始化配置管理器"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.config = self.load()
    
    def load(self) -> Dict[str, Any]:
        """
        从文件加载配置
        
        Returns:
            配置字典
        """
        if not CONFIG_FILE.exists():
            # 配置文件不存在，返回默认配置
            return DEFAULT_CONFIG.copy()
        
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 合并默认配置（确保新增字段存在）
            merged_config = DEFAULT_CONFIG.copy()
            merged_config.update(config)
            
            return merged_config
        except Exception as e:
            print(f"加载配置文件失败: {e}")
            return DEFAULT_CONFIG.copy()
    
    def save(self, config: Dict[str, Any] = None):
        """
        保存配置到文件
        
        Args:
            config: 要保存的配置字典，如果为 None 则保存当前配置
        """
        if config is not None:
            self.config = config
        
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置文件失败: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项
        
        Args:
            key: 配置键
            default: 默认值
        
        Returns:
            配置值
        """
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any):
        """
        设置配置项并自动保存
        
        Args:
            key: 配置键
            value: 配置值
        """
        self.config[key] = value
        self.save()
    
    def update(self, updates: Dict[str, Any]):
        """
        批量更新配置并保存
        
        Args:
            updates: 要更新的配置字典
        """
        self.config.update(updates)
        self.save()
    
    def get_all(self) -> Dict[str, Any]:
        """
        获取所有配置
        
        Returns:
            完整配置字典
        """
        return self.config.copy()


# 全局配置管理器实例
config_manager = ConfigManager()
