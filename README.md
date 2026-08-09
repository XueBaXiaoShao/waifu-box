# 每日老婆（waifu-box）

从 galgame-box 拆出的独立 NoneBot2 插件：基于本地 `final_company_library`
资料库的每日老婆抽卡，并生成角色信息图片。

## 功能

| 命令 | 说明 |
| --- | --- |
| `/waifu` | 从 `final_company_library` 抽每日老婆，生成角色信息卡片（左立绘 / 右信息简介 / 右下会社 logo） |
| `/yuzuwaifu` | 柚子社专属老婆（固定 Yuzusoft，保持原有输出，与 `/waifu` 每天二选一） |
| `/waifu settings` | 查看/修改抽卡设置（热度、年代、全局会社池；仅管理员） |
| `/waifu settings pool set|off` | 设置 final_company_library 全量会社池 / 关闭 |
| `/waifu settings group=<群号> kaisha=<会社key|off>` | 群会社后门 |
| `/waifu settings group=<群号> year=off|on` | 该群解除/恢复年代限制 |
| `/waifu settings group=<群号> popular=off|on` | 该群解除/恢复热度限制 |
| `/waifu reset [all|<QQ号>]` | 重置每日额度（仅管理员） |
| `/waifu set [<QQ号>] <角色名或cID>` | 管理员指定/代指定（绕过全部规则） |

## 机制

- `/waifu` 从本地 `final_company_library` 抽卡，采用 **LRU 轮换**：优先抽最久没
  抽到的角色（从未抽过的优先），使用记录存 `data/waifu_usage.json`；
- `/waifu` 用 Pillow 合成角色信息卡片：左侧为立绘，右侧为角色信息与简介，
  右下角按 `company_ids` 从 `company_logos` 匹配来源会社 logo；
- 旧版 15 家默认会社池会自动迁移为本地库全量 48 家会社池；
- 热度阈值只作用于 `/yuzuwaifu`（`final_company_library` 无投票数字段）；
- `/yuzuwaifu` 保持随机，不参与 LRU；
- `/yuzuwaifu` 的实时查询结果按会社写入本地缓存 `data/waifu_cache.json`，
  当天有新鲜缓存时不请求 VNDB；
- 每天 `WAIFU_CACHE_REFRESH_TIME`（默认 04:00）增量刷新 yuzuwaifu 的 VNDB
  缓存：已有角色的作品跳过接口，只查新作品；
- 管理员名单复用 `data/admin_ids.json`（与 x_admin/galgame-box 共用）；
- 分群开关复用 `data/plugin_switches.json` 的 `waifu_box` 键。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `WAIFU_DATA_DIR` | `data/` | 状态/缓存目录（回退 `LOCALSTORE_DATA_DIR`） |
| `WAIFU_LIBRARY_DIR` | `data/final_company_library` | vndb 角色资料库目录 |
| `WAIFU_LOGO_DIR` | `data/company_logos` | 会社 logo 目录 |
| `WAIFU_REQUEST_TIMEOUT` | `30` | VNDB 请求超时（秒） |
| `WAIFU_REQUEST_RETRIES` | `3` | 重试次数 |
| `WAIFU_CACHE_REFRESH_ENABLED` | `true` | 每日刷新缓存 |
| `WAIFU_CACHE_REFRESH_TIME` | `04:00` | 刷新时间 |
| `WAIFU_CACHE_VN_LIMIT` | `30` | 每家会社刷新作品数 |

卡片文字使用随插件携带的 Noto Sans SC（SIL Open Font License）。

## 测试

```bash
make test
```
