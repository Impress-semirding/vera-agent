# 贡献指南

感谢您关注 Vera Agent 项目！我们欢迎各种形式的参与。

## 🐛 报告 Bug

如果你发现了 Bug，请在 [GitHub Issues](https://github.com/Impress-semirding/vera-agent/issues) 中提交，并包含：

- 清晰的问题描述
- 复现步骤
- 预期行为 vs 实际行为
- 你的环境（OS、Python 版本、Node 版本等）

## 💡 建议功能

有新想法？请在 [GitHub Discussions](https://github.com/Impress-semirding/vera-agent/discussions) 中讨论，或直接提交 Issue。

我们特别欢迎关于以下方面的建议：
- 新的 Agent 模式支持
- Skills 系统的增强
- UI/UX 改进
- 性能优化

## 🚀 提交代码

### 开发环境搭建

```bash
# 1. Fork 并 Clone
git clone https://github.com/YOUR_USERNAME/vera-agent.git
cd vera-agent

# 2. 创建特性分支
git checkout -b feature/your-feature-name

# 3. 后端开发
cd backend
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 4. 前端开发
cd ../frontend
pnpm install
```

### 代码规范

- Python: 遵循 [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- TypeScript: 使用 Prettier 格式化，ESLint 检查
- 提交信息: 使用 Conventional Commits 格式
  ```
  feat: add new skill system feature
  fix: resolve agent deadlock issue
  docs: update README
  ```

### 提交 PR 的步骤

1. **确保代码质量**
   ```bash
   # Python 检查
   cd backend
   black .
   flake8 .
   mypy .
   
   # TypeScript 检查
   cd ../frontend
   prettier --write .
   npm run lint
   ```

2. **编写/更新测试**
   ```bash
   # 后端测试
   cd backend
   pytest
   
   # 前端测试
   cd ../frontend
   npm run test
   ```

3. **更新文档**
   - 如果改变了 API，请更新 `docs/websocket-chat-protocol.md`
   - 如果添加了新特性，请在 README 中体现

4. **Push 并提交 PR**
   ```bash
   git push origin feature/your-feature-name
   ```
   
   在 PR 描述中包含：
   - 改动的目的
   - 主要改动点
   - 相关 Issue（如果有）

## 📝 改进文档

欢迎以下形式的文档贡献：

- 翻译文档（英文 ↔ 中文）
- 完善现有文档
- 编写使用教程
- 创建常见问题解答

## 📋 行为准则

我们致力于为所有贡献者提供一个友好、包容的环境。请遵守以下准则：

- 尊重他人的观点和想法
- 建设性地提出批评
- 不骚扰、歧视或骚扰任何人
- 尊重社区决定

## ❓ 有疑问？

- 在 GitHub Discussions 中提问
- 查看 [README](README.md) 快速开始指南
- 查看 `docs/` 目录中的详细文档

---

感谢你对 Vera 的支持！🙏