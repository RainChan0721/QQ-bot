import nonebot
from nonebot.adapters.onebot.v11 import Adapter
from nonebot.log import logger

# 初始化 NoneBot
nonebot.init()

# 注册 OneBot V11 适配器
driver = nonebot.get_driver()
driver.register_adapter(Adapter)

# 自动加载插件目录
nonebot.load_plugins("rcbot/plugins")

# 启动自检
def startup_check():
    """打印启动配置摘要，方便排查"""
    config = driver.config
    test_mode = getattr(config, "test_mode", False)
    test_group_id = getattr(config, "test_group_id", None)
    allowed_ids = getattr(config, "allowed_group_ids", [])

    logger.info("========== RCBot 启动自检 ==========")
    logger.info(f"运行环境: {config.environment}")
    logger.info(f"监听地址: {config.host}:{config.port}")
    logger.info(f"超级用户: {config.superusers}")
    logger.info(f"日志级别: {config.log_level}")
    logger.info(f"测试模式: {'开启' if test_mode else '关闭'}")
    if test_mode and test_group_id:
        logger.info(f"测试目标群: {test_group_id}")

    if allowed_ids:
        logger.info(f"群白名单: {allowed_ids}")
    else:
        logger.info("群白名单: 未配置（允许所有群）")

    token = getattr(config, "onebot_access_token", "") or ""
    if token:
        logger.info(f"Access Token: 已配置 (长度 {len(token)})")
    else:
        logger.info("Access Token: 未配置")

    logger.info("====================================")

# 用 on_startup 确保配置已加载完毕
@driver.on_startup
def _on_startup():
    startup_check()

# 启动 Bot
if __name__ == "__main__":
    nonebot.run()
