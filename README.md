# Test Flake Summary CLI

不稳定测试（Flaky Test）汇总工具，用于从持续集成系统中拉取测试结果，识别和分析偶发抖动的测试用例。

## 功能特性

- 支持 JUnit XML 和 JSON 格式的测试结果
- HTTP/HTTPS 远程拉取，支持多种认证方式及 Token 自动刷新
- 智能分类：稳定通过、偶发抖动、连续失败
- 按团队和文件分组统计
- 可配置的权重评分算法（容差可调）
- 时间窗口筛选历史数据（兼容跨年 ISO week）
- 文本表格和 JSON 两种输出格式
- 被跳过样本 metadata 输出，方便下游 dashboard

## 安装

要求 Python 3.8+，仅使用标准库，无需额外依赖。

```bash
# 克隆后直接使用
python -m flake_summary --help
```

## 快速开始

```bash
# 从本地目录分析
python -m flake_summary --dir sample_data/

# 从远程 URL 分析
python -m flake_summary --files https://ci.example.com/results/run.xml --bearer-token YOUR_TOKEN

# JSON 格式输出
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

JSON 输出包含两个版本字段：

```json
{
  "schema_version": "1.1.0",
  "tool_version": "1.0.0",
  "...": "..."
}
```

- `schema_version`: JSON 输出结构的版本号，结构变更时递增
- `tool_version`: 工具本身的版本号

### 版本历史与迁移指南

#### v1.1.0（当前）

**新增字段：**
- `schema_version`: 标识输出结构版本
- `tool_version`: 标识工具版本
- `fail_ratio_pct`: 失败百分比（整数）
- `total_runs`: 每个用例的总运行次数字段
- `skipped_tests`: 被跳过用例的 metadata 列表，包含 name / file / team / total_runs / min_runs_required / passed / failed / skipped_count / reason

**变更说明：**
- `recent_consecutive_failures` 字段语义变更：从"连续失败次数"改为"失败比例百分比"，保留字段名以兼容旧代码
- 运行次数不足 `min-runs` 的用例不再出现在 `classified_tests` 中，改为输出到 `skipped_tests`

**从 v1.0.0 升级到 v1.1.0：**
1. 检查 `schema_version` 字段以确定兼容性
2. 若使用 `recent_consecutive_failures`，请迁移到使用 `fail_ratio_pct` 字段（语义相同）
3. 若依赖不足 min-runs 的用例数据，改为从 `skipped_tests` 字段读取
4. 下游 dashboard 可通过 `skipped_tests` 展示样本不足的用例及原因

#### v1.0.0

初始版本，包含基本的分类和统计功能。

### Schema 双向兼容路径

#### v1.1.0 → v1.0.0 降级（Downgrade）

当 v1.1.0 的 JSON 输出需要被只支持 v1.0.0 的下游系统消费时：

| v1.1.0 字段 | v1.0.0 处理方式 |
|-------------|----------------|
| `schema_version` | 忽略（v1.0.0 无此字段） |
| `tool_version` | 忽略 |
| `fail_ratio_pct` | 映射回 `recent_consecutive_failures`，值不变（整数百分比） |
| `skipped_tests` | 忽略，或将 reason=insufficient_runs 的条目按原逻辑回填到 `classified_tests`，category 设为 `flaky`（如有失败）或 `stable_pass` |
| `classified_tests[].total_runs` | 可从 passed + failed + skipped 推算 |

降级脚本示例：

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
    data.pop("schema_version", None)
    data.pop("tool_version", None)
    data.pop("skipped_tests", None)
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

升级脚本示例：

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

**归一化与容差：** 三个权重值之和应在 1.0 的容差范围内。默认容差为 0.001，可通过 `weight_tolerance` 参数调整。超出容差时自动归一化（默认行为），或抛出错误。

```python
from flake_summary.classifier import WeightsConfig, TestCaseClassifier

