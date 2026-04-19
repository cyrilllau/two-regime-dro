# 05. Tiny Exact Oracles And Brute Force

## 1. 这一阶段解决什么问题

到目前为止，我们已经有：

- disaster primal 真值
- auto dual / KKT 验证
- paper dual decomposition
- outage enumeration / outer-DRO exact oracle

但还缺最后一个环节：

- 怎么证明 production Benders 整条链在 tiny case 上真的找到对的 first-stage plan？

这就是 `src/reference/brute_force_stage1.py` 的作用。

## 2. 它在整条链路中的位置

位置是：

`bounded first-stage candidate set -> exact evaluation of each candidate -> best tiny plan`

然后把这个 best tiny plan 拿去和：

- production Benders engine

做 end-to-end 比对。

## 3. 对应的核心公式 / equation groups

它不是单独对应一个方程，而是把多个层拼起来：

- Eq. (10)–(12): first-stage construction cost
- Eq. (13)–(25): normal-operation cost
- Eq. (26)–(38): disaster value path
- Eq. (33), Eq. (37)–(39), Eq. (41): production Benders 最终在解的 sampled problem

换句话说，它是在 tiny domain 上做一个“慢但 exact 的 stage-1 oracle”。

## 4. 对应的核心代码文件和主要 dataclass / builder / solver

核心文件：

- `src/reference/brute_force_stage1.py`

关键 dataclass：

- `BoundedFirstStagePlanCandidate`
- `BruteForcePlanEvaluation`
- `BruteForceStage1OracleResult`

关键入口：

- `build_bounded_candidate(...)`
- `solve_bounded_first_stage_bruteforce(...)`

内部会调用：

- `src/production/first_stage.py`
- `src/production/normal_block.py`
- `src/reference/disaster_exact_oracle.py`
- 或 `src/production/disaster_dual_paper.py + src/reference/dro_outer_lp_oracle.py`

## 5. 输入是什么

输入不是任意大 first-stage feasible region，而是**受控的小候选集**。

也就是：

- 你先显式列出若干 candidate plans
- brute-force oracle 对每个 candidate 做完整评估

这也是为什么它能 exact：

- 它不是在连续/整数决策空间里穷举全局
- 它是在 tiny fixture 指定的 bounded candidate set 上 exact

## 6. 输出是什么

输出包括：

- 每个 candidate 的完整评估
  - construction cost
  - averaged normal cost
  - disaster DRO cost
  - total objective
- 最优 candidate
- 最优 objective

这就给了 production Benders 一个很强的 tiny regression target：

- 不只是“数值差不多”
- 而是“candidate ranking 和最终最优 plan 都一致”

## 7. 这个阶段的结果如何被下一阶段使用

它直接支撑：

- `tests/integration/test_benders_vs_oracle.py`
- `tests/integration/test_disaster_exact_crosscheck.py`

也就是说，Benders engine 是否可信，不只是看内部 lower bound 或 certificate，而是看它在 tiny case 上能不能打赢这个 brute-force oracle。

## 8. 对应 tests 在验证什么

主要 tests：

- `tests/integration/test_benders_vs_oracle.py`
- `tests/integration/test_disaster_exact_crosscheck.py`

前者验证：

- Benders final objective 是否等于 brute-force optimum
- lower-bound / cut-count bookkeeping 是否单调

后者验证：

- bounded brute-force 的 disaster 部分如果改成 `primal_exact`
- 仍然与 production Benders 和 `paper_dual` 版本一致

## 9. 对应 round report 里最关键的结论是什么

主要对应：

- `docs/reports/round_09_report.md`
- `docs/reports/round_10_report.md`

### Round 09 的关键结论

在 tiny regression `benders_two_cut_unique_plan.yaml` 上：

- final stop reason: `certified_exact`
- iteration count: `3`
- lower-bound trace: `(9.999999999999998, 70.0, 71.0)`
- cut-count trace: `(1, 2, 3)`
- final exact objective: `71.0`
- final first-stage plan: open bus `3` with `10` slow chargers

### Round 10 的关键结论

三条路径全部支持同一个 tiny optimum：

1. exact Benders
2. bounded brute-force with `paper_dual` disaster evaluation
3. bounded brute-force with `primal_exact` disaster evaluation

它们都得到：

- optimal objective `71.0`
- best plan `bus3_10`

## 具体结果：为什么 `bus3_10` 重要

`bus3_10` 的意义不是“这个 plan 很现实”，而是：

- 这是一个 tiny 完全可控问题
- brute-force 能精确证明它是最优
- Benders 也能收敛到它
- independent primal-exact disaster oracle 也支持它

当三条路径都对齐时，你就获得了很强的 end-to-end correctness anchor。

## 10. 读代码建议：先看哪里，再看哪里

建议顺序：

1. 先看 `BoundedFirstStagePlanCandidate`
2. 再看 `_evaluate_construction_cost(...)`
3. 然后看 `_evaluate_normal_costs(...)`
4. 再看 `_evaluate_disaster_dro_cost(...)`
5. 最后看 `solve_bounded_first_stage_bruteforce(...)`

这里最重要的不是 Gurobi 细节，而是理解“它把哪几层拼起来”。

## 11. 这一阶段常见误解

### 误解 1

“brute-force oracle 就是在穷举全问题。”

不是。它只在 tiny fixture 提供的 bounded candidate set 上穷举。

### 误解 2

“既然已经有 Benders，就不需要 brute-force 了。”

错。恰恰因为 Benders 很复杂，才需要 brute-force tiny oracle 当端到端真值。

### 误解 3

“`paper_dual` 和 `primal_exact` 两种 disaster evaluation 只是重复实现。”

不是。Round 10 专门就是要用 `primal_exact` 做 independent cross-check。
