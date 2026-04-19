# 00. Repo Map And Reading Strategy

## 1. 这一阶段解决什么问题

这不是一个数学 phase，而是整个教程的导航层。

它要解决的问题是：

- 这个 repo 为什么要拆成 `instance / reference / production / audit`
- `src/reference` 在整个结构里到底是什么角色
- 读代码时应该按什么顺序，才能先抓住“数学骨架”，再理解 production 主线

## 2. 它在整条链路中的位置

它是第 0 步。

如果跳过这一层，后面很容易发生三种误解：

- 把 `src/reference` 当成生产求解器
- 把 `src/production` 当成参考真值
- 把 `tests` 和 `docs/reports` 当成附属材料，而不是“数学证据”

## 3. 对应的核心公式 / equation groups

这一层本身不实现具体方程，但它对应两个最关键的索引文档：

- `docs/spec/01_architecture.md`
- `docs/spec/02_equation_registry.md`

你可以把它们理解为：

- `01_architecture.md` 说明“哪些模块负责什么”
- `02_equation_registry.md` 说明“哪些方程由哪些模块负责”

最核心的映射是：

- Eq. (26)–(32) -> `src/reference/disaster_primal_ref.py`
- Eq. (34)–(35) -> `src/reference/disaster_dual_auto.py` 与 `src/production/disaster_dual_paper.py`
- Eq. (37)–(41) -> `src/reference/dro_outer_lp_oracle.py`、`src/production/master_problem.py`、`src/production/separation_milp.py`

## 4. 对应的核心代码文件和主要 dataclass / builder / solver

这一层主要要记住文件职责，而不是具体变量。

### Canonical foundation

- `src/instance/canonical_instance.py`
- `src/instance/selection.py`
- `src/instance/validators.py`
- `src/instance/network_topology.py`

### Reference track

- `src/reference/disaster_primal_ref.py`
- `src/reference/lp_canonicalizer.py`
- `src/reference/disaster_dual_auto.py`
- `src/reference/kkt_checks.py`
- `src/reference/outage_enumerator.py`
- `src/reference/dro_outer_lp_oracle.py`
- `src/reference/disaster_exact_oracle.py`
- `src/reference/brute_force_stage1.py`

### Production track

- `src/production/disaster_dual_paper.py`
- `src/production/separation_milp.py`
- `src/production/master_problem.py`
- `src/production/cut_factory.py`
- `src/production/benders_engine.py`

### Audit / evidence

- `src/audit/residual_report.py`
- `src/audit/cut_audit.py`
- `src/audit/iteration_log.py`

## 5. 输入是什么

如果你把整个 repo 看作一条链，最上游输入是 canonical instance。

也就是：

- runtime data package
- runtime selection
- explicit `critical_buses`

通过 `src/instance/` 统一变成：

- `CanonicalInstance`

然后 reference 和 production 都只读这个 canonical object。

## 6. 输出是什么

这一层的输出不是某个数值，而是一套稳定的阅读路径。

最推荐的理解顺序是：

1. `src/reference/disaster_primal_ref.py`
2. `src/reference/lp_canonicalizer.py`
3. `src/reference/disaster_dual_auto.py`
4. `src/production/disaster_dual_paper.py`
5. `src/reference/outage_enumerator.py`
6. `src/reference/dro_outer_lp_oracle.py`
7. `src/reference/disaster_exact_oracle.py`
8. `src/reference/brute_force_stage1.py`
9. `src/production/separation_milp.py`
10. `src/production/master_problem.py`
11. `src/production/cut_factory.py`
12. `src/production/benders_engine.py`

## 7. 这个阶段的结果如何被下一阶段使用

后面的每一节 tutorial 都默认你已经接受下面这个基本结构：

- `instance` 负责“数据语义正确”
- `reference` 负责“数学正确”
- `production` 负责“算法主线可跑”
- `audit/tests/reports` 负责“证据和解释”

如果你后面想改算法，还是应该优先回到这个结构上定位“你到底在改哪一层”。

## 8. 对应 tests 在验证什么

这一层对应的不是单一 test，而是整个测试组织方式：

- `tests/unit/`
  - 接口、系数、shape、边界条件
- `tests/oracle/`
  - tiny exact math checks
- `tests/integration/`
  - 多模块组合后的 bounded regression

所以读代码时，不要只看模块本身，还要看它属于哪类 test 保护。

## 9. 对应 round report 里最关键的结论是什么

对应整个 repo 演化的关键 round：

- `docs/reports/round_02_report.md`
  - 参考 disaster primal 落地
- `docs/reports/round_03_report.md`
  - canonicalization + auto dual + KKT 落地
- `docs/reports/round_04_report.md`
  - hand-coded paper dual 和 `beta/gamma/phi` 暴露出来
- `docs/reports/round_05_report.md`
  - separation exactness 被 tiny oracle 保护
- `docs/reports/round_09_report.md`
  - full Benders engine 形成
- `docs/reports/round_10_report.md`
  - independent primal exact oracle 和 readiness 证据形成

也就是说，`src/reference` 不是孤立代码，而是被一串 round report 明确接力验证过的。

## 10. 读代码建议：先看哪里，再看哪里

推荐顺序：

1. 先读 `docs/spec/01_architecture.md`
2. 再读 `docs/spec/02_equation_registry.md`
3. 然后开始读 `src/reference/disaster_primal_ref.py`
4. 每读完一个 reference 文件，就去看对应的 `tests/oracle/*`
5. 最后回头看对应 round report，确认你理解的“数学意义”和 repo 里的“验证结论”一致

如果你准备改 production：

1. 先读完 tutorial 的 `01` 到 `05`
2. 再读 `06`
3. 最后才碰 `src/production/*`

## 11. 这一阶段常见误解

### 误解 1

“`src/reference` 是备用版本，可以不看。”

错。它是 production 可信度的数学锚点。

### 误解 2

“只要 `src/production` 能跑，reference 就不重要。”

错。这个 repo 明确是 `reference before production`。

### 误解 3

“report 只是总结，读代码就够了。”

错。这里的 `docs/reports/*` 其实是把每轮验证结论结构化保存下来的证据层。

### 误解 4

“当前 `runtime_12` 跑出来的东西已经等于论文复现。”

错。尤其在 Round 11 的解释包里，已经明确说了：

- `runtime_12` 不是 paper-scale numerical reproduction
- 很多 runtime family 只能按 `smoke_only` 解读
