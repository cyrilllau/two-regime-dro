# 02. Canonicalizer And Auto Dual

## 1. 这一阶段解决什么问题

这一阶段解决的是：

- 已经有了一个正确的 primal LP
- 但如果想机械地验证 dual 正确性，需要先把 primal 变成标准可对偶化形式

所以它分成两个动作：

1. canonicalize primal
2. mechanically derive the auto dual

这一步的核心目标不是求更快的解，而是建立一个**不靠手写推导的对偶参考物**。

## 2. 它在整条链路中的位置

位置是：

`disaster_primal_ref -> lp_canonicalizer -> disaster_dual_auto -> kkt_checks`

这条链的作用是：

- 把 Round 02 的 primal 作为真值
- 自动构造一个 dual
- 再用 KKT / strong duality 去确认 primal 和 auto dual 真正一致

这样后面手写的 paper dual 才有稳固的比照对象。

## 3. 对应的核心公式 / equation groups

它没有新增论文里的新方程组，而是在数学上把 Eq. (26)–(32) 的 primal 重新整理成 canonical form。

关键规范来自：

- `min c^T x`
- `x >= 0`
- rows 只保留 `=` 和 `>=`

然后 auto dual 再按 canonical LP 的一般规则生成。

## 4. 对应的核心代码文件和主要 dataclass / builder / solver

核心文件：

- `src/reference/lp_canonicalizer.py`
- `src/reference/disaster_dual_auto.py`
- `src/reference/kkt_checks.py`

关键 dataclass：

- `CanonicalVariable`
- `CanonicalConstraint`
- `CanonicalizedReferenceLP`
- `DisasterAutoDualModel`
- `DisasterAutoDualSolution`
- `KKTCheckReport`

关键入口：

- `canonicalize_reference_lp(...)`
- `extract_canonical_primal_solution(...)`
- `build_disaster_dual_auto(...)`
- `solve_disaster_dual_auto(...)`
- `run_kkt_checks(...)`

## 5. 输入是什么

### 输入 1: Round 02 的 primal model

这一层不自己发明 primal。

它直接读取：

- `DisasterPrimalReferenceModel`

里的 Gurobi model。

### 输入 2: primal solution

KKT 检查时，还需要：

- `DisasterPrimalSolution`

因为要算：

- primal feasibility
- row slacks
- complementarity

## 6. 输出是什么

### 输出 1: canonical LP

这个对象显式保存：

- canonical variables
- equality constraints
- geq constraints
- free-variable split 映射

### 输出 2: auto dual

这是从 canonical LP 机械推出来的 dual model，不带 paper-specific 人工解释。

### 输出 3: KKT report

它给出：

- primal feasibility max violation
- dual feasibility max violation
- strong duality gap
- row complementarity
- variable complementarity

## 7. 这个阶段的结果如何被下一阶段使用

这个阶段最重要的用途是“给 hand-coded paper dual 一个对照基准”。

也就是说，Round 04 可以拿：

- auto dual objective
- auto dual feasibility
- KKT result

去检查：

- paper dual 是不是推对了
- `beta/gamma/phi` 的符号是不是写反了

没有这一步，Round 04 的 hand-coded dual 就只能靠人工信念，不够稳。

## 8. 对应 tests 在验证什么

主要 tests：

- `tests/oracle/test_disaster_primal_dual.py`

验证：

- toy cases 上 primal objective = auto dual objective
- canonicalizer 是否正确 split free line-flow variable
- KKT residual 是否足够小

还有：

- `tests/integration/test_disaster_primal_dual_runtime_fixture.py`

它说明这条链不只在 toy 上成立，也能吃当前 canonical runtime fixture。

## 9. 对应 round report 里最关键的结论是什么

对应：

- `docs/reports/round_03_report.md`

最关键的结论有四条：

### 结论 1

Round 02 的 primal 数学没有被改动，它仍然是唯一 primal source of truth。

### 结论 2

canonicalization 的符号约定被明确钉死了：

- primal 是 `min c^T x`
- canonical variables 都满足 `x >= 0`
- equality row 保持 `=`
- 原始 `<=` row 通过乘 `-1` 变成 canonical `>=`

### 结论 3

free variable 用显式 split：

- `p = p_pos - p_neg`
- `p_pos >= 0`
- `p_neg >= 0`

### 结论 4

toy 和 runtime fixture 上都观测到：

- primal objective = auto dual objective
- KKT residual 基本为 0

例如 runtime fixture：

- primal objective: `76273.74000000002`
- auto-dual objective: `76273.74`
- absolute gap: `1.4551915228366852e-11`

## 具体结果：KKT residual 为 0 在说明什么

Round 03 runtime-fixture 里最关键的一组数是：

- primal feasibility max violation: `0.0`
- dual feasibility max violation: `0.0`
- strong duality gap: `1.4551915228366852e-11`
- max row complementarity: `0.0`
- max variable complementarity: `0.0`

这组数的意义不是“浮点很好看”，而是：

- primal model 的行结构没乱
- canonicalization 没把符号翻错
- auto dual 没有丢约束
- KKT 检查链可用

## 10. 读代码建议：先看哪里，再看哪里

建议顺序：

1. 先看 `CanonicalVariable` / `CanonicalConstraint`
2. 再看 `_supports_nonnegative_form(...)` 和 `_supports_free_form(...)`
3. 再看 `canonicalize_reference_lp(...)` 里怎么处理 `= / > / <`
4. 然后看 `build_disaster_dual_auto(...)`
5. 最后看 `run_kkt_checks(...)`

读的时候重点想这三个问题：

1. 原 primal 哪些变量是 free 的
2. 哪些 row 被改成了 canonical `>=`
3. dual feasibility row 是怎么从 canonical coefficients 拼出来的

## 11. 这一阶段常见误解

### 误解 1

“auto dual 就是 paper dual。”

不是。

auto dual 是机械导出的 canonical dual。paper dual 是按论文结构和方程组组织的 hand-coded dual。

### 误解 2

“canonicalize 只是代码格式转换，不影响数学。”

表面上是，但如果你把 `<=` / `>=` 或 free variable split 处理错，后面 dual 会整体错。

### 误解 3

“只要 objective 一样就够了。”

不够。

这个 repo 还要看：

- primal feasibility
- dual feasibility
- complementarity

否则很可能是“objective 碰巧一样，但约束语义错了”。
