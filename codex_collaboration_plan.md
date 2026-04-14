# EVCS Hybrid DRO Mainline：Codex 多轮协作开发总纲（v1）

## 1. 文档目的

这份文档不是实现细节说明书，而是整个新 repo 的**协作总纲**。用途是：

1. 固定我们和 Codex 的协作方式；
2. 固定多轮开发的阶段划分；
3. 固定每一轮任务包的格式、边界、验收方式；
4. 确保代码结构天然支持 **debug、审计、对偶化验证、Benders-like 外循环验证**；
5. 避免 Codex 在多轮中“自行补数学”或把旧代码库中的工程遗留语义混入新主线。

---

## 2. 总体目标

新 repo 的目标不是“尽快跑出一个结果”，而是构建一个：

- **paper-faithful** 的新主线实现；
- 结构上适合 **调试**；
- 结构上适合 **验证对偶化是否正确**；
- 结构上适合 **逐轮让 Codex 安全接手局部任务**；
- 结构上适合后续扩展到更大实例、更多场景、更多测试。

核心原则：

> 先把“可审计的参考实现”建出来，再把“可跑的生产实现”建出来；
> 生产实现不能先于参考验证通过。

---

## 3. 数学与实现的主线认识

论文的主线是一个两阶段混合不确定优化模型：

- 第一阶段：EVCS 选址与快慢充规模决策；
- 第二阶段正常工况：样本驱动 stochastic recourse；
- 第二阶段灾害工况：外层 DRO + 内层灾后样本平均 recourse；
- 求解上：对灾害 recourse 对偶化，再进入 master + separation 的 Benders-like 外循环。

因此，新 repo 必须在结构上体现这四个层次：

1. 第一阶段规划；
2. 正常工况显式 recourse；
3. 灾害工况 primal / dual / separation；
4. 主算法外循环与 cut 管理。

---

## 4. 新 repo 的结构原则

### 4.1 不围绕旧 codebase 组织

旧 codebase 只提供两类价值：

1. 数据/loader/schema 经验；
2. `{1,2}` 小实例的调试经验。

新 repo **不复用旧 codebase 的模型结构**，也不围绕旧模块命名来组织。

### 4.2 参考轨与生产轨并行

整个 repo 分成两条并行轨道：

- **reference track**：专门做数学验证，允许慢，但必须清晰可审计；
- **production track**：专门做主算法和求解效率，必须和 reference 结果一致。

### 4.3 先可验证，再可扩展

任何复杂模块都必须先有一个小规模、可手推、可枚举、可对照的版本，再上生产主线。

---

## 5. 顶层目录建议

```text
repo/
  docs/
    spec/
    tasks/
    reports/

  src/
    instance/
    contracts/
    reference/
    production/
    audit/

  tests/
    unit/
    integration/
    oracle/
    fixtures/
```

### 5.1 `docs/spec/`

只放稳定规范，原则上不让 Codex 随意修改：

- `00_freeze_contract.md`
- `01_architecture.md`
- `02_equation_registry.md`
- `03_data_contract.md`
- `04_test_strategy.md`
- `05_round_protocol.md`

### 5.2 `docs/tasks/`

每轮发给 Codex 的任务包，一个 round 一个文件，例如：

- `round_00_repo_bootstrap.md`
- `round_01_instance_layer.md`
- `round_02_disaster_primal_ref.md`
- `round_03_auto_dual.md`

### 5.3 `docs/reports/`

Codex 每轮完成后必须生成：

- `round_00_report.md`
- `round_01_report.md`
- ...

### 5.4 `src/instance/`

只负责数据标准化与实例构造：

- 原始数据读取
- 冻结配置装配
- canonical instance 构建
- validators
- indexer
- network topology helpers

### 5.5 `src/contracts/`

只负责合同与公式映射：

- freeze contract
- equation registry
- naming rules
- fail-fast validation rules

### 5.6 `src/reference/`

只做参考实现与数学审计：

- disaster primal reference model
- LP canonicalization
- auto-generated dual
- KKT / strong duality checks
- outage enumeration
- DRO outer LP oracle

### 5.7 `src/production/`

只做生产主线：

- first-stage builder
- normal-operation block
- hand-coded disaster dual
- separation MILP
- cut factory
- master problem
- benders engine

### 5.8 `src/audit/`

只做证据输出：

- LP dump
- residual report
- cut audit
- iteration log
- scenario validation log

---

## 6. 设计哲学：共享底座 + 双轨验证

### 6.1 共享底座

参考轨和生产轨共用：

- 同一份 `CanonicalInstance`
- 同一份索引体系
- 同一份拓扑对象
- 同一份 freeze 配置
- 同一份公式编号 registry

