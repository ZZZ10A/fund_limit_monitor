# Fund Limit Monitor (基金限额监控)

此项目用于监控指定 QDII 基金（如纳斯达克 100、标普 500）的单日申购限额，并通过企业微信或钉钉机器人发送通知。

## 功能

- 爬取天天基金网的基金详情数据。
- 提取“交易状态”和“单日限额”信息。
- 实时抓取基金费率；Markdown 日报保留“费率摘要”区，图片日报按指数表格合并展示限额和费率。
- 使用 SQLite 保存每日限额历史，并在限额变化时展示“旧值 -> 新值”。
- 生成日报并通过抽象通知通道推送。
- 支持企业微信 Markdown 机器人。
- 支持钉钉 Markdown 机器人（加签模式），可发送图片版日报。

## 目录结构

```
.
├── config.json       # 配置文件 (需填入Webhook URL)
├── monitor.py        # 主程序
├── notifier.py       # 通知通道实现
├── report_renderer.py # 图片日报渲染
├── history.db        # 自动生成的历史数据库
├── assets/fonts/     # 内置中文字体子集
└── requirements.txt  # Python依赖
```

## 安装与配置

1. **安装依赖**

   ```bash
   pip install -r requirements.txt
   ```

2. **配置通知**

   程序由 `config.json` 中的 `notifiers` 指定通知通道列表：

   - `dingtalk`：钉钉机器人
   - `wechat`：企业微信机器人
   - `console`：仅打印到终端

   程序会按列表顺序逐个发送，同一条日报可以同时推送到多个群。某个通知配置不完整时只跳过该项，不影响其他通知。

   `webhook_url`、`secret` 等敏感值只从环境变量读取，`config.json` 只保存环境变量名。
   默认 `config.json` 已声明钉钉和企业微信；是否实际发送取决于对应环境变量是否有值。

   **多个通知通道**

   ```json
   {
       "notifiers": [
           {
               "type": "dingtalk",
               "webhook_url_env": "DINGTALK_WEBHOOK_URL",
               "secret_env": "DINGTALK_SECRET"
           },
           {
               "type": "wechat",
               "webhook_url_env": "WEBHOOK_URL"
           }
       ],
       "funds": [
           ...
       ]
   }
   ```

   **钉钉机器人**

   钉钉群机器人启用“加签”安全设置后，配置：

   ```json
   {
       "notifiers": [
           {
               "type": "dingtalk",
               "webhook_url_env": "DINGTALK_WEBHOOK_URL",
               "secret_env": "DINGTALK_SECRET"
           }
       ],
       "funds": [
           ...
       ]
   }
   ```

   然后通过环境变量或 GitHub Secrets 提供真实值：

   ```bash
   export DINGTALK_WEBHOOK_URL="https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"
   export DINGTALK_SECRET="SECxxxxxxxxxxxxxxxx"
   ```

   如果不配置 `webhook_url_env` 和 `secret_env`，默认读取 `DINGTALK_WEBHOOK_URL` 和 `DINGTALK_SECRET`。

   **钉钉图片日报**

   钉钉自定义 Webhook 机器人通过 Markdown 展示图片，因此图片必须先有公网 URL。本项目默认将 PNG 保存到 `reports/`，GitHub Actions 会提交后再发送钉钉消息：

   ```bash
   export REPORT_IMAGE_BASE_URL="https://raw.githubusercontent.com/OWNER/REPO/main/reports"
   export REPORT_IMAGE_DIR="reports"
   ```

   如果未配置 `REPORT_IMAGE_BASE_URL`，`python3 monitor.py` 会保持纯 Markdown 通知；`--prepare-report` 仍会生成本地 PNG，但 payload 中不会附带公网图片 URL。

   图片渲染默认使用项目内置字体 `assets/fonts/FundReportSans-Subset.otf`。如需替换字体：

   ```bash
   export REPORT_FONT_PATH="/path/to/font.otf"
   ```

   **历史数据**

   程序使用 `history.db` 保存每日限额快照，表中每个自然日只保留一条记录。生成日报时会与数据库中早于当天的最近一条记录对比；如果限额发生增加或减少，Markdown 和图片日报都会展示类似 `100元 -> 500元 ↑` 的变化。

   旧版 `history.json` 不再读取，也不会迁移。切换到 SQLite 后首次运行数据库为空，因此当日报告不会显示历史变化。

   **费率摘要**

   日报会从天天基金基金档案费率页实时抓取每只基金的费率信息，例如：

   ```text
   https://fundf10.eastmoney.com/jjfl_270042.html
   ```

   Markdown 报告末尾会新增“费率摘要”区；图片日报会按纳斯达克 100、标普 500 生成两张表格，合并展示名称、价差信息、运作费率、申购优惠、赎回费率。当前展示口径为：

   - 运作费用：管理费率、托管费率、销售服务费率，以及可解析百分比的年度合计。
   - 申购费率：最低金额档的天天基金优惠费率，优先取“银行卡购买”列。
   - 赎回费率：第一条和最后一条持有期档位。

   若某只基金费率页请求失败或结构异常，该基金会显示“费率获取失败”，不会影响限额日报生成和通知发送。

   **企业微信机器人**

   ```json
   {
       "notifiers": [
           {
               "type": "wechat",
               "webhook_url_env": "WEBHOOK_URL"
           }
       ],
       "funds": [
           ...
       ]
   }
   ```

   然后通过环境变量或 GitHub Secrets 提供真实值：

   ```bash
   export WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"
   ```

   如果不配置 `webhook_url_env`，默认读取 `WEBHOOK_URL`。

   **多个同类机器人**

   多个钉钉或企业微信机器人需要使用不同的环境变量名：

   ```json
   {
       "notifiers": [
           {
               "type": "dingtalk",
               "webhook_url_env": "DINGTALK_WEBHOOK_URL_A",
               "secret_env": "DINGTALK_SECRET_A"
           },
           {
               "type": "dingtalk",
               "webhook_url_env": "DINGTALK_WEBHOOK_URL_B",
               "secret_env": "DINGTALK_SECRET_B"
           }
       ],
       "funds": [
           ...
       ]
   }
   ```

   **终端打印**

   ```json
   {
       "notifiers": [
           {
               "type": "console"
           }
       ],
       "funds": [
           ...
       ]
   }
   ```

   旧的单个 `notifier` 对象仍然兼容；新配置建议使用 `notifiers` 数组。

   您也可以在该文件中调整需要监控的基金代码。

