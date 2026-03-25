# Agent Town `run` 非阻塞异步化设计方案

## 1. 背景

当前仿真执行流程是同步且会阻塞终端交互的。

当前关键行为如下：

- CLI 入口位于 `reverie/backend_server/reverie.py`
- `open_server()` 接收 `run <step-count>` 命令
- `open_server()` 直接同步调用 `self.start_server(int_count)`
- `start_server()` 会一直循环，直到请求的步数全部完成才返回
- 每一个 step 都会对所有 persona 同步执行一次 `persona.move(...)`
- `persona.move(...)` 会串行触发整条认知链：
  - `perceive`
  - `retrieve`
  - `plan`
  - `reflect`
  - `execute`
- 前端通过 `update_environment` 持续轮询，直到 `movement/<step>.json` 出现为止

这个模型实现简单，但存在两个明显问题：

- 后端 shell 在 `run N` 执行期间被完全占用
- 当 LLM 调用耗时很长时，用户几乎看不到明确的运行进度

这个问题在“新 simulation 的首日首轮运行”时尤其明显，因为系统可能在第一次执行时集中生成：

- wake-up hour
- daily plan
- hourly schedule
- task decomposition
- embeddings

这些操作都比较重，而且当前实现是串行执行的。

## 2. 目标

本方案聚焦于一个核心用户目标：

**执行 `run N` 时，不再阻塞后端交互 shell。**

次级目标包括：

- 保持当前 simulation 语义不变
- 保持单个 simulation 内部 step 顺序确定
- 让 CLI 和前端都能看到运行进度
- 第一阶段尽量低风险落地
- 避免一开始就重构整条 persona 认知链

## 3. 非目标

本方案第一阶段**不**尝试解决以下问题：

- 不做全项目 `asyncio` 重构
- 不并行执行所有 persona 的完整 `move()` 流程
- 不引入分布式任务系统
- 不支持多人同时修改同一个 simulation
- 不把前端轮询直接改成 WebSocket 推送

## 4. 为什么不能直接“全部改异步”

当前 simulation 主循环依赖大量共享可变状态：

- `self.maze`
- `self.personas`
- `self.personas_tile`
- movement 文件
- object cleanup 事件

同时它还依赖明确的 step barrier：

- step `k+1` 不能早于 step `k` 完成
- 同一个 step 内所有 persona 应该基于一致的世界状态做决策

如果一开始就把整个 `persona.move()` 对所有 persona 并行化，很容易带来：

- 状态竞争
- 非确定性行为
- 同一步内观测结果不一致
- 非常难排查的记忆写入顺序问题

因此，正确的第一步不是“全量 async”，而是：

**后台执行 + 可视化进度 + 严格保持 step 串行**

## 5. 总体方案

### 5.1 高层思路

在后端 server 进程内部引入一个后台执行层。

当前模型是：

- CLI 收到 `run 10`
- CLI 线程直接同步执行 `start_server(10)`

目标模型是：

- CLI 收到 `run 10`
- CLI 线程把任务提交给后台 simulation worker
- worker 在线程中后台执行这些 step
- CLI 立即返回，用户可以继续输入命令
- 运行状态持续写入共享状态文件

### 5.2 核心原则

第一阶段坚持下面四条：

- 一个 simulation 进程
- 一个 simulation server 只允许一个活动 worker
- 一次只跑一个活动 run job
- step 内部不并发改写世界状态

这意味着：

- simulation 的逻辑语义依旧是串行的
- 改变的是“执行模型”，不是“行为模型”

这样可以在不改变世界规则的前提下，先把用户体验做对。

## 6. 架构概览

### 6.1 新增组件

建议在 `reverie/backend_server/reverie.py` 内部，或者新建辅助模块，加入以下三个概念：

- `SimulationJobManager`
- `SimulationRunJob`
- `SimulationStatusStore`

### 6.2 组件职责

`SimulationJobManager`

- 管理后台 worker 生命周期
- 接受 run 请求
- 拒绝不合法并发请求或按策略排队
- 暴露当前 job 状态
- 接受 stop/cancel 控制信号

`SimulationRunJob`

- 表示一次 `run N` 请求
- 保存如下信息：
  - job id
  - 目标步数
  - 已完成步数
  - simulation code
  - 当前 persona
  - 当前阶段
  - 开始时间 / 结束时间
  - 最近错误

`SimulationStatusStore`

- 把运行状态写入磁盘
- 供 CLI 和 Django 前端读取
- 保证覆盖写入安全、状态结构稳定

## 7. 执行模型

### 7.1 Worker 模式

第一阶段建议使用**后台线程**，而不是进程池。

原因：

- 最容易与现有 `ReverieServer` 对象整合
- 不需要处理多进程序列化 `maze/persona` 对象
- 不需要大规模改动现有状态访问模型
- 适合快速验证“非阻塞 run”的目标

