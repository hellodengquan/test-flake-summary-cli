# Test Flake Summary CLI

不稳定测试（Flaky Test）汇总工具，用于从持续集成系统中拉取测试结果，识别和分析偶发抖动的测试用例。

## 功能特性

- 支持 JUnit XML 和 JSON 格式的测试结果
- HTTP/HTTPS 远程拉取，支持多种认证方式及 Token 自动刷新链
- 智能分类：稳定通过、偶发抖动、连续失败
- 按团队和文件分组统计
- 可配置的权重评分算法（三档容差预设）
- 时间窗口筛选历史数据（兼容跨年 ISO week）
- 文本表格和 JSON 两种输出格式
- 被跳过样本 metadata 输出（含 sample IDs），方便下游 dashboard

## 安装

要求 Python 3.8+，仅使用标准库，无需额外依赖。

```bash
python -m flake_summary --help
```

## 快速开始

```bash
python -m flake_summary --dir sample_data/
python -m flake_summary --files https://ci.example.com/results/run.xml --bearer-token YOUR_TOKEN
python -m flake_summary --dir sample_data/ --format json --output report.json
```

## 命令行参数

### 输入选项

| 参数 | 说明 |
|------|------|
| `--dir` | 包含测试结果文件的目录（.xml 或 .json） |
| `--files` | 一个或多个测试结果文件路径或 URL |

### HTTP 认证选项

| 参数 | 说明 |
|------|------|
| `--basic-auth-user` | HTTP Basic Auth 用户名 |
| `--basic-auth-pass` | HTTP Basic Auth 密码 |
| `--bearer-token` | Bearer Token 用于 API 认证 |
| `--proxy` | 代理服务器 URL |

### 分类选项

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--min-runs` | 3 | 参与分类的最少运行次数，不足则跳过 |
| `--stable-threshold` | 0.95 | 稳定通过的通过率阈值 |
| `--fail-ratio` | 0.7 | 连续失败的失败率阈值 |
| `--weights` | - | 权重配置文件路径（JSON 格式） |
| `--time-window` | - | 历史数据时间窗口（天） |

### 输出选项

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--format` | text | 输出格式：text 或 json |
| `--output` | stdout | 输出文件路径 |
| `--all` | - | 显示所有用例（包括稳定通过） |
| `--only-flaky` | - | 仅显示偶发抖动用例 |

## JSON Schema 版本说明

本工具的 JSON 输出格式遵循语义化版本规范，方便下游系统进行兼容性判断。

### 当前版本

- **Schema Version**: `1.1.0`
- **Tool Version**: `1.0.0`

### 版本字段

```json
{
  "schema_version": "1.1.0",
  "tool_version": "1.0.0",
  "...": "..."
}
```

- `schema_version`: JSON 输出结构的版本号，结构变更时递增
- `tool_version`: 工具本身的版本号

### 版本历史

#### v1.1.0（当前）

**新增字段：**
- `schema_version`: 标识输出结构版本
- `tool_version`: 标识工具版本
- `fail_ratio_pct`: 失败百分比（整数）
- `total_runs`: 每个用例的总运行次数字段
- `skipped_tests`: 被跳过用例的 metadata 列表，含 name / file / team / total_runs / min_runs_required / passed / failed / skipped_count / reason / skipped_sample_ids / skip_reason

**变更说明：**
- `recent_consecutive_failures` 字段语义变更：从"连续失败次数"改为"失败比例百分比"
- 运行次数不足 `min-runs` 的用例不再出现在 `classified_tests`，改为输出到 `skipped_tests`

#### v1.0.0

初始版本，包含基本的分类和统计功能。

### Schema 双向兼容路径

#### v1.1.0 → v1.0.0 降级（Downgrade）

当 v1.1.0 的 JSON 输出需要被只支持 v1.0.0 的下游系统消费时：

| v1.1.0 字段 | v1.0.0 处理方式 |
|-------------|----------------|
| `schema_version` | **必须删除**。v1.0.0 无此字段，保留会导致下游校验失败。降级时 `del data["schema_version"]` |
| `tool_version` | **必须删除**。v1.0.0 无此字段。降级时 `del data["tool_version"]` |
| `fail_ratio_pct` | 映射回 `recent_consecutive_failures`，值不变（整数百分比） |
| `skipped_tests` | 删除，或将条目回填到 `classified_tests`（category 设为 `flaky` 或 `stable_pass`） |
| `classified_tests[].total_runs` | 删除，v1.0.0 可从 passed + failed + skipped 推算 |
| `skipped_tests[].skipped_sample_ids` | **必须删除**。v1.0.0 无此字段 |
| `skipped_tests[].skip_reason` | **必须删除**。v1.0.0 无此字段 |

