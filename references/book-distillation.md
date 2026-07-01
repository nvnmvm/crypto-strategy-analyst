# 书籍蒸馏与需求映射

本文件只记录与 `crypto-strategy-analyst` 直接相关、能够转成规则或测试的原则。页码中的“印刷页”是书内页码，“PDF页”是文件查看器页码；EPUB 使用内部文件和锚点。概念均为归纳，不是原文摘录。

## 附件清点

### 已读取书籍

- David R. Aronson，*Evidence-Based Technical Analysis*，2007，ISBN 978-0-470-00874-4，PDF 528 页。
- Robert Pardo，*The Evaluation and Optimization of Trading Strategies*，第二版，2008，ISBN 978-0-470-12801-5，PDF 367 页。
- Ernest P. Chan，*Quantitative Trading*，第一版，2009，ISBN 978-0-470-28488-9，PDF 204 页。
- Ralph Vince，*The Mathematics of Money Management*，1992，ISBN 0-471-54738-7，PDF 106 页。
- Martin Kleppmann、Chris Riccomini，*Designing Data-Intensive Applications*，第二版 Early Release，EPUB，ISBN 978-1-098-11906-5；内部只有 8 章且目录标为未最终确定。
- Michael T. Nygard，*Release It!*，第二版，2018，ISBN 978-1-68050-239-8，PDF 366 页。
- Perry J. Kaufman，*Trading Systems and Methods*，第六版，2020，ISBN 978-1-119-60535-5，PDF 2285 页；仅作补充。

### 未提供书籍

- 无。提示中列出的六本主书及 Kaufman 补充书均有附件。

### 无法解析书籍

- 无。七个附件均可提取目录和相关正文。

### 书籍版本或版本不确定

- Chan：需求指定第二版，但附件是第一版。已核验第二版 Wiley 官方条目（2021，ISBN 9781119800064），未找到可合法下载的完整第二版；本阶段只引用附件第一版中可核对的内容。
- Kaufman：需求说第五版，附件是第六版；只采用跨版本稳定的方法论，不据此增加指标。
- DDIA：文件名标注 “Sixth Early Release”，内部可确认“第二版 Early Release”，但内部修订历史未明确写第六次早期发布；位置以 EPUB 内部锚点为准。

## 针对性蒸馏

### Aronson：客观规则与数据挖掘偏差

来源书籍：*Evidence-Based Technical Analysis*  
章节：第 1 章 “Objective Rules and Their Evaluation”  
页码或电子书位置：印刷页 15–16 / PDF 页 22–23  
原始问题：主观图形描述无法被不同研究者稳定复现。  
核心原则：规则必须精确定义输入、运算和输出，并能由程序无歧义重复执行。  
适用于本项目的原因：靠近支撑、有效反弹、强信号等词若无阈值，会让实时分析与回测产生不同结果。  
应转换成的代码或测试规则：所有候选条件登记参数、单位、边界和缺失值行为；相同输入必须产生相同信号。  
是否进入 v0.1.3：是。  
不采用的部分及原因：不把作者讨论的做空或其他资产规则扩展到项目边界之外。

来源书籍：同上  
章节：第 6 章 “The Case Study: Signal Rules and Data-Mining Bias”  
页码或电子书位置：印刷页 255–264、287 / PDF 页 258–267、290  
原始问题：在大量规则和参数中保留历史最好者，会把随机好运误认为有效性。  
核心原则：区分样本内观察与样本外期望；记录尝试数量、预先选择规则，多重尝试会放大虚假发现。  
适用于本项目的原因：用户要求诊断并优化策略，若在全历史上反复调参，600 USDT 收益估计会被严重高估。  
应转换成的代码或测试规则：回测报告写入 `research_protocol`；默认只评估一个预定义参数集；完整历史只做最终一次审计，不自动选择最优参数。  
是否进入 v0.1.3：部分进入；数据挖掘偏差校正放入 backlog。  
不采用的部分及原因：不在本版本实现大规模规则搜索或显著性校正框架。

### Pardo：精确定义、鲁棒性、成本与监控

来源书籍：*The Evaluation and Optimization of Trading Strategies*, 2nd ed.  
章节：第 6 章 “Historical Simulation”、第 7 章 “The Trading Strategy”  
页码或电子书位置：印刷页 113–115、150–152 / PDF 页 146–148、183–185  
原始问题：模糊策略、乐观成交与遗漏成本会制造不可实现的回测。  
核心原则：先把策略写成精确规格；模拟必须采用现实且偏保守的佣金、滑点、限价与跳空假设。  
适用于本项目的原因：下一根开盘、tick 舍入、同根 K 线止损/止盈顺序会直接改变结果。  
应转换成的代码或测试规则：买入向上取 tick、卖出向下取 tick；同根先止损；所有假设进入 `backtest-assumptions.md` 并测试。  
是否进入 v0.1.3：是。  
不采用的部分及原因：真实订单路由、期货和杠杆执行不适用。

