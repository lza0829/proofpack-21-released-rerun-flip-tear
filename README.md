# 05-proofpack（核证匣）

Proofpack — 举证放行：采样抽取 → 证据打包 → 校验清单 → 放行/驳回闭环。

与 Feedstitch（多源归并）、Batchgate（作业编排）、Syncledger（双端对账）、Changecast（CDC 投影）主链路不同。夹具全本地，不连活库。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5500 |
| API | http://localhost:10500 |

## 主链

选举证对象 → 按固定种子采样 → 生成证据包（含指纹）→ 跑基础校验清单 → 放行绑定具体运行号，否则驳回并留痕

## 校验运行与放行绑定

每次跑校验清单都落一条**独立运行记录**，永不覆盖：

- 运行号（`CR-<包号>-<序>`）、包号、规则版本、各项结果、通过/失败计数、是否全过、执行时间
- 同一包复跑生成新运行号；旧运行及其结果保留可查

放行（pass）必须绑定一个具体运行号（`run_id` 或 `run_no`），并在留痕中写明运行号与当时的规则版本。以下情形一律拒绝放行：

- 未绑定运行号，或绑定的运行不存在
- 运行不属于该证据包
- 运行未全部通过
- 运行之后规则版本已晋升（历史运行作废）
- 策略为 `latest_only` 时，所绑运行不是该包最近一次运行

驳回（reject）不必绑定运行，但必须留原因；若提供运行号则校验其存在且属于该包。

放行可用运行策略（`/api/settings/release-policy`）二选一：

| 策略 | 含义 |
| --- | --- |
| `latest_only`（默认） | 仅允许绑定该包最近一次且全过的运行 |
| `any_passed` | 允许绑定该包历史上任一次全过运行；留痕写明运行号与当时规则版本；该运行之后若规则版本已晋升则作废不可再绑 |

`GET /api/consistency` 做三方互证：运行列表、放行留痕中的运行号、包状态；发现不一致即列出。

## 种子举证对象

- 门店日结抽检
- 渠道结算抽检
- 价目变更核证

底座内置基础校验：条数一致、键唯一、必填非空。影子试跑 / 规则版本表空挂，深逻辑留给后题。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 本地后端

```bash
cd backend
pip install -r requirements.txt
set DATA_DIR=%TEMP%\proofpack-data
uvicorn app.main:app --host 127.0.0.1 --port 10500
```
