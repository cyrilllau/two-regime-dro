# Appendix. Glossary

## A

### `alpha`

restricted master problem 里的标量变量，用来承载 disaster outer term 的截距部分。

### `ambig.w`

legacy ambiguity-related data。这个 repo 明确禁止从它推 `critical_buses`。

## B

### `beta`

在 cut decomposition 里，不乘 first-stage `x`、也不乘 outage `delta` 的常数部分。

### `Benders engine`

production 侧的迭代驱动器。当前实现见：

- `src/production/benders_engine.py`

它负责：

- solve master
- solve separation
- certify or add cut
- iterate

## C

### canonicalization

把 primal LP 转成：

- `min c^T x`
- `x >= 0`
- rows 为 `=` 和 `>=`

以便机械对偶化。

### `CanonicalInstance`

从 `src/instance/` 输出的统一 canonical runtime object。production / reference 都只应消费它，而不是直接读 raw CSV/JSON。

### `certificate`

Benders 在停止时给出的证据。

典型 stop reason：

- `certified_exact`
- `certified_epsilon`
- `max_iterations`

## D

### disaster primal reference

固定 `(x, delta, b)` 的灾难阶段 primal LP 真值源。实现见：

- `src/reference/disaster_primal_ref.py`

### disaster exact oracle

独立于 production paper-dual chain 的 tiny exact disaster value path。实现见：

- `src/reference/disaster_exact_oracle.py`

### dual

primal LP 的对偶问题。

在这个 repo 里有两个重要 dual：

- auto dual
- paper dual

## E

### `epsilon_certified`

validation label。表示 run 不是 exact，但 Benders violation 已经小于等于给定 epsilon，存在显式 certificate。

### `exact`

validation label。表示当前结论在受控问题上是 exact 的。

## F

### free variable split

把 free primal variable 写成：

`x = x_pos - x_neg`

且：

- `x_pos >= 0`
- `x_neg >= 0`

## G

### `gamma`

cut decomposition 中乘 first-stage plan `x` 的系数块。

当前 repo 分成：

- `gamma_z_by_bus`
- `gamma_n_sl_by_bus`
- `gamma_n_fa_by_bus`

## K

### KKT checks

用于验证：

- primal feasibility
- dual feasibility
- strong duality
- complementarity

实现见：

- `src/reference/kkt_checks.py`

## L

### `lambda`

有两个常见语境：

1. paper dual 里 Eq. (27) 的 free dual variable group  
2. restricted master problem 里 linewise ambiguity multipliers

看上下文区分。

## O

### outage pattern

一个固定的线路失效 realization，也就是 `delta` 的一个离散模式。

### outer-DRO LP oracle

在 enumerated outage states 上解最坏分布 LP 的 tiny exact oracle。实现见：

- `src/reference/dro_outer_lp_oracle.py`

### `omega`

在 separation MILP 里承载 linewise outage-sensitivity 聚合项的变量。

## P

### paper dual

按论文 equation groups 写出来的 hand-coded dual。实现见：

- `src/production/disaster_dual_paper.py`

### `phi`

cut decomposition 里乘 outage vector `delta` 的 linewise 系数块。

### primal

原始优化问题。在这里通常指灾难阶段 fixed `(x, delta, b)` primal LP。

## R

### reference track

repo 里负责可审计数学真值的代码路径，主要在：

- `src/reference/`

### restricted master problem / RMP

Benders 里的 master problem，当前 production 实现在：

- `src/production/master_problem.py`

## S

### separation MILP

固定 `(x, alpha, lambda)` 后，寻找最坏 outage 的线性化 MILP。实现见：

- `src/production/separation_milp.py`

### `smoke_only`

validation label。表示这个 run 只能用于链路通顺和方向性观察，不能上升为强结论。

### support function

在 budgeted outage ambiguity 下：

`max_{delta in Omega(K)} v^T delta`

这个 repo 用 enumeration / top-k oracle 对它做 tiny exact 验证。

## T

### tiny exact oracle

在小规模、可枚举、可手算的 setting 下，提供数学真值的 oracle。

### `tau`

在 separation MILP 中用于表示 `delta * omega` 的 McCormick 线性化变量。

## V

### validation label

结果解释时必须带的证据级别标签：

- `exact`
- `epsilon_certified`
- `smoke_only`

## W

### `runtime_12`

当前本地 runtime package。

它适合：

- bounded validation
- runtime smoke experiments
- directionality analysis

它**不**等于 paper-scale numerical reproduction。