**schema_version 降级规则：**

1. 若 `schema_version` 为 `"1.1.0"` → 直接删除字段
2. 若 `schema_version` 为更高版本 → 先检查是否有不认识的字段，有则报警，无则降为 `"1.0.0"` 再删除
3. 降级后的 JSON 不应包含任何 `schema_version` 或 `tool_version` 字段，因为 v1.0.0 不定义这些字段

降级脚本：

```python
import json

def downgrade_1_1_to_1_0(data: dict) -> dict:
    if data.get("schema_version") != "1.1.0":
        return data
    for ct in data.get("classified_tests", []):
        ct["recent_consecutive_failures"] = ct.pop("fail_ratio_pct", 0)
        ct.pop("total_runs", None)
    for st in data.get("skipped_tests", []):
        entry = {
            "name": st["name"],
            "file": st["file"],
            "team": st["team"],
            "category": "flaky" if st["failed"] > 0 else "stable_pass",
            "flaky_score": 0.0,
            "passed": st["passed"],
            "failed": st["failed"],
            "skipped": st["skipped_count"],
            "pass_rate": round(st["passed"] / max(st["total_runs"], 1) * 100, 2),
            "fail_rate": round(st["failed"] / max(st["total_runs"], 1) * 100, 2),
            "recent_consecutive_failures": 0,
            "history": [],
        }
        data["classified_tests"].append(entry)
    del data["schema_version"]
    del data["tool_version"]
    del data["skipped_tests"]
    return data
```

#### v1.0.0 → v1.1.0 升级（Upgrade）

当 v1.0.0 的旧 JSON 需要被只支持 v1.1.0 的下游系统消费时：

| v1.0.0 字段 | v1.1.0 处理方式 |
|-------------|----------------|
| `recent_consecutive_failures` | 映射到 `fail_ratio_pct`，值不变 |
| 缺少 `schema_version` | 补充 `"schema_version": "1.1.0"` |
| 缺少 `tool_version` | 补充 `"tool_version": "0.0.0"` |
| 缺少 `skipped_tests` | 补充 `"skipped_tests": []` |
| 缺少 `classified_tests[].total_runs` | 从 passed + failed + skipped 推算 |

升级脚本：

```python
def upgrade_1_0_to_1_1(data: dict) -> dict:
    if "schema_version" in data:
        return data
    data["schema_version"] = "1.1.0"
    data["tool_version"] = "0.0.0"
    data["skipped_tests"] = []
    for ct in data.get("classified_tests", []):
        ct["fail_ratio_pct"] = ct.pop("recent_consecutive_failures", 0)
        ct["total_runs"] = ct["passed"] + ct["failed"] + ct.get("skipped", 0)
    return data
```

## 权重配置

权重配置文件为 JSON 格式，用于调整 flaky 评分算法的各因素权重。

示例（`sample_data/weights_config.json`）：

```json
{
  "fail_rate_weight": 0.5,
  "transition_weight": 0.3,
  "recency_weight": 0.2,
  "recency_window_size": 5
}
```

**配置项说明：**

| 配置项 | 说明 |
|--------|------|
| `fail_rate_weight` | 失败率权重 |
| `transition_weight` | 状态转换频率权重 |
| `recency_weight` | 近期失败权重 |
| `recency_window_size` | 近期窗口大小 |

### 归一化容差三档预设

三个权重值之和应在 1.0 的容差范围内。提供三档预设供运维选择：

| 预设名称 | 容差值 | 说明 | 适用场景 |
|----------|--------|------|----------|
| `strict` | 0.001 | 精确归一化，仅允许浮点误差 | 生产环境，权重需严格等于 1.0 |
| `normal` | 0.01 | 允许 1% 偏差 | 日常使用，权重手工配置时的小误差 |
| `loose` | 0.05 | 允许 5% 偏差 | 探索性分析，快速调参无需精确归一 |

超出容差时自动归一化（默认行为），或抛出错误。

```python
from flake_summary.classifier import WeightsConfig, TestCaseClassifier

# 使用预设
tolerance = WeightsConfig.tolerance_preset("normal")  # 0.01

weights = WeightsConfig(fail_rate_weight=0.5, transition_weight=0.35, recency_weight=0.16)
classifier = TestCaseClassifier(weights=weights, weight_tolerance=tolerance)

# 也可直接传数值
classifier = TestCaseClassifier(weights=weights, weight_tolerance=0.05)
```

## Token 认证链与降级策略

当使用 Bearer Token 认证时，支持配置完整的认证链来处理 token 过期场景。

### 认证链流程