# 自定义容差（更宽松）
weights = WeightsConfig(fail_rate_weight=0.5, transition_weight=0.35, recency_weight=0.16)
classifier = TestCaseClassifier(weights=weights, weight_tolerance=0.02)
```

## Token 自动刷新

当使用 Bearer Token 认证时，支持配置自动刷新机制以避免 token 过期导致的失败。

**容错机制：** 如果刷新函数本身抛出异常，系统会自动退回原 token 继续使用，避免整个任务因刷新失败而中断。

使用方式（Python API）：

```python
from flake_summary.parser import HTTPConfig, TestResultParser

def refresh_token():
    # 调用你的 token 刷新接口
    return "new_token_value"

config = HTTPConfig(
    bearer_token="initial_token",
    token_refresh_fn=refresh_token,
    max_refresh_retries=1,
)

result = TestResultParser.parse_file("https://ci.example.com/run.xml", config)
```

**刷新流程：**
1. 请求返回 401/403 时，尝试调用 `token_refresh_fn` 获取新 token
2. 刷新成功 → 用新 token 重试请求
3. 刷新失败（异常）→ 退回原 token 继续尝试，避免任务全失败
4. 超过最大重试次数 → 抛出原始 HTTPError

## 时间窗口与跨年 ISO Week 处理

`--time-window` 参数支持多种时间戳格式，包括 ISO week 格式（如 `2025-W53-1`）。在跨年场景下，ISO week 边界需要特别注意：

### 2025-W53 与 2026-W01 边界的三种取值场景

ISO 8601 周历中，年末年初可能出现 W53（部分年份）和 W01 的边界重叠。本工具提供三种语义解读：

#### 1. 语义层（Semantic / ISO 标准解读）

- `2025-W53-1` = 2025 年最后一周的周一（2025-12-29）
- `2026-W01-1` = 2026 年第一周的周一（2026-01-05）
- 两者不重叠，严格按 ISO 8601 定义

**适用场景：** CI 系统输出的时间戳本身符合 ISO 8601 周格式，需要精确语义匹配。

本工具默认使用此模式：`datetime.fromisocalendar(year, week, day)` 进行解析。

#### 2. 历史（Historical / 日历映射）

- `2025-W53` 映射到该周的实际日期范围（2025-12-29 ~ 2026-01-04）
- `2026-W01` 映射到（2026-01-05 ~ 2026-01-11）
- 时间窗口过滤基于实际日期计算

**适用场景：** 需要将 ISO week 转换为精确日期范围后进行时间窗口过滤。本工具在解析 ISO week 格式后自动转换为此模式进行过滤。

#### 3. 当周（Current Week / 周数差值）

- 计算当前周与目标周的周数差值
- `2025-W53` 距 `2026-W25` 约 25 周前
- 不考虑具体日期，仅按周数差判断

**适用场景：** 某些 CI 系统只用周数标识构建，不关心具体日期。

### 跨年处理注意事项

- 并非所有年份都有 W53：只有当年首周的周四所在的年有 53 周时才存在（如 2020、2025、2031 年有 W53，2021、2026 年无 W53）
- 本工具解析 `YYYY-Www-d` 格式时，使用 Python `datetime.fromisocalendar()` 自动处理无效周数（抛出 ValueError 后回退到其他格式）
- 如果 CI 系统输出的是标准 ISO 日期时间格式，无需关心 ISO week 边界问题

## 被跳过样本

当测试用例的运行次数不足 `--min-runs` 阈值时，该用例会被跳过，不参与分类统计。被跳过的用例 metadata 会输出到 JSON 的 `skipped_tests` 字段中，方便下游 dashboard 展示。

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
      "reason": "insufficient_runs"
    }
  ]
}
```

下游 dashboard 可据此：
- 提示团队某用例样本不足，需要更多 CI 运行
- 区分"未分类"与"分类为稳定"的用例
- 追踪新加入用例的积累进度

## 测试

```bash
python -m unittest test_flake_summary.py -v
```

## 许可证

MIT License
