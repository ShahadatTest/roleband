## companies：en/companies.ftl 的译文

## features/companies/AddMoreCompanies.tsx
companies-add-more-companies-add-more-companies = 添加更多公司
companies-add-more-companies-add-by-link = 通过链接添加
companies-add-more-companies-stop-scanning = 停止扫描
companies-add-more-companies-find-the-ones-hiring-for = 找出正在为你招聘的公司
companies-add-more-companies-add-a-company-by-link = 通过链接添加公司
companies-add-more-companies-company-name = 公司名称
companies-add-more-companies-careers-page-link = 招聘页面链接
companies-add-more-companies-cancel = 取消
companies-add-more-companies-a-specific-company = 指定公司
companies-add-more-companies-added-by-its-careers-page = 通过招聘页面添加
companies-add-more-companies-not-on-this-list-paste = 不在列表中？粘贴链接，即可知道能否扫描。
companies-add-more-companies-the-wider-market = 更广的市场
companies-add-more-companies-stop-scanning-the-wider-market = 停止扫描更广的市场
companies-add-more-companies-the-wider-market-heading = 更广的市场
companies-add-more-companies-about-companies-on-the-same = 同类招聘网站上的约 { $about } 家公司
companies-add-more-companies-each-one-is-checked-daily = 每家公司每天扫描一次，只有正在招聘你雷达上职位的公司才会加入你的列表。
companies-add-more-companies-first-scan-state = { $scan ->
    [paused] 约 { $about } 家公司，首次扫描因使用电池已暂停
   *[running] 约 { $about } 家公司，首次扫描进行中
}
companies-add-more-companies-first-scan-note = { $scan ->
    [paused] 接通电源后会从中断处继续。目前的匹配结果在“其他公司”中。
   *[running] 匹配结果一出现就会显示在“其他公司”中。离开此页面后扫描仍会继续。
}
companies-add-more-companies-scanned-of-about = 已扫描，共约 { $to_check } 家
companies-add-more-companies-hiring-for-you-so-far = 目前正在为你招聘
companies-add-more-companies-companies-scanned = 已扫描的公司
companies-add-more-companies-about-companies-checked-daily = 约 { $about } 家公司，每天扫描
companies-add-more-companies-daily-check-note = { $scan ->
    [paused] 因使用电池已暂停。接通电源后恢复每日扫描。
   *[running] 暂无动静的公司明天会再次扫描。
}
companies-add-more-companies-hiring-for-you = 正在为你招聘
companies-add-more-companies-quiet-today = 今日无动静
companies-add-more-companies-couldn-t-add-that-company = 无法添加该公司。{ $caught }
companies-add-more-companies-try-again = 请重试。
companies-add-more-companies-add-by-link-dialog = 通过链接添加公司
companies-add-more-companies-acme = Acme
companies-add-more-companies-careers-page-link-aria = 招聘页面链接
companies-add-more-companies-add-company = { $state ->
    [adding] 正在添加…
   *[idle] 添加公司
}

## features/companies/CompaniesData.tsx
companies-data-undo = 撤销
companies-data-couldn-t-undo-that-change = 无法撤销该更改。
companies-data-change-undone = 已撤销更改。
companies-data-follow-failed = { $direction ->
    [follow] 无法关注 { $name }。
   *[unfollow] 无法取消关注 { $name }。
}
companies-data-unfollowed = 已取消关注 { $display }。
companies-data-followed = { $coverage ->
    [covered] 已关注 { $company }。
   *[uncovered] 已关注 { $company }。能读取其招聘页面后就会开始扫描。
}
companies-data-sector-follow-result = { $direction ->
    [follow] 已关注 { $sector } 中显示的所有公司。{ $paused ->
        [0] { "" }
       *[other] 其中 { $paused } 家尚未扫描。
    }
   *[unfollow] 已取消关注 { $sector }。
}
companies-data-wider-market-result = { $state ->
    [waiting] 正在使用电池：接通电源后开始扫描另外约 { $size } 家公司。
    [scanning] 正在扫描另外约 { $size } 家公司，知名公司优先。
   *[stopped] 已停止扫描。{ $added ->
        [0] { "" }
       *[other] 已取消关注 { $added } 家由它添加的公司。
    }
}
companies-data-wider-market-failed = { $direction ->
    [start] 无法开始扫描更广的市场。
   *[stop] 无法停止扫描更广的市场。
}
companies-data-curated-follow-failed = { $direction ->
    [follow] 无法关注这几家公司。
   *[unfollow] 无法取消关注你的{ $curatedList }之外的这几家公司。
}
companies-data-curated-follow-result = { $direction ->
    [follow] 已再关注 { $count } 家公司。
   *[unfollow] 已取消关注你的{ $curatedList }之外的 { $count } 家公司。
}
companies-data-visibility-failed = { $visibility ->
    [shown] 无法将 { $company } 重新放回你的雷达。
   *[hidden] 无法在你的雷达上隐藏 { $company }。
}
companies-data-visibility-changed = { $visibility ->
    [hidden] 已在你的雷达上隐藏 { $company }。
   *[shown] { $company } 已回到你的雷达。
}
companies-data-company-added-to-your-roster = 已将公司添加到你的列表。

