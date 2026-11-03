## scan：简体中文翻译（AI 初稿，待审校）

## features/sync/SyncScopePopover.tsx
scan-sync-scope-popover-roleband-can-t-scan-any = 还没有可扫描的公司。请先在 设置 › 已关注的公司 中关注一家。
scan-sync-scope-popover-all-shown = { $choice ->
    [yes] 全部显示（{ $shown }/{ $total }）
   *[no] 全部显示（{ $shown }）
}
scan-sync-scope-popover-no-company-matches-that-filter = 没有公司符合该筛选条件。
scan-sync-scope-popover-stale = 已过时（{ $length }）
scan-sync-scope-popover-failed-last-run = 无法扫描（{ $length }）
scan-sync-scope-popover-a-targeted-sync-refreshes-only = 只扫描几家公司时，只更新你选择的公司。其他公司保留各自上次扫描的时间。
scan-sync-scope-popover-cut-short = 被中断
scan-sync-scope-popover-not-reached = 未处理
scan-sync-scope-popover-lists-no-roles = 没有发布职位
scan-sync-scope-popover-failed = 失败
scan-sync-scope-popover-blocked = 被阻止
scan-sync-scope-popover-partial = 部分完成
scan-sync-scope-popover-a-few-rows-unread = 部分条目未读
scan-sync-scope-popover-capped = 已达上限
scan-sync-scope-popover-paused = 已暂停
scan-sync-scope-popover-companies = { $count ->
   *[other] 公司
}
scan-sync-scope-popover-scan = { $choice ->
    [yes] 扫描所有公司
   *[no] 扫描 { $count } 家{ $value }
}
scan-sync-scope-popover-filter-companies-to-scan = 筛选要扫描的公司
scan-sync-scope-popover-filter-companies = 筛选公司…
scan-sync-scope-popover-select-all-shown-companies = 选择所有显示的公司
scan-sync-scope-popover-companies-to-scan-2 = 要扫描的公司
scan-sync-scope-popover-select-companies = 选择公司
scan-sync-scope-popover-choose-companies-to-scan = 选择要扫描的公司
scan-sync-scope-popover-loading = 正在加载要扫描的公司…
scan-sync-scope-popover-load-failed = 无法加载要扫描的公司
scan-sync-scope-popover-joins-running = 正在进行的扫描接下来读取它们。
scan-sync-scope-popover-joined = { $count ->
   *[other] 正在进行的扫描接下来读取这 { $count } 家{ -company(num: "other") }。
}
