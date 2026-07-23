# A股5分钟K线实时监测系统 — GitHub Actions 部署指南

## 🚀 5分钟部署

### 第1步：注册 PushPlus（免费）
1. 打开 https://www.pushplus.plus/
2. 微信扫码登录
3. 个人中心 → 复制你的 **Token**（免费版每天200条，完全够用）

### 第2步：创建 GitHub 仓库
1. 打开 https://github.com/new
2. 仓库名填 `stock-5min-monitor`
3. 选 **Public**（免费无限 Actions 时长）
4. 不要勾选 "Add a README file"
5. 点 "Create repository"

### 第3步：上传代码
在仓库创建后的页面上，把以下两个文件上传：

**文件1: `monitor.py`** （已生成在 `/workspace/stock-action/monitor.py`）
**文件2: `.github/workflows/monitor.yml`** （已生成在 `/workspace/stock-action/.github/workflows/monitor.yml`）

### 第4步：配置 Secret
1. 仓库页面 → Settings → Secrets and variables → Actions
2. 点 "New repository secret"
3. Name: `PUSHPLUS_TOKEN`
4. Value: 粘贴你的 PushPlus Token
5. 点 "Add secret"

### 第5步：启用 Actions
1. 仓库页面 → Actions 标签
2. 看到 "A股5分钟K线实时监测" workflow
3. 点 "I understand my workflows, go ahead and enable them"

## ✅ 完成！
之后每个交易日 09:30-15:00，GitHub Actions 每5分钟自动运行一次，
有买卖信号立刻通过 PushPlus 推送到你微信。

## 📝 修改目标个股
编辑仓库里的 `monitor.py`，修改 `TARGET_STOCKS` 字典即可。
修改后 GitHub Actions 下次运行自动生效。
