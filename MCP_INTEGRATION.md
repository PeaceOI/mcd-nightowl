# MCP 接入说明

> 本项目基于麦当劳中国 MCP Server 构建。接入地址 `https://mcp.mcd.cn`，
> 协议 Streamable HTTP，鉴权 Bearer Token。

---

## 一、接入配置

### 申请 Token

1. 打开 https://open.mcd.cn/mcp
2. 右上角【登录】→ 手机号验证登录
3. 右上角变为【控制台】→ 点开弹窗 →【激活】→ 申请 MCP Token
4. 阅读并同意服务协议 → 一键复制

### WorkBuddy 配置

左侧边栏【专家·技能·连接器】→【连接器】→ 右上角【自定义连接器】→【配置MCP】，
填入以下 JSON：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_TOKEN"
      }
    }
  }
}
```

保存后回到【自定义连接器】，把 `mcd-mcp` 启用即可。

### 本项目配置

```bash
cp .env.example .env     # 填入 MCP_TOKEN=xxx
```

> `.env` 已在 `.gitignore` 中，仓库内只保留占位符 `your_token_here`。

---

## 二、使用的 Tool

| # | Tool | 决策层 | 用途 |
|---|---|---|---|
| 1 | `now-time-info` | ① 时间感知 | 取服务端时间，判定时段（夜宵/早餐/正餐） |
| 2 | `query-nearby-stores` | ② 营业过滤 | 按城市+关键词搜门店，取 `businessStatus` 与营业起止 |
| 3 | `query-meals` | ③ 组合寻优 | 拉门店菜单（分类 + 商品及现价/原价） |
| 4 | `calculate-price` | ③ 组合寻优 | **服务端真实价格校验（核心）** |
| 5 | `list-nutrition-foods` | ④ 营养约束 | 160 条营养数据，用于热量核算 |

**未接入**：`create-order`、`cancel-order`、`auto-bind-coupons`、`draw-lottery`
等交易/领券/抽奖类工具——本项目只做查询与决策，不触发任何真实交易。

---

## 三、调用流程

```
now-time-info
    │  取服务端时间 → 判定时段 → 得出热量预算
    ▼
query-nearby-stores (beType=1, searchType=2, city, keyword)
    │  按 businessStatus + 营业起止过滤 → 只留此刻营业的门店（含跨午夜判断）
    ▼
query-meals (storeCode, orderType=1, beType=1)
    │  得到 124 个商品 {name, currentPrice, originalPrice}
    ▼
list-nutrition-foods
    │  解析 158 条营养数据 → 与菜单名模糊匹配 → 得到每件的热量
    ▼
【本地】束搜索生成候选组合（预算剪枝 + 热量上下限剪枝 + 剔除蘸酱）
    ▼
calculate-price × N 次   ← ★ 服务端价格校验
    │  拿真实到手价与优惠金额，覆盖本地估算
    ▼
帕累托前沿（价格 × 热量）→ 输出多档方案 → 渲染决策卡
```

单次决策 MCP 调用数约 **20 次**，远低于 600 次/分钟的限流上限。

---

## 四、为什么必须用 `calculate-price` 做价格校验

这是本项目最关键的设计决策。

多数点餐类项目把菜单价格拉下来，在本地做加减法算总价。但服务端的价格受三类因素影响：

| 影响因素 | 本地能否模拟 |
|---|---|
| 优惠券互斥规则（哪些券可叠加） | ❌ 只有服务端知道 |
| 门店差异（同款商品不同店不同价） | ❌ 需实时查询 |
| 时段限制（早餐/夜市专属价） | ❌ 随时段动态变化 |

因此本地算出的价格**不可信**。本项目的处理：

- 本地只负责**生成候选组合**（这是搜索问题，适合本地做）
- 每个候选都调用 `calculate-price` 拿**服务端真实到手价**作为 ground truth
- 用真实价参与最终排序与帕累托比较

`calculate-price` 返回示例（**价格单位为分**）：

```json
{
  "productOriginalPrice": 3400, "productPrice": 3400,
  "originalPrice": 3400, "discount": 0, "price": 3400,
  "productList": [{"productCode":"9900005456","productName":"麦辣鸡腿汉堡三件套",
                   "quantity":1,"originalSubtotal":3400,"subtotal":3400}],
  "takeWayList": [{"code":"eat-in","title":"堂食"}, {"code":"take-in-store","title":"外带"}]
}
```

---

## 五、关键参数字典

以下枚举值官方文档未完整给出，为实测所得：

| 参数 | 取值 | 出处 |
|---|---|---|
| `beType` | 1-到店取餐｜2-麦乐送到家｜5-得来速｜6-企业团餐 | `query-meals` |
| `orderType` | 1-到店（含自取+得来速）｜2-外送 | `query-meals` |
| `searchType` | 1-搜索收藏餐厅｜2-按位置搜索 | `query-nearby-stores` |
| `beType` | 1-到店自提｜5-得来速车道取餐 | `query-nearby-stores` |
| `items[]` | `productCode` + `quantity`(≥1) ｜ 可选 `couponId`/`couponCode`/`modification` | `calculate-price` |

---

## 六、错误处理

| 场景 | 处理 |
|---|---|
| HTTP 401 | Token 无效/过期 → 提示重新申请（客户端抛出可读错误） |
| HTTP 429 | 触发限流 → 客户端内置 600 次/分钟滑窗限流 + 指数退避重试 |
| 业务码 600050 | 收藏餐厅列表为空 → 改用 `city + keyword` 搜索 |
| 返回非 JSON | 官方返回多为 Markdown 包裹的文本 → 客户端用括号配对扫描提取 JSON |
| 营养查不到 | 新品在营养表中无记录 → 热量记 0，并在帕累托比较中降权 |

**限流实现**：滑动窗口计数，600 次/60 秒；接近上限时自动退避等待。
单次决策约 20 次调用，无触发风险。

---

## 七、实测结论

| 项 | 结果 |
|---|---|
| 工具总数 | **35**（官方 README 记录 32；多出 `query-promotions`、`query-survey-coupon`） |
| 联调通过 | 22 个，**失败 0** |
| 价格校验成功率 | 20/20 |
| 菜单规模 | 124 个商品 |
| 营养数据 | 158–160 条（含能量/蛋白质/脂肪/碳水/钠/钙，**无咖啡因字段**） |

> 注：官方 README 中的 `query-partystore-*` 实际命名为 `query-party-store-*`。

---

## 八、合规

- 未接入任何下单、领券、抽奖类工具，不触发真实交易
- 仓库内不含真实 Token，配置仅使用环境变量占位符
- 不含任何个人信息，示例输出中的地址均为公开门店信息
- 详见 `CONTEST_DECLARATION.md`
