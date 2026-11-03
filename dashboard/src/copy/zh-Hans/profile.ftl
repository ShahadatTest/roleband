## profile：简体中文翻译（AI 初稿，待审校）

## features/scope/ExperiencePage.tsx
profile-experience-page-back-to-summary = 返回摘要
profile-experience-page-your-experience = 你的经历
profile-experience-page-coming-soon = 即将推出
profile-experience-page-cv-upload-isn-t-available = 暂不支持上传简历。之后你可以在这里添加简历，并确认用于核对每个职位要求的经历。

## features/scope/NewMark.tsx
profile-new-mark-new = 新
profile-new-mark-added-since-you-last-saved = 自你上次保存后新增

## features/scope/PersonaRail.tsx
profile-persona-rail-level = 级别
profile-persona-rail-tuned-for = 设定目标

## features/scope/ProfileSuggestions.tsx
profile-suggestions-you-marked-there-not-for = 你把那里的 { $dismissed_wrong_domain } 标为不适合我：领域不对
profile-suggestions-more-not-for-me-with = 另有 { $dismissed_other } 个标为不适合我，未注明原因
profile-suggestions-in-progress = { $pursued }正在推进
profile-suggestions-role-there-is = 个该领域职位
profile-suggestions-roles-there-are = 个该领域职位
profile-suggestions-you-saved-there = 你保存了该领域的 { $favorited }
profile-suggestions-followed-company-sector-points = 个已关注公司的行业
profile-suggestions-followed-company-sectors-point = 个已关注公司的行业
profile-suggestions-your-aim-names-it = 你的目标提到了它
profile-suggestions-turned-on-on-your-radar = { $choice ->
    [yes] 已关闭 { $display } · 你的雷达上有 { $in_scope_changed } 已更新
   *[no] 已开启 { $display } · 你的雷达上有 { $in_scope_changed } 已更新
}
profile-suggestions-could-not-apply-the-suggestion = 无法应用该建议。它仍待处理。
profile-suggestions-could-not-dismiss-the-suggestion = 无法忽略该建议。请重试。
profile-suggestions-could-not-load = 无法加载你的建议调整。请重试。
profile-suggestions-suggested-adjustments = 建议的调整
profile-suggestions-turn-on = { $choice ->
    [yes] 关闭 { $display }？
   *[no] 开启 { $display2 }？
}
profile-suggestions-inferred-from-your-recent-activity = { $choice ->
    [yes] 因为 { $join }。
   *[no] 根据你最近的操作推断。
}
profile-suggestions-accept-turn-on = { $choice ->
    [yes] 接受：关闭 { $display }
   *[no] 接受：开启 { $display }
}
profile-suggestions-turn-it-on = { $choice ->
    [yes] 关闭
   *[no] 开启
}
profile-suggestions-dismiss-suggestion-about = 忽略关于 { $display } 的建议
profile-suggestions-no-thanks = { $choice ->
    [yes] 保持开启
   *[no] 不用了
}

## features/scope/ScopeGuide.tsx
profile-scope-guide-how-your-radar-works = 你的雷达如何运作
profile-scope-guide-radar-guide = 雷达指南
profile-scope-guide-how-your-radar-works-2 = 你的雷达如何运作
profile-scope-guide-five-answers-decide-what-reaches = 五个回答决定哪些内容进入你的雷达。只有全部符合的职位才会出现。
profile-scope-guide-decide = 决定
profile-scope-guide-sharpen-optional = 细化（可选）
profile-scope-guide-your-radar = 你的雷达
profile-scope-guide-when-changes-apply = 更改何时生效
profile-scope-guide-save-applies-your-answers-to = 保存后，你的回答会立即应用到已收集的职位。只有新回答才涵盖的职位会在下次扫描时出现。
profile-scope-guide-about-the-counts = 关于计数
profile-scope-guide-progress-shows-how-many-of = 进度显示根据最近一次计数，每个回答会保留你关注公司的多少个职位。在完成第一次计数前，显示为“暂无计数”，点击“立即计数”即可开始。
profile-scope-guide-nothing-hidden-by-a-guess = 不会因猜测而隐藏
profile-scope-guide-a-role-we-haven-t = 尚未归入任何领域的职位会一直留在你的雷达上。
profile-scope-guide-career-track-level-discipline-and = 职业路线、级别、职能和地点都匹配后，职位才会出现在你的雷达上。
profile-scope-guide-opportunity-radar = 机会雷达
profile-scope-guide-saving-applies-to-roles-already = 保存后会立即应用到你雷达上已有的职位。新纳入的职能会在下次完整扫描后出现。
profile-scope-guide-how-your-radar-works-3 = 你的雷达如何运作
profile-scope-guide-close-guide = 关闭指南
profile-scope-guide-career-track = 职业路线
profile-scope-guide-how-you-contribute = 你如何贡献
profile-scope-guide-where-you-are-and-aim = 你的现状和目标
profile-scope-guide-discipline = 职能
profile-scope-guide-the-work-you-want = 你想做的工作
profile-scope-guide-location = 地点
profile-scope-guide-where-it-can-be-based = 工作可以在哪里

