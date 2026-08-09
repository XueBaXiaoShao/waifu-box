# 每日老婆（waifu-box）

从 galgame-box 拆出的独立 NoneBot2 插件：VNDB 角色每日老婆抽卡。

## 功能

| 命令 | 说明 |
| --- | --- |
| `/waifu` | 每日抽老婆（每人每天一次，普通池） |
| `/yuzuwaifu` | 柚子社专属老婆（固定 Yuzusoft，与 `/waifu` 每天二选一） |
| `/waifu settings` | 查看/修改抽卡设置（热度、年代、全局会社池；仅管理员） |
| `/waifu settings pool set|off` | 设置 15 家默认会社池 / 关闭 |
| `/waifu settings group=<群号> kaisha=<会社key|off>` | 群会社后门 |
| `/waifu settings group=<群号> year=off|on` | 该群解除/恢复年代限制 |
| `/waifu settings group=<群号> popular=off|on` | 该群解除/恢复热度限制 |
| `/waifu reset [all|<QQ号>]` | 重置每日额度（仅管理员） |
| `/waifu set [<QQ号>] <角色名或cID>` | 管理员指定/代指定（绕过全部规则） |

## 机制

- 普通 waifu 采用 **LRU 轮换**：优先抽最久没抽到的角色（从未抽过的优先），
  使用记录存 `data/waifu_usage.json`；
- `/yuzuwaifu` 保持随机，不参与 LRU；
- 实时查询结果按会社写入本地缓存 `data/waifu_cache.json`，当天有新鲜缓存时
  抽卡不请求 VNDB；
- 每天 `WAIFU_CACHE_REFRESH_TIME`（默认 04:00）增量刷新：已有角色的作品
  跳过接口，只查新作品；
- 管理员名单复用 `data/admin_ids.json`（与 x_admin/galgame-box 共用）；
- 分群开关复用 `data/plugin_switches.json` 的 `waifu_box` 键。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `WAIFU_DATA_DIR` | `data/` | 状态/缓存目录（回退 `LOCALSTORE_DATA_DIR`） |
| `WAIFU_REQUEST_TIMEOUT` | `30` | VNDB 请求超时（秒） |
| `WAIFU_REQUEST_RETRIES` | `3` | 重试次数 |
| `WAIFU_CACHE_REFRESH_ENABLED` | `true` | 每日刷新缓存 |
| `WAIFU_CACHE_REFRESH_TIME` | `04:00` | 刷新时间 |
| `WAIFU_CACHE_VN_LIMIT` | `30` | 每家会社刷新作品数 |

## 测试

```bash
make test
```
