## notifications：简体中文翻译（AI 初稿，待审校）

## features/notifications/DigestPanel.tsx
notifications-digest-panel-more-roles-opened-today = { $count ->
   *[other] 今天还有 { $hidden } 个职位开放。
}
notifications-digest-panel-unranked-set-an-intent-statement = { $choice ->
    [yes] 最佳匹配优先，依据你当前的意向。
   *[no] 未排序：写一句意向说明，或保存几个职位来排序。
}

## features/notifications/NotificationFilters.tsx
notifications-notification-filters-status = 状态
notifications-notification-filters-read-status = 阅读状态
notifications-notification-filters-all = 全部
notifications-notification-filters-unread = 未读
notifications-notification-filters-priority = 优先级
notifications-notification-filters-priority-2 = 优先级
notifications-notification-filters-high = 高
notifications-notification-filters-scans = 扫描
notifications-notification-filters-filter-by-scan-event = 按扫描事件筛选
notifications-notification-filters-roles = 职位
notifications-notification-filters-filter-by-role-event = 按职位事件筛选

## features/notifications/NotificationRow.tsx
notifications-notification-row-unread = 未读
notifications-notification-row-show-details = { $choice ->
    [yes] 隐藏详情
   *[no] 显示详情
}
notifications-notification-row-copy-notification-text = 复制通知文本
notifications-notification-row-copy-notification-text-2 = { $choice ->
    [yes] 你的浏览器阻止了剪贴板访问
   *[no] 复制通知文本
}
notifications-notification-row-mark-read = { $choice ->
    [yes] 标为未读
   *[no] 标为已读
}
notifications-notification-row-dismiss = 忽略
notifications-notification-row-dismiss-2 = 忽略
notifications-notification-row-details-for = { $title } 的详情
notifications-notification-row-copy-summary = 复制摘要
notifications-notification-row-copy-full-details = 复制完整详情

## features/notifications/NotificationScreen.tsx
notifications-notification-screen-reset-all = 全部重置
notifications-notification-screen-nothing-unread = 没有未读
notifications-notification-screen-mark-all-read = 全部标为已读
notifications-notification-screen-nothing-here-yet = { $choice ->
    [yes] 没有匹配项
   *[no] 这里还没有内容
}
notifications-notification-screen-scans-new-roles-for-you = { $choice ->
    [yes] 没有符合这些筛选条件的通知。
   *[no] 扫描、为你推荐的新职位、公布薪酬区间的变化，以及你保存的职位的动态，都会显示在这里。
}
notifications-notification-screen-search-notifications = 搜索通知
notifications-notification-screen-find-a-role-company-or = 查找职位、公司或扫描…
notifications-notification-screen-clear-every-filter-and-lens = 清除所有筛选和视图
notifications-notification-screen-loading = 正在加载通知…
notifications-notification-screen-load-failed = 无法加载通知
notifications-notification-screen-refresh-failed = 无法更新通知。显示的是上一次的结果。

## features/notifications/diagnostics/NotifDiagnostics.tsx
notifications-notif-diagnostics-run = 运行
notifications-notif-diagnostics-status = 状态
notifications-notif-diagnostics-duration = 时长
notifications-notif-diagnostics-sources-ok = 正常来源
notifications-notif-diagnostics-errors = 错误（{ $length }）
notifications-notif-diagnostics-drift-alerts = 偏移警报（{ $length }）
notifications-notif-diagnostics-per-source = 按来源
notifications-notif-diagnostics-source = 来源
notifications-notif-diagnostics-scanned = 已扫描
notifications-notif-diagnostics-kept = 保留
notifications-notif-diagnostics-new = 新增
notifications-notif-diagnostics-closed = 已关闭
notifications-notif-diagnostics-took = 耗时
notifications-notif-diagnostics-error = 错误
notifications-notif-diagnostics-drift = { $drift_count } 处偏移
notifications-notif-diagnostics-ok = 正常
notifications-notif-diagnostics-drift-recorded = 已记录偏移
notifications-notif-diagnostics-unknown-error = 未知错误
notifications-notif-diagnostics-run-started-took = 运行 #{ $value }（{ $value2 }）· 开始于 { $value3 } · 耗时 { $duration_seconds }
notifications-notif-diagnostics-errors-2 = 错误（{ $length }）：
notifications-notif-diagnostics-drift-alerts-2 = 偏移警报（{ $length }）：
notifications-notif-diagnostics-per-source-2 = 按来源：
notifications-notif-diagnostics-source-scanned-kept-new-closed = 来源 | 已扫描 | 保留 | 新增 | 已关闭 | 耗时 | 状态
notifications-notif-diagnostics-notes = 备注：{ $notes }
notifications-notif-diagnostics-copy-blocked = { $choice ->
    [yes] 已复制
   *[no] 复制被阻止
}
notifications-notif-diagnostics-your-browser-blocked-clipboard-access = 你的浏览器阻止了剪贴板访问
notifications-notif-diagnostics-text = { $choice ->
    [v1] 已复制到剪贴板
    [v2] 浏览器阻止了剪贴板
   *[v3] { "" }
}

