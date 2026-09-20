# 每日老婆（waifu-box）

从 galgame-box 拆出的独立 NoneBot2 插件：基于本地 `final_company_library`
资料库的每日老婆抽卡，并生成角色信息图片。

## 功能

| 命令 | 说明 |
| --- | --- |
| `/waifu` | 从 `final_company_library` 抽每日老婆，生成角色信息卡片（左立绘 / 右信息简介 / 右下会社 logo） |
| `/waifu 2025` | 从 2025 新收录作品池抽取（与 `/waifu` 共享每日额度） |
| `/yuzuwaifu` | 柚子社专属老婆（固定 Yuzusoft，同样输出角色卡片，与 `/waifu` 共享每日额度） |
| `/waifu settings` | 查看/修改抽卡设置（热度、年代、全局会社池；仅管理员） |
| `/waifu settings pool set|off` | 设置 final_company_library 全量会社池 / 关闭 |
| `/waifu settings group=<群号> kaisha=<会社key|off>` | 群会社后门 |
| `/waifu settings group=<群号> year=off|on` | 该群解除/恢复年代限制 |
| `/waifu settings group=<群号> popular=off|on` | 该群解除/恢复热度限制 |
| `/waifu reset [all|<QQ号>]` | 重置每日额度（仅管理员） |
| `/waifu check <QQ号>` | 查看指定用户今天抽到的老婆（仅管理员） |
| `/waifu set [<QQ号>] <角色名或cID>` | 管理员指定/代指定（绕过全部规则） |
| `/yuzuwaifu list [<QQ号>|@对方]` | 查看今天抽到的每日老婆（含稀有度） |
| `/yuzuwaifu trade @对方` | 提议交换双方今天的柚子社每日老婆（其他会社暂不可交易） |
| `/yuzuwaifu accept` / `/yuzuwaifu reject` | 接受/拒绝交易（只有一笔待处理时不用交易号） |
| `/yuzuwaifu cancel` | 撤销自己发起的交易（只有一笔时不用交易号） |
| `/yuzuwaifu rank` | 今日每日老婆稀有度排行榜 |

## 机制

- `/waifu` 从本地 `final_company_library` 抽卡，采用 **LRU 轮换**：优先抽最久没
  抽到的角色（从未抽过的优先），使用记录存 `data/waifu_usage.json`；
- `/waifu` 用 Pillow 合成角色信息卡片：左侧为立绘，右侧为角色信息与简介，
  右下角按 `company_ids` 从 `company_logos` 匹配来源会社 logo；
- 旧版 15 家默认会社池会自动迁移为本地库全量 48 家会社池；
- 热度阈值暂不生效（`final_company_library` 无投票数字段）；
- `/yuzuwaifu` 在本地库中固定抽柚子社，同样输出卡片、保持随机、不参与 LRU；
- `/waifu` 与 `/yuzuwaifu` 共享每日额度，二者当天二选一；
- **同群不重复**：每个群每天内，后抽的用户会自动避开本群今天已被其他人抽到
  的角色（防牛头人）；不同群之间不受限制。抽取记录按群记录在
  `data/waifu_state.json`（`group_id` 字段）；
- 本地库不可用时回退 VNDB；回退查询结果仍按会社写入
  `data/waifu_cache.json`，当天有新鲜缓存时不请求 VNDB；
- 每天 `WAIFU_CACHE_REFRESH_TIME`（默认 04:00）增量刷新回退用的 VNDB 缓存：
  已有角色的作品跳过接口，只查新作品；
- 管理员名单复用 `data/admin_ids.json`（与 x_admin/galgame-box 共用）；
- 分群开关复用 `data/plugin_switches.json` 的 `waifu_box` 键。

## 每日老婆互换交易

- **只交换今天的柚子社每日老婆**：交易直接作用于 `data/waifu_state.json` 中的
  今日记录，且双方都必须是用 `/yuzuwaifu` 抽到的（`source=yuzu`）；`/waifu`
  抽到的其他会社角色**暂时不开放交易**；每人每天只有一条记录，不存在
  卡号、不存在多卡收藏；抽卡、重复展示、`list`、交易全部读取同一数据源，
  展示永远与实际一致；
- `/yuzuwaifu trade @对方` 发起互换提议（无需卡号），对方直接发
  `/yuzuwaifu accept` 确认（只有一笔待处理交易时无需交易号；多笔时才需附
  `/yuzuwaifu accept <交易号>`），两位用户的今日老婆在同一把锁内
  原子互换；交易 10 分钟未处理自动过期；发起人可用
  `/yuzuwaifu cancel` 撤销；
- **稀有度**：按角色在作品中的定位（`role`）分级——
  `primary`=SSR 5★、`main`=SR 4★、`side`=R 3★、`appears`=N 2★；仅用于
  `list`/`rank` 展示，记录缺 `role` 时回查本地资料库补齐；
- `/yuzuwaifu rank` 按今日老婆稀有度排行（群内）；交易记录存
  `data/waifu_trades.json`。

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
