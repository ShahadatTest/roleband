## role：按原样迁移（wording=as-is）

## features/job-detail/JobCompPanel.tsx
role-job-comp-panel-the-employer-s-exact-words = 雇主的原话
role-job-comp-panel-no-compensation-data-for-this = 这个职位没有薪酬数据。
role-job-comp-panel-market-median-at-this-level = 该级别的市场中位数
role-job-comp-panel-this-package-is-the-market = 该估算是该级别市场中位数的 { $toFixed } 倍，通常说明级别或职能有误。
role-job-comp-panel-base = 基本工资
role-job-comp-panel-base-salary-stated-in-the = 招聘信息中注明的基本工资。
role-job-comp-panel-this-employer-publishes-no-pay = 该雇主未公布薪酬区间。以下内容均为估算。
role-job-comp-panel-we-have-not-checked-this = 还没有检查这条招聘信息是否公布了薪酬区间。
role-job-comp-panel-stated = 已注明
role-job-comp-panel-estimated = 估算
role-job-comp-panel-our-independent-estimate-of-total = 总薪酬的独立估算：{ $range }
role-job-comp-panel-from-the-posting-s-pay = 来自招聘信息的薪酬字段，而非正文。
role-job-comp-panel-bonus = 奖金
role-job-comp-panel-equity = 股权
role-job-comp-panel-cash-every-month = 现金，每月发放
role-job-comp-panel-target-not-guaranteed = 目标值，不保证
role-job-comp-panel-per-year-vests-over-time = 每年，分期归属
role-job-comp-panel-measured-split = 实测构成
role-job-comp-panel-split-from-another-discipline = 来自其他职能的构成
role-job-comp-panel-estimated-split = 估算构成
role-job-comp-panel-this-company-s-real-base = 这家公司在该级别和职能上实际的基本工资/奖金/股权构成
role-job-comp-panel-no-measured-split-for-this = 该职能没有实测构成：根据这家公司其他职能同级别的数据推算
role-job-comp-panel-no-measured-split-for-this-2 = 该公司没有实测构成：使用按资历估算的规则
role-job-comp-panel-posted-band-sits-well-above = 公布的区间远高于这家公司实测的 { $band } 基本工资，因此级别可能更高。
role-job-comp-panel-posted-band-sits-well-below = 公布的区间远低于这家公司实测的 { $band } 基本工资，因此级别可能更低。
role-job-comp-panel-you-choose-the-cash-stock = 现金与股权的比例由你选择
role-job-comp-panel-equity-fills-a-per-level = 股权用于补足各级别的总薪酬目标
role-job-comp-panel-equity-is-a-dollar-grant = 股权是按级别确定金额的美元授予
role-job-comp-panel-vests = { $choice ->
    [yes] { $vesting } 归属，签约现金奖金补足第 1–2 年
   *[no] { $vesting } 归属
}
role-job-comp-panel-no-annual-bonus = 无年度奖金
role-job-comp-panel-bonus-is-a-level-set = 奖金为按级别设定的基本工资百分比
role-job-comp-panel-base-capped-at = 基本工资上限为 { $base_cap_usd }
role-job-comp-panel-yr = / 年
role-job-comp-panel-mo = / 月
role-job-comp-panel-hr = / 小时
role-job-comp-panel-hourly-rate = 时薪
role-job-comp-panel-the-posting-gives-an-hourly = 招聘信息给出的是时薪，按原样显示。
role-job-comp-panel-monthly-rate = 月薪
role-job-comp-panel-the-posting-gives-a-monthly = 招聘信息给出的是月薪，按原样显示。
role-job-comp-panel-period-unclear = 计薪周期不明
role-job-comp-panel-the-posting-s-wording-and = 招聘信息的措辞与这个数字的大小不一致，因此无法判断是按小时、按月还是按年支付。请阅读下方雇主的原话。
role-job-comp-panel-states-this-as-total-annual = { $company } 将其注明为不含奖金的年度总薪酬。员工自行选择工资与股票期权的比例，因此没有固定的现金/股权构成可以显示。
role-job-comp-panel-employee-selected-mix = 员工自选比例
role-job-comp-panel-total-compensation = 总薪酬
role-job-comp-panel-the-posting-states-total-compensation = 招聘信息注明了总薪酬，但没有构成明细，因此不显示明细。
role-job-comp-panel-basis-not-stated = 口径未注明
role-job-comp-panel-the-posting-states-this-figure = 招聘信息没有说明这个数字是基本工资还是总薪酬，因此不拆分为基本工资、奖金和股权。
role-job-comp-panel-no-estimate-available = 暂无估算
role-job-comp-panel-estimated-total-package = { $choice ->
    [yes] 公布的总薪酬
   *[no] 估算总薪酬
}
role-job-comp-panel-estimated-total-comp = 估算总薪酬
role-job-comp-panel-stated-by-the-employer = 由雇主注明
role-job-comp-panel-about-stated-base-salary = 关于公布的基本工资
role-job-comp-panel-of-base-stated = 基本工资的 { $round }%，已注明

