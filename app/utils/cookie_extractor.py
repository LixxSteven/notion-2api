import logging
import browser_cookie3
from typing import Optional

logger = logging.getLogger(__name__)

def get_notion_cookie_from_browser(browser_name: str = 'chrome') -> Optional[str]:
    """
    尝试从指定的浏览器中获取 Notion 的 token_v2 Cookie
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
        else:
            logger.warning(f"不支持的浏览器类型: {browser_name}")
            return None
            
        if cj:
            for cookie in cj:
                if cookie.name == cookie_name and domain in cookie.domain:
                    logger.info("成功读取到 token_v2")
                    return cookie.value
                    
        logger.warning(f"在 {browser_name} 中未找到 token_v2")
        return None
        
    except Exception as e:
        logger.error(f"读取 Cookie 失败: {e}")
        return None
