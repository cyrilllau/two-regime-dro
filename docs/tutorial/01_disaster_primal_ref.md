# 01. Disaster Primal Reference LP

## 1. 这一阶段解决什么问题

这一阶段的任务是把论文里的 disaster-stage recourse，固定成一个**可审计的 LP 真值源**。

更具体地说，它解的是：

- fixed first-stage plan `x`
- fixed outage vector `delta`
- fixed disaster sample `b`

下的灾难阶段 primal LP。

所以它不是：

- 全两阶段问题
- master problem
- separation problem
- Benders driver

它只是整条 reference 数学链的第一个、也是最基础的“真值块”。

## 2. 它在整条链路中的位置

它的位置是：

`CanonicalInstance -> disaster_primal_ref -> canonicalize/dualize -> exact oracle / paper dual / separation / Benders`

如果这个 primal 不对，后面所有 dual、cut、separation、Benders 都会一起漂。

## 3. 对应的核心公式 / equation groups

对应 `docs/spec/02_equation_registry.md` 里的 Eq. (26)–(32)：

- Eq. (26): disaster objective
- Eq. (27): active-power balance
- Eq. (28): regional V2G assignment limits
- Eq. (29): station discharge capacity limits
- Eq. (30): assignment-siting linkage
- Eq. (31): load shedding bounds
- Eq. (32): outage-dependent line capacity

代码归属：

- `src/reference/disaster_primal_ref.py`

## 4. 对应的核心代码文件和主要 dataclass / builder / solver

核心 dataclass：

- `FixedFirstStagePlan`
- `FixedOutageVector`
- `DisasterPrimalReferenceModel`
- `DisasterPrimalSolution`

核心入口：

- `build_fixed_first_stage_plan(...)`
- `build_fixed_outage_vector(...)`
- `build_disaster_primal_reference_model(...)`
- `solve_disaster_primal_reference(...)`

这里最值得先看的不是 Gurobi 细节，而是三个输入对象：

- `CanonicalInstance`
- `FixedFirstStagePlan`
- `FixedOutageVector`

因为这三个对象决定了“这个 primal 到底在解决哪一个固定子问题”。

## 5. 输入是什么

### 输入 1: `CanonicalInstance`

这是从 `src/instance/` 层来的统一语义对象。

它已经把：

- buses
- line ordering
- regions
- loaded disaster scenarios
- runtime parameters
- topology

都固定好了。

### 输入 2: `FixedFirstStagePlan`

它包含：

- `z_by_bus`
- `n_sl_by_bus`
- `n_fa_by_bus`

在进入 primal 前就被 validate：

- bus id 合法
- `z` 是 binary
- charger 数量非负
- `z[n] = 0` 时不能偷偷装 charger

### 输入 3: `FixedOutageVector`

它包含：

- `values`
- `by_line_id`

并且按 canonical line ordering 对齐。

这里的关键点是：

- outage 不是连续变量
- 不是 separation 在优化的 `delta`
- 它在这一层已经是固定 realization

### 输入 4: explicit `critical_buses`

这一层必须有 disaster-objective-ready 的 `critical_buses`。

它会通过：

- `require_explicit_critical_buses(...)`

来卡死。

repo 明确禁止：

- 从 `ambig.w` 推 `critical_buses`

## 6. 输出是什么

输出是一个 solved LP 结果：

- objective value
- load shedding
- slow / fast V2G discharge
- line flow

结构化保存于：

- `DisasterPrimalSolution`

这意味着后面的 dual 层可以把它当成：

- primal objective 真值
- primal feasibility 真值
- named row residual 真值

## 7. 这个阶段的结果如何被下一阶段使用

它主要被三类后续阶段消费：

### 1. `lp_canonicalizer.py`

从这个 primal model 机械读取：

- objective coefficients
- row coefficients
- row senses

### 2. `disaster_dual_auto.py`

不手写 paper dual，而是从 canonical primal 自动导出一个机械 dual，用来做数学对照。

### 3. `disaster_exact_oracle.py`

在 Round 10 里，这个 primal 又被拿来做 independent disaster exact oracle，故意绕开 paper dual chain，作为额外真值源。

## 8. 对应 tests 在验证什么

最核心的 test 是：

- `tests/oracle/test_disaster_primal_ref.py`

它用几个 tiny fixture 验证：

- zero-demand
- shortage
- critical priority
- failed line

还会检查：

- LP dump 能写出来
- residual report 中 Eq. (27) 和 failed-line checks 都是干净的

integration 侧还有：

- `tests/integration/test_disaster_primal_runtime_fixture.py`

它证明这个 reference primal 能吃 canonical runtime fixture，而不是只会跑 toy。

## 9. 对应 round report 里最关键的结论是什么

对应：

- `docs/reports/round_02_report.md`

最关键的结论有三条：

### 结论 1

Eq. (26)–(32) 全部被落成了固定 `(x, delta, b)` 的 active-power-only reference LP。

### 结论 2

toy cases 的行为是可解释的：

- `zero-demand` -> objective `0.0`
- `shortage` -> objective `70.0`
- `critical_priority` -> objective `30.0`
- `failed_line` -> objective `20.0`

这些不是随机数，而是每个约束组是否按论文语义工作的证据。

### 结论 3

runtime fixture 审计结果干净：

- objective `76273.74000000002`
- max bound violation `0.0`
- max Eq. (27) residual `0.0`
- max failed-line flow violation `0.0`

## 具体结果：toy cases 在告诉你什么

### `shortage` case

Round 02 report 里的解释是：

- failed line 把负荷隔离
- slow V2G 只能提供 `3`
- 还剩 `7` 必须 shed
- 所以 objective = `7 * 10 = 70`

这类 case 的价值在于：

- 不是只看 solver status
- 而是用手算能对上的业务语义确认 Eq. (28)–(31) 没写偏

### `critical_priority` case

结果：

- critical bus `2` 不 shed
- noncritical bus `3` shed `3.0`
- objective `30.0`

这说明 disaster objective 里 `CLS_n` 的 critical / noncritical 权重真的进入了模型，而不是只停留在配置里。

## 10. 读代码建议：先看哪里，再看哪里

建议顺序：

1. 先看 `FixedFirstStagePlan` 和 `FixedOutageVector`
2. 再看 `_resolve_cls_by_bus(...)`
3. 然后顺着 `build_disaster_primal_reference_model(...)` 看变量和约束生成
4. 最后看 `DisasterPrimalSolution` 的提取方式

然后立刻对照：

- `tests/oracle/test_disaster_primal_ref.py`
- `docs/reports/round_02_report.md`

不要一上来就从 `quicksum(...)` 里面硬抠公式。

## 11. 这一阶段常见误解

### 误解 1

“这是灾难阶段的最终 production 模型。”

不是。它是 reference primal。

### 误解 2

“这里的 `delta` 是 separation 里要优化的变量。”

不是。这里的 `delta` 已经固定。

### 误解 3

“这个模型越接近论文完整两阶段越好。”

不是。这一层的目标是做一个**固定子问题真值源**。

### 误解 4

“如果 `critical_buses` 缺了，可以拿 `ambig.w` 顶一下。”

完全不行。这个 repo 明确禁止这种 fallback。