## features/scope/ScopeSection.tsx
profile-scope-section-company-exclusions = 公司排除项
profile-scope-section-matching-teams-and-departments-stay = 匹配的团队和部门不会出现在你的雷达上。
profile-scope-section-remove = 移除
profile-scope-section-business-functions = 业务职能
profile-scope-section-industries = 行业
profile-scope-section-roles = { $count ->
   *[other] { $count2 } 个职位
}
profile-scope-section-could-not-restore-that-exclusion = 无法恢复该排除项。请重试。
profile-scope-section-exclusion-restored-left-your-radar = 排除项已恢复 · { $in_scope_changed } 再次离开你的雷达。
profile-scope-section-exclusion-removed-back-on-your = 排除项已移除 · { $in_scope_changed } 回到你的雷达上。
profile-scope-section-undo = 撤销
profile-scope-section-could-not-remove-that-exclusion = 无法移除该排除项。请重试。
profile-scope-section-company-exclusions-2 = 公司排除项
profile-scope-section-remove-exclusion-at = 移除 { $company } 的排除项 { $value }

## features/scope/StageDimmer.tsx
profile-stage-dimmer-you-are-here = 你在这里
profile-stage-dimmer-aiming-for = 目标
profile-stage-dimmer-roles = { $slug } 个职位
profile-stage-dimmer-what-this-means-at-each = 在每家公司的含义
profile-stage-dimmer-this-kind-of-role-tops = { $choice ->
    [yes] 这类职位在这里起点更高
   *[no] 这类职位在这里上限更低
}
profile-stage-dimmer-gated = { $range ->
    [from] 这类职位从{ $from }起步。
    [to] 这类职位最高到{ $to }。
   *[both] 这类职位从{ $from }到{ $to }。
}
profile-stage-dimmer-click-your-level-today = { $choice ->
    [v1] 现在选择你的目标级别
    [v2] 选择任意级别重新开始
   *[v3] 选择你当前的级别
}
profile-stage-dimmer-level-range = 级别范围
profile-stage-dimmer-your-level-today = 你当前的级别
profile-stage-dimmer-level-you-re-aiming-for = 你的目标级别
profile-stage-dimmer-companies = { $count ->
   *[other] 家公司
}

## features/scope/WelcomeWizard.tsx
profile-welcome-wizard-back = 返回

## features/scope/useScopeDraft.ts
profile-use-scope-draft-couldn-t-load-your-radar = 无法加载你的雷达。请重试。
profile-use-scope-draft-couldn-t-save-your-radar = 无法保存你的雷达。请重试。
profile-use-scope-draft-refreshing-role-counts-this-reads = 正在重新统计职位。此操作只读取招聘页面，你雷达上的职位不会改变。
profile-use-scope-draft-that-refresh-was-deferred-because = 该计数会等当前扫描或计数结束后再进行。
profile-use-scope-draft-couldn-t-count-roles-at = 无法统计你关注公司的职位。请重试。

