"""
日志管理模块
提供统一的日志配置和管理功能
"""
import logging
import os
from pathlib import Path
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

# 日志目录
LOG_DIR = Path.home() / ".notion-ai-proxy" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 日志文件名（按日期）
LOG_FILE = LOG_DIR / f"proxy_{datetime.now().strftime('%Y-%m-%d')}.log"

# 日志格式
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def cleanup_old_logs(days=7):
    """清理超过指定天数的旧日志文件"""
    try:
        cutoff_date = datetime.now() - timedelta(days=days)
        for log_file in LOG_DIR.glob("proxy_*.log"):
            try:
                # 从文件名提取日期
                date_str = log_file.stem.replace("proxy_", "")
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                
                if file_date < cutoff_date:
                    log_file.unlink()
                    print(f"已清理旧日志: {log_file.name}")
            except (ValueError, OSError) as e:
                print(f"清理日志文件 {log_file.name} 时出错: {e}")
    except Exception as e:
        print(f"清理旧日志时出错: {e}")


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """
    获取配置好的 logger 实例
    
    Args:
        name: logger 名称（通常使用 __name__）
        level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
    
    Returns:
        配置好的 logger 实例
    """
    logger = logging.getLogger(name)
    
    # 避免重复添加 handler
    if logger.handlers:
        return logger
    
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # 文件 handler
    file_handler = logging.FileHandler(
        LOG_FILE,
        encoding='utf-8',
        mode='a'
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    file_handler.setFormatter(file_formatter)
    
    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    console_handler.setFormatter(console_formatter)
    
    # 添加 handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


# 启动时清理旧日志
cleanup_old_logs(days=7)
