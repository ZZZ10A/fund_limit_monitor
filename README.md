# Fund Limit Monitor (基金限额监控)

此项目用于监控指定 QDII 基金（如纳斯达克 100、标普 500）的单日申购限额，并通过企业微信机器人发送通知。

## 功能

- 爬取天天基金网的基金详情数据。
- 提取“交易状态”和“单日限额”信息。
- 生成日报并通过企业微信（Markdown 格式）推送。

## 目录结构

```
.
├── config.json       # 配置文件 (需填入Webhook URL)
├── monitor.py        # 主程序
└── requirements.txt  # Python依赖
```

## 安装与配置

1. **安装依赖**

   ```bash
   pip install -r requirements.txt
   ```

2. **配置 Webhook**
   打开 `config.json`，将 `webhook_url` 替换为您企业微信机器人的真实地址。
   ```json
   {
       "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY",
       "funds": [
           ...
       ]
   }
   ```
   您也可以在该文件中添加不需要监控的基金代码。

## 运行

**手动运行测试：**

```bash
python3 monitor.py
```

正常情况下，您会在终端看到输出（如果没有配置 Webhook），或者在企业微信群收到消息。

## GitHub Actions 自动运行

本项目已配置 GitHub Actions workflow，每天可自动运行并更新历史记录。

### 启用步骤

1. **推送代码到 GitHub**
   将本项目代码 push 到您的 GitHub 仓库。

2. **配置权限**
   GitHub Actions 需要写入权限来更新 `history.json`（用于记录涨跌历史）。

   - 进入仓库 **Settings** > **Actions** > **General**
   - 找到 **Workflow permissions**
   - 勾选 **Read and write permissions**
   - 点击 **Save**

3. **配置 Webhook (可选但推荐)**
   如果仓库是公开的（Public），**强烈建议**不要将 Webhook URL 直接写在 `config.json` 中。
   您可以使用 GitHub Secrets：

   - 在 Settings > Secrets and variables > Actions 中添加 `WEBHOOK_URL`。
   - (需修改代码以支持从环境变量读取，目前版本仅支持 `config.json`)
   - **注意**：当前代码直接读取 `config.json`。如果是私有仓库（Private），则可以直接保留 `config.json` 中的配置。

4. **查看运行结果**
   - 进入 **Actions** 标签页。
   - 您会看到 "Daily Fund Limit Monitor" 的工作流。
   - 它可以手动触发（Workflow dispatch），也会在每天北京时间 14:00 (UTC 06:00) 自动运行。

## 注意事项

- 脚本依赖天天基金网的页面结构，如果网站改版可能会失效。
- 请适度控制抓取频率，避免被封禁 IP。
