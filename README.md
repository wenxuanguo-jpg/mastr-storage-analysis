# MaStR 阳台光伏与阳台储能分析

项目包含一个 GitHub Actions 流程，用于从 Bundesnetzagentur 的官方 MaStR Gesamtdatenexport 下载全量数据，在 GitHub Actions runner 临时目录中流式筛选，并部署交互式 GitHub Pages 看板。

筛选口径：阳台光伏为 `Registrierungsdatum der Einheit > 2023-01-01` 且 `Art der Solaranlage = Steckerfertige Solaranlage (sog. Balkonkraftwerk)`；阳台储能为同一日期条件、`Nettonennleistung der Einheit = 0.8 kW` 且 `Energieträger = Speicher`。官方 CSV 的 `0,8` 会按数值 `0.8` 解析。

手动运行：在 GitHub 仓库的 **Actions → MaStR balcony dashboard → Run workflow** 启动。成功后，Pages 看板和同一次运行的 artifact 分别提供压缩交互明细、完整筛选 CSV、月度/年度汇总、特征统计和中文分析报告。完整 ZIP 只写入 runner 临时目录，不提交到仓库。

本地只做小样本验证时，可运行：

```powershell
D:\Python\python.exe -X utf8 mastr_official_export.py --source-path "C:\path\to\Stromerzeuger_*.csv" --output-dir .\test_outputs --site-dir .\test_site
```

---

# 阳台及家庭储能日报机器人

每天北京时间10:00采集过去36小时的公开来源，按关键词筛选、分类、去重，并通过飞书自建应用机器人发送卡片日报：

- pv magazine Deutschland（主源，含编辑新闻、企业新闻和主题搜索）
- pv magazine Global（区域补充，覆盖美国、欧洲、英国、亚太等区域）
- Balkon.Solar
- PluginSolarUS
- EnergieNerds
- Solarserver
- photovoltaik
- BSW-Solar
- HTW Berlin Solar
- ESS News
- Energy-Storage.news
- LinkedIn 重点账号和帖子（需要登录浏览器采集）

关注范围包括阳台及家庭储能、阳台光伏、企业/产品动态、市场数据、AC 耦合改造、能源管理与直接售电、动态电价、热泵及家庭能源生态、多户住宅并网、EEG/法规、友商竞品及插入式/即插即用方案；德国版还重点跟踪小型光伏建设节奏、政策预期和“提前抢装效应”等居民侧市场信号。

## 配置飞书自建应用机器人

1. 在飞书开放平台创建企业自建应用，并启用“机器人”能力。
2. 给应用开通发送消息所需权限，例如“获取与发送单聊、群组消息”。
3. 创建应用版本并发布，由企业管理员审批。
4. 将机器人添加到接收日报的群聊。
5. 复制 `.env.example` 为 `.env`，填写 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 和接收目标。
6. 群推送使用 `FEISHU_RECEIVE_ID_TYPE=chat_id`；个人推送通常使用 `open_id`。
7. `.env` 只保存在本机，不要提交到 Git。

如果还不知道群聊 ID，可以先运行：

```powershell
.\run.ps1 --list-chats
```

从输出中复制目标群的 `chat_id`，填入 `.env` 的 `FEISHU_RECEIVE_ID`，然后运行：

```powershell
.\run.ps1 --test-message
```

如继续使用群自定义机器人，也可以只填写 `FEISHU_WEBHOOK_URL` 和可选的 `FEISHU_SECRET`。

## 本地验证

```powershell
.\run.ps1 --dry-run
.\run.ps1 --test-message
.\run.ps1
```

`--dry-run` 只采集并输出结果，不推送；`--test-message` 只测试飞书连接。日报最多推送5条精选信息；没有新增高相关信息时发送空日报提示。

如需人工补发、并允许展示已经推送过的36小时内文章，可一次性运行：

```powershell
.\run.ps1 --allow-repeats
```

该开关只影响本次手动运行；每天10:00的自动日报仍按历史去重，避免重复打扰。

## 不依赖 Codex 审批的自动运行

如果希望电脑每天自动运行，不依赖 Codex 当时是否打开或是否触发临时审批，可以安装 Windows 计划任务：

```powershell
.\install_task.ps1
```

计划任务名仍保留为 `BalconyEnergyWeeklyBot`（沿用旧周报任务标识，避免创建重复任务），触发频率已改为每天上午 10:00；如果电脑在该时间关机，Windows 会在下次开机后尽快补跑。删除方式：

```powershell
.\uninstall_task.ps1
```

安装本机计划任务后，应暂停 Codex 中同名的自动任务，避免重复推送。

## 调整关注内容

编辑 `config.json`：

- `daily_max_items`：日报精选安全上限，默认8条；仍按相关度筛选，不为凑数加入低价值内容。
- `weekly_max_items`：周报精选安全上限，默认12条，覆盖过去7天；高价值内容充足时可超过原来的5条限制。
- `lookback_hours`：每日回看窗口，默认36小时。
- `minimum_score`：相关度门槛。
- `topics`：主题及德语、荷兰语、英语、中文关键词。
- `sources`：数据源及已知 Feed 地址。

采集器会优先寻找 RSS/Atom，失败时回退到网页文章链接。所有来源正常参与综合排序；仅在 pv magazine 体系内部优先德国版，全球版用于补充不同区域的插入式和家庭储能动态。Balkon.Solar、EnergieNerds 与 Solar Magazine 会按当地语言检索相同主题，其他行业媒体也会照常采集。新增媒体若能自动发现 RSS 就使用订阅，否则解析公开首页文章。筛选器不仅识别产品本体，也识别“产品 + 市场数据/商业模式/家庭能源生态/并网约束”的组合信号，同时排除无居民侧关联的大型电站储能。某个来源失败不会阻止日报生成，但不会更新已发送去重状态；失败来源只显示名称，不显示内部错误。

对进入精选的德语、英语和荷兰语文章，机器人会先生成中文标题与中文摘要；仅在翻译服务暂不可用时，才保留来源、类型和原文链接，并标注“中文摘要生成失败，待人工确认”。该兜底信息不会替代正文中的中文标题或外文长句。

标题采用原文直译优先策略，保留品牌、容量、耦合方式、产品对象和政策主体等关键信息；无法直译时使用具体事件模板，不再使用“产品发布相关动态”等空泛标题。

现有每日自动任务保持为唯一入口：每天上午10:00发送日报；北京时间周一在日报后额外运行 `.\run.ps1 --weekly --allow-repeats`，发送过去7天周报。`--allow-repeats` 仅用于周报汇总，避免已进入日报的高价值文章被历史去重全部过滤；不会创建新的项目或重复自动任务。

## LinkedIn 社交信号

LinkedIn 没有适合任意公开账号的稳定 RSS，很多帖子还要求登录。因此项目使用两层结构：

1. `linkedin_watchlist.json` 保存需要关注的公司主页、个人主页、示例帖子和关键词。
2. 登录浏览器采集到的帖子写入 `data/social_posts.json`，主程序会与网站文章一起分类、去重和推送。

可复制 `data/social_posts.example.json` 作为数据格式参考。LinkedIn 用于提前发现新品、合作、渠道和高管动态；重要信息应通过企业官网、新闻稿或行业媒体交叉验证。