这样所有差异只允许出现在“数学表达方式”上，不允许出现在“数据含义”上。

### 6.2 双轨验证

对于灾害部分，至少保留三种表示：

1. `disaster_primal_ref`
2. `disaster_dual_auto`
3. `disaster_dual_paper`

验证链是：

- `primal_ref` vs `dual_auto`
- `dual_auto` vs `dual_paper`
- `dual_paper` 的 cut 系数回代检查
- `separation_milp` vs outage enumeration

只有这条链都打通，生产轨才能被认为可靠。

---

## 7. 冻结合同（mainline 级别）

以下内容作为主线规范冻结：

```yaml
mainline_spec_freeze:
  source_of_truth:
    schema_and_loader: "m1_data_setup.py"
    runtime_numeric_params: "parameters.json"
    scenario_index_source: "csv_contents_then_validate_against_json"

  default_runtime_fixture:
    instance_id: "local_tested_small_v1"
    scenarios_a: [1, 2]
    scenarios_b: [1, 2]
    expanded_scenario_packages: "opt_in_only"
    on_support_mismatch: "raise_explicit_validation_error"

  economics:
    Cunmet: 3.0
    annualize_normal_cost_by_365: true
    annualize_disaster_cost_by_365: false
    Ctrans_mode: "time_vector"
    power_unit: "kW"

  network_freeze:
    root_bus: 1
    candidate_buses: "all_except_root"
    allow_evcs_at_root: false
    v_ref_sq: 1.0

  ambiguity_freeze:
    p_bar_equals_FP: true
    use_ambig_w_in_paper_model: false
    ambig_w_meaning: "legacy engineering weight in old repo only, not the paper CLS_n contract"

  disaster_objective_freeze:
    critical_buses: REQUIRED_EXTERNAL_INPUT
    CLS_critical: 50.0
    CLS_noncritical: 10.0

  prohibited_inference:
    infer_critical_buses_from_ambig_w: false
    fallback_to_ambig_w_when_critical_buses_missing: false
    synthesize_paper_CLS_from_old_repo_weights: false
```

说明：

- `critical_buses` 是当前唯一必须由外部显式提供的 paper-level 模型输入；
- 缺失时必须在构建灾害目标前 fail fast；
- 不允许用 `ambig.w` 代替或推断 `critical_buses`。

---

## 8. 数据层的唯一职责

数据层只做两件事：

1. 读取原始数据；
2. 转成标准化内部对象。

它**不负责**：

- 补数学；
- 默认推断 critical nodes；
- 混入旧工程路径的权重语义；
- 直接驱动模型结构。

### 8.1 内部标准对象

至少包含：

- `FrozenConfig`
- `CanonicalInstance`
- `NormalScenarioTensor`
- `DisasterScenarioTensor`
- `NetworkTopology`
- `IndexMap`

### 8.2 Fail-fast 规则

以下任一情况必须在模型层之前报错：

- `critical_buses` 缺失；
- scenario 支持与默认 fixture 不一致；
- 拓扑不是单根树形网络；
- line / node / region / scenario 索引缺失；
- 正常或灾害张量 shape 不完整；
- `p_bar` 长度与线路数不一致；
- `critical_buses` 包含非法 bus id。

---

## 9. 模块级职责划分

## 9.1 `src/instance/`

### `schema.py`
定义内部数据类和类型契约。

### `canonical_instance.py`
构造标准化实例对象。

### `validators.py`
执行全部 fail-fast 检查。

### `indexer.py`
把 bus / line / region / time / scenario 变成稳定索引。

### `network_topology.py`
维护父子节点关系、下游线路、根节点检查等。

---

## 9.2 `src/reference/`

### `disaster_primal_ref.py`
固定 `(x, δ, b)` 后，直接按原始灾害 LP 建模。

用途：

- 手推校验；
- primal feasibility 检查；
- 审计固定 outage 下的最优负荷切除与 V2G 分配。

### `lp_canonicalizer.py`
把 `disaster_primal_ref` 机械转为 compact form：

```text
min d^T y
s.t. W y >= H^b - Z^b x + U δ,
     y >= 0
```

### `disaster_dual_auto.py`
由 canonical primal 自动构造 dual。

### `kkt_checks.py`
检查：

- primal feasibility
- dual feasibility
- strong duality
- complementary slackness

### `outage_enumerator.py`
枚举小规模 `Ω(K)`。

### `dro_outer_lp_oracle.py`
对 tiny case 直接解 worst-case distribution LP，作为 separation / outer-DRO 真值 oracle。

---

## 9.3 `src/production/`

### `first_stage.py`
实现第一阶段选址定容变量与约束。

### `normal_block.py`
实现正常工况显式 recourse block。