## features/companies/CompaniesIndex.tsx
companies-index-sectors = 行业
companies-index-add-more-companies = 添加更多公司
companies-index-sectors-aria = 行业

## features/companies/CompaniesSection.tsx
companies-section-loading-companies = 正在加载公司…
companies-section-company = 公司
companies-section-coverage = 覆盖情况
companies-section-open = 在招
companies-section-companies = 公司
companies-section-load-failed = 无法加载公司
companies-section-refresh-failed = 无法更新公司。显示的是上一次的结果。

## features/companies/CompanyRegisterRows.tsx
companies-company-register-rows-open-count = { $count } 个在招{ $mark }
companies-company-register-rows-aka = 又名 { $aliasHit }
companies-company-register-rows-limits-collection = 限制收集
companies-company-register-rows-also = 另有 { $name }
companies-company-register-rows-showing-of-matches-keep-typing = 显示 { $matchCount } 个匹配中的 { $shown } 个。继续输入以缩小范围。
companies-company-register-rows-planned = 计划中
companies-company-register-rows-coverage-problem = { $cause ->
    [empty_listing] 未列出职位
    [board_missing] 招聘页面已失效
   *[other] 无法扫描
}
companies-company-register-rows-blocked = 已阻止
companies-company-register-rows-needs-consent = 需要同意
companies-company-register-rows-live-or-ready = { $connector ->
    [ready] 就绪
   *[other] 运行中
}
companies-company-register-rows-scanned-ago = { $scanned }前扫描。
companies-company-register-rows-label-scanned-ago = { $label } · { $scanned }前扫描
companies-company-register-rows-scanned-ago-roleband-scans-when = { $scanned }前扫描。你选择“立即扫描”时会扫描 { $display }。
companies-company-register-rows-not-counted-last-read-ago = { $label } · 未计入，上次扫描于 { $lastRead }前
companies-company-register-rows-roleband-last-read-s-roles = { $display } 上次扫描是在 { $lastRead }前，时间太久，无法计入你的雷达。下次扫描会重新计入其职位。
companies-company-register-rows-partly-counted = { $label } · 部分计入
companies-company-register-rows-s-scans-have-not-read = 对 { $display } 的扫描尚未读完其整个招聘页面，因此部分职位未计入。下次完整扫描会补上。
companies-company-register-rows-not-counted-yet = { $label } · 尚未计入
companies-company-register-rows-not-counted-why = { $reason ->
    [stale] { $company } 的职位来自较早的一次扫描，你的雷达无法计入。下次完整扫描会补上。
   *[other] { $company } 的职位尚未计入你的雷达。下次扫描会补上。
}
companies-company-register-rows-following-not-scanned-yet = 已关注 · 尚未扫描
companies-company-register-rows-roleband-starts-scanning-as-soon = 能读取 { $display } 的招聘页面后就会开始扫描。
companies-company-register-rows-open-role-counts-are-unavailable = 在招职位数暂不可用
companies-company-register-rows-open-roles-loading = 正在加载在招职位
companies-company-register-rows-of-s-roles-name-a = { $display } 有 { $unplaced } 个职位的地点无法识别，因此无论你选择哪个地点都不会显示它们。
companies-company-register-rows-of-s-roles-fit-no = { $display } 有 { $unsorted } 个职位不属于任何已知方向，因此无论你选择哪个方向都不会显示它们。
companies-company-register-rows-open-careers-page = 打开 { $display } 的招聘页面
companies-company-register-rows-careers-page = 招聘页面
companies-company-register-rows-show-or-hide-on-radar = { $visibility ->
    [shown] 在你的雷达上隐藏 { $company }
   *[hidden] 在你的雷达上显示 { $company }
}
companies-company-register-rows-radar-visibility = { $visibility ->
    [shown] 在你的雷达上
   *[hidden] 已从你的雷达隐藏
}
companies-company-register-rows-scan-now = 立即扫描 { $display }
companies-company-register-rows-scan-now-hint = { $scan ->
    [running] 加入正在进行的扫描
    [waiting] 已有扫描在排队
   *[idle] 立即扫描这家公司
}
companies-company-register-rows-scan-joined = 正在进行的扫描接下来读取 { $display }。
companies-company-register-rows-scanning = 正在扫描 { $display }…
companies-company-register-rows-couldn-t-start-a-scan = 无法开始扫描 { $display }。
companies-company-register-rows-followed = 已关注 { $followed }/{ $total }
companies-company-register-rows-covered-count = { $coverage ->
    [none] 均未覆盖
   *[some] 已覆盖 { $covered } 家
}
companies-company-register-rows-planned-hidden = 已隐藏 { $hiddenPlanned } 家计划中的公司
companies-company-register-rows-sector-follow-all = { $direction ->
    [unfollow] 取消关注 { $sector } 的所有公司
   *[follow] 关注 { $sector } 的所有公司
}
companies-company-register-rows-nothing-to-follow-why = { $coverage ->
    [none] 该行业暂时没有可扫描的公司
   *[some] 没有公司符合你的筛选条件
}
companies-company-register-rows-sector-action = { $action ->
    [none] 没有可关注的公司
    [unfollow] 全部取消关注
   *[follow] 全部关注
}