关键约束：

- worker 线程是唯一允许修改 simulation 状态的执行线程
- CLI 主线程只读状态、发控制命令，不直接改仿真核心对象

### 7.2 Job 生命周期

建议定义如下状态：

- `idle`
- `queued`
- `running`
- `cancelling`
- `completed`
- `failed`
- `stopped`

### 7.3 CLI 行为变化

当前：

- `run 10` 会阻塞

目标：

- `run 10` 启动后台 job 后立即返回

建议新增命令：

- `status`
- `jobs`
- `stop`
- `run 10`
- `run 10 --wait` 可选兼容模式

推荐语义：

- `run 10`
  - 如果当前空闲：创建并启动后台 job
  - 如果当前已有 job 在跑：给出清晰提示，拒绝或要求显式排队
- `status`
  - 打印当前 job 进度
- `stop`
  - 请求后台任务在安全边界停止

### 7.4 安全停止策略

不建议在任意时刻强制中断：

- 正在执行的 LLM 请求
- 正在写入 movement 文件的代码
- 正在修改 world state 的中间阶段

第一阶段推荐的停止语义是：

**`stop` = 当前 step 完成后停止**

这样最稳妥，不会留下半提交状态。

## 8. 进度模型

### 8.1 为什么必须做进度可视化

即使把任务放到后台运行，如果用户完全看不到进度，仍然会误以为系统卡死。

所以“非阻塞”必须配套“可观测”。

### 8.2 推荐暴露的状态字段

建议状态结构至少包含：

```json
{
  "simulation": {
    "sim_code": "local-20260325-181719",
    "fork_sim_code": "base_the_ville_isabella_maria_klaus"
  },
  "job": {
    "job_id": "run-20260325-181800-001",
    "state": "running",
    "requested_steps": 10,
    "completed_steps": 2,
    "current_world_step": 2,
    "started_at": "2026-03-25T18:18:00+08:00",
    "updated_at": "2026-03-25T18:18:34+08:00"
  },
  "progress": {
    "current_persona": "Isabella Rodriguez",
    "current_stage": "plan.task_decomp",
    "current_prompt_type": "task_decomp",
    "llm_requests_completed": 17,
    "llm_requests_failed": 0
  },
  "last_error": null
}
```

### 8.3 状态文件位置

建议第一阶段直接写到：

- `environment/frontend_server/temp_storage/simulation_status.json`

原因：

- 项目当前已经用 `temp_storage` 做前后端协调
- Django 前端读取方便
- 不需要先引入数据库

后续如果需要扩展成多 simulation 并行，可再改成：

- `temp_storage/simulation_status/<sim_code>.json`

第一阶段先用单文件就足够。

## 9. 前端集成

### 9.1 当前前端行为

当前 simulation 页逻辑是：

- 通过 `process_environment` 把当前位置快照传给后端
- 通过 `update_environment` 轮询 movement 文件
- 如果当前 step 的 movement 还没生成，就继续等待

### 9.2 建议新增接口

新增一个轻量接口：

- `/simulation_status/`

这个接口只负责返回当前后台 job 状态，例如：

- 当前 job state
- 当前 step 进度
- 当前 persona / stage
- 最近错误

### 9.3 前端页面展示建议

在 `simulator_home` 页面增加一个小型状态面板：

- `Simulation: running`
- `Step progress: 2 / 10`
- `Current persona: Isabella Rodriguez`
- `Stage: plan.task_decomp`
- `Last update: 18:18:34`

这一步是纯增强，不需要替换现有 movement 轮询机制。

## 10. 向后兼容

### 10.1 CLI 兼容

我们应保留用户现有的命令心智：

- `run 10` 仍然表示“推进 10 个 step”

变化仅在于：

- 默认变成后台执行

如果后续需要，可以保留一个兼容模式：

- `run 10 --wait`

供调试脚本或回归场景使用。

### 10.2 前后端文件协议兼容

第一阶段不改掉现有文件交互协议：

- 前端写 `environment/<step>.json`
- 后端写 `movement/<step>.json`

这样可以避免前端主逻辑大面积返工。

## 11. 详细设计

### 11.1 `ReverieServer` 建议新增字段

建议增加：

```python
self.job_manager
self.status_file_path
self.current_job_id
self.stop_requested
```

### 11.2 状态更新钩子

建议新增统一方法：

```python
def update_runtime_status(self, **fields): ...
```

在以下时机调用：

- job start
- step start
- persona start
- 阶段切换
- movement 文件写出
- step 完成
- job 完成
- 异常路径

### 11.3 阶段命名建议

建议统一用下面这些 stage 名称：