## features/notifications/moved-page/MovedPagePanel.tsx
notifications-moved-page-panel-stop-following = 取消关注
notifications-moved-page-panel-find-new-careers-page = 查找新的招聘页面
notifications-moved-page-panel-looking-for-s-new-careers = 正在查找 { $display } 的新招聘页面…
notifications-moved-page-panel-not-this-one = 不是这个
notifications-moved-page-panel-careers-page-link = 招聘页面链接
notifications-moved-page-panel-check = 检查
notifications-moved-page-panel-roleband-couldn-t-find-it = { $choice ->
    [yes] 该链接不是可读取的招聘页面。
   *[no] 没有找到。请粘贴 { $display } 新招聘页面的链接。
}
notifications-moved-page-panel-couldn-t-look-just-now = 暂时无法查找。请重试，或粘贴它的链接。
notifications-moved-page-panel-s-careers-page = { $display } 的招聘页面
notifications-moved-page-panel-use-this-careers-page = { $choice ->
    [yes] 正在切换…
   *[no] 使用此招聘页面
}
notifications-moved-page-panel-paste-the-link-to-s = 请粘贴 { $display } 新招聘页面的链接。

## features/notifications/moved-page/model.ts
notifications-model-roles = { $count ->
   *[other] { $count2 } 个职位
}
notifications-model-that-page-lists = { $choice ->
    [yes] 该页面有响应。
   *[no] 该页面列出了 { $roles }。
}
notifications-model-s-own-careers-page-links = { $choice ->
    [yes] { $display } 自己的招聘页面链接到了它。
   *[no] { $display2 } 自己的招聘页面链接到了它：{ $roles }。
}
notifications-model-found-it-roleband-saw-at = 找到了：其中 { $shared }之前在 { $display } 出现过。
notifications-model-of-them-roles = { $count ->
    [1] 1 个
   *[other] { $shared } 个
}
notifications-model-found-it-roleband-saw-at-2 = 找到了：{ $roles }，其中 { $seen }之前在 { $display } 出现过。

## features/notifications/sync-progress/SyncContribution.tsx
notifications-sync-contribution-what-has-landed = 已完成的公司
notifications-sync-contribution-opportunities = { $count ->
   *[other] { $total } 个职位
}
notifications-sync-contribution-landed = 已完成
notifications-sync-contribution-scraping = 扫描中
notifications-sync-contribution-queued = 等待中
notifications-sync-contribution-failed = 失败
notifications-sync-contribution-blocked = 被阻止
notifications-sync-contribution-failed-2 = 失败：{ $failed }
notifications-sync-contribution-blocked-the-source-is-refusing = 被其招聘页面阻止：{ $blocked }
notifications-sync-contribution-paused-while-this-computer = 此电脑休眠或离线时已暂停：{ $suspended }
notifications-sync-contribution-partial = 部分扫描：{ $degraded }
notifications-sync-contribution-scanned-nothing-in-scope = 已扫描，没有适合你的职位：{ $emptyButFine }
notifications-sync-contribution-more = 还有 { $length } 个
notifications-sync-contribution-opportunities-2 = { $label } · { $count ->
   *[other] { $value } 个职位
}
notifications-sync-contribution-roles-found-per-company = 各已完成公司的职位
notifications-sync-contribution-opportunities-3 = { $label }：{ $value } 个职位
notifications-sync-contribution-more-2 = { $join }，还有 { $value } 个