## features/companies/CuratedList.tsx
companies-curated-list-confirm = 确认

## features/companies/RegisterChrome.tsx
companies-register-chrome-followed-companies-wait-for-your = { $count ->
   *[other] { $count } 家已关注的公司等待你的同意
}
companies-register-chrome-roleband-doesn-t-scan-them = { $count ->
   *[other] 你回复之前不会扫描它们。
}
companies-register-chrome-review = 查看 { $display }
companies-register-chrome-companies-failed-the-last-scan = { $count ->
   *[other] { $count } 家公司上次扫描失败
}
companies-register-chrome-rescan = 重新扫描 { $count } 家
companies-register-chrome-toolbar-stats = { $followed } / { $total } 已关注 { $sep } { $openRoles } 个在招职位 { $sep } { $live } 运行中 { $sep } { $ready } 就绪
companies-register-chrome-following-only = 仅已关注
companies-register-chrome-show-planned = 显示计划中
companies-register-chrome-follow-all = 全部关注
companies-register-chrome-curated-list-only = 仅精选列表
companies-register-chrome-show-all-to-see = { $showAll } 查看这 { $released } { $search ->
        [query] 个匹配项（你未关注）
       *[none] 家公司
    }。
companies-register-chrome-show-all-companies = 显示所有公司
companies-register-chrome-show-planned-to-see = { $showPlanned } 查看另外 { $released } 家。
companies-register-chrome-show-planned-button = 显示计划中
companies-register-chrome-clear-search-to-see = { $clearSearch } 查看全部 { $catalogTotal } 家。
companies-register-chrome-clear-the-search = 清除搜索
companies-register-chrome-more = { $names } 等另外 { $more } 家
companies-register-chrome-followed-companies-are-blocked = { $count ->
   *[other] { $count } 家已关注的公司已被阻止
}
companies-register-chrome-followed-companies-are-not-scanned = { $count ->
   *[other] { $count } 家已关注的公司尚未扫描
}
companies-register-chrome-followed-companies-are-hidden-from = { $count ->
   *[other] { $count } 家已关注的公司已从你的雷达隐藏
}
companies-register-chrome-companies-needing-attention = 需要处理的公司
companies-register-chrome-a-scan-is-already-running = 已有扫描在进行
companies-register-chrome-rescanning-companies = { $count ->
   *[other] 正在重新扫描 { $count } 家公司…
}
companies-register-chrome-couldn-t-start-that-rescan = 无法开始重新扫描。
companies-register-chrome-search-companies = 搜索公司
companies-register-chrome-find-a-company-alias-or = 查找公司、别名或行业
companies-register-chrome-a-search-shows-planned-companies = 搜索结果也会显示计划中的公司
companies-register-chrome-register-empty = { $blamed ->
    [search-following] 你关注的公司中没有与“{ $search }”匹配的。
    [search] 没有与“{ $search }”匹配的公司。
    [following-planned] 你还没有关注任何已覆盖的公司。
    [following] 你还没有关注任何公司。
    [planned] 这里的公司都还在计划中，尚未覆盖。
   *[none] 还没有公司。
}

## features/companies/companiesModel.ts
companies-model-ready-to-enable = 就绪：关注后即开始扫描
companies-model-your-additions = 你添加的公司
companies-model-other-companies = 其他公司

