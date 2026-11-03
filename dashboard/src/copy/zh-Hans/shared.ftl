## 延迟加载的页面共用的词，应用外框从不使用
## （docs/copy.md）。

shared-count-role = { $count ->
   *[other] { $count } 个{ -role(num: "other") }
}
shared-count-posting = { $count ->
   *[other] { $count } 条{ -posting(num: "other") }
}
shared-count-company = { $count ->
   *[other] { $count } 家{ -company(num: "other") }
}
shared-curated-list = 精选列表
shared-not-for-me = 不适合我
shared-results-role = { $count ->
   *[other] { $n } 个{ -role(num: "other") }
}
shared-results-of-role = { $total ->
   *[other] { $n } / { $t } 个{ -role(num: "other") }
}
shared-results-company = { $count ->
   *[other] { $n } 家{ -company(num: "other") }
}
shared-results-of-company = { $total ->
   *[other] { $n } / { $t } 家{ -company(num: "other") }
}

## 筛选按钮（patterns/FilterSurface.tsx），用于雷达和通知
shared-filters = 筛选
shared-filters-count = 筛选 · { $count }

## 公司标签及其悬浮卡片（patterns/companies/CompanyChip.tsx）
shared-company-chip-aria = { $company }，查看公司资料
shared-company-not-followed = 不在你的雷达上。关注{ $company }即可查看其职位。
shared-company-open-roles = { $count ->
   *[other] { $count } 个在招{ -role(num: "other") }
}
shared-company-no-open-roles = 目前没有在招职位
shared-company-view-profile = 查看资料

## patterns/Pager.tsx
shared-pager-prev = 上一页
shared-pager-page-of = 第 { $page } / { $pages } 页
shared-pager-next = 下一页

## ui/EChart.tsx
shared-echart-chart-unavailable = 图表不可用。{ $summary }

## ui/FilterRail.tsx
shared-filter-rail-clear = 清除
shared-filter-rail-more = + 还有 { $hidden } 个
shared-filter-rail-select-all = 全选
shared-filter-rail-no-options-match = 没有匹配的选项。
shared-filter-rail-search = 搜索{ $title }
shared-filter-rail-search-2 = 搜索{ $title }…
shared-filter-rail-show-all = 显示全部{ $title }
shared-filter-rail-select-all-2 = 全选{ $title }

## ui/FilterSelect.tsx
shared-filter-select-clear = 清除
shared-filter-select-filter-by = 按{ $label }筛选
shared-filter-select-search = 搜索{ $label }
shared-filter-select-search-2 = 搜索{ $label }…

## patterns/companies/CompanyChip.tsx
shared-company-chip-summary = { $display_name } 概要

## ui/FilterSelect.tsx
shared-filter-select-filter = { $label }筛选
shared-filter-select-options = { $label }选项

## 按键划分的匹配度等级（backend/tracker/search/fit.py FIT_BAND_EDGES）。
shared-fit-band-strong = 强
shared-fit-band-good = 良好
shared-fit-band-some = 一般
shared-fit-band-weak = 弱
shared-pay-est-base = 估算基本工资 { $range }
shared-pay-est-base-hint = 仅基本工资。奖金和股权尚不清楚。
shared-tc-full = 总薪酬
shared-est-tc-full = 估算总薪酬
shared-base-salary-full = 基本工资
shared-base-posted-hint = 公布的区间：{ $low } 至 { $high }{ $unit }
shared-base-posted-point-hint = 公布的基本工资：{ $amount }{ $unit }
shared-base-estimate-hint = 我们对该级别的估算
shared-base-unknown = 基本工资未知
shared-pay-not-covered = { $plugin } 尚未读取
shared-pay-not-covered-hint = 当 { $plugin } 提供薪酬时，它尚未读取的公司不显示估算，也不显示内置估算。
shared-price-feed-get-key = 获取免费密钥

## ui/AsyncBoundary.tsx：调用方未提供完整消息时显示的内容
shared-empty = 这里还没有内容
shared-refresh-failed = 无法更新。显示的是上一次的结果。