## features/scope/walk/PayFloorRow.tsx
profile-pay-floor-row-pay-floor = 最低基本工资
profile-pay-floor-row-a-year-base = 每年
profile-pay-floor-row-cancel = 取消
profile-pay-floor-row-checking = 检查中…
profile-pay-floor-row-couldn-t-read-your-pay = 无法读取你的最低基本工资。
profile-pay-floor-row-retry = 重试
profile-pay-floor-row-compared-where-pay-is-stated = 仅在招聘信息公布了基本工资时比较。
profile-pay-floor-row-no-roles-are-hidden = 不会隐藏任何职位。
profile-pay-floor-row-enter-a-yearly-amount-like = 输入年度金额，例如 250,000 或 250k。
profile-pay-floor-row-could-not-save-the-pay = 无法保存最低基本工资。请重试。
profile-pay-floor-row-pay-floor-2 = 最低基本工资
profile-pay-floor-row-lowest-yearly-base-pay = 最低年基本工资
profile-pay-floor-row-currency = 货币
profile-pay-floor-row-save-floor = { $choice ->
    [yes] 保存中…
   *[no] 保存最低基本工资
}
profile-pay-floor-row-set-floor = 设定最低基本工资
profile-pay-floor-row-could-not-remove-the-pay = 无法移除最低基本工资。请重试。
profile-pay-floor-row-retry-reading-the-pay-floor = 重新读取最低基本工资
profile-pay-floor-row-add-a-pay-floor = { $choice ->
    [yes] 调整最低基本工资
   *[no] 添加最低基本工资
}
profile-pay-floor-row-set-your-pay-floor = { $choice ->
    [yes] 每年 { $amount }
   *[no] 设置你的最低基本工资
}
profile-pay-floor-row-minimum-yearly-base-pay = { $choice ->
    [yes] 调整
   *[no] 最低年基本工资
}

## features/scope/walk/ProgressRail.tsx
profile-progress-rail-focus-your-radar = 聚焦你的雷达
profile-progress-rail-all-roles = 所有职位
profile-progress-rail-no-count-yet = 暂无计数。
profile-progress-rail-of-all-roles = 占所有职位
profile-progress-rail-choose-your-role-level-and = 选择职业路线、级别和地点，看看哪些合适。
profile-progress-rail-review-changes = 查看更改
profile-progress-rail-more-are-added-when-the = { $choice ->
    [yes] 当前扫描结束时，或每家公司下次扫描时，最多还会新增 { $arriving } 个。
   *[no] 当前扫描结束时会新增更多。
}
profile-progress-rail-text = { $choice ->
    [yes] { " " }每家公司下次扫描时，最多还会新增 { $arriving } 个。
   *[no] { "" }
}
profile-progress-rail-text-2 = { $choice ->
    [yes] ，例如 { $joinAnd }
   *[no] { "" }
}
profile-progress-rail-your-board-goes-from-to = { $choice ->
    [yes] 你的雷达保持 { $now }。
   *[no] 你的雷达从 { $now2 } 变为 { $after }。
}
profile-progress-rail-of-them-from-earlier-scans = 其中 { $adds } 个来自之前的扫描{ $like }。
profile-progress-rail-a-scan-is-running-from = 扫描正在进行：之前扫描中的 { $later } 会在结束时加入{ $like }。
profile-progress-rail-more-join-as-each-company = 每家公司下次扫描时会加入更多。
profile-progress-rail-your-progress = 你的进度
profile-progress-rail-count-now = { $choice ->
    [yes] 正在开始…
   *[no] 立即计数
}
profile-progress-rail-save-to-count-the-roles = { $choice ->
    [yes] 正在统计 { $pendingPlaces } 的职位…
   *[no] 保存后统计 { $pendingPlaces2 } 的职位。
}
profile-progress-rail-roles-match = { $count ->
   *[other] 个职位匹配
}
profile-progress-rail-roles-when-you-save = { $choice ->
    [yes] 保存后无变化
   *[no] 个职位（保存后）
}
profile-progress-rail-we-ll-know-after-the = { $choice ->
    [v1] 保存后更新
    [v2] 保存后无变化
    [v3] 个职位（保存后）
   *[v4] 下次计数后才能知道
}
profile-progress-rail-save = { $choice ->
    [yes] 保存中…
   *[no] 保存
}
profile-progress-rail-roles = { $count ->
   *[other] 个职位
}
profile-progress-rail-roles-are = { $count ->
   *[other] 个职位
}
profile-progress-rail-text-3 = { $choice ->
    [yes] ，其中 { $promoted } 个来自之前的扫描。
   *[no] 。
}
profile-progress-rail-saved-on-your-board-now = { $choice ->
    [yes] 已保存。你的雷达上有 { $changed } { $value }发生变化。
   *[no] 已保存。你的雷达上现在有 { $onBoard } { $value2 }{ $value3 }{ $arriving }
}

