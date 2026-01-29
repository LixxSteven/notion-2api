"""
Windows 系统通知模块
使用 plyer 库发送 Toast 通知
"""
from plyer import notification
import logging

logger = logging.getLogger(__name__)


def notify_token_expired():
    """
    发送 Token 失效通知
    """
    try:
        notification.notify(
            title="Notion AI Proxy",
            message="Token 已失效，请更新 token_v2",
            app_name="Notion AI Proxy",
            timeout=10  # 通知显示 10 秒
        )
        logger.info("已发送 Token 失效通知")
    except Exception as e:
        logger.error(f"发送通知失败: {e}")


def notify_service_started(port: str):
    """
    发送服务启动通知
    
    Args:
        port: 服务端口
    """
    try:
        notification.notify(
            title="Notion AI Proxy",
            message=f"服务已启动，端口: {port}",
            app_name="Notion AI Proxy",
            timeout=5
        )
        logger.info(f"已发送服务启动通知 (端口: {port})")
    except Exception as e:
        logger.error(f"发送通知失败: {e}")


def notify_service_stopped():
    """
    发送服务停止通知
    """
    try:
        notification.notify(
            title="Notion AI Proxy",
            message="服务已停止",
            app_name="Notion AI Proxy",
            timeout=5
        )
        logger.info("已发送服务停止通知")
    except Exception as e:
        logger.error(f"发送通知失败: {e}")


def notify_error(message: str):
    """
    发送错误通知
    
    Args:
        message: 错误消息
    """
    try:
        notification.notify(
            title="Notion AI Proxy - 错误",
            message=message,
            app_name="Notion AI Proxy",
            timeout=10
        )
        logger.info(f"已发送错误通知: {message}")
    except Exception as e:
        logger.error(f"发送通知失败: {e}")