## features/job-detail/JobDescription.tsx
role-job-description-no-description-captured = 未获取到职位描述。

## features/job-detail/JobDetail.tsx
role-job-detail-back = 返回
role-job-detail-1-in-compare-pick-one = 对比中有 1 个 · 再选一个
role-job-detail-compare-roles = 对比 { $compareCount } 个职位
role-job-detail-view-apply = 查看并申请
role-job-detail-postings = { $lineage_size } 条招聘信息
role-job-detail-reposted = 重新发布 ×{ $repost_count }
role-job-detail-description = 职位描述
role-job-detail-your-progress = 你的进展
role-job-detail-set-a-stage = 设置阶段…
role-job-detail-next = 下一步：{ $next_action }
role-job-detail-radar-s-read = 雷达的判断
role-job-detail-advisory-unclear = 招聘信息的措辞没有明确对应某一个领域。
role-job-detail-advisory-basis = 根据招聘信息的措辞推测，不会把任何职位移出你的雷达。
role-job-detail-details = 详情
role-job-detail-team = 团队
role-job-detail-workplace = 办公方式
role-job-detail-status = 状态
role-job-detail-to-apply = 申请方式
role-job-detail-more-like-this = 更多类似职位
role-job-detail-other-companies = 其他公司
role-job-detail-same-company = 同一公司 · { $company }
role-job-detail-could-not-unsave-this-role = { $choice ->
    [yes] 无法保存这个职位
   *[no] 无法将这个职位从已保存中移除
}
role-job-detail-couldn-t-update-the-stage = 无法更新阶段
role-job-detail-role = { $choice ->
    [yes] 职位：{ $title }
   *[no] 职位
}
role-job-detail-back-2 = 返回
role-job-detail-compare-is-full-max = 对比已满（最多 { $compareCap } 个）
role-job-detail-compare = { $choice ->
    [yes] 对比中
   *[no] 对比
}
role-job-detail-it-s-no-longer-in = 这个职位已不存在。
role-job-detail-not-started = { $choice ->
    [yes] 阶段
   *[no] 未开始
}
role-job-detail-stage = 阶段
role-job-detail-likely-your-kind-of-role = 很可能是你想要的职位类型
role-job-detail-likely-outside-your-worlds = 很可能不在你的领域内
role-job-detail-hard-to-place = 难以归类
role-job-detail-questions-the-employer-added-beyond = 雇主在姓名、联系方式和简历之外添加的问题，读取自招聘信息页面
role-job-detail-similarity = 相似度