## features/notifications/sync-progress/SyncProgressPanel.tsx
notifications-sync-progress-panel-sources-failed-see-the-run = { $count ->
   *[other] { $companiesFailed } 家公司失败，完成后请查看扫描摘要。
}
notifications-sync-progress-panel-nothing-is-written-to-the = 每扫描一家公司，职位就会出现在你的雷达上。
notifications-sync-progress-panel-scan-progress = 扫描进度：{ $pHASE_LABEL }
notifications-sync-progress-panel-companies-scanned = 已扫描公司
notifications-sync-progress-panel-still-scraping = 仍在扫描
notifications-sync-progress-panel-roles-found = 找到的职位
notifications-sync-progress-panel-recorded = 来自已完成的公司

## features/notifications/sync-progress/SyncStream.tsx
notifications-sync-stream-scraping-now = 正在扫描
notifications-sync-stream-held = 仍在扫描
notifications-sync-stream-on-disk = 已完成 { $written }
notifications-sync-stream-in-memory = 找到的职位
notifications-sync-stream-no-update-for-this-run = 已有 { $staleMs } 没有更新，此次扫描可能已停止。
notifications-sync-stream-every-source-recorded = 扫描已完成
notifications-sync-stream-writing-collected-sources-to-the = 正在添加最后的职位
notifications-sync-stream-running-post-passes = 正在收尾
notifications-sync-stream-waiting-on-the-first-source = { $choice ->
    [yes] 等待第一家公司 · { $companiesQueued } 家等待中
   *[no] 等待第一家公司
}
notifications-sync-stream-opportunities-held-in-memory-written = { $choice ->
    [yes] 正在扫描：{ $join }。已完成的公司有 { $written } 个职位，仍在扫描的公司有 { $held } 个。
   *[no] { $progress }。已完成的公司有 { $written } 个职位，仍在扫描的公司有 { $held } 个。
}
notifications-sync-stream-path = path("{ $path }")

## features/notifications/sync-progress/model.ts
notifications-model-scanning-companies = 正在扫描公司
notifications-model-recording-roles = 正在添加最后的职位
notifications-model-finishing-up = 即将完成
notifications-model-sources = { $companiesCollected }/{ $companiesTotal } 家公司
notifications-model-scanned-found = 已扫描 { $companies } · 找到 { $opportunitiesDetected } 个职位

## features/notifications/useNotificationsController.ts
notifications-use-notifications-controller-could-not = 无法{ $what }
notifications-use-notifications-controller-mark-it-read = 标为已读
notifications-use-notifications-controller-mark-it-unread = { $choice ->
    [yes] 标为已读
   *[no] 标为未读
}
notifications-use-notifications-controller-dismiss-that-notification = 忽略该通知
notifications-use-notifications-controller-removed-from-your-notifications = 已从你的通知中移除“{ $title }”
notifications-use-notifications-controller-undo = 撤销
notifications-use-notifications-controller-undo-that = 撤销该操作
notifications-use-notifications-controller-use-that-careers-page = 使用该招聘页面
notifications-use-notifications-controller-roleband-now-reads-s-new = 现在读取 { $display } 的新招聘页面
notifications-use-notifications-controller-stop-following = 取消关注 { $display }
notifications-use-notifications-controller-stopped-following = 已取消关注 { $display }
notifications-use-notifications-controller-mark-them-read = 全部标为已读
notifications-use-notifications-controller-marked-notifications-read = { $count ->
   *[other] 已将 { $updated } 条通知标为已读
}

