## duplicates：按原样迁移（wording=as-is）

## features/review/ComparisonLedger.tsx
duplicates-comparison-ledger-field = 字段
duplicates-comparison-ledger-earlier-posting = 较早的招聘信息
duplicates-comparison-ledger-newer-posting = 较新的招聘信息
duplicates-comparison-ledger-fields = 个字段
duplicates-comparison-ledger-same = 相同
duplicates-comparison-ledger-different = 不同
duplicates-comparison-ledger-side-by-side = 并排对比
duplicates-comparison-ledger-show-matching-fields = { $choice ->
    [yes] 隐藏 { $length } 个相同字段
   *[no] 显示 { $length } 个相同字段
}
duplicates-comparison-ledger-show = { $choice ->
    [yes] 隐藏
   *[no] 显示
}
duplicates-comparison-ledger-title = 职位名称
duplicates-comparison-ledger-status = 状态
duplicates-comparison-ledger-level = 级别
duplicates-comparison-ledger-family = 职能
duplicates-comparison-ledger-locations = 地点
duplicates-comparison-ledger-workplace = 办公方式
duplicates-comparison-ledger-department = 部门
duplicates-comparison-ledger-team = 团队
duplicates-comparison-ledger-comp-est = 估算总薪酬
duplicates-comparison-ledger-disclosed-band = 公布的薪酬区间
duplicates-comparison-ledger-first-seen = 首次发现
duplicates-comparison-ledger-last-observed = 最近发现
duplicates-comparison-ledger-age = 发布时长
duplicates-comparison-ledger-links = 链接
duplicates-comparison-ledger-role-details = 职位详情
duplicates-comparison-ledger-role-details-of = { $side ->
    [earlier] 职位详情，较早的招聘信息
   *[newer] 职位详情，较新的招聘信息
}
duplicates-comparison-ledger-careers-page = 招聘页面
duplicates-comparison-ledger-careers-page-of = { $side ->
    [earlier] 招聘页面，较早的招聘信息
   *[newer] 招聘页面，较新的招聘信息
}
duplicates-comparison-ledger-not-disclosed = 未公布

## features/review/DecisionConsole.tsx
duplicates-decision-console-ai-judgment-unavailable = AI 判断不可用
duplicates-decision-console-ai = AI
duplicates-decision-console-ai-judgment = AI 判断
duplicates-decision-console-tokens-ms = { $model } · { $value } 个 token · { $wall_time_ms } 毫秒
duplicates-decision-console-current = 当前
duplicates-decision-console-make-a-decision = 做出决定
duplicates-decision-console-ask-the-model = 询问模型
duplicates-decision-console-get-an-optional-independent-assessment = 获取一份可选的独立评估
duplicates-decision-console-ask-ai = { $choice ->
    [v1] 分析中…
    [v2] 重新询问
   *[v3] 询问 AI
}
duplicates-decision-console-uncertain = { $choice ->
    [v1] 可能是同一职位
    [v2] 可能是不同职位
   *[v3] 不确定
}
duplicates-decision-console-local-model-assessment = 本地模型评估
duplicates-decision-console-make-a-decision-2 = { $choice ->
    [yes] 更改决定
   *[no] 做出决定
}
duplicates-decision-console-your-judgment = { $choice ->
    [yes] 更改你的决定
   *[no] 你的判断
}
duplicates-decision-console-what-is-the-relationship = { $choice ->
    [yes] 重新归类这一对
   *[no] 它们是什么关系？
}

## features/review/DescriptionComparison.tsx
duplicates-description-comparison-descriptions = 职位描述
duplicates-description-comparison-no-differing-passages = 没有不同的段落。
duplicates-description-comparison-changed-passage = 已更改的段落
duplicates-description-comparison-description-comparison = 职位描述对比
duplicates-description-comparison-differences = { $choice ->
    [same] 未发现段落层面的差异。
   *[differ] { $count } 处段落不同。琥珀色段落仅出现在该{ -posting(num: "one") }中。
}
duplicates-description-comparison-show-differences-only = { $choice ->
    [yes] 显示完整描述
   *[no] 仅显示差异
}
duplicates-description-comparison-description = 职位描述