### `disaster_dual_paper.py`
按论文 compact dual 手写生产 dual。

### `separation_milp.py`
实现带二进制 outage 和 McCormick 线性化的 separation MILP。

### `cut_factory.py`
给定最坏 outage 后，重解 dual 并生成新 cut 系数。

### `master_problem.py`
维护：

- 第一阶段变量
- 正常工况 blocks
- α, λ
- 当前 cut 集

### `benders_engine.py`
维护迭代流程：

1. solve RMP
2. solve separation
3. certify or generate new cut
4. update master
5. log iteration

---

## 9.4 `src/audit/`

### `model_dump.py`
导出 LP/MPS 文件。

### `residual_report.py`
输出固定场景 primal/dual 残差报告。

### `cut_audit.py`
输出每条 cut 的来源：

- 哪个 round
- 哪个 outage vector
- 哪组 dual extreme point
- 作用于哪些 master 变量

### `iteration_log.py`
记录：

- iteration id
- RMP objective
- violation
- cut count
- solve time breakdown

---

## 10. 分阶段开发路线图

整个项目按“证明义务”分阶段开发，每轮任务只解决一个闭环。

### Phase 0：Repo bootstrap

目标：

- 建目录结构
- 建 `pyproject.toml`
- 建基础测试框架
- 建 spec/docs 骨架

产物：

- 可运行 repo
- smoke tests
- docs/spec 初始化

不要求：

- 任何优化器逻辑

---

### Phase 1：标准化实例层

目标：

- 完成 `FrozenConfig`
- 完成 `CanonicalInstance`
- 完成 validators / indexer / topology helpers

验收：

- `{1,2}` fixture 可正确加载
- `critical_buses` 缺失会 fail fast
- 模型层不能直接接触原始 CSV/JSON

---

### Phase 2：灾害 primal 参考模型

目标：

- 写 `disaster_primal_ref`
- 支持固定 `(x, δ, b)` 的 LP 求解
- 支持 toy case 手推验证

验收：

- 小例子结果与手推一致
- 能导出 LP
- 能输出 primal residual 报告

---

### Phase 3：canonicalize + auto dual

目标：

- 提取 `W, d, H^b, Z^b, U`
- 自动生成 dual
- 做 primal/dual/KKT 检查

验收：

- `objective(primal_ref) = objective(dual_auto)`
- dual feasibility 通过
- 互补松弛检查通过

---

### Phase 4：hand-coded paper dual

目标：

- 写 `disaster_dual_paper`
- 对照 `dual_auto`

验收：

- `objective(dual_auto) = objective(dual_paper)`
- cut 系数抽取逻辑可单测

---

### Phase 5：budget support + separation oracle

目标：

- 写 `outage_enumerator`
- 写 `dro_outer_lp_oracle`
- 写 `separation_milp`

验收：

- tiny case 下 `separation_milp` 的最优 violation 与枚举 oracle 一致
- `max_{δ∈Ω(K)} v^Tδ` 的 reformulation 与 top-K/枚举一致

---

### Phase 6：第一阶段 + 正常工况 block

目标：

- 写 `first_stage`
- 写 `normal_block`

验收：

- 第一阶段与正常工况可独立求解
- 交通成本 / unmet / 购电成本都可检查
- 网络约束有单测

---

### Phase 7：RMP 主体

目标：

- 写 `master_problem`
- 接入 trivial cut
- 接入 normal blocks 与 α, λ

验收：

- 可解 RMP
- 可导出 master LP
- iteration-0 结果可记录

---

### Phase 8：cut extractor + 单轮外循环

目标：

- 写 `cut_factory`
- 支持一轮 solve RMP → separation → add cut

验收：

- 至少能成功生成并加入一条新 cut
- cut audit 可回看

---

### Phase 9：完整 Benders engine

目标：

- 写 `benders_engine`
- 加入终止条件与日志

验收：

- toy oracle case 上结果与 brute force 一致
- 默认 `{1,2}` fixture 能完整跑通

---

### Phase 10：审计、回归、加固

目标：

- 增强日志、报告、回归测试
- 稳定接口
- 准备后续扩展

验收：

- 全测试通过
- 每个 round 的核心产物都有对应 regression

---

## 11. 多轮协作协议

### 11.1 我（ChatGPT）的职责

我负责：

- 写稳定 spec；
- 设计 round 计划；
- 写每一轮任务包；
- 定义验收标准；
- 审查 Codex 回传结果；
- 决定通过、修补或回滚。

### 11.2 你（中间人）的职责

你负责：

- 把任务包原样交给 Codex；
- 把 Codex 的代码改动、测试输出、报告文件发回；
- 不在 round 中途更改 spec；
- 在必要时补充外部输入（尤其是 `critical_buses`）。

