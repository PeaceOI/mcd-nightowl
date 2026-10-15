# WorkBuddy 开发上下文

> 本文件用于核验「使用 WorkBuddy 开发参赛」的专项奖励资格。
> 记录本项目在 WorkBuddy 中的开发过程。

---

## 项目信息

| 项 | 内容 |
|---|---|
| 项目名称 | 麦麦夜宵官 `mcd-nightowl` |
| 项目地址 | https://github.com/PeaceOI/mcd-nightowl |
| 开发工具 | WorkBuddy（Agent 模式） |
| 开发日期 | 2026-10-10 |
| MCP 接入 | 麦当劳中国 MCP Server（`https://mcp.mcd.cn`） |

---

## 开发过程

### 1. 赛事调研

- 读取官方推文，定位 GitHub 官方账号 `M-China`
- 抓取 `mcd-developer-innovation-challenge` 赛事规则与 `RANKING.md` 排行榜
- 逐项分析 90 个已上榜项目，绘制赛道拥挤度地图
- 结论：深夜时段为零竞争空白赛道；泛化的 "xx Assistant / Smart Order" 全部沉底（1–3 star）

### 2. MCP 接入联调

- 搭建 `mcd-lab` 验证实验台：MCP 客户端 + 批量联调验证器 + 单工具调试器
- 全量验证 35 个 Tool，通过 22 个、失败 0
- 产出字段字典与返回结构速查（见 `MCP_INTEGRATION.md`）

### 3. 方案设计

- 确定四层决策架构：时间感知 → 营业过滤 → 组合寻优 → 营养约束
- 技术核心：不本地算价，用 `calculate-price` 做服务端校验

### 4. 编码实现

在 WorkBuddy 中完成：

| 模块 | 内容 |
|---|---|
| `src/mcp_client.py` | MCP 客户端：Session 管理、Markdown 包裹 JSON 提取、600/min 滑窗限流、401/429 处理 |
| `src/time_guard.py` | 时段判定（含跨午夜）与热量预算 |
| `src/store_filter.py` | 营业门店过滤（服务端状态 × 本地营业时间交叉校验） |
| `src/nutrition.py` | 营养文本解析 + 商品名模糊匹配 + 运动折算 |
| `src/optimizer.py` | 束搜索 + 服务端价格校验 + 帕累托前沿 |
| `src/card.py` | 决策卡渲染 |
| `src/cli.py` | 命令行入口 |

### 5. 关键调试记录

| 问题 | 解决 |
|---|---|
| MCP 返回是 Markdown 包裹的文本，无法直接 JSON 解析 | 实现括号配对扫描提取 JSON（`_extract_json`） |
| 首版用 `rfind('}')` + 回退重试，在 124 个商品的大文本上退化成 O(n²) 卡死 | 改为 O(n) 的括号配对扫描 |
| 按价格排序时，最优解永远是 ¥3 的蘸酱 | 剔除蘸酱小料 + 束搜索按「能否吃饱」分层 + 引入热量下限 |
| 营养表商品名与菜单名不一致（如「麦辣鸡腿汉堡」vs「麦辣鸡腿汉堡三件套」） | 实现剥后缀 + 双向包含的模糊匹配 |
| 白天无法演示夜宵场景 | 增加 `--at HH:MM` 强制时刻参数 |

---

## 效果验证

```bash
python -m src.cli --keyword 徐家汇 --at 23:30 --budget 30 --beam 12
```

输出：徐家汇店（营业至 23:59，355m）→ 那么大鸡排 ¥14 → 385 kcal（未超夜宵 500 上限）
→ ≈ 慢跑 6.2 km。服务端价格校验 20/20 通过，单次决策 MCP 调用 24 次。

---

## 备注

若需提交更完整的对话记录，可在 WorkBuddy 中导出本次会话上下文，
替换或追加到本文件末尾。文件名必须为 `workbuddy.md`。