来源书籍：同上  
章节：第 8–11 章参数研究与 Walk-Forward；第 13 章过拟合；第 14 章实盘监控  
页码或电子书位置：印刷页 158、237–255、281–293、301 起 / PDF 页 191、270–288、314–326、334 起  
原始问题：单点参数、重复优化和把固定时间切分冒充滚动验证，都会夸大鲁棒性。  
核心原则：关注连续参数邻域和样本外稳定性；真正 walk-forward 由滚动估计窗与后续未见测试窗组成；运行表现需与预先基准比较。  
适用于本项目的原因：现有 60/20/20 只是一次时间切分。  
应转换成的代码或测试规则：名称固定为 `chronological_holdout_split`；参数邻域只做敏感度、不自动挑最好；制定停用阈值。  
是否进入 v0.1.3：协议与命名进入；真正 walk-forward 为 v0.2.0 backlog。  
不采用的部分及原因：本版本不进行自动重优化，也不把 BTC/ETH 扩成多市场搜索池。

### Chan：前视偏差、成本与执行差异

来源书籍：*Quantitative Trading*，附件第一版  
章节：第 2 章策略问题；第 3 章 Backtesting；第 5 章 Execution Systems  
页码或电子书位置：印刷页 22–26、51–54、89–94 / PDF 页 44–48、73–76、111–116  
原始问题：未来数据、遗漏成本、数据源/模拟与实际执行差异使回测失真。  
核心原则：历史变量必须滞后到当时可见；截断未来数据后早期信号应不变；成本和滑点可把盈利策略变成亏损策略；记录执行假设。  
适用于本项目的原因：项目用 1d/4h/1h 严格重放，最容易在周期收盘和下一开盘处产生前视偏差。  
应转换成的代码或测试规则：三周期只取已收盘数据；修改未来 K 线不得改变历史信号；下一根开盘前不得成交；成本敏感度必须报告。  
是否进入 v0.1.3：是。  
不采用的部分及原因：附件不是第二版；真实自动执行、券商/API 私有连接及做空内容被拒绝。固定 BTC/ETH 不能证明不存在全市场幸存者偏差，只能明确样本边界。

### Vince：风险单位、回撤与组合风险

来源书籍：*The Mathematics of Money Management*  
章节：第 2 章风险、回撤与组合；第 5 章多同时持仓  
页码或电子书位置：印刷/PDF 页 18、28、34、66–72  
原始问题：仓位过大和多个同时头寸会让资金曲线的回撤与破产风险非线性恶化。  
核心原则：用可承受损失定义风险单位；同时头寸必须作为组合共同约束；回撤深度和持续时间都需要监控。  
适用于本项目的原因：BTC 与 ETH 可同时产生候选，单笔各自合规不代表组合开放风险合规。  
应转换成的代码或测试规则：分别记录初始风险、剩余开放风险、组合开放风险、日实现亏损和当前回撤；现金、部署比例和 2% 组合风险共同限制开仓。  
是否进入 v0.1.3：是。  
不采用的部分及原因：明确拒绝 optimal-f、激进 Kelly、杠杆最优增长、根据近期胜率放大仓位和亏损加仓。

### DDIA：事件事实、物化状态、幂等与原子性

来源书籍：*Designing Data-Intensive Applications*, 2nd ed. Early Release  
章节：第 1 章 “Systems of Record and Derived Data”；第 3 章事件日志；第 5 章演化与请求；第 8 章事务  
页码或电子书位置：`OEBPS/ch01.html#sec_introduction_derived`；`OEBPS/ch03.html#sec_datamodels_events`；`OEBPS/ch05.html#id101`、段落 `#id107`；`OEBPS/ch08.html#sec_transactions_acid_atomicity`、`#sec_transactions_compare_and_swap`  
原始问题：多个状态文件分别写入会产生半完成状态；重试可能重复执行；状态结构必须随版本演化并可恢复。  
核心原则：追加事件是事实记录，物化视图可由事实确定性重放；命令先校验再成为事件；重试必须有去重标识；原子写入与版本条件防止部分提交和丢失更新。  
适用于本项目的原因：风险、现金、持仓、pending 计划和已处理 ID 必须在一个账户不变量下变化。  
应转换成的代码或测试规则：`apply_command` 为唯一写入口；命令含 `command_id/timestamp/expected_state_version`；JSON 物化状态 + JSONL 事件；锁、WAL、fsync、原子替换、重放核对和 schema 迁移测试。  
是否进入 v0.1.3：是，采用单机文件事务的有限实现。  
不采用的部分及原因：不引入分布式数据库、复制、共识或“精确一次”宣传；本项目只承诺单机锁内的幂等命令语义。

### Nygard：有限失败、熔断与可观测性