## 运行

**手动运行：**

```bash
python3 monitor.py
```

正常情况下，您会在终端看到输出（如果没有配置 Webhook），或者在钉钉群/企业微信群收到消息。

**两阶段生成并发送：**

```bash
python3 monitor.py --prepare-report --report-output .report/latest.json
python3 monitor.py --send-report .report/latest.json
```

该模式适合 CI：先生成并提交 `reports/*.png` 和 `history.db`，让图片 URL 生效后，再发送钉钉消息。

**重新生成字体子集：**

修改基金列表或图片文案后，运行：

```bash
python3 scripts/build_font_subset.py
```

字体来源为 Noto Sans CJK SC，许可证见 `assets/fonts/OFL.txt`。

**运行测试：**

```bash
python3 -m unittest test_monitor.py test_report_renderer.py test_notifier.py
python3 -m py_compile monitor.py notifier.py report_renderer.py test_notifier.py test_report_renderer.py test_monitor.py
```

## GitHub Actions 自动运行

本项目已配置 GitHub Actions workflow，每天可自动运行、生成图片日报、更新历史记录并发送通知。

它可以手动触发（Workflow dispatch），也会在每天北京时间 13:30 (UTC 05:30) 自动运行。

如需在 GitHub Actions 使用钉钉通知，请先在 `config.json` 的 `notifiers` 中添加 `dingtalk` 项，再在仓库 Settings -> Secrets and variables -> Actions 中添加：

- `DINGTALK_WEBHOOK_URL`
- `DINGTALK_SECRET`

如需使用企业微信通知，请在 `notifiers` 中添加 `wechat` 项，并添加 Secret `WEBHOOK_URL`。

## 注意事项

- 脚本依赖天天基金网的页面结构，如果网站改版可能会失效。
- 请适度控制抓取频率，避免被封禁 IP。