### 11.3 Codex 的职责

Codex 只负责：

- 按当前 round 的任务包修改限定文件；
- 跑指定测试；
- 生成 round report；
- 不越界修改 spec 或其它模块。

---

## 12. 每一轮任务包必须包含的内容

每个 `docs/tasks/round_xx.md` 固定包含以下字段：

```md
# Round XX - Title

## Objective
本轮唯一目标。

## Allowed files to create/update
本轮允许修改的文件。

## Do not modify
本轮禁止修改的文件或目录。

## Required behavior
本轮必须完成的行为清单。

## Acceptance tests
必须通过的测试。

## Deliverables
代码、测试、报告。

## Report format
Codex 必须写出的 round report 结构。
```

这样做的目的，是严格限制 Codex 的自由度。

---

## 13. 每一轮 round report 必须包含的内容

每个 `docs/reports/round_xx_report.md` 至少要包含：

```md
# Round XX Report

## Files changed
- ...

## Design decisions
- ...

## Tests run
- command
- result

## Known limitations
- ...

## Open issues for next round
- ...
```

如果本轮涉及优化模型，还必须补充：

- LP dump 路径
- primal/dual objective 对照
- 关键 residual 摘要

---

## 14. 强制纪律

### 14.1 一轮只解决一个证明义务

例如：

- “写 disaster primal reference 并通过 toy tests”

而不是：

- “顺便把 dual、separation、cut generation 一起写了”。

### 14.2 生产实现不能先于参考验证通过

特别是以下模块：

- `disaster_dual_paper`
- `separation_milp`
- `cut_factory`
- `benders_engine`

### 14.3 每轮必须有退出产物

每轮不允许只交代码，必须同时交：

- 测试
- report
- 必要时 LP dump / residual report

### 14.4 Codex 不得自行补冻结语义

特别禁止：

- 从旧字段推断 `critical_buses`
- 把 `ambig.w` 作为 paper `CLS_n`
- 默认把更多 scenario 自动并入主线 fixture
- 在未经允许时修改 `docs/spec/*`

---

## 15. 测试策略总纲

测试分成五层：

### 15.1 数据合同层

检查：

- shape
- 索引覆盖
- 拓扑合法性
- 参数长度一致性
- fixture 一致性

### 15.2 系数装配层

检查某一组公式的矩阵系数是否和预期一致。

### 15.3 参考 LP 层

检查固定 `(x, δ, b)` 下：

- primal feasibility
- dual feasibility
- objective equality

### 15.4 oracle 层

在 tiny case 上：

- outage 全枚举
- outer-DRO LP 真值
- support function 真值

### 15.5 端到端层

检查：

- Benders 主线 vs brute force oracle
- cut 迭代收敛
- 近似证书条件

---

## 16. 推荐的第一批 round 顺序

为了尽快进入“可验证开发”，建议按这个顺序推进：

### Round 00：Repo bootstrap

只搭工程，不写优化。

### Round 01：Instance layer

把数据标准化、validators、topology 先做完。

### Round 02：Disaster primal reference

最先建立灾害 primal 的参考实现。

### Round 03：Auto dual + KKT

优先打通对偶化验证链。

### Round 04：Hand-coded paper dual

在 auto dual 审计通过后才开始。

### Round 05：Separation MILP + oracle

把 hardest part 放在 dual 化已经稳定之后。

---

## 17. 目前唯一未冻结的外部输入

当前唯一必须由用户/配置层显式提供的 paper-level 输入是：

```yaml
critical_buses: REQUIRED_EXTERNAL_INPUT
```

这意味着：

- repo 其它部分都可以继续开发；
- 但 paper-faithful 的灾害主线目标函数最终联调前，必须由配置层提供 `critical_buses`。

---

## 18. Definition of Done（项目级）

当以下条件全部满足时，认为主线 repo 初版完成：

1. `CanonicalInstance` 和全部 validators 稳定；
2. `disaster_primal_ref` / `dual_auto` / `dual_paper` 三角校验通过；
3. `separation_milp` 在 tiny case 上与 outage enumeration 一致；
4. 第一阶段与正常工况显式 block 可独立求解；
5. 完整 `benders_engine` 可在默认 `{1,2}` fixture 上运行；
6. 关键 toy/oracle/regression tests 全通过；
7. 所有 round 产物、报告和审计文件都可追溯。

---

## 19. 一句话执行原则

> 用稳定 spec 管住全局，按证明义务拆分轮次，让 Codex 每轮只做一个闭环；
> 先建 reference track 证明数学没错，再建 production track 跑主算法；
> 所有复杂环节都必须有 oracle 或审计链托底。