## features/review/ReviewHistory.tsx
duplicates-review-history-decided = 已决定
duplicates-review-history-every-judgment-ready-to-revisit = 所有判断，随时可以回看
duplicates-review-history-of = { $length } / { $value }
duplicates-review-history-try-another-title-requisition-id = 试试其他职位名称、职位编号或筛选条件。
duplicates-review-history-system-score = 系统评分
duplicates-proposed-as = { $kind ->
    [twin] 识别为相关职位
   *[duplicate] 识别为同一职位
}
duplicates-review-history-reviewed = 已审核
duplicates-review-history-revised = 已修改 { $count } 次
duplicates-review-history-decided-2 = 已决定
duplicates-review-history-search-decisions = 搜索决定
duplicates-review-history-search-title-or-requisition-id = 搜索职位名称或职位编号
duplicates-review-history-filter-decisions = 筛选决定
duplicates-review-history-all-decisions = 全部决定
duplicates-review-history-no-matching-decisions = 没有匹配的决定
duplicates-review-history-loading = 正在加载决定…
duplicates-review-history-load-failed = 无法加载决定

## features/review/ReviewScreen.tsx
duplicates-review-screen-every-pair-matched-automatically-has = 所有自动匹配的组合都已核对。你可以在“已决定”中回看任意一对。
duplicates-review-screen-open-decided = 打开已决定
duplicates-review-screen-every-close-pair-on-your = 你的雷达上每一对相近的职位都已有决定。你可以在“已决定”中回看任意一对。
duplicates-review-screen-pairs-left-in-the-queue = { $choice ->
    [yes] { $total } 对自动匹配，尚未核对
   *[no] 队列中还剩 { $total } 对
}
duplicates-review-screen-system-similarity = 系统相似度
duplicates-review-screen-undone-your-later-decision-on = 已撤销。你之后对这些招聘信息做出的决定保持不变。
duplicates-review-screen-could-not-undo = 无法撤销：{ $message }
duplicates-review-screen-marked-as = { $decision ->
    [duplicate] 已标记为同一职位
    [twin] 已标记为相关职位
   *[different] 已标记为不同职位
}
duplicates-review-screen-undo = 撤销
duplicates-review-screen-could-not-record-the-verdict = 无法记录判定：{ $message }
duplicates-review-screen-duplicate-review-views = 重复项审核视图
duplicates-review-screen-queue = 队列
duplicates-review-screen-matched-automatically = 自动匹配
duplicates-review-screen-nothing-to-check = 没有需要核对的内容
duplicates-review-screen-queue-clear = 队列已清空
duplicates-review-screen-none-found = 尚未发现重复项
duplicates-review-screen-none-found-why = 一家公司常会把同一个{ -role(num: "one") }发布不止一次：发在多个城市，或隔一段时间再发。扫描发现两条看起来相似的{ -posting(num: "other") }时，它们会在这里等你判断：是同一职位、相关职位，还是不同职位。
duplicates-review-screen-none-found-yet = 暂时没有需要决定的内容。扫描发现新的组合后，会显示在这里。
duplicates-review-screen-candidate-pair = 候选组合
duplicates-review-screen-system-similarity-2 = 系统相似度 { $score }
duplicates-review-screen-about-system-similarity = 关于系统相似度
duplicates-review-screen-loading = 正在加载队列…
duplicates-review-screen-load-failed = 无法加载队列

## features/review/decision.ts
duplicates-decision-different-roles = 不同职位
duplicates-decision-two-different-roles-keep-both = 两个不同的职位。两个都保留。
duplicates-decision-related-roles = 相关职位
duplicates-decision-related = 相关
duplicates-decision-close-but-not-the-same = 相近但不相同：相关职位，存在实际差异。
duplicates-decision-same-role = 同一职位
duplicates-decision-duplicate = 重复
duplicates-decision-one-role-two-postings-listed = 一个职位，两条招聘信息：以不同的职位编号再次发布。

## features/review/DescriptionComparison.tsx
duplicates-description-comparison-description-2 = { $label }的职位描述
duplicates-reason-same-title = 职位名称相同
duplicates-reason-titles-alike = 职位名称相似度 { $pct }%
duplicates-reason-descriptions-alike = 描述相似度 { $pct }%
duplicates-reason-listed-at-once = 同时在招
duplicates-reason-same-department = 部门相同
duplicates-reason-department-unknown = 其中一则未注明部门
duplicates-reason-passages-differ = { $earlier } 段仅见于较早的，{ $later } 段仅见于较新的
