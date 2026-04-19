# 07. Reports And Results: How To Read Them

## 1. 这一阶段解决什么问题

这一节不是再讲模型，而是教你：

- 怎么把 `docs/reports/round_02_report.md` 到 `round_10_report.md` 串成一条证据链
- 怎么看 `results/summary.csv`
- 怎么看 `docs/analysis_packs/experiment_interpretation_pack.md`
- 什么地方可以下强结论，什么地方只能说 smoke-only

## 2. 它在整条链路中的位置

它在整条链路的最末端：

`math model -> code -> tests -> reports -> packaged results -> interpretation`

如果你不读这一节，很容易出现一个常见错误：

- 看见一个 objective 数值，就默认它已经是论文级结论

## 3. 对应的核心公式 / equation groups

这一层不新增公式，但它要帮你识别“每个 report 在给哪一层方程作证”。

最重要的对应关系：

- Round 02 -> Eq. (26)–(32)
- Round 03 -> primal canonicalization / auto dual / KKT
- Round 04 -> dual groups + `beta/gamma/phi`
- Round 05 -> Eq. (41) separation exactness
- Round 07 -> Eq. (33), Eq. (37)–(39) fixed-cut master
- Round 09 -> Algorithm 1 style iterative Benders
- Round 10 -> independent exact oracle + readiness

## 4. 对应的核心代码文件和主要 dataclass / builder / solver

这层主要读的不是 solver 文件，而是输出文件：

- `docs/reports/round_02_report.md`
- `docs/reports/round_03_report.md`
- `docs/reports/round_04_report.md`
- `docs/reports/round_05_report.md`
- `docs/reports/round_09_report.md`
- `docs/reports/round_10_report.md`
- `results/summary.csv`
- `docs/analysis_packs/experiment_interpretation_pack.md`

如果你要回到代码源头，再跳回：

- `src/reference/*.py`
- `src/production/*.py`

## 5. 输入是什么

这一层的输入是前面所有阶段生成的证据：

- toy exact checks
- integration regressions
- LP dumps
- iteration logs
- summary CSV
- interpretation markdown

也就是说，报告不是凭空写的，它应该能回溯到 tests 和 artifacts。

## 6. 输出是什么

输出是“对当前 repo 能说什么、不能说什么”的清晰判断。

你最终应该能回答：

- 目前 reference 链在哪些点上是 exact 的
- 哪些 production 行为已经被 tiny exact oracle 兜住
- 哪些 runtime 结果只有 epsilon certificate
- 哪些 runtime family 只是 smoke-only

## 7. 这个阶段的结果如何被下一阶段使用

这一层直接决定：

- 你怎么写对外/对同事的解释
- 你后面做更多实验时，哪些结论能复用
- 你改算法时，哪些 baseline 是必须保持的

如果后面继续扩展实验 pack，建议每个新 family 都沿用这一节的阅读方式。

## 8. 对应 tests 在验证什么

Round 11 之后，结果包装层主要由这些东西兜住：

- `tests/integration/test_experiment_pack_smoke.py`
- `tests/integration/test_benders_runtime_certification.py`
- `tests/integration/test_readiness_matrix.py`

它们验证的是：

- 实验 pack 能生成 summary / plans / logs / report
- certified-small runtime-like Benders regression 仍然在
- readiness matrix 对 exact / epsilon / smoke 的边界没有说谎

## 9. 对应 round report 里最关键的结论是什么

### `docs/reports/round_02_report.md`

告诉你：

- disaster primal 已经是一个可信 reference LP

### `docs/reports/round_03_report.md`

告诉你：

- canonicalization 和 auto dual 没写偏

### `docs/reports/round_04_report.md`

告诉你：

- hand-coded paper dual 可用
- `beta/gamma/phi` decomposition 可用

### `docs/reports/round_05_report.md`

告诉你：

- separation exactness 在 tiny cases 上已经被 reference oracle 保护

### `docs/reports/round_09_report.md`

告诉你：

- full Benders loop 在 tiny end-to-end 上和 brute force 一致

### `docs/reports/round_10_report.md`

告诉你：

- 有一条 independent primal-exact disaster path 在给 production chain 做独立 cross-check

## 具体结果：当前该怎么读 `results/summary.csv`

当前 [results/summary.csv](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/results/summary.csv) 最值得先看的不是 objective，而是 `validation_level`。

### 目前的 exact runs

- `normal_only_certified_small`
- `normal_only_runtime12`

### 目前的 epsilon-certified runs

- `integrated_mainline_certified_small`
- `deterministic_mean_value_certified_small`

### 目前的 smoke-only runs

- `integrated_mainline_runtime12`
- `deterministic_mean_value_runtime12`
- `ev_penetration_1_5x_runtime12`
- `ev_penetration_2_0x_runtime12`

这意味着：

- 你可以对 certified-small family 下的 integrated run 做“epsilon-certified”解释
- 你不能把 default `runtime_12` integrated family 写成 paper-scale 结论

## 具体结果：当前 experiment pack 在告诉你什么

从 [docs/analysis_packs/experiment_interpretation_pack.md](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/docs/analysis_packs/experiment_interpretation_pack.md) 可读出：

### Integrated vs normal-only

- certified-small family 下：
  - integrated 和 normal-only 给出了同一个 first-stage plan
- default `runtime_12` family 下：
  - integrated 和 normal-only 在当前 bounded smoke pack 里也给出同一个 first-stage plan

但第二条只能按 smoke-only 解读。

### Deterministic vs integrated

- certified-small family 里 deterministic mean-value 不太有信息量，因为本来就是 singleton support
- default `runtime_12` family 里 deterministic mean-value 改变了 first-stage plan

### EV penetration

从 `base -> 1.5x -> 2.0x`：

- opened buses: `18 -> 25 -> 26`
- slow chargers: `360 -> 500 -> 520`
- fast chargers: `24 -> 42 -> 53`

这可以做方向性解读，但仍然是 smoke-only。

## 10. 读代码建议：先看哪里，再看哪里

推荐顺序：

1. 先读 `docs/reports/round_02_report.md` 到 `round_05_report.md`
2. 再读 `docs/reports/round_09_report.md` 和 `round_10_report.md`
3. 然后看 `results/summary.csv`
4. 最后读 `docs/analysis_packs/experiment_interpretation_pack.md`

读的时候一直问自己三个问题：

1. 这个结论的 validation level 是什么
2. 这个数值是来自 toy exact、epsilon-certified、还是 smoke-only
3. 这能不能写成 paper-comparable statement

## 11. 这一阶段常见误解

### 误解 1

“summary.csv 里的 objective 最小就是最终答案。”

错。先看 validation label，再看 objective。

### 误解 2

“runtime_12 结果可以直接跟 paper 表格对比。”

错。Round 11 已经明确说：

- current `runtime_12` is not numerically paper-Table-II comparable

### 误解 3

“只要一条集成 run 看起来合理，就可以说 integrated 比 deterministic 更好。”

错。除非证据级别够强，否则只能说方向性趋势。

### 误解 4

“report 里的 smoke-only 只是保守写法，实际可以当真。”

不能这样读。这个 repo 的一个核心纪律就是不要把 smoke-only 说成 certified。
