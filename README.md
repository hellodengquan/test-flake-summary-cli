# Test Flake Summary CLI

不稳定测试（Flaky Test）汇总工具，用于从持续集成系统中拉取测试结果，识别和分析偶发抖动的测试用例。

## 功能特性

- 支持 JUnit XML 和 JSON 格式的测试结果
- HTTP/HTTPS 远程拉取，支持多种认证方式
- 智能分类：稳定通过、偶发抖动、连续失败
- 按团队和文件分组统计
- 可配置的权重评分算法
- 时间窗口筛选历史数据
- 文本表格和 JSON 两种输出格式

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
- `schema_version`: 新增，标识输出结构版本
- `tool_version`: 新增，标识工具版本
- `fail_ratio_pct`: 新增，失败百分比（整数）
- `total_runs`: 每个用例的总运行次数字段

**变更说明：**
- `recent_consecutive_failures` 字段语义变更：从"连续失败次数"改为"失败比例百分比"，保留字段名以兼容旧代码
- 运行次数不足 `min-runs` 的用例不再出现在输出中

**迁移指南：**
1. 检查 `schema_version` 字段以确定兼容性
2. 若使用 `recent_consecutive_failures`，请迁移到使用 `fail_ratio_pct` 字段（语义相同）
3. 若依赖不足 min-runs 的用例数据，需调整逻辑或降低 `--min-runs` 参数

#### v1.0.0

初始版本，包含基本的分类和统计功能。

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

**注意：** 三个权重值之和必须等于 1.0，否则会自动归一化。

## Token 自动刷新

当使用 Bearer Token 认证时，支持配置自动刷新机制以避免 token 过期导致的失败。

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

**刷新机制：**
- 当请求返回 401 或 403 时，自动调用刷新函数
- 刷新成功后重试请求
- 可配置最大刷新重试次数

## 测试

```bash
python -m unittest test_flake_summary.py -v
```

## 许可证

MIT License
