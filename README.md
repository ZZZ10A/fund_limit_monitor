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

它可以手动触发（Workflow dispatch），也会在每天北京时间 13:30 (UTC 05:30) 自动运行。

## 注意事项

- 脚本依赖天天基金网的页面结构，如果网站改版可能会失效。
- 请适度控制抓取频率，避免被封禁 IP。