## features/scope/walk/RadarPyramid.tsx
profile-radar-pyramid-illustrative-funnel-each-percentage-is = 示意漏斗。每个百分比表示该回答之后剩余的比例。
profile-radar-pyramid-after-the-first-three-answers = 完成前三个回答后
profile-radar-pyramid-locked = 已锁定
profile-radar-pyramid-not-answered-yet = { $choice ->
    [yes] 任意，未缩小范围
   *[no] 尚未回答
}
profile-radar-pyramid-choose = { $choice ->
    [yes] 任意
   *[no] 选择
}
profile-radar-pyramid-answered-no-count-yet = 已回答，暂无计数
profile-radar-pyramid-no-count = 无计数
profile-radar-pyramid-counting = 计数中
profile-radar-pyramid-counted-after-you-save = 保存后计数
profile-radar-pyramid-save-first = 请先保存
profile-radar-pyramid-keeps = 保留 { $kept }，{ $kept2 }
profile-radar-pyramid-what-each-answer-keeps = 每个回答保留的内容
profile-radar-pyramid-url-fill = url(#{ $id }-fill)

## features/scope/walk/RolesStep.tsx
profile-roles-step-pick-a-kind-of-role = 请先选择一条职业路线。
profile-roles-step-nothing-called-under = { $label } 下没有名为“{ $query }”的内容。
profile-roles-step-filter-roles = 筛选职位
profile-roles-step-filter-roles-2 = 筛选职位…
profile-roles-step-craft-for = { $label } 的专业方向
profile-roles-step-roles = { $count ->
   *[other] { $count2 } 个职位 · { $examples }
}

## features/scope/walk/SubjectsStep.tsx
profile-subjects-step-choose-a-list-then-tick = 选择一个列表，然后勾选要放入的内容
profile-subjects-step-nothing-called = 没有名为“{ $query }”的内容。
profile-subjects-step-removes-of-the-roles-you = { $avoid } { $subject } 会从你在 { $label } 下选择的 { $of } 个职位中移除 { $dropped } 个。如果这不是你的本意，请取消勾选其中一项。
profile-subjects-step-of-your-roles-aren-t = 你的 { $of } 个职位中有 { $untagged } 个尚未归入任何领域。无论你选择什么，它们都会留在你的雷达上。
profile-subjects-step-technologies = 技术
profile-subjects-step-you-ll-see-roles-about = 你会看到这些领域中的职位，以及尚未归入任何领域的职位。
profile-subjects-step-roles-about-these-drop-off = 与这些相关的职位会被去掉，即使也符合你的某个兴趣。
profile-subjects-step-switch-to-this = { $choice ->
    [yes] 正在选择
   *[no] 切换到此项
}
profile-subjects-step-picked = { $choice ->
    [yes] 暂无
   *[no] 已选 { $picked } 个
}
profile-subjects-step-filter-interests = 筛选领域
profile-subjects-step-filter-interests-2 = 筛选领域…

## features/scope/walk/SummaryStep.tsx
profile-summary-step-summary = 摘要
profile-summary-step-adjust = 调整
profile-summary-step-what-it-keeps = 保留的内容
profile-summary-step-no-count-yet-once-a = 暂无计数。完成一次扫描后，这里会显示每个回答保留多少个职位。
profile-summary-step-counting-the-roles-in = 正在统计 { $pendingPlaces } 的职位…
profile-summary-step-save-to-count-the-roles = 保存后统计 { $pendingPlaces } 的职位。
profile-summary-step-add-your-cv = 添加你的简历
profile-summary-step-role = 职业路线
profile-summary-step-where = 地点
profile-summary-step-which-roles = 职能
profile-summary-step-interests = 领域
profile-setup-unfinished = 设置尚未完成，你的雷达正在使用初始设置。
profile-setup-finish = 完成设置
profile-setup-later = 稍后设置
profile-setup-title = 设置你的雷达
profile-setup-step = 设置，第 { $step } 步，共 { $count } 步
profile-setup-companies-tab = 公司
profile-setup-companies-title = 你的雷达应该看向哪里？
profile-setup-companies-note = 你会先从知名公司开始。现在或之后随时都可以关注更多公司。
profile-setup-summary-later = 之后可以随时在个人资料中修改任何回答。
profile-summary-step-nothing-picked-yet = 尚未选择
profile-summary-step-any-role-that-fits = 任何合适的职位
profile-summary-step-none-yet = 任何领域
profile-summary-step-not-set = 未设置
profile-summary-step-adjust-2 = 调整{ $label }
profile-summary-step-after-you-save = { $choice ->
    [yes] 计数中
   *[no] 保存后
}
profile-summary-step-see-your-radar = { $choice ->
    [v1] 保存中…
    [v2] 保存并查看你的雷达
   *[v3] 查看你的雷达
}

## features/scope/walk/Walk.tsx
profile-walk-locked-reason = 回答前三个问题后，其余步骤才会开放。
profile-walk-optional = 可选
profile-walk-skip = 跳过
profile-walk-summary = 摘要
profile-walk-what-your-radar-looks-for = 你的雷达在找什么
profile-walk-steps = 步骤
profile-walk-continue-reason-accountable = 至少选择一条职业路线才能继续。
profile-walk-continue-reason-level = 选择你的当前级别和目标级别才能继续。
profile-walk-continue-reason-where = 至少添加一个地点才能继续。
profile-walk-continue = { $choice ->
    [yes] 完成
   *[no] 继续
}

## features/scope/walk/WhereStep.tsx
profile-where-step-go-worldwide = 全球范围
profile-where-step-nothing-called-try-a-city = 没有名为“{ $query }”的地点。试试城市或国家。
profile-where-step-include-all = 全部纳入
profile-where-step-nothing-called-in = { $display } 中没有名为“{ $inside }”的地点。
profile-where-step-haven-t-been-scanned-for = { $count ->
   *[other] { $companies } 尚未针对 { $few } 进行扫描。
}
profile-where-step-replaces-the-places-you-ve = 将你添加的地点替换为任意地点
profile-where-step-in-choose-to-narrow-to = { $choice ->
    [yes] 已添加
   *[no] 位于 { $display }，选择以缩小到此处
}
profile-where-step-add-back = 重新添加 { $name }
profile-where-step-excepted-add-it-back = 已排除，可重新添加
profile-where-step-add = { $choice ->
    [yes] 将 { $display } 缩小到 { $name }
   *[no] 添加 { $name2 }
}
profile-where-step-add-2 = 添加 { $display }
profile-where-step-all-member-countries = { $choice ->
    [yes] 已添加
   *[no] 全部 { $length } 个成员国
}
profile-where-step-add-another-place = { $choice ->
    [v1] 你在哪里？
    [v2] 改为输入地点
   *[v3] 添加其他地点
}
profile-where-step-add-another-place-2 = { $choice ->
    [v1] 城市、国家或地区
    [v2] 改为输入地点
   *[v3] 添加其他地点
}
profile-where-step-places = 地点
profile-where-step-your-bases = 你的所在地
profile-where-step-any-country-any-city = 任何国家，任何城市。
profile-where-step-include-all-of = 纳入整个 { $display }
profile-where-step-choose-in = { $choice ->
    [yes] 完成选择 { $display } 中的{ $noun }
   *[no] 选择 { $display2 } 中的{ $noun2 }
}
profile-where-step-choose = { $choice ->
    [yes] 完成
   *[no] 选择{ $noun }
}
profile-where-step-how-far-from = 距离 { $display } 多远
profile-where-step-remove = 移除 { $display }
profile-where-step-filter-in = 筛选 { $display } 中的{ $noun }
profile-where-step-filter = 筛选{ $noun }
profile-where-step-and-more = { $join } 及其他 { $value } 个
profile-where-step-careers-sites-cant-be-searched = 暂时无法在 { $companies } 的招聘网站上搜索 { $places } 的{ -role(num: "other") }，因此那里的{ -role(num: "other") }不会出现在你的雷达上。

## features/scope/walk/walkModel.ts
profile-walk-model-leading-a-team = 带领团队
profile-walk-model-people-managers-and-directors-any = 经理和总监
profile-walk-model-leading-a-team-2 = 带领团队
profile-walk-model-owning-a-product-or-program = 负责产品
profile-walk-model-product-program-or-project-management = 产品、项目群、项目
profile-walk-model-owning-a-product-or-program-2 = 负责产品
profile-walk-model-hands-on-as-the-expert = 亲自动手，作为专家
profile-walk-model-engineer-scientist-designer-analyst = 工程、科学、设计
profile-walk-model-working-with-customers = 与客户合作
profile-walk-model-sales-partnerships-customer-success = 销售与客户成功
profile-walk-model-working-with-customers-2 = 与客户合作
profile-walk-model-anywhere = 任意地点
profile-walk-model-no-chosen-yet = 尚未选择{ $locations }
profile-walk-model-only = 仅限 { $names }
profile-walk-model-everywhere = { $choice ->
    [v1] 所有国家
    [v2] 所有城市
   *[v3] 所有地点
}
profile-walk-model-anywhere-in = { $display } 的任意地点
profile-walk-model-anywhere-in-2 = { $wide } 的任意地点
profile-walk-model-interested-in = 感兴趣
profile-walk-model-not-interested-in = 不感兴趣
profile-walk-model-or = { $join }或{ $parts }
profile-walk-model-not = 不含：{ $off }
profile-walk-model-from-to = { $choice ->
    [yes] { $first }
   *[no] 从 { $first2 } 到 { $last }
}
profile-walk-model-from-to-2 = { $count ->
    [1] { $display }
   *[other] 从 { $display2 } 到 { $display3 }
}

## features/scope/walk/walkSteps.ts
profile-walk-steps-what-kind-of-role-are = 你在找哪类职位？
profile-walk-steps-pick-one-or-more = 选择一个或多个。
profile-walk-steps-the-kind-of-work-you = 你负责的工作类型
profile-walk-steps-your-level = 你的级别
profile-walk-steps-today-and-the-one-you = 当前级别和目标级别。
profile-walk-steps-where-you-are-today-up = 从你当前所处到你的目标
profile-walk-steps-where-do-you-want-to = 你想在哪里工作？
profile-walk-steps-where-you-re-based-and = 你的所在地，以及为合适的职位你愿意走多远。
profile-walk-steps-your-bases-and-how-far = 你的所在地，以及你愿意走多远
profile-walk-steps-any-particular-roles = 有特定的职位吗？
profile-walk-steps-every-role-of-each-kind = 每类中的全部职位，或只选你挑出的职位。跳过即全部保留。
profile-walk-steps-particular-roles-or-any-that = 特定职位，或任何合适的职位
profile-walk-steps-anything-you-care-about-or = 有你在意或想避开的内容吗？
profile-walk-steps-the-fields-and-industries-the = 要寻找或避开的方向和行业。跳过则不排除任何内容。
profile-walk-steps-topics-to-look-for-and = 要寻找的领域，以及要去掉的领域

## features/scope/walk/walkModel.ts (by hand)
profile-walk-model-the-place = { $place }

## features/scope/ProfileSuggestions.tsx
profile-suggestions-there = { $length }指向这里

## features/scope/walk/ProgressRail.tsx
profile-progress-rail-at = { $company_display } 的 { $title }

## features/scope/walk/WhereStep.tsx
profile-where-step-in = { $display } 中的{ $noun }{ $slice }

## features/scope/walk/walkModel.ts
profile-walk-model-except = 除 { $names } 外
profile-walk-model-except-2 = { $every }，除 { $joinAnd } 外
profile-walk-model-and = { $join }和{ $parts }
profile-walk-model-only-2 = 仅限 { $display }
profile-walk-model-in = { $display }
profile-walk-model-or-3 = { $parts }或{ $parts2 }
profile-walk-model-more = { $said }{ $comma }{ $word }其他 { $value } 个

## 读取失败时的说明。
profile-scope-section-rules-load-failed = 无法加载你的公司排除项
