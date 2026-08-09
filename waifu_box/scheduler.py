"""每日定时增量刷新 waifu 缓存。"""

from __future__ import annotations

from nonebot import logger

from .config import config


def setup_cache_refresh() -> bool:
    """注册每日刷新任务；缺少 apscheduler 时返回 False。"""
    if not config.cache_refresh_enabled:
        logger.info("WAIFU_CACHE_REFRESH_ENABLED=false，不注册缓存刷新")
        return False
    try:
        hour_text, minute_text = config.cache_refresh_time.replace("：", ":").split(
            ":", 1
        )
        hour, minute = int(hour_text), int(minute_text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        logger.error("WAIFU_CACHE_REFRESH_TIME 格式错误：{}", config.cache_refresh_time)
        return False

    try:
        from nonebot import require

        require("nonebot_plugin_apscheduler")
        from nonebot_plugin_apscheduler import scheduler
    except Exception as exc:
        logger.warning(
            "未加载 nonebot-plugin-apscheduler，waifu 缓存刷新不可用（{}）", exc
        )
        return False

    @scheduler.scheduled_job(
        "cron",
        hour=hour,
        minute=minute,
        id="waifu_cache_refresh",
        misfire_grace_time=600,
    )
    async def _refresh() -> None:
        import asyncio

        from . import commands, vndb, waifu

        settings = waifu.load_settings()
        groups = settings.get("pool_company_ids") or {}
        tasks = []
        if isinstance(groups, dict):
            for key in settings.get("pool_companies") or []:
                ids = groups.get(key) or []
                if ids:
                    tasks.append(
                        vndb.refresh_company_cache(
                            key,
                            [str(item) for item in ids],
                            vn_limit=config.cache_vn_limit,
                        )
                    )
        try:
            yuzu_ids = await commands._yuzusoft_ids()
        except Exception:
            yuzu_ids = []
        if yuzu_ids:
            tasks.append(
                vndb.refresh_company_cache(
                    "yuzusoft",
                    yuzu_ids,
                    vn_limit=config.cache_vn_limit,
                )
            )
        if not tasks:
            return
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = [result for result in results if isinstance(result, dict)]
        total_new = sum(result.get("new_characters", 0) for result in ok)
        total_skip = sum(result.get("skipped", 0) for result in ok)
        failed = sum(1 for result in results if not isinstance(result, dict))
        logger.info(
            "waifu 缓存刷新完成：新增 {} 角色，跳过 {} 个已有作品，失败 {} 个会社",
            total_new,
            total_skip,
            failed,
        )

    logger.info(
        "waifu-box 缓存每日刷新已注册：{}",
        config.cache_refresh_time,
    )
    return True