## features/job-detail/JobRequirementsPanel.tsx
role-job-requirements-panel-no-explicit-skill-requirements-found = 这条招聘信息中没有找到明确的技能要求。这表示没有内容与已知技能匹配，并不是说这个职位不需要技能。
role-job-requirements-panel-core-skills = 核心技能
role-job-requirements-panel-supporting = 辅助技能
role-job-requirements-panel-show-more = 再显示 { $value } 项
role-job-requirements-panel-industry = 行业
role-job-requirements-panel-qualifications = 资质
role-job-requirements-panel-ways-of-working = 工作方式
role-job-requirements-panel-role-requirements = 职位要求
role-job-requirements-panel-what-this-role-asks-for = 这个职位要求什么
role-job-requirements-panel-importance-reflects-how-strongly-this = 重要程度反映这条招聘信息对每一项的强调程度：即在这条招聘信息中找到的明确要求，并保留雇主的原话。它与你自己的技能或机会无关。
role-job-requirements-panel-required = 要求 { $requiredYears } { $requiredYears2 }
role-job-requirements-panel-core = { $core } 项核心
role-job-requirements-panel-supporting-2 = { $supporting } 项辅助
role-job-requirements-panel-sources = { $count ->
   *[other] { $sources } 个来源
}
role-job-requirements-panel-show-in-description = 在职位描述中显示
role-job-requirements-panel-required-2 = 必需
role-job-requirements-panel-preferred = 优先
role-job-requirements-panel-used-in-role = 工作中使用
role-job-requirements-panel-mentioned = 提及
role-job-requirements-panel-technology = 技术
role-job-requirements-panel-skill = 技能
role-job-requirements-panel-language = 编程语言
role-job-requirements-panel-framework = 框架
role-job-requirements-panel-ml-ai = ML / AI
role-job-requirements-panel-cloud = 云
role-job-requirements-panel-data = 数据
role-job-requirements-panel-infra = 基础设施
role-job-requirements-panel-security = 安全
role-job-requirements-panel-process = 流程
role-job-requirements-panel-leadership = 领导力
role-job-requirements-panel-collaboration = 协作
role-job-requirements-panel-years = { $count ->
   *[other] 年
}
role-job-requirements-panel-role-requirements-2 = 职位要求
role-job-requirements-panel-this-posting-has-no-stored = { $choice ->
    [yes] 正在分析要求…
   *[no] 这条招聘信息没有已保存的文本可供分析。
}
role-job-requirements-panel-preferred-2 = { $choice ->
    [yes] 必需
   *[no] 优先
}
role-job-requirements-panel-show-evidence = { $choice ->
    [yes] 隐藏依据
   *[no] 显示依据
}
role-job-requirements-panel-ways-of-working-evidence = 工作方式依据
role-job-requirements-panel-about-importance = 关于重要程度
role-job-requirements-panel-important = { $choice ->
    [yes] 核心
   *[no] 重要
}
role-job-requirements-panel-skill-sources-show-evidence = { $count ->
   *[other] { $display }，{ $bandLabel } { $modality } 技能，{ $sources } 个来源。显示依据。
}
role-job-requirements-panel-requirement-sources = { $count ->
   *[other] { $display }：{ $bandLabel } 要求，{ $modality }，{ $sources } 个来源
}
role-job-requirements-panel-importance-inline = { $band ->
    [core] 核心
   *[other] 重要
}
role-job-requirements-panel-modality-inline = { $modality ->
    [required] 必需
    [preferred] 优先
    [used_in_role] 工作中使用
   *[context] 提及
}
role-job-requirements-panel-title = 职位名称

## features/job-detail/LineageDiff.tsx
role-lineage-diff-not-disclosed = 未公布
role-lineage-diff-title-changed = 职位名称已更改
role-lineage-diff-level-changed = 级别已更改
role-lineage-diff-pay-band-newly-disclosed = { $choice ->
    [yes] 公布的薪酬区间已变动
   *[no] 新公布薪酬区间
}
role-lineage-diff-pay-basis-changed = 公布区间口径已更改
role-lineage-diff-locations-changed = 地点已更改
role-lineage-diff-estimate-changed = 估算已更改
role-lineage-diff-changes-since-the-previous-posting = 与上一条招聘信息相比的变化

## features/job-detail/LineageStack.tsx
role-lineage-stack-could-not-load-posting-history = 无法加载招聘信息历史。请重试。
role-lineage-stack-postings-of-this-role = 这个职位的 { $size } 条招聘信息
role-lineage-stack-first-seen = 首次发现 { $relDays }
role-lineage-stack-req = 编号 { $req_id }
role-lineage-stack-locations = 地点
role-lineage-stack-comp-est = 估算总薪酬
role-lineage-stack-first-seen-2 = 首次发现
role-lineage-stack-changes-from-the-previous-posting = 与上一条招聘信息相比的变化
role-lineage-stack-posting-history = 招聘信息历史
role-lineage-stack-previous-posting = 上一条招聘信息
role-lineage-stack-postings = 招聘信息
role-lineage-stack-posting = { $choice ->
    [yes] 招聘信息 { $seq }：{ $role }
   *[no] 招聘信息 { $seq }
}
role-lineage-stack-role = { $role ->
    [original] 原始
    [duplicate] 重复
   *[repost] 重新发布
}
role-lineage-stack-badge = { $choice ->
    [yes] { $role } · #{ $seq }
   *[no] #{ $seq }
}
role-lineage-stack-next-posting = 下一条招聘信息
role-lineage-stack-last-seen = { $choice ->
    [yes] 已关闭
   *[no] 最后发现
}

