# 使用手册 · v1.1.0

## 启动与数据

安装 Python 3.10–3.13 后运行 `start.bat`，访问 `http://127.0.0.1:8000`。首次安装需要网络，安装后本地模型与工作台不需要外部请求。`/docs` 为交互式接口说明。

默认在 `runtime/commerce.db` 保存数据；`COMMERCE_HOME` 可覆盖运行目录，`DATABASE_URL` 可覆盖数据库。旧版根目录若有 `demo.db` 会继续使用，新增复核、批次表，保留旧订单。

`COMMERCE_SEED_DEMO=0` 可关闭虚构种子数据；首次演示产生的240条订单不会自动清空，也没有重置按钮。已有数据库请备份，不建议面试当天随意删除。

## 导入

点击“导入订单”，选择 CSV。界面展示字段映射、新增订单数、文件内重复、已存在重复和无效行。预检不写数据库。

| 标准字段 | 支持的中文表头示例 | 要求 |
| --- | --- | --- |
| order_id | 订单编号、订单号、主订单编号 | 必填，最长80字符 |
| platform | 平台、订单来源 | 最长40字符；缺省“授权CSV” |
| customer_id | 客户编号、买家编号、用户ID | 必填，最长80字符；需为商家统一ID |
| product_name | 商品名称、商品标题、商品 | 必填，最长240字符 |
| amount | 实付金额、订单金额、金额 | 大于0、最大1000万；四舍五入到分 |
| quantity | 数量、购买数量 | 缺省1，正整数，最大100000 |
| ordered_at | 下单日期、下单时间、订单日期 | ISO日期/时间；支持日期中的斜杠；不可晚于今天 |

UTF-8（可含BOM）与 GB18030 编码均支持。最多8 MB、10,000行。金额可带人民币符号和千分位，带逗号的 CSV 字段须用引号包裹。无效行整批阻止写入，不进行静默部分导入。

填写数据来源并确认授权声明后导入。浏览器将预检文件摘要一同提交，后端校验摘要、重新校验所有行，在事务中完成订单和批次写入。去重键为“平台+订单号”；同键不覆盖原订单，退款/状态变化尚不支持。

授权勾选仅记录操作者声明，不能代替平台授权凭据或多租户权限控制。中文样例文件也只是演示映射，不宣称兼容所有平台实际导出格式。

## 分类与复核

新订单通过本地字符 TF-IDF + 逻辑回归分类。“其他”、低分或类别分差较小时标记待复核。选择“仅待复核”，点击“复核”，确认类别并填写说明。

人工结果存于独立表，原始分类、模型分值和模型理由保留。有效分类使用最新复核结果，总览、客户分层和复购清单随之更新。复核不会自动训练模型。模型说明见 `model-card.md`。

## 看板与客户洞察

- 累计订单和成交客户为全量去重汇总，销售额是订单金额之和，未扣退款、成本或税费。
- 30天窗口包含今天及前29天，环比对照再前30天。基期为零显示“暂无可比基数”。
- 客户分层：R为距最近购买天数，F为不同购买日数，M为累计订单金额。具体固定阈值见架构文档。
- 复购按客户与品类、不同购买日的间隔中位数计算。预计周期日期是历史节奏参考。优先分不是购买概率；过度逾期客户进入唤回评估。
- 按客户品类组合计复购机会；同一客户可能出现多个组合。页面显示前60项，导出包含全部候选。

## 导出

“导出筛选结果”包含当前搜索、平台、类别及待复核条件匹配的全部订单，不仅是当前页。CSV 带 UTF-8 BOM，并对以公式前缀开头的文本加单引号。

经营报告为独立 HTML，可在浏览器保存或打印为 PDF。导出包含客户编号，演示或分享应使用虚构数据。

## 环境变量

```powershell
$env:COMMERCE_HOME = "D:\CommerceDemo\runtime"
$env:COMMERCE_SEED_DEMO = "0"
# 可选：实际部署前须另行验证 MySQL、迁移、备份和权限。
$env:DATABASE_URL = "mysql+pymysql://app_user:password@127.0.0.1:3306/commerce_copilot?charset=utf8mb4"
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

`.env.example` 仅用于说明，不会由当前启动脚本自动加载。数据库凭据不要提交到 Git。

## 主要接口

| 接口 | 用途 |
| --- | --- |
| GET /api/health、/api/summary | 状态、版本和经营统计 |
| POST /api/import/preview | 上传、字段映射、预检，不写入 |
| POST /api/import/csv | file、authorized、source、expected_sha256 表单 |
| GET /api/import/batches | 最近20个导入批次 |
| GET /api/orders/page | q、category、platform、review_only、page、page_size |
| PATCH /api/orders/{id}/category | category、note JSON |
| GET /api/customers、/api/recommendations | 客户分层与复购组合 |
| GET /api/model；POST /api/classify | 模型说明、商品试分类 |
| GET /api/export/orders.csv、/api/export/opportunities.csv | CSV 导出 |
| GET /api/report | 独立HTML报告 |
