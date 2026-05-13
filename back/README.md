# SDT2.0-Hourly - IKEA China Store Hourly Data Pipeline

> 自动化采集宜家中国门店实时销售与客流数据，下载 JSON 原始文件并生成去重后的 CSV 汇总报告。

---

## 目录

| 模块 | 说明 |
|------|------|
| [需求背景](#需求背景) | 业务痛点与目标 |
| [整体架构](#整体架构) | 数据流转与模块关系 |
| [文件清单](#文件清单) | 项目文件结构说明 |
| [核心功能](#核心功能) | 四大功能模块详解 |
| [快速上手](#快速上手) | 安装、配置与运行 |
| [打包发布](#打包发布) | PyInstaller 打包为 EXE |
| [数据字段](#数据字段) | CSV 输出字段约定 |
| [更新日志](#更新日志) | 历史变更汇总 |

---

## 需求背景

宜家中国各门店每小时会产生销售概览（Sales Summary）和客流统计（Traffic）数据，数据托管在内网 API 平台（spica-tianji）。业务侧需要：

1. **定时采集** — 每小时自动从 API 拉取 32 家门店的 JSON 数据
2. **数据汇聚** — 将分散的 JSON 文件合并为一张可读的 CSV 汇总表
3. **去重增量** — 重复采集的数据不重复写入，只保留最新一份
4. **格式转换** — 自动将 K/M 后缀数值转为千分位格式，将 IndexToGoal / CVR 字段转为百分比

---

## 整体架构

```
 ┌─────────────┐      HTTP GET       ┌──────────────────┐
 │  spica-tianji│ ──────────────────► │  main_app.py     │
 │  Internal API│                     │                  │
 └─────────────┘                     │  1) 下载 JSON     │
                                     │  2) 合并+清洗     │
           ┌─────────────────────────┤  3) 导出 CSV      │
           │                         │  4) 归档历史      │
           ▼                         └──────────────────┘
   output/*.json                          report/report.csv
   output/history/*.json                       │
                                               ▼
                                        供 Power BI / Excel 分析
```

### 数据流转

| 阶段 | 输入 | 处理 | 输出 |
|------|------|------|------|
| ① 下载 | API Key 列表 | 遍历每家店发 2 个 API 请求（Summary + Traffic） | `output/{store}_{no}_{timestamp}.json` |
| ② 解析 | JSON 文件 | 展平嵌套字典、数值格式化、从文件名提取元数据 | 内存中的 Row 字典 |
| ③ 去重 | 已有 CSV + 新 Rows | 按 (StoreName, StoreNo, Date, Time) 去重，保留 Seq 最大者 | 去重后行列表 |
| ④ 写入 | 去重后行列表 | 重新编号 Seq，按 Date/Time/StoreName/StoreNo 排序 | `report/report.csv` |
| ⑤ 归档 | 已处理的 JSON | 移动到 `output/history/` | `output/history/*.json` |

---

## 文件清单

```
SDT2.0-Hourly/
├── main_app.py               ← 主程序（合并后的入口，包含下载+CSV导出全部逻辑）
├── rts_app.py                ← 独立版 RTS 下载脚本（已并入 main_app.py，保留参考）
├── json_to_csv.py            ← 独立版 JSON→CSV 转换脚本（已并入 main_app.py，保留参考）
├── main_app.spec             ← PyInstaller 打包配置文件
├── my_icon.ico               ← 打包 EXE 使用的应用图标
├── config.json               ← 路径配置文件（运行时自动生成 / 用户手动配置）
├── package.md                ← 开发更新日志（内部文档）
│
├── output/                   ← JSON 数据输出目录（运行时创建）
│   └── history/              ← 已处理的 JSON 归档目录
│
├── report/                   ← CSV 报告输出目录（运行时创建）
│   └── report.csv            ← 最终汇总报表
│
├── logs/                     ← 运行日志目录（运行时创建）
│   └── app_YYYYMMDD_HHMMSS.log
│
├── build/                    ← PyInstaller 构建缓存
├── dist/                     ← PyInstaller 输出目录
└── .venv/                    ← Python 虚拟环境
```

---

## 核心功能

### 1. 店铺交互式管理 (CRUD)

程序启动时显示 10 秒倒计时，按 `Enter` 可进入管理模式：

| 操作 | 说明 |
|------|------|
| **查看** | 列出全部 32 家门店的名称、店号、API Key |
| **添加** | 新增门店（输入店名 / 店号 / Key） |
| **修改** | 按序号修改任一门店信息 |
| **删除** | 按序号删除门店（需 y 确认） |
| **退出** | 保存更改并继续执行下载任务 |

> 修改后的门店列表会立即重新构建 `STORES` 字典，确保本次任务使用最新数据。

**实现方式**：

- 使用 `msvcrt.kbhit()` 非阻塞键盘检测（仅 Windows 有效）
- 超时 10 秒自动跳过，不阻塞无人值守运行

### 2. JSON 数据下载

遍历门店列表，每家店发起 **2 个 API 请求**：

| API | 端点 | 数据内容 |
|-----|------|----------|
| Summary | `/realtime/anonymity-report/store/sales/summary` | 销售额、目标、索引等经营指标 |
| Traffic | `/realtime/anonymity-report/store/sales/list` | `totalStoreTraffic` 客流总数 |

**数据处理**：

- 合并 Summary + Traffic 数据到同一个 JSON 对象
- 删除 `foodSales` 下 6 个无值字段（`offlineSales`, `offlineGoal`, `offlineIndexToGoal`, `onlineSales`, `onlineGoal`, `onlineIndexToGoal`）
- 文件名格式：`{店名}_{店号}_{YYYYMMDD-HHMM}.json`
- 10 秒超时保护，单个门店失败不影响其他门店

### 3. CSV 导出与去重

将 `output/` 目录下所有 JSON 文件解析并汇总为一张 CSV 表：

| 步骤 | 方法 |
|------|------|
| 文件名解析 | `parse_filename()` — 从文件名提取 StoreName、StoreNo、Date、Time |
| 字典展平 | `flatten_data()` — 嵌套字典转为 `key_subkey` 扁平格式 |
| 数值转换 | `transform_value()` — 按字段规则格式化数值 |
| 去重策略 | 按 `(StoreName, StoreNo, Date, Time)` 四元组去重，保留 Seq 最大的行 |
| 排序输出 | 按 Date → Time → StoreName → StoreNo 排序，重新分配 Seq 序号 |

**数值转换规则 (`transform_value`)**：

| 条件 | 转换方式 | 示例 |
|------|----------|------|
| Key 包含 `IndexToGoal` 或 `CVR` | 浮点数 × 100 转为百分比 | `0.85` → `85.0%` |
| 值以 `K` 结尾 | 去掉 K，× 1000，千分位格式 | `12.5K` → `12,500` |
| 值以 `M` 结尾 | 去掉 M，× 1,000,000，千分位格式 | `3.2M` → `3,200,000` |

### 4. 配置持久化与日志

| 功能 | 实现 |
|------|------|
| 路径记忆 | 首次运行时用户输入 JSON 输出路径和 CSV 报告路径，保存到 `config.json`，后续运行自动读取 |
| 配置文件位置 | Windows: `%APPDATA%\SDT2.0-Hourly\config.json`（解决打包后权限问题） |
| 日志记录 | 使用 Python `logging` 模块，同时输出到控制台和 `logs/app_YYYYMMDD_HHMMSS.log` |

---

## 快速上手

### 环境要求

- **Python**: 3.9+
- **OS**: Windows（倒计时功能依赖 `msvcrt`，Linux/macOS 可运行但跳过交互等待）
- **依赖**: `requests`（`pip install requests`）

### 安装与运行

```bash
# 1. 进入项目目录
cd SDT2.0-Hourly

# 2. 创建虚拟环境（可选）
python -m venv .venv
source .venv/Scripts/activate   # Windows
# source .venv/bin/activate     # Linux/macOS

# 3. 安装依赖
pip install requests

# 4. 运行主程序
python main_app.py
```

### 首次运行流程

```
1. 程序启动 → 自动配置日志
2. 检查 config.json → 若不存在，提示输入 JSON 输出路径和 CSV 报告路径
3. 10 秒倒计时 → 按 Enter 进入店铺管理（可选）
4. 自动下载所有门店 JSON 数据到 output/
5. 10 秒倒计时 → 按 Enter 可取消 CSV 导出（默认自动执行）
6. 导出 CSV 到 report/report.csv，JSON 移至 output/history/
```

---

## 打包发布

使用 PyInstaller 将主程序打包为独立可执行文件：

```bash
# 安装 PyInstaller
pip install pyinstaller

# 打包（使用项目提供的 spec 文件）
pyinstaller main_app.spec
```

打包产物：`dist/main_app.exe`

| 配置项 | 值 |
|--------|-----|
| 入口文件 | `main_app.py` |
| 输出名称 | `main_app.exe` |
| 应用图标 | `my_icon.ico` |
| 压缩 | UPX 启用 |
| 模式 | 单文件 / 控制台模式 |

---

## 数据字段

CSV 报告的固定列：

| 列名 | 类型 | 说明 |
|------|------|------|
| `Seq` | int | 自增序号（去重后重新编号） |
| `StoreName` | string | 门店名称（如 "天津店"） |
| `StoreNo` | string | 门店编号（如 "058"） |
| `Date` | string | 采集日期 `yyyy/mm/dd` |
| `Time` | string | 采集时间 `hh:00` |

动态列（来自 API JSON 数据，经 `flatten_data` 展平后生成）：

- `salesSummary_totalSales` — 总销售额
- `salesSummary_goal` — 销售目标
- `salesSummary_indexToGoal` — 目标达成指数
- `foodSales_total` — 餐饮销售额
- `foodSales_indexToGoal` — 餐饮目标达成（转为百分比）
- `totalStoreTraffic` — 总客流数
- `CVR_*` — 转化率相关字段（转为百分比）
- ... 以及其他随 API 返回动态变化的字段

---

## 更新日志

### 2026-04-01
- 修复 `transform_value` 中 IndexToGoal/CVR 百分比转换的条件语法错误

### 2026-03-31
- 修复 `StoreNo` 类型不一致（int/string 混用）导致的排序 TypeError
- 新增动态百分比转换：包含 `IndexToGoal` 或 `CVR` 的字段自动转为百分比格式
- 优化 `get_existing_data` 中 Seq 字段的类型处理顺序

### 2026-03-23
- 配置文件路径改为 `%APPDATA%\SDT2.0-Hourly\`（解决打包后写权限问题）
- 新增 Traffic 数据 API 请求（`totalStoreTraffic`）
- 脚本合并：`rts_app.py` + `json_to_csv.py` → `main_app.py`
- 使用 PyInstaller 打包为 `main_app.exe`，添加自定义图标

### 2026-03-16
- 新增日志记录功能（logging 双输出：控制台 + 文件）
- 统一路径配置：优先读取 config.json，否则提示用户输入

### 2026-03-15
- 店铺管理模式下 print 输出与 logging 兼容
- 删除 foodSales 下 6 个 null 字段

### 2026-03-13 ~ 03-14
- 项目初始化：RTS 数据下载、JSON 转 CSV、店铺 CRUD 管理

---

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.9+ | 核心语言 |
| requests | HTTP API 请求 |
| logging | 双通道日志（控制台 + 文件） |
| csv / json / pathlib | 数据处理与文件操作 |
| msvcrt | Windows 非阻塞键盘检测 |
| PyInstaller | 打包为独立 EXE |