来源书籍：*Release It!*, 2nd ed.  
章节：第 4 章 Cascading Failures；第 5 章 Stability Patterns  
页码或电子书位置：印刷页 49–50、80、91–108 / PDF 页 61–63、92、103–120；连接/读取超时建议见 PDF 页 55  
原始问题：无超时或无界重试会耗尽资源并把依赖故障放大为级联故障。  
核心原则：连接和读取均要超时；重试有上限并退避；连续失败触发 circuit breaker；依赖不可用时失败关闭或明确降级；日志必须支持定位。  
适用于本项目的原因：一次 OpenClaw 调用不应在 Binance 公共端点失败时持续轰击；行情失败与交易规则失败的安全后果不同。  
应转换成的代码或测试规则：connect/read timeout、最大尝试和总耗时；短期开路；行情异常 `no_trade`，规则异常不输出仓位；结构化无敏感日志。  
是否进入 v0.1.3：是，单进程简单熔断。  
不采用的部分及原因：不增加微服务基础设施、远程运维控制台或复杂集群隔离。

### Kaufman：技术规则的补充检查

来源书籍：*Trading Systems and Methods*, 6th ed.（需求原指定第五版）  
章节：第 3 章图表与支撑阻力；第 23 章风险控制；交易成本、滑点和鲁棒性相关章节  
页码或电子书位置：PDF 页 239–246（支撑阻力）、1456–1464（成本与滑点）、目录 PDF 页 68（波动率移动止损）、PDF 页 116–119（简化与过拟合提示）  
原始问题：技术规则容易堆叠重复指标，成本和参数敏感性容易被忽略。  
核心原则：趋势、波动和水平区域必须系统定义；成本估计应保守；简单、跨邻域稳定的规则优于精调。  
适用于本项目的原因：现有 EMA/MACD/ATR/RSI 已足够表达当前假设，重点是定义和验证，而不是继续加指标。  
应转换成的代码或测试规则：保留现有指标集合；新增指标需证明解决已知缺陷、低冗余且样本外有益；ATR 仅作为尺度与移动止损，不作为收益保证。  
是否进入 v0.1.3：部分采用。  
不采用的部分及原因：不加入随机指标、指标变体、期货/做空/杠杆、复杂滤波器和大量形态。

## 书籍—需求—代码映射

| 书籍原则 | 项目风险 | 设计决策 | 对应模块 | 对应测试 | 当前状态 |
|---|---|---|---|---|---|
| 客观、可编程规则 | 自然语言条件不可复现 | 规则、边界、缺失值集中定义 | `strategy.py`, `signal.py` | `test_objective_rules.py` | partially_adopted |
| 记录研究尝试 | 只展示最佳参数 | 报告包含 `research_protocol` | `models.py`, `backtest.py` | `test_research_protocol.py` | backlog |
| 样本外与数据挖掘偏差 | 全历史调参虚高 | 预定义参数；固定留出；不自动选优 | `backtest.py` | `test_research_protocol.py` | partially_adopted |
| 精确策略规格 | 实时/回测漂移 | 共用 `evaluate_setup_at_time` | `strategy.py` | `test_strategy_consistency.py` | adopted |
| 保守成交与成本 | tick 舍入制造好成交 | 买向上、卖向下；手续费/滑点 | `execution.py`, `backtest.py` | `test_execution_conservatism.py` | backlog |
| 真正 Walk-Forward 定义 | 60/20/20 名称误导 | 改名 `chronological_holdout_split`；滚动研究延后 | `models.py`, `backtest.py` | `test_research_protocol.py` | backlog |
| 参数邻域稳定性 | 单点参数过拟合 | 固定邻域，不自动挑最好 | 研究协议文档 | 未来研究命令测试 | backlog |
| 截断未来数据一致 | 前视偏差 | 仅使用已收盘三周期 K 线 | `strategy.py`, `backtest.py` | `test_no_lookahead.py` | adopted |
| 风险单位与组合风险 | BTC/ETH 风险叠加 | 2% aggregate open risk 硬限制 | `account_state.py` | `test_account_risk.py` | backlog |
| 拒绝 optimal-f/Kelly | 仓位和回撤爆炸 | 固定 1%，硬上限 3%，无杠杆 | `risk.py`, config | `test_position_sizing.py` | rejected |
| 事件为事实、状态为物化视图 | 多文件半提交 | 统一命令处理器 + 事件日志 | `account_state.py` | `test_account_state.py` | backlog |
| 命令幂等和版本条件 | 重试重复扣款/平仓 | command ID 去重 + expected version | `account_state.py` | `test_account_state.py` | backlog |
| 原子与崩溃恢复 | 损坏或状态/日志不一致 | 锁、WAL、fsync、原子替换、恢复 | `account_store.py` | `test_account_store_recovery.py` | backlog |
| 有限超时、退避、熔断 | Binance 故障级联 | 总耗时上限与 circuit open | `data.py` | `test_reliability.py` | backlog |
| 明确降级 | 规则缺失却给仓位 | 行情失败 no_trade；规则失败无仓位 | `analysis.py`, `data.py` | `test_data_gates.py` | partially_adopted |
| 简单指标优于堆叠 | 指标冗余和过拟合 | 不新增指标，新增需证据审查 | `indicators.py` | `test_indicators.py` | adopted |

状态只表示当前代码库在文档首次生成时的事实；完成实现后必须同步更新，不得把“书中提出”写成“代码已验证”。