## features/job-detail/ListingAge.tsx
role-listing-age-reading-the-history = 正在读取历史记录…
role-listing-age-couldn-t-read-the-history = 无法读取历史记录。
role-listing-age-retry = 重试
role-listing-age-role-listed-for-across-postings = 职位已发布 { $days }，共 { $postings } 条招聘信息。
role-listing-age-compare-the-postings = 对比这些招聘信息
role-listing-age-possibly-the-same-role-not = 可能是同一职位：{ $value }，确认前不计入。
role-listing-age-review = 审核
role-listing-age-listed-for = 已发布
role-listing-age-since = 自 { $listed_since } 起，{ $bASIS }
role-listing-age-history = 历史记录
role-listing-age-listing-history = 发布历史
role-listing-age-role = 职位
role-listing-age-first-listed-postings = 首次发布 { $roleSince } · { $rolePostings } 条招聘信息
role-listing-age-the-employer-s-date = 雇主给出的日期
role-listing-age-when-roleband-first-saw-it = 首次发现的时间
role-listing-age-title = 职位名称
role-listing-age-stated-pay = 公布的薪酬区间
role-listing-age-level = 级别
role-listing-age-discipline = 职能
role-listing-age-location = 地点
role-listing-age-posting = 招聘信息
role-listing-age-same-role-matched-automatically = { $choice ->
    [yes] 同一职位，已确认
   *[no] 同一职位，自动匹配
}
role-listing-age-published-by-the-employer = 由雇主发布
role-listing-age-the-start = 起点
role-listing-age-first-seen-by-roleband = 首次发现
role-listing-age-gone-from-the-careers-page = 已从招聘页面消失
role-listing-age-came-back-same-requisition = 重新出现，职位编号相同
role-listing-age-employer-changed-its-date-to = 雇主将日期改为 { $to_at }
role-listing-age-never-the-start = 不作为起点
role-listing-age-an-earlier-posting-was-listed = { $choice ->
        [yes] 较早的招聘信息 { $posting } 已发布
       *[no] 曾发布过一条较早的招聘信息
    }{ $choice2 ->
        [yes] ，{ $until } 关闭
       *[no] { "" }
    }
role-listing-age-reposted = { $choice ->
    [yes] 以 { $posting } 重新发布
   *[no] 已重新发布
}
role-listing-age-still-listed-at-the-last = 上次扫描时仍在发布
role-listing-age-events = 事件

## features/job-detail/PayFloorLine.tsx
role-pay-floor-line-clears-your-pay-floor = 高于你的最低基本工资 { $floor }
role-pay-floor-line-your-pay-floor-falls-inside = 你的最低基本工资 { $floor } 落在这个区间内
role-pay-floor-line-below-your-pay-floor = 低于你的最低基本工资 { $floor }

## features/job-detail/PlaceSetSection.tsx
role-place-set-section-could-not-load-this-role = 无法加载这个职位的其他地点。请重试。
role-place-set-section-you-marked-this-posting-as = 你已将这条招聘信息标记为与其他地点相同文本不同的职位。
role-place-set-section-undo = 撤销
role-place-set-section-same-title-and-the-same = 每个地点的职位名称和职位描述都相同，只是地点及其相关内容（当地薪酬、福利或法律文本）或少量措辞不同，因此算作一个职位。
role-place-set-section-different-roles = 不同职位
role-place-set-section-marked-as-a-different-role = 已标记为不同职位
role-place-set-section-undo-2 = 撤销
role-place-set-section-could-not-record-the-verdict = 无法记录判断：{ $message }
role-place-set-section-also-listed-in = 也发布于
role-place-set-section-same-place = 同一地点
role-place-set-section-place-not-stated = 未注明地点
role-place-set-section-listed = · 发布于 { $listed_since }
role-place-set-section-a-second-posting-at-the = 同一地点的第二条招聘信息是该职位的再次发布。
role-place-set-section-the-employer-files-them-all = 雇主把它们都归在 { $employer_label } 下。
role-place-set-section-other-places = { $count ->
   *[other] 另外 { $otherPlaces } 个地点
}
role-place-set-section-times-here = 此处 { $value } 次
role-place-set-section-also-listed-in-and = 也发布于 { $places }，以及 { $times }
role-place-set-section-listed-2 = 发布 { $times }
role-place-set-section-also-listed-in-2 = 也发布于 { $places }