## features/companies/followCopy.ts
companies-follow-copy-thousands-of-roles = 数千个职位
companies-follow-copy-hundreds-of-roles = 数百个职位
companies-follow-copy-more-roles = 更多职位
companies-follow-copy-following-all-will-likely-bring = 公司越多，职位越多，每次扫描也会更久。
companies-follow-copy-follow-more = 关注整个列表？
companies-follow-copy-roleband-starts-you-with-a = 你的雷达从一份知名公司的{ $curatedList }开始，所以你最先看到的职位来自你熟悉的雇主。
companies-follow-copy-you-can-unfollow-any-company = 你可以在 设置 › 已关注的公司 中取消关注任何公司。
companies-follow-copy-keep = 保留{ $curatedList }
companies-follow-copy-follow-all = 关注全部 { $count } 家
companies-follow-copy-unfollow-outside-your = 取消关注你的{ $curatedList }之外的 { $count } 家公司？
companies-follow-copy-roleband-stops-scanning-them-your = { $count ->
   *[other] 将停止扫描它们。你的{ $curatedList }以及你自己添加的公司仍保持关注。
}
companies-follow-copy-keep-following = 继续关注
companies-follow-copy-unfollow = 取消关注 { $count } 家
companies-follow-copy-follow-all-in = 关注 { $sector } 中的全部 { $count } 家公司？
companies-follow-copy-this-will-likely-add-to = 这可能会为你的雷达增加{ $estimate }，并让每次扫描变长。你之后可以取消关注任何公司。
companies-follow-copy-cancel = 取消
companies-follow-copy-follow = 关注 { $display }？
companies-follow-copy-by-following-you-choose-to = 关注即表示你选择收集 { $display } 的公开招聘信息。你可以随时取消关注，收集随即停止。
companies-follow-copy-follow-company = 关注 { $display }
companies-follow-copy-scan-about-more-companies = 再扫描约 { $about } 家公司？
companies-follow-copy-only-companies-hiring-for-roles = 只有正在招聘你雷达上职位的公司才会加入你的关注列表，其余公司不会显示。
companies-follow-copy-roleband-scans-the-best-known = 第一次扫描需要几小时，先从最知名的公司开始。之后每家公司每天扫描一次，适合你的职位发布当天就会出现。
companies-follow-copy-you-can-stop-at-any = 你可以随时停止。
companies-follow-copy-start-scanning = 开始扫描
companies-follow-copy-follow-every-company-question = 也关注其他公司？
companies-follow-copy-your-radar-covers-the-whole = 你的雷达会在列表中的公司之外，加上其他公司。
companies-follow-copy-with-more-companies-scans-take = 公司越多，扫描耗时越长。
companies-follow-copy-change-it-any-time-in = 可随时在 设置 中更改。
companies-follow-copy-follow-every-company = 关注它们
companies-follow-copy-unfollow-company-question = 取消关注 { $display }？
companies-follow-copy-s-job-listings-stop-being = 将不再收集 { $display } 的招聘信息。你可以随时重新关注。
companies-follow-copy-unfollow-company = 取消关注 { $display }

## features/companies/CompaniesIndex.tsx
companies-index-match-count = { $count } 个匹配
companies-index-followed-of = { $followed }/{ $total }

## features/companies/CompanyRegisterRows.tsx
companies-company-register-rows-sector-open = { $openRoles } 个在招

## 公司的读取状态，以及暂停时的原因。
companies-connector-live = 自动扫描
companies-connector-family = 就绪：可以读取其招聘页面
companies-connector-active = 由你添加，正在扫描
companies-connector-planned = 计划支持
companies-connector-parked = 其网站拒绝扫描
companies-parked-bot-protected = 其招聘页面阻止自动读取
companies-parked-robots-disallow = { $company } 要求不要自动读取其招聘页面
companies-parked-prohibits-collection = 其招聘页面禁止自动收集
companies-company-register-rows-board-found = { $reason ->
    [policy_refused] 使用 { $family }；已关闭对它的收集
   *[board_silent] 使用 { $family }，它没有响应
}
companies-company-register-rows-board-family = { $family ->
    [jibe] Jibe
    [radancy] Radancy TalentBrew
    [avature] Avature
   *[other] { $family }
}
companies-company-register-rows-waiting-to-scan = 等待扫描

companies-setup-followed-now = 当前已关注
companies-setup-and-more = 以及另外 { $count } 家
companies-setup-well-known = 知名公司
companies-setup-well-known-detail = { $count ->
   *[other] { $count } 家{ -company(num: "other") }，几分钟内出现第一批{ -role(num: "other") }
}
companies-setup-every-listed = 所有列出的公司
companies-setup-every-listed-detail = { $count ->
   *[other] 覆盖多个行业的 { $count } 家{ -company(num: "other") }
}
companies-setup-everything = 再加上其他公司
companies-setup-everything-detail = 另外约 { $about } 家；第一次扫描需要几小时
companies-setup-choice-aria = 扫描哪些公司
companies-setup-later = 之后可随时在 设置 > 关注的公司 中关注或取消关注单个公司。
companies-setup-load-failed = 无法加载公司列表。知名公司仍保持关注。
companies-setup-back = 返回
companies-setup-start = { $choice ->
    [yes] 启动中…
   *[no] 启动雷达
}