```
请求 → 401/403?
  ├─ 是 → 有 token_refresh_fn 且未超重试次数?
  │     ├─ 是 → 调用 refresh_fn
  │     │     ├─ 成功 → 用新 token 重试
  │     │     └─ 失败(异常) → 退回原 token，标记刷新耗尽
  │     └─ 否 → 原始 token 也过期，触发 on_auth_exhausted 策略
  └─ 否 → 正常返回
```

### on_auth_exhausted 策略

当 token 刷新失败且原始 token 也过期时，通过 `on_auth_exhausted` 参数控制行为：

| 值 | 行为 | 适用场景 |
|----|------|----------|
| `"abort"` (默认) | 抛出 HTTPError，任务终止 | 数据完整性要求高，不允许无认证读取 |
| `"readonly"` | 去掉认证头重试一次，若成功则返回只读数据 | CI 系统支持公开只读访问，宁可降低权限也要拿到数据 |

**注意：** `readonly` 模式下重试也失败时，仍抛出原始 HTTPError，不会无限 hang。

```python
from flake_summary.parser import HTTPConfig

# 策略一：认证耗尽时直接放弃（默认）
config = HTTPConfig(
    bearer_token="initial_token",
    token_refresh_fn=refresh_fn,
    on_auth_exhausted="abort",
)

# 策略二：认证耗尽时降级到只读
config = HTTPConfig(
    bearer_token="initial_token",
    token_refresh_fn=refresh_fn,
    on_auth_exhausted="readonly",
)
```

## 时间窗口与跨年 ISO Week 处理

`--time-window` 参数支持多种时间戳格式，包括 ISO week 格式（如 `2020-W53-1`）。在跨年场景下，ISO week 边界需要特别注意。

### 三种取值场景与优先级

| 场景 | 优先级 | Default | 说明 |
|------|--------|---------|------|
| 语义层（Semantic） | **1（最高）** | ✅ 本工具默认 | 严格按 ISO 8601 定义解析，`fromisocalendar()` 直接映射为精确日期 |
| 历史（Historical） | 2 | 自动转换 | ISO week 解析后自动转为日历日期，时间窗口过滤基于实际日期计算 |
| 当周（Current Week） | 3（最低） | ❌ 不默认 | 仅按周数差值判断，不考虑具体日期；需外部实现 |

**优先级含义：** 本工具始终先按语义层解析 ISO week，然后自动转为历史模式做日期比较。当周模式不作为默认行为，因为同一周数在不同年份的含义不同，可能导致误判。

### 跨年边界映射表

以 2020→2021 年为例（2020 年有 W53）：

| ISO Week 标识 | 语义层日期 | 历史模式日期范围 | 当周模式（周数差） | Default 取值 |
|--------------|-----------|-----------------|-------------------|-------------|
| `2020-W52-1` | 2020-12-21 | 12/21 ~ 12/27 | 距今 N 周 | 语义层 → 2020-12-21 |
| `2020-W53-1` | 2020-12-28 | 12/28 ~ 01/03 | 距今 N-1 周 | 语义层 → 2020-12-28 |
| `2021-W01-1` | 2021-01-04 | 01/04 ~ 01/10 | 距今 N-2 周 | 语义层 → 2021-01-04 |

**关键点：**
- `2020-W53` 和 `2021-W01` **不重叠**：W53 的日期范围是 12/28~01/03，W01 是 01/04~01/10
- 2025-12-31 在 ISO 周历中属于 `2026-W01`（2025 年没有 W53）
- 有 W53 的年份：2020、2026、2032…（该年首周周四所在年拥有 53 周）

## 被跳过样本

当测试用例运行次数不足 `--min-runs` 阈值时，不参与分类统计。被跳过用例的 metadata 输出到 JSON 的 `skipped_tests` 字段。

```json
{
  "skipped_tests": [
    {
      "name": "SomeTest.test_new",
      "file": "tests/test_new.py",
      "team": "frontend",
      "total_runs": 2,
      "min_runs_required": 3,
      "passed": 1,
      "failed": 1,
      "skipped_count": 0,
      "reason": "insufficient_runs",
      "skipped_sample_ids": ["run_001", "run_002"],
      "skip_reason": "Only 2 run(s) collected, minimum 3 required for reliable classification"
    }
  ]
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `skipped_sample_ids` | `string[]` | 该用例参与的 CI run ID 列表，下游可据此回溯具体构建 |
| `skip_reason` | `string` | 人类可读的跳过原因，可直接展示在 dashboard 上 |

下游 dashboard 可据此：
- 通过 `skipped_sample_ids` 追溯哪些 CI 构建包含了该用例
- 通过 `skip_reason` 展示跳过原因，提示团队需要更多 CI 运行
- 区分"未分类"与"分类为稳定"的用例
- 追踪新加入用例的积累进度

## 测试

```bash
python -m unittest test_flake_summary.py -v
```

## 许可证

MIT License
