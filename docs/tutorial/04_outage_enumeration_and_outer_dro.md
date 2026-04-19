# 04. Outage Enumeration And Outer-DRO Oracle

## 1. 这一阶段解决什么问题

前面我们已经有了：

- fixed `(x, delta, b)` 的 primal / dual 真值
- samplewise `beta / gamma / phi`

但还缺两个关键问题：

1. `delta` 到底有哪些可能的 outage pattern
2. 在 budgeted outage ambiguity 下，最坏分布怎么求

这就是这一节的目标。

## 2. 它在整条链路中的位置

位置是：

`paper-dual or primal sample value -> enumerate outage patterns -> outer-DRO LP -> exact disaster value`

从依赖关系看：

- `outage_enumerator.py` 负责状态空间和 budget-support oracle
- `dro_outer_lp_oracle.py` 负责最坏分布 LP
- `disaster_exact_oracle.py` 负责把 samplewise primal value 接到 outer-DRO 上

## 3. 对应的核心公式 / equation groups

对应：

- Eq. (37): moment dualization
- Eq. (38): semi-infinite / outer DRO formulation
- Eq. (40): `omega` bounds 的 oracle 参照
- Eq. (41): separation 里的 budgeted outage structure

同时也对应附录里关于：

- budget support function
- finite exact reformulation

的证明钩子。

## 4. 对应的核心代码文件和主要 dataclass / builder / solver

核心文件：

- `src/reference/outage_enumerator.py`
- `src/reference/dro_outer_lp_oracle.py`
- `src/reference/disaster_exact_oracle.py`

关键对象和入口：

- `EnumeratedOutagePattern`
- `enumerate_outages(...)`
- `solve_budget_support_by_enumeration(...)`
- `solve_budget_support_top_k(...)`
- `solve_dro_outer_lp_oracle(...)`
- `solve_disaster_exact_oracle(...)`

## 5. 输入是什么

### 输入 1: canonical line ordering

所有 outage pattern 都必须对齐：

- `instance.sets.line_ids`

这是非常关键的稳定接口。

### 输入 2: outage budget `K`

`enumerate_outages(...)` 会在 `Omega(K)` 上枚举 outage pattern。

### 输入 3: `value_by_pattern`

outer-DRO oracle 不自己求 recourse value。

它只接受：

- 每个 outage pattern 的 value

然后求：

- 满足 `sum p = 1`
- 满足 linewise marginal upper bound `sum p * delta <= FP`

下的最坏分布。

### 输入 4: exact disaster value path

在 `disaster_exact_oracle.py` 中，这个 `value_by_pattern` 是通过：

- 每个 pattern
- 每个 disaster scenario
- 调一次 `disaster_primal_ref`

算出来的。

## 6. 输出是什么

### `outage_enumerator.py`

输出：

- 稳定有序的 outage pattern 集合
- support-function exact oracle

### `dro_outer_lp_oracle.py`

输出：

- outer-DRO objective
- worst-case probability by pattern
- linewise marginals

### `disaster_exact_oracle.py`

输出：

- weighted disaster objective
- outer-DRO value
- `value_by_pattern`
- samplewise primal objective by pattern
- worst-case active patterns

## 7. 这个阶段的结果如何被下一阶段使用

这层有两个重要用途：

### 用途 1: tiny exact oracle

它给你一个 independent exact disaster value path。

这个路径在 Round 10 很重要，因为它故意绕开 production paper-dual chain，用 primal recourse 来做独立对照。

### 用途 2: separation / Benders 验证

`outage_enumerator.py` 里的 tiny exact oracle 还被用来验证：

- separation MILP exactness
- budget support function exactness

也就是说，production 层在做更快的可扩展 formulation，而 reference 层用这些 oracle 给它兜数学底。

## 8. 对应 tests 在验证什么

主要 tests：

- `tests/oracle/test_dro_outer_lp.py`
- `tests/oracle/test_budget_support_fn.py`
- `tests/oracle/test_separation_exactness.py`
- `tests/oracle/test_disaster_exact_oracle.py`
- `tests/integration/test_disaster_exact_crosscheck.py`

这些 test 在验证：

- outage enumeration 稳定而且穷尽
- budget support function 和 top-k 正例等价
- outer-DRO LP hand-computable tiny case 没写错
- independent exact disaster oracle 和 production chain 给出的 tiny optimum 一致

## 9. 对应 round report 里最关键的结论是什么

这一节主要对应两个 report：

- `docs/reports/round_05_report.md`
- `docs/reports/round_10_report.md`

### Round 05 的关键结论

两线路 tiny outer-DRO oracle 的 hand-checkable case 给出：

- objective `7.0`
- `p(delta_10) = 0.5`
- `p(delta_01) = 0.25`
- `p(delta_00) = 0.25`

这说明 outer-DRO finite LP oracle 自己是可信的。

### Round 10 的关键结论

independent disaster exact oracle 的三总线 tiny case 给出：

- `value_by_pattern = {delta_00: 0.0, delta_10: 0.0, delta_01: 500.0}`
- outer-DRO value `250.0`
- weighted disaster term `225.0`

然后它和：

- full exact Benders
- bounded brute-force with paper-dual disaster evaluation

都一致地支持最终最优值 `71.0`。

## 具体结果：为什么两线路 tiny oracle 是 `7.0`

Round 05 里的 tiny case 参数是：

- `line_1` marginal upper bound `0.5`
- `line_2` marginal upper bound `0.25`
- pattern values:
  - `delta_00 -> 0.0`
  - `delta_10 -> 10.0`
  - `delta_01 -> 8.0`

最坏分布解出来是：

- `0.5` 放在 `delta_10`
- `0.25` 放在 `delta_01`
- 剩下 `0.25` 放在 `delta_00`

所以目标值就是：

`0.5 * 10 + 0.25 * 8 + 0.25 * 0 = 7.0`

这个 case 很重要，因为它说明 outer-DRO LP 不是黑箱，而是你可以手算核对的。

## 10. 读代码建议：先看哪里，再看哪里

建议顺序：

1. 先看 `EnumeratedOutagePattern`
2. 再看 `enumerate_outages(...)`
3. 然后看 `solve_budget_support_by_enumeration(...)`
4. 再看 `solve_dro_outer_lp_oracle(...)`
5. 最后看 `solve_disaster_exact_oracle(...)`

理解时请一直抓住一句话：

- `outage_enumerator` 负责“模式集合”
- `outer_dro_lp_oracle` 负责“最坏分布”
- `disaster_exact_oracle` 负责“把 pattern value 喂给最坏分布问题”

## 11. 这一阶段常见误解

### 误解 1

“outer-DRO oracle 直接在求 paper dual。”

不是。它只在 pattern values 之上做一个有限 LP。

### 误解 2

“enumeration 只是为了测试，不影响主线理解。”

错。enumeration 是 separation exactness 和 independent exact oracle 的数学锚点。

### 误解 3

“independent disaster exact oracle 只是换个接口调 production dual。”

不是。Round 10 明确要求它走：

- outage enumeration
- disaster primal reference
- outer-DRO LP oracle

而不是 production paper-dual chain。