## features/notifications/filters.ts
notifications-category-scanning = 扫描中
notifications-category-scan-problems = 扫描问题
notifications-category-ran-out-of-time = 超时
notifications-category-scan-failed = 扫描失败
notifications-category-coverage = 覆盖情况
notifications-category-for-you = 为你推荐
notifications-category-reminders = 提醒
notifications-category-saved = 已保存
notifications-category-pay-up = 公布区间上调
notifications-category-pay-down = 公布区间下调
notifications-category-reposted = 已重新发布
notifications-category-long-open = 长期开放
notifications-category-changed = 已变更
notifications-category-closed = 已关闭

## features/notifications/sync-progress/SyncProgressPanel.tsx
notifications-sync-progress-panel-of = 共 { $companiesTotal }
notifications-sync-progress-panel-pending = { $opportunitiesPending } 个仍在扫描

## 服务器通知：后端写入 `meta.say` 的键。

notif-companies = { $count } 家公司
notif-duration-unknown = 时长未知
notif-duration-seconds = { $s } 秒
notif-duration-minutes = { $m } 分 { $s } 秒
notif-duration-hours = { $h } 小时 { $m } 分
notif-sources-all = 你关注的所有公司
notif-sources-more = { $names }，另外 { $more } 个
notif-affected-none = 不限于某一家公司，请查看扫描备注
notif-closed = { $company } 关闭了你保存的一个职位
notif-reposted = { $company } 重新发布了你保存的一个职位
notif-listed-again = { $company } 再次列出了你保存的一个职位
notif-listed = { $company } 发布了你保存的一个职位
notif-saved-elsewhere = { $places ->
   *[other] { $company } 仍在其他 { $places } 个地点发布你保存的一个职位
}
notif-saved-elsewhere-body = { $more ->
    [yes] { $title }。你保存的招聘信息已关闭；该职位仍在 { $places } 等地发布。
   *[no] { $title }。你保存的招聘信息已关闭；该职位仍在 { $places } 发布。
}
notif-pay-raised = { $company } 上调了你保存的一个职位的公布薪酬区间
notif-pay-lowered = { $company } 下调了你保存的一个职位的公布薪酬区间
notif-pay-change = { $title }：{ $before } -> { $after }
notif-updated-long-open = { $company } 更新了你保存的一个长期发布的职位
notif-changed = { $company } 更改了你保存的一个职位
notif-digest = 今天为你推荐 { $count } 个新职位
notif-digest-lead = { $company } 的 { $title }
notif-digest-fit = 匹配度{ $band }：{ $lead }
notif-digest-more = { $lead }，另外还有 { $more } 个
notif-follow-up = 跟进 { $company } · { $when }
notif-due-today = 今天到期
notif-overdue = 逾期 { $days } 天
notif-follow-up-body = { $action }：{ $title }（{ $stage }）
notif-no-next-action = 未设置下一步
notif-coverage-unreachable = 它的招聘页面没有响应。
notif-coverage-unreadable = 它的招聘页面有响应，但没有可读取的内容。
notif-coverage-partial = 扫描只读取了它招聘页面的一部分。
notif-coverage-unknown = 还没有扫描到达它的招聘页面。
notif-coverage-empty-listing = 它的招聘页面返回了空列表。
notif-coverage-board-missing = 它的招聘页面已不在上次的地址。
notif-coverage-scan-title = { $days ->
    [0] 无法扫描 { $company }
   *[other] 无法扫描 { $company } · { $days } 天
}
notif-coverage-not-scanned-since = 自 { $day } 以来它没有完成过完整扫描，因此可能缺少 { $company } 的新职位。下次完整扫描后会恢复。
notif-coverage-not-scanned = 它还没有完成过完整扫描，因此可能缺少 { $company } 的新职位。下次完整扫描后会恢复。
notif-coverage-empty-title = { $days ->
    [0] { $company } 没有发布职位
   *[other] { $company } 没有发布职位 · { $days } 天
}
notif-coverage-empty-moved = 如果 { $company } 仍在招聘，它的职位可能已移到新的招聘页面。
notif-coverage-held-until-listed = { $held } 个职位保持最后一次看到的状态，直到它再次发布职位。
notif-coverage-gone-title = { $days ->
    [0] { $company } 的招聘页面已不存在
   *[other] { $company } 的招聘页面已不存在 · { $days } 天
}
notif-coverage-gone-moved = { $company } 可能已将职位移到新的招聘页面。请查找它的新招聘页面，或取消关注 { $company }。
notif-coverage-held-until-then = 在此之前，{ $held } 个职位保持最后一次看到的状态。
notif-coverage-outage = { $days ->
    [0] 无法扫描 { $count } 家公司
   *[other] 无法扫描 { $count } 家公司 · { $days } 天
}
notif-coverage-outage-since = 自 { $day } 以来它们都没有完成过完整扫描，因此可能缺少新职位。随着扫描完成，这会恢复。
notif-coverage-outage-body = 它们都没有完成过完整扫描，因此可能缺少新职位。随着扫描完成，这会恢复。
notif-scan-started = 扫描已开始
notif-scan-started-body = 正在扫描 { $count } 家公司：{ $sources }。
notif-scan-started-all-body = 正在扫描{ $sources }。
notif-scan-summary = 找到 { $found } / 新建 { $created } / 更新 { $updated }
notif-scan-summary-skipped = 找到 { $found } / 新建 { $created } / 更新 { $updated } / 跳过或未变 { $skipped }
notif-finished-at = 于 { $at } 完成，用时 { $duration }。
notif-failed-at = 于 { $at } 失败，用时 { $duration }。
notif-scan-stopped = 扫描已停止
notif-stopped-before-any = 你在它扫描任何公司之前停止了扫描。
notif-stopped-after = 你在它扫描了 { $companies } 后停止了扫描。
notif-problems-at = 出现问题：{ $affected }。
notif-read-saved = 已找到的内容已保存。
notif-scan-failed = 无法扫描，没有任何更新
notif-run-failed = 扫描失败
notif-scan-derivation-failed = 扫描已收集，但一项派生处理失败
notif-post-pass-unfinished = 一项扫描后处理未完成：{ $failure }。
notif-every-source-delivered = 本次扫描的每家公司都已读取，但一项扫描后处理未完成：{ $failure }。
notif-data-saved = 扫描找到的内容已保存。
notif-scan-problems = 扫描完成，但有问题
notif-asleep = 扫描期间这台电脑休眠了 { $duration }，这会导致公司的职位列表不完整。
notif-unreached = { $count ->
   *[other] 扫描超时前未处理：{ $sources }。仍待扫描，下次扫描会处理。
}
notif-offline = { $count ->
   *[other] 扫描期间这台电脑没有网络连接：{ $sources }。已找到的内容已保存，且仍待扫描，下次扫描会处理。
}
notif-cut-short = 因达到扫描时间上限而停止：{ $sources }。已找到的内容已保存，那里的招聘信息保持最后一次看到的状态。
notif-unfinished-u = 扫描在 { $unreached } 之前超时
notif-unfinished-o = 扫描在 { $offline } 时断网
notif-unfinished-c = 扫描只覆盖了 { $cut } 的一部分
notif-unfinished-uo = 扫描在 { $unreached } 之前超时，并在 { $offline } 时断网
notif-unfinished-uc = 扫描在 { $unreached } 之前超时，且只覆盖了 { $cut } 的一部分
notif-unfinished-oc = 扫描在 { $offline } 时断网，且只覆盖了 { $cut } 的一部分
notif-unfinished-uoc = 扫描在 { $unreached } 之前超时，在 { $offline } 时断网，且只覆盖了 { $cut } 的一部分

## 通知徽章上的优先级。
notifications-priority-high = 高
notifications-priority-normal = 普通
notifications-priority-low = 低

## 一段没有回音的申请。
notif-gone-quiet = { $company } 已 { $days } 天没有消息
notif-gone-quiet-body = { $title }（{ $stage }）：该跟进了，或设定一个日期
notif-coverage-waiting-title = 等待扫描 { $company }
notif-coverage-waiting-outage = 等待扫描 { $count } 家公司