- `step.begin`
- `persona.perceive`
- `persona.retrieve`
- `persona.plan`
- `persona.plan.daily_plan`
- `persona.plan.hourly_schedule`
- `persona.plan.task_decomp`
- `persona.reflect`
- `persona.execute`
- `step.commit`
- `step.complete`

这样既能给用户看，也能给日志排障用。

### 11.4 Worker 主循环形态

推荐的伪流程：

```text
CLI 主线程:
  解析 "run 10"
  如果 manager 空闲:
    创建 job
    启动 worker 线程
    打印 "Job started"
  否则:
    提示 simulation 正在运行

Worker 线程:
  将 job 标记为 running
  对每一个请求 step:
    若收到 stop 请求: break
    等待 environment/<step>.json
    顺序处理所有 personas
    写 movement/<step>.json
    更新步数进度
  写入最终状态
```

### 11.5 等待状态区分

当前 `start_server()` 用 `time.sleep(self.server_sleep)` 做轮询等待。

第一阶段可以保留这个实现，但建议把等待原因显式写进状态：

- `waiting_for_frontend_environment`
- `running_persona_logic`
- `waiting_for_llm`

这样用户就能区分：

- 是前端环境文件还没写到
- 还是后端正在算
- 还是正在等待模型接口返回

## 12. 并发边界

### 12.1 第一阶段必须保持串行的部分

以下内容在 phase 1 中必须继续串行：

- step 顺序
- movement commit
- maze 修改
- personas_tile 修改
- object cleanup

### 12.2 后续可以考虑并发的部分

后续可以评估的并发点：

- 不同 persona 的首日 daily plan 生成
- 相互独立的 prompt 调用
- 独立 embedding 请求

但是前提是：

- 后台 job 模型已经稳定
- 进度状态已可见
- 共享状态边界已经明确

## 13. 失败处理

### 13.1 需要覆盖的错误类型

至少需要明确处理：

- LLM 请求错误
- parse / validate 错误
- 文件 IO 错误
- persona pipeline 未知异常
- 前端环境文件长时间未到达

### 13.2 Job 失败后的行为

当 job 失败时，建议：

- job 状态标记为 `failed`
- 将最近错误写入状态文件
- traceback 继续进入 `backend.log`
- shell 立即恢复可用

CLI 提示建议像这样：

- `Job failed at step 2, persona Isabella Rodriguez, stage plan.task_decomp`

### 13.3 超时策略

第一阶段不建议对长时间 LLM 任务做激进超时控制。

但必须至少区分：

- `running`
- `waiting_for_llm`
- `waiting_for_frontend`

仅这一点就能显著提升可用性。

## 14. 分阶段落地计划

### Phase A：后台 run 执行

范围：

- 引入 job manager
- `run N` 改为后台线程执行
- 增加 `status` 和 `stop`
- 写入 `simulation_status.json`

预期收益：

- shell 不再被 `run N` 阻塞

风险：

- 低

### Phase B：前端状态可视化

范围：

- 增加 Django `simulation_status` 接口
- 在 simulator 页面增加简易状态面板

预期收益：

- 用户能明确看到系统正在前进

风险：

- 低

### Phase C：结构化阶段埋点

范围：

- 在 persona/stage/prompt 级别持续更新状态
- 提高 backend.log 的进度粒度

预期收益：

- 排障效率显著提升
- 用户更容易判断是否是真卡死

风险：

- 低

### Phase D：受控并发的性能优化

范围：

- 只对独立 LLM 任务做线程池并发
- 保持 step barrier

预期收益：

- 总运行时间下降

风险：

- 中

## 15. 推荐实现顺序

建议按这个顺序实现：

1. 新增状态结构和状态写文件工具
2. 新增后台 job manager
3. 把 `run N` 改成后台执行
4. 增加 `status` / `stop`
5. 增加 Django 状态接口
6. 增加前端状态面板
7. 最后再评估受控并发的 LLM 提速

## 16. 需要确认的开放问题

在正式实现前，有几个问题需要明确：

1. `run N` 是否默认后台执行，还是先通过显式参数开启？
2. 当前版本是否只允许单一活动 job，还是要支持 queue？
3. `stop` 的语义是“当前 step 完成后停止”还是“当前 persona 完成后停止”？
4. 状态是否只写 `temp_storage`，还是也同步写成结构化日志？
5. prompt 级别的细节要不要对前端用户可见，还是仅保留在日志里？

## 17. 推荐结论

推荐的下一步非常明确：

**先实现 Phase A + Phase B，不要先动全局并发。**

也就是：

- `run` 后台化
- shell 可执行 `status`
- 写 `simulation_status.json`
- 前端增加状态接口和状态展示

这样可以在不破坏 simulation 行为语义的前提下，优先解决“执行 run 时系统整体像卡死”的核心体验问题。

只有在这一层稳定之后，再考虑真正的并发提速。

