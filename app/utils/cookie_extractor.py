import logging
import browser_cookie3
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class CookieError:
    """Cookie 获取错误类型"""
    DATABASE_LOCKED = "database_locked"
    PERMISSION_DENIED = "permission_denied"
    FILE_NOT_FOUND = "file_not_found"
    COOKIE_NOT_FOUND = "cookie_not_found"
    UNKNOWN = "unknown"

def get_notion_cookie_from_browser(browser_name: str = 'edge') -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    尝试从指定的浏览器中获取 Notion 的 token_v2 Cookie
    
    Returns:
        Tuple[cookie_value, error_type, error_message]
        - 成功: (cookie_value, None, None)
        - 失败: (None, error_type, error_message)
    """
    domain = "notion.so"
    cookie_name = "token_v2"
    
    logger.info(f"尝试从 {browser_name} 读取 Notion Cookie...")
    
    try:
        cj = None
        if browser_name.lower() == 'chrome':
            cj = browser_cookie3.chrome(domain_name=domain)
        elif browser_name.lower() == 'edge':
            cj = browser_cookie3.edge(domain_name=domain)
        elif browser_name.lower() == 'firefox':
            cj = browser_cookie3.firefox(domain_name=domain)
        else:
            logger.warning(f"不支持的浏览器类型: {browser_name}")
            return None, CookieError.UNKNOWN, f"不支持的浏览器: {browser_name}"
            
        if cj:
            for cookie in cj:
                if cookie.name == cookie_name and domain in cookie.domain:
                    logger.info("成功读取到 token_v2")
                    return cookie.value, None, None
                    
        logger.warning(f"在 {browser_name} 中未找到 token_v2")
        return None, CookieError.COOKIE_NOT_FOUND, f"未找到 Notion Cookie，请确认已登录 notion.so"
        
    except Exception as e:
        error_str = str(e).lower()
        
        # 数据库锁定（浏览器正在运行）
        if "database is locked" in error_str or "locked" in error_str:
            return None, CookieError.DATABASE_LOCKED, "浏览器正在运行，请关闭所有浏览器窗口后重试"
        
        # 权限错误
        elif "permission" in error_str or "access" in error_str:
            return None, CookieError.PERMISSION_DENIED, "没有权限读取浏览器数据，请以管理员身份运行"
        
        # 文件不存在
        elif "no such file" in error_str or "not found" in error_str or isinstance(e, FileNotFoundError):
            return None, CookieError.FILE_NOT_FOUND, f"找不到浏览器 Cookie 文件，请确认已安装 {browser_name.title()}"
        
        # 其他错误
        else:
            logger.error(f"读取 Cookie 失败: {e}")
            return None, CookieError.UNKNOWN, f"自动获取失败：{str(e)}"

def try_all_browsers() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    尝试从所有支持的浏览器获取 Cookie
    
    Returns:
        Tuple[cookie_value, error_type, error_message]
    """
    browsers = ['edge', 'chrome', 'firefox']
    last_error_type = None
    last_error_msg = None
    
    for browser in browsers:
        cookie, error_type, error_msg = get_notion_cookie_from_browser(browser)
        if cookie:
            return cookie, None, None
        
        # 记录最后一个错误
        last_error_type = error_type
        last_error_msg = error_msg
        
        # 如果是数据库锁定，不继续尝试其他浏览器（因为可能都在运行）
        if error_type == CookieError.DATABASE_LOCKED:
            break
    
    return None, last_error_type, last_error_msg