## features/job-detail/PostingReality.tsx
role-posting-reality-of-signs = { $criteria_total } 项信号中的 { $length } 项 · { $sTANDING_HEDGE }

## features/job-detail/TwinDeck.tsx
role-twin-deck-could-not-load-twin-postings = 无法加载这个职位的孪生招聘信息。请重试。
role-twin-deck-separate-roles-with-closely-related = 工作内容密切相关的不同职位
role-twin-deck-req = 编号 { $req_id } · { $value }
role-twin-deck-via-a-related-group-not = 通过相关分组 · 并非直接相关
role-twin-deck-req-2 = { $title } · 编号 { $req_id }
role-twin-deck-compare-with-related-roles = 与相关职位对比
role-twin-deck-related-roles = 相关职位
role-twin-deck-has-related-roles = { $count ->
   *[other] 有 { $length } 个相关职位
}
role-twin-deck-location-not-listed = 未列出地点

## features/job-detail/applyAsk.ts
role-apply-ask-nothing-beyond-your-resume = 简历之外无其他要求
role-apply-ask-questions = { $count ->
   *[other] { $count } 个问题
}
role-apply-ask-written-answers = { $count ->
   *[other] { $count } 个书面回答
}
role-apply-ask-asks-your-expected-pay = 询问你的期望薪酬

## features/job-detail/JobRequirementsPanel.tsx
role-job-requirements-panel-evidence = { $display } 的依据

## features/job-detail/LineageDiff.tsx
role-lineage-diff-added = 新增 { $join }
role-lineage-diff-removed = 移除 { $join }

## features/job-detail/ListingAge.tsx
role-listing-age-changed = { $choice ->
    [yes] { $field } 更改了 { $count } 次
   *[no] { $field } 已更改
}

## features/job-detail/JobCompPanel.tsx
role-job-comp-panel-the-posted-band-does-not = { $sPLIT_TITLE }。公布的区间与该级别不符，因此请将该构成视为暂定

## 招聘信息的状态代码，以文字表述。
role-job-status-open = 开放
role-job-status-closed = 已关闭

## 构成数据的来源。
role-job-comp-panel-split-from-roleband = { $choice ->
    [yes] 构成来自内置数据，截至 { $date }。
   *[no] 构成来自内置数据。
}
role-job-comp-panel-split-from-plugin = { $choice ->
    [yes] 构成来自 { $plugin }，截至 { $date }。
   *[no] 构成来自 { $plugin }。
}

## 同一职位的其他招聘信息中不同的内容。
role-place-set-section-states-pay = · 公布 { $range }
role-place-set-section-states-no-pay = · 未公布区间

## 选择阶段的作用。
role-job-detail-tracking-explainer = 选择一个阶段来跟踪这个职位：它会被保存，已保存页面会显示它的阶段，之后设定的跟进日期到期时会提醒你。
role-job-comp-panel-estimate-of-total = 估算总薪酬：{ $range }
role-job-comp-panel-split-not-reported = 无构成数据
role-job-comp-panel-the-plugin-reports-no-split = 提供薪酬的插件给出了这个级别的数字，但没有说明它如何分为基本工资、奖金和股权，因此不做拆分。
role-job-comp-panel-roleband-splits-us-pay-only = 薪酬仅依据美国数据拆分为基本工资、奖金和股权。此职位在美国以外或跨多个国家，因此不做拆分。
role-job-comp-panel-not-read-yet = 尚未读取
role-job-comp-panel-estimated-base = 估算基本工资
role-job-comp-panel-from-roleband-data = 来自内置数据。
