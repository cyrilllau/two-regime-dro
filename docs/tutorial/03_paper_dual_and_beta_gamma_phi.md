# 03. Paper Dual And `beta / gamma / phi`

## 1. 这一阶段解决什么问题

前一节的 auto dual 解决的是“机械正确性”。

这一节要解决的是：

- 怎样把 disaster recourse dual 写成**论文可解释的 compact form**
- 怎样把 dual value 拆成后面 cut generation 能直接用的块

所以它的核心不是“再推一个 dual”，而是把 dual 改写成：

`beta_b - gamma_b^T x + phi_b^T delta`

这就是后面 cut factory 和 master problem 真正需要的桥。

## 2. 它在整条链路中的位置

位置是：

`disaster_primal_ref -> auto dual (mechanical check) -> paper dual (structured interpretation) -> cut factory`

这里有一个非常重要的认识：

- auto dual 负责“你没写错”
- paper dual 负责“你能拿去做 cut”

## 3. 对应的核心公式 / equation groups

它对应的还是 disaster recourse dual，也就是 `docs/spec/02_equation_registry.md` 里：

- Eq. (34): dual feasible region
- Eq. (35): dual representation of disaster recourse

但它不是从 canonical auto dual 直接复制 row，而是按 primal equation groups 重新组织：

- Eq. (27) -> `lam`
- Eq. (28) -> `eta`
- Eq. (29) -> `mu`
- Eq. (30) -> `nu`
- Eq. (31) -> `sigma`
- Eq. (32) -> `rho`

## 4. 对应的核心代码文件和主要 dataclass / builder / solver

核心文件：

- `src/production/disaster_dual_paper.py`

虽然它在 `src/production/`，但这里一定要讲，因为它是 reference 数学链进入 production 的第一座桥。

关键 dataclass：

- `SamplewisePaperDualDecomposition`
- `DisasterPaperDualModel`
- `DisasterPaperDualSolution`

关键入口：

- `build_disaster_dual_paper(...)`
- `solve_disaster_dual_paper(...)`
- `SamplewisePaperDualDecomposition.evaluate(...)`

## 5. 输入是什么

输入仍然是固定子问题：

- `CanonicalInstance`
- fixed `plan`
- fixed `outage`
- fixed disaster `scenario_id`

也就是说，这一层还不是 aggregated multi-sample cut。

它先做的是 samplewise dual。

## 6. 输出是什么

最重要的输出不是 dual var 数值本身，而是：

- `samplewise_decomposition`

也就是：

- `beta_b`
- `gamma_z_by_bus`
- `gamma_n_sl_by_bus`
- `gamma_n_fa_by_bus`
- `phi_by_line_id`

然后你可以直接用：

- `SamplewisePaperDualDecomposition.evaluate(plan=..., outage=...)`

来验证：

`beta_b - gamma_b^T x + phi_b^T delta`

是不是等于当前 dual objective。

## 7. 这个阶段的结果如何被下一阶段使用

它直接支撑三个后续层：

### 1. Separation MILP

`src/production/separation_milp.py` 不是重新写闭式分数，而是把 samplewise dual blocks 放进 separation 里。

### 2. Cut factory

`src/production/cut_factory.py` 会把 samplewise `beta_b / gamma_b / phi_b` 聚合成 structured master cut。

### 3. Master problem

`src/production/master_problem.py` 接受的 cut 结构正是：

- `beta`
- `gamma_z_by_bus`
- `gamma_n_sl_by_bus`
- `gamma_n_fa_by_bus`
- `phi_by_line_id`

所以如果你不理解这一层，就很难理解后面的 cut 到底是什么。

## 8. 对应 tests 在验证什么

主要 tests：

- `tests/oracle/test_disaster_dual_paper.py`
- `tests/oracle/test_lp_canonicalizer_signs.py`
- `tests/oracle/test_disaster_readiness_gate.py`

它们验证的不是“solver 能不能跑”，而是：

- primal = auto dual = paper dual
- hand-coded dual 的符号没有写错
- `critical_buses` 缺失时会明确失败
- `ambig.w` 不会被拿来兜底

## 9. 对应 round report 里最关键的结论是什么

对应：

- `docs/reports/round_04_report.md`

最关键的结论有四条：

### 结论 1

paper dual 是直接从 Round 02 的 primal equation groups 写出来的，不是抄 auto dual。

### 结论 2

dual groups 的符号约束被明确固定：

- `lam_eq27` 是 free
- `eta / mu / nu / sigma / rho` 都是 nonnegative

### 结论 3

decomposition 被显式暴露成：

- `beta_b`
- `gamma_*`
- `phi_by_line_id`

### 结论 4

runtime fixture 上：

- primal objective: `76273.74000000002`
- auto-dual objective: `76273.74`
- paper-dual objective: `76273.74`
- decomposition reconstruction gap: `3.245077095925808e-09`

也就是说，paper dual 不只是“能解”，而且 decomposition 真能重构 dual value。

## 具体结果：`beta / gamma / phi` 到底长什么样

Round 04 report 里给了一个 runtime-fixture 示例：

- `beta_b = -1923726.2599999967`
- `phi_b[line_01_02] = 2000000.0`

它的意义不是“这个数本身很重要”，而是：

- `beta_b` 收集了与当前 sample 相关、但不乘 first-stage 和 outage 的部分
- `gamma_b` 是 first-stage sensitivity
- `phi_b` 是 outage sensitivity

所以当后面 separation 或 cut factory 写成：

`beta - gamma^T x + phi^T delta`

它不是凭空来的，而是直接从这层 decomposition 暴露出来的。

## 10. 读代码建议：先看哪里，再看哪里

建议顺序：

1. 先看 `SamplewisePaperDualDecomposition`
2. 再看 `evaluate(...)`
3. 然后看 dual variable group 的 dataclass 字段
4. 再看 objective 构造和各类 dual row
5. 最后回头看 Round 04 report 的 sign fix 说明

重点要抓住两个问题：

1. 哪些 dual group 对应 first-stage `x`
2. 哪些 dual group 对应 outage `delta`

## 11. 这一阶段常见误解

### 误解 1

“paper dual 只是 auto dual 的换名字版本。”

不是。paper dual 是按论文 compact interpretation 重写后的结构化 dual。

### 误解 2

“`beta / gamma / phi` 是 cut factory 自己发明的。”

不是。它们是这一层 samplewise dual decomposition 的直接产物。

### 误解 3

“只要 primal = paper dual objective 就够了。”

不够。这里还要关心：

- dual variable sign restrictions
- dual row feasibility
- decomposition reconstruction gap

### 误解 4

“既然它在 `src/production`，就不用放进 reference tutorial。”

错。这个文件是理解 `src/reference` 数学链如何进入 production 的关键桥梁。
