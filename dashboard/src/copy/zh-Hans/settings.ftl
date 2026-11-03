## 设置 > 语言和地区 (docs/copy.md)

settings-language-title = 语言和地区
settings-language-intro = 选择应用使用的语言，以及数字和日期的写法。更改立即生效，已打开的内容不会重新加载。
settings-language-label = 语言
settings-language-description = 公司名称、职位名称和招聘信息保持雇主的原文。
settings-language-partial = { $name }，部分翻译
settings-language-check = { $name }，用于检查文案
settings-region-label = 数字和日期
settings-region-description = 数字和日期的写法：{ $number }，{ $date }。
settings-region-automatic = 跟随系统
settings-region-option = { $country }：{ $number }，{ $date }
settings-save-failed = 无法保存。请重试。

## features/settings/ChronographDial.tsx
settings-chronograph-dial-night = 夜间
settings-chronograph-dial-full-scan = 完整扫描
settings-chronograph-dial-quick-scan = 快速扫描
settings-chronograph-dial-usually-off = 通常关机
settings-chronograph-dial-a-time-you-set = 你设定的时间
settings-chronograph-dial-reconciliation-orbit = 完整扫描
settings-chronograph-dial-discovery-orbit = 快速扫描
settings-chronograph-dial-authoritative-cycle = 完整扫描时段
settings-chronograph-dial-scan-clock = 扫描时钟
settings-chronograph-dial-draggable-schedule-marks = 可拖动的计划标记
settings-chronograph-dial-scan-running = { $kind ->
    [full] 完整扫描自 { $time } 起进行中
   *[quick] 快速扫描自 { $time } 起进行中
}
settings-chronograph-dial-move-planned-scan = { $kind ->
    [full] { $start ->
        [wake] 移动完整扫描，开机时，约 { $time }
       *[clock] 移动完整扫描，于 { $time }
    }
   *[quick] { $start ->
        [wake] 移动快速扫描，开机时，约 { $time }
       *[clock] 移动快速扫描，于 { $time }
    }
}
settings-chronograph-dial-move-company = 移动 { $company } { $scan }，当前为 { $time }
settings-chronograph-dial-stack-movable = { $stack } { $state ->
        [overdue] 现在到期
       *[scheduled] 于 { $time }
    }，打开查看全部，拖动可将 { $company } 移出
settings-chronograph-dial-stack-locked = { $stack } { $state ->
        [overdue] 现在到期
       *[scheduled] 于 { $time }
    }，打开查看全部
settings-chronograph-dial-still-at = { $stack } 仍在 { $time }
settings-chronograph-dial-schedule-clock-legend = 计划时钟图例

## features/settings/ChronographInspector.tsx
settings-chronograph-inspector-share = { $count } 个共用 { $time }
settings-chronograph-inspector-due-now = 现在到期
settings-chronograph-inspector-scheduled = 已计划
settings-chronograph-inspector-closes-roles = 关闭职位
settings-chronograph-inspector-held-until = 保留至
settings-chronograph-inspector-locked = 已锁定
settings-chronograph-inspector-scan-schedule-inspector = 扫描计划检查器
settings-chronograph-inspector-stack-movable = 可在此为其中任意一个单独设定时间，或先拖动标记将 { $company } 移出。
settings-chronograph-inspector-stack-locked = 此组中的所有标记均已锁定。
settings-chronograph-inspector-pass = { $mode ->
    [discovery] 快速扫描
   *[reconcile] 完整扫描
}
settings-chronograph-inspector-runs-at = 运行时间

## features/settings/PlanRunInspector.tsx
settings-plan-run-inspector-scanning-now = 正在扫描
settings-plan-run-inspector-when-you-turn-it-on = 开机时
settings-plan-run-inspector-planned = 已计划
settings-plan-run-inspector-companies = 公司
settings-plan-run-inspector-takes = 耗时
settings-plan-run-inspector-starts = 开始
settings-plan-run-inspector-yes = 是
settings-plan-run-inspector-repeats = 重复
settings-plan-run-inspector-every = 每隔
settings-plan-run-inspector-count-from-the-last-scan = 改为从上次扫描起计时
settings-plan-run-inspector-use-my-usual-start = 使用我平常的开始时间
settings-plan-run-inspector-it-also-runs-when-you = 关机两小时或以上后再开机时，它也会运行。
settings-plan-run-inspector-scan-inspector = 扫描检查器
settings-plan-run-inspector-repeats-every = { $anchor ->
    [fixed] 每 { $hours } 小时，固定时间
   *[last] 上次扫描后每 { $hours } 小时
}
settings-plan-run-inspector-quick-time = { $state ->
    [planned] 快速扫描时间
   *[running] 已开始
}
settings-plan-run-inspector-quick-scan-time = 快速扫描时间
settings-plan-run-inspector-quick-scan-every = 快速扫描间隔
settings-plan-run-inspector-a-quick-scan-every-hours = 每 { $hours } 小时快速扫描一次。
settings-plan-run-inspector-quick-scans-every-hours-after = 上次扫描后每 { $repeat_hours } 小时快速扫描一次。
settings-plan-run-inspector-full-time = { $state ->
    [planned] 完成时间
   *[running] 已开始
}
settings-plan-run-inspector-full-scan-done-by = 完整扫描完成时间
settings-plan-run-inspector-full-scan-back-to-your = 完整扫描已恢复为你平常的开始时间。

## features/settings/RecipesSection.tsx
settings-recipes-section-the-recipe-has-problems = { $count ->
   *[other] 规则有 { $length } 个问题：
}
settings-recipes-section-this-careers-page-asks-not = 此招聘页面要求不被自动读取，因此不会扫描它。
settings-recipes-section-no-roles-found-on-the = 前几页未找到职位。
settings-recipes-section-no-recipes-yet-write-one = 还没有规则。在下方写一条并预览。
settings-recipes-section-open = 打开
settings-recipes-section-recipe-json = 规则（JSON）
settings-recipes-section-save-draft = 保存草稿
settings-recipes-section-edit = 编辑
settings-recipes-section-check-the-whole-page = 检查整个页面
settings-recipes-section-use-this-version = 使用此版本
settings-recipes-section-scan-with-it = 用它扫描
settings-recipes-section-a-recipe-is-one-json = 一条规则是一个 JSON 对象。
settings-recipes-section-not-valid-json = JSON 无效：{ $caught }
settings-recipes-section-could-not-read-it = 无法读取
settings-recipes-section-whole-page-check-result = { $choice ->
    [yes] 预览结果
   *[no] 整页检查结果
}
settings-recipes-section-not-checked-the-whole-page = { $choice ->
    [yes] 已检查：读完了整个页面，{ $pages } 页共 { $found } 个职位。
   *[no] 未检查：整个页面未能读到末尾。
}
settings-recipes-section-no-place-stated = 未注明地点
settings-recipes-section-in-use = 使用中
settings-recipes-section-not-checked = { $choice ->
    [yes] 检查于 { $validated_at }
   *[no] 未检查
}
settings-recipes-section-couldn-t-preview-the-recipe = 无法预览规则。
settings-recipes-section-saved-version-of = 已保存 { $slug } 的第 { $version } 版。
settings-recipes-section-couldn-t-save-the-recipe = 无法保存规则。
settings-recipes-section-couldn-t-check-the-whole = 无法检查整个页面。
settings-recipes-section-version-is-now-the-one = 第 { $version } 版现在用于扫描新公司。
settings-recipes-section-couldn-t-switch-versions = 无法切换版本。
settings-recipes-section-is-now-scanned-with-its = { $company } 现在使用 { $slug } 扫描。只有当已检查的版本读完它的整个页面后，它缺失的职位才会关闭。
settings-recipes-section-couldn-t-scan-that-company = 无法用此规则扫描该公司。
settings-recipes-section-recipes = 规则
settings-recipes-section-a-recipe-tells-roleband-how = 规则说明如何读取尚未支持的招聘页面。
settings-loading = 加载中…
settings-recipes-section-draft-only = { $choice ->
    [yes] 正在使用第 { $active_version } 版
   *[no] 仅草稿
}
settings-recipes-section-not-checked-2 = { $choice ->
    [yes] 已检查
   *[no] 未检查
}
settings-recipes-section-scans-no-company = { $choice ->
    [yes] 扫描 { $join }
   *[no] 未扫描任何公司
}
settings-recipes-section-new-recipe = 新规则
settings-recipes-section-preview = { $choice ->
    [yes] 正在预览…
   *[no] 预览
}
settings-recipes-section-versions = 版本
settings-recipes-section-versions-2 = 版本
settings-recipes-section-version = 第 { $version } 版
settings-recipes-section-scan-a-company-with-it = 用它扫描一家公司
settings-recipes-section-no-company-is-scanned-with = { $choice ->
    [yes] 扫描 { $join }。
   *[no] 还没有公司使用它扫描。
}
settings-company = 公司
settings-recipes-section-choose-a-company = 选择一家公司

## features/settings/RetentionSection.tsx
settings-retention-section-kept = 已保留 { $stored } 条
settings-retention-section-remove-after = { $choiceLabel }后删除
settings-cancel = 取消
settings-retention-section-1-year = 1 年
settings-retention-section-never = 从不
settings-retention-section-makes-postings-due-they-are = 设为 { $days } 后，{ $due } 条招聘信息将到期待删。它们会在接下来的扫描中被删除。
settings-retention-section-none-yet = 暂无
settings-retention-section-text = { $choice ->
    [yes] { " " }· 下次扫描时会删除更多
   *[no] { "" }
}
settings-retention-section-removed = { $at } · 已删除 { $removed } 条{ $more }
settings-retention-section-data-retention = 数据保留
settings-retention-section-roleband-keeps-every-posting-its = 扫描找到的每条招聘信息都会保留，因此你更改搜索条件后，职位可以立即出现在你的雷达上。
settings-retention-section-remove-postings-after = 招聘信息删除期限
settings-retention-section-a-posting-stops-being-read = 招聘信息不再发布，或你取消关注其公司后，就不再被扫描。超过这段时间没有任何扫描看到它，它就会被删除。你的雷达上的职位、你保存的内容及其历史记录永远不会被删除。
settings-retention-section-no-longer-listed = · { $no_longer_listed } 条已不再发布
settings-retention-section-from-companies-you-stopped-following = · { $stopped_following } 条来自你已取消关注的公司
settings-retention-section-remove-postings-after-2 = 招聘信息删除期限
settings-retention-section-last-removal = 上次删除
settings-retention-section-due-for-removal = 待删除
settings-retention-section-due-count = { $due } 条{ -posting(num: "other") }
settings-retention-section-due-detail = { $state ->
    [never] 设为“永不”时不会删除任何内容。
   *[set] 待删除的招聘信息会在扫描时删除，保存时不会删除。
}
settings-retention-section-saved = 已保存。

## features/settings/ScheduleChronograph.tsx
settings-schedule-chronograph-on-wake = 开机时{ $kind ->
        [full] 完整扫描
       *[quick] 快速扫描
    }
settings-schedule-chronograph-due = 到期 · { $name }
settings-schedule-chronograph-waiting = { $waiting ->
    [paused] 已暂停
    [day_off] 休息日
   *[mains] 等待接通电源
}
settings-schedule-chronograph-waiting-status = { $waiting ->
    [paused] 已暂停
    [day_off] 今天不扫描
   *[mains] 正在使用电池
}
settings-schedule-chronograph-the-next-scan-runs-once = 接通电源后运行下一次扫描
settings-schedule-chronograph-next-scan = 下次扫描 { $time }
settings-schedule-chronograph-hub-title = { $state ->
    [running] 正在扫描
   *[next] 下次扫描
}
settings-schedule-chronograph-due-now = 现在到期
settings-schedule-chronograph-on-wake-2 = 开机时
settings-schedule-chronograph-when-you-turn-it-on = 开机时，约 { $time }
settings-schedule-chronograph-next-dispatch = 下次扫描
settings-schedule-chronograph-hub-stack = { $mode ->
    [reconcile] { $count } 次完整扫描
   *[discovery] { $count } 次快速扫描
}
settings-schedule-chronograph-hub-company = { $mode ->
    [reconcile] { $company } · 完整扫描
   *[discovery] { $company } · 快速扫描
}
settings-schedule-chronograph-projected-through = 预计至 { $time }
settings-schedule-chronograph-stack-movable = { $count } 个标记共用 { $time }：可在下方设定任意时间，或拖动标记将 { $company } 移出。
settings-schedule-chronograph-stack-locked = { $count } 个标记共用 { $time }。它们全部已锁定。
settings-schedule-chronograph-saving-schedule = 正在保存计划…
settings-schedule-chronograph-drag-a-scan-to-move = 拖动扫描可移动它 · 点击可设定精确时间

## features/settings/ScheduleSection.tsx
settings-schedule-section-how-scanning-works = 扫描如何运作
settings-schedule-section-reads-every-company-s-whole = 读取你关注的每家公司的整个招聘页面，因此也能关闭已消失的职位。它在你开机时运行，且每天至少一次。
settings-schedule-section-looks-for-new-and-changed = 电脑开机期间，每 { $repeat_hours } 小时在你关注的每家公司查找新增和变更的职位。它从不关闭职位。
settings-schedule-section-when-the-computer-is-off = 电脑关机时
settings-schedule-section-nothing-runs-and-missed-scans = 不会运行任何扫描，错过的扫描也不会补做：下一次在你开机时运行。计划会按你通常使用电脑的时间自动调整，无需设置。
settings-schedule-section-times-you-set = 你设定的时间
settings-schedule-section-a-company-with-a-time = 有单独时间的公司会保留该时间。拖动它的标记，或点击后输入时间。
settings-schedule-section-outer-orbit-is-the-full = 外圈是完整扫描，内圈是快速扫描；每段弧的长度等于扫描所需时间。着色的时段是电脑通常关机的时间，指针表示现在。
settings-schedule-section-discovery = 快速扫描
settings-schedule-section-probes-a-company-s-board = 查看公司的招聘页面，查找新增和变更的职位。它可以添加或更新职位，但从不关闭职位。
settings-schedule-section-reconciliation = 完整扫描
settings-schedule-section-the-authoritative-cycle-only-this = 只有完整扫描可以关闭已消失的职位，且仅在完整读取该公司的招聘页面之后。
settings-schedule-section-the-cycle = 同时进行的扫描
settings-schedule-section-marks-coming-due-together-dispatch = 同时到期的扫描会一起运行，同时最多 { $maxParallel } 个网站，因此弧线显示的是运行时长，而不只是开始时间。
settings-schedule-section-editing = 编辑
settings-schedule-section-drag-a-mark-around-the = 沿表盘拖动标记，或点击后输入时间。时间以 10 分钟为单位对齐。被提供方策略阻止的标记保持锁定。
settings-schedule-section-outer-orbit-is-reconciliation-inner = 外圈是完整扫描，内圈是快速扫描；着色的时段是夜间，指针表示当前本地时间。
settings-schedule-section-first-scan-of-the-day = 每天第一次扫描
settings-schedule-section-full-scan-done-by = 完整扫描，完成时间
settings-schedule-section-then-while-it-is-on = 之后，开机期间
settings-schedule-section-a-quick-scan-every-hours = 每 { $repeat_hours } 小时快速扫描一次
settings-schedule-section-days = 日期
settings-schedule-section-power = 电源
settings-schedule-section-only-when-plugged-in = 仅在接通电源时
settings-schedule-section-pause = 暂停
settings-schedule-section-paused-until = 暂停至
settings-schedule-section-resume = 恢复
settings-schedule-section-after-two-hours-or-more = { $learned } 关机两小时或以上后，你回来时会运行一次完整扫描；错过的扫描不会补做。
settings-schedule-section-need-attention = { $count ->
   *[other] { $count } 个需要处理
}
settings-schedule-section-scan-clock = 扫描时钟
settings-schedule-section-next-scans = 接下来的扫描
settings-schedule-section-companies = { $companies } 家公司 · { $duration }
settings-schedule-section-companies-keep-a-time-you = { $count ->
   *[other] { $count } 家公司保留你设定的时间
}
settings-schedule-section-upcoming = 即将进行
settings-schedule-section-bindings-projected-through = { $count ->
   *[other] { $count } 次扫描 · 预计至 ~{ $end }
}
settings-schedule-section-more-see-all-deadlines = +{ $count } 个 · 查看所有截止时间
settings-schedule-section-discovery-cadence = 快速扫描间隔
settings-schedule-section-adapts-to-8-12-24h = 快速扫描为空后调整为 8 / 12 / 24 小时
settings-schedule-section-only-this-cycle-can-close = 只有完整扫描能关闭缺失的职位
settings-schedule-section-provider-pressure = 提供方负载
settings-schedule-section-max = 最多 { $max_parallel_providers } 个
settings-schedule-section-one-binding-per-provider-in = 每个分片中每个提供方一个绑定
settings-schedule-section-plan-roster = { $companies } 家公司 · 每次完整扫描 { $roster } 家
settings-schedule-section-plan-roster-pinned = { $companies } 家公司 · 每次完整扫描 { $roster } 家 · { $pinned } 家在你设定的时间
settings-schedule-section-plan-roster-excepted = { $companies } 家公司 · 每次完整扫描 { $roster } 家 · { $excepted } 个例外
settings-schedule-section-plan-roster-pinned-excepted = { $companies } 家公司 · 每次完整扫描 { $roster } 家 · { $pinned } 家在你设定的时间 · { $excepted } 个例外
settings-schedule-section-timers-roster = { $companies } 家公司 · 已计划 { $scheduled } 家
settings-schedule-section-timers-roster-excepted = { $companies } 家公司 · 已计划 { $scheduled } 家 · { $excepted } 个例外
settings-schedule-section-timers-roster-reconcile-only = { $companies } 家公司 · 已计划 { $scheduled } 家 · { $reconcileOnly } 个仅完整扫描
settings-schedule-section-timers-roster-excepted-reconcile-only = { $companies } 家公司 · 已计划 { $scheduled } 家 · { $excepted } 个例外 · { $reconcileOnly } 个仅完整扫描
settings-schedule-section-every-company-s-scans = 每家公司的扫描
settings-schedule-section-a-full-scan-reads-a = 完整扫描读取公司的整个招聘页面，可以关闭已消失的职位。快速扫描查找新增和变更的职位，从不关闭职位。
settings-schedule-section-last-full-scan = 上次完整扫描
settings-schedule-section-last-quick-scan = 上次快速扫描
settings-schedule-section-how-it-is-scanned = 扫描方式
settings-schedule-section-not-yet = 尚未
settings-schedule-section-not-available = 不可用
settings-schedule-section-until = 至 { $cooldown_until }
settings-schedule-section-persisted-deadlines = 已保存的截止时间
settings-schedule-section-discovery-can-add-or-update = 快速扫描可以添加或更新职位，但从不关闭缺失的职位。完整扫描只在完整读取招聘页面之后才会关闭职位。提供方冷却会推迟可执行时间，但不会覆盖公司本来的截止时间。
settings-schedule-section-provider-state = 提供方状态
settings-schedule-section-reconciliation-only = 仅完整扫描
settings-schedule-section-non-authoritative = 不能关闭职位
settings-schedule-section-not-scheduled = 未计划
settings-schedule-section-only-when-you-press-scan = 仅在你点击“立即扫描”时
settings-schedule-section-only-after-you-allow-it = 仅在你允许之后
settings-schedule-section-full-scan-at = 完整扫描于 { $reconcile_anchor_minute }
settings-schedule-section-quick-scan-at = 快速扫描于 { $discovery_anchor_minute }
settings-schedule-section-its-own-time = 单独时间：{ $times }
settings-schedule-section-planned-scans = { $scans ->
    [all] 所有计划扫描
   *[full] 仅完整扫描
}
settings-schedule-section-only-when-you-scan = 仅在你扫描时
settings-schedule-section-needs-your-ok = 需要你的许可
settings-schedule-section-policy-denied = 策略拒绝
settings-schedule-section-cooling-down = 冷却中
settings-schedule-section-unscheduled = 未计划
settings-schedule-section-manual-priority = 手动优先
settings-schedule-section-paused = 已暂停
settings-schedule-section-provider-policy-denies-scheduled-collection = 其网站不允许定时扫描
settings-schedule-section-provider-scheduling-is-paused = 提供方计划已暂停
settings-schedule-section-setting-scan-times = 正在为 { $count } 家新公司设置扫描时间。
settings-schedule-section-cooling-down-until = 冷却至 { $cooldown_until }
settings-schedule-section-how-scanning-works-2 = 扫描如何运作
settings-schedule-section-how-scanning-works-3 = 扫描如何运作
settings-schedule-section-1-hour = 1 小时
settings-schedule-section-3-hours = 3 小时
settings-schedule-section-until-tomorrow = 直到明天
settings-schedule-section-couldn-t-save-that-change = 无法保存该更改。请重试。
settings-schedule-section-plan-settings = 计划设置
settings-schedule-section-starts-about = { $source ->
    [usual] 已学习你平常的开始时间。约 { $time } 开始 · { $companies } 家公司
   *[set] 约 { $time } 开始 · { $companies } 家公司
}
settings-schedule-section-starts-about-duration = { $source ->
    [usual] 已学习你平常的开始时间。约 { $time } 开始 · { $companies } 家公司 · { $duration }
   *[set] 约 { $time } 开始 · { $companies } 家公司 · { $duration }
}
settings-schedule-section-no-time-set = 未设定时间：在你开机时运行，且每天至少一次 · { $companies } 家公司
settings-schedule-section-no-time-set-duration = 未设定时间：在你开机时运行，且每天至少一次 · { $companies } 家公司 · { $duration }
settings-schedule-section-clear-ready-by = { $fallback ->
    [usual] 使用我平常的开始时间
   *[none] 清除
}
settings-schedule-section-scan-days = 扫描日
settings-schedule-section-days-a-week = { $count ->
    [7] 每天
   *[other] 每周 { $count } 天
}
settings-schedule-section-power-note = { $power ->
    [waiting] 正在使用电池：下次扫描会等待接通电源。
    [mains] 电脑使用电池时，扫描会等待。
   *[any] 使用电池时也会扫描。
}
settings-schedule-section-pause-scans = 暂停扫描
settings-schedule-section-when-roleband-scans = 何时扫描
settings-schedule-section-next-scans-2 = 接下来的扫描
settings-schedule-section-run-title = { $state ->
    [running] { $kind ->
            [full] 完整扫描
           *[quick] 快速扫描
        } · 正在扫描
    [ready] { $kind ->
            [full] 完整扫描
           *[quick] 快速扫描
        } · { $time } 前就绪
    [wake] { $kind ->
            [full] 完整扫描
           *[quick] 快速扫描
        } · 开机时
   *[planned] { $kind ->
            [full] 完整扫描
           *[quick] 快速扫描
        }
}
settings-schedule-section-times-you-set-2 = 你设定的时间
settings-schedule-section-scan-at-a-time-you-set = { $mode ->
    [reconcile] 在你设定的时间完整扫描
   *[discovery] 在你设定的时间快速扫描
}
settings-schedule-section-upcoming-scans = 即将进行的扫描
settings-schedule-section-title-due-now = { $title } · 现在到期
settings-schedule-section-pass-provider = { $mode ->
    [reconcile] 完整扫描 · { $provider }
   *[discovery] 快速扫描 · { $provider }
}
settings-schedule-section-scheduler-policy = 计划策略
settings-schedule-section-deadlines-link = { $schedule ->
    [plan] 每家公司的扫描
   *[timers] 所有已保存的截止时间
}
settings-schedule-section-every-company-s-scans-2 = 每家公司的扫描
settings-schedule-section-what-the-columns-mean = 各列的含义
settings-schedule-section-all-persisted-deadlines-2 = 所有已保存的截止时间
settings-schedule-section-how-scheduling-safety-works = 计划安全机制如何运作
settings-schedule-section-schedule = 计划

## features/settings/charts/plan.ts
settings-plan-hours-minutes = { $hours } 小时 { $minutes } 分钟
settings-plan-hours = { $hours } 小时
settings-plan-still-learning-when-your-computer = 仍在学习你的电脑何时开机：已观察 { $observed_days } / { $needed_days } 天。
settings-plan-learned-every-day = 根据最近 { $days } 天学习：你的电脑每天 { $usual ->
        [all] 全天开机
        [off] 通常关机
       *[set] { $times } 开机
    }。
settings-plan-learned-weekdays-weekends = 根据最近 { $days } 天学习：你的电脑工作日 { $weekdays ->
        [all] 全天开机
        [off] 通常关机
       *[set] { $weekdayTimes } 开机
    }，周末 { $weekends ->
        [all] 全天开机
        [off] 通常关机
       *[set] { $weekendTimes } 开机
    }。
settings-plan-learned = 根据最近 { $days } 天学习：你的电脑{ $usual ->
        [all] 全天开机
        [off] 通常关机
       *[set] { $times } 开机
    }。
settings-plan-learned-unseen = 根据最近 { $days } 天学习：你的电脑尚未观察到开机。
settings-plan-companies = { $kind ->
        [full] 完整扫描
       *[quick] 快速扫描
    } · { $companies } 家公司
settings-plan-scan-kind = { $kind ->
    [full] 完整扫描
   *[quick] 快速扫描
}

## features/settings/charts/schedule.ts
settings-schedule-24-hour-scan-clock-planned = 24 小时扫描时钟：{ $runs } 次计划扫描，以及 { $pinned } 家公司在你设定的时间扫描。
settings-schedule-24-hour-scan-clock-planned-next = 24 小时扫描时钟：{ $runs } 次计划扫描，下一次是 { $companies } 家公司的{ $kind ->
        [full] 完整扫描
       *[quick] 快速扫描
    }，以及 { $pinned } 家公司在你设定的时间扫描。
settings-schedule-24-hour-chronograph-discovery-probes = 24 小时扫描时钟：{ $probes } 次快速扫描、{ $reconciliations } 次完整扫描，以及 { $excluded } 家被排除或未计划的公司。
settings-schedule-stack = { $count } { $schedule ->
        [plan] { $mode ->
            [reconcile] 完整扫描
           *[discovery] 快速扫描
        }
       *[timers] { $mode ->
            [reconcile] 完整扫描
           *[discovery] 快速扫描
        }
    }
settings-schedule-mode-name = { $schedule ->
    [plan] { $mode ->
        [discovery] 快速扫描
       *[reconcile] 完整扫描
    }
   *[timers] { $mode ->
        [discovery] 快速扫描
       *[reconcile] 完整扫描
    }
}
settings-schedule-provider-policy-denies-scheduled-collection = 提供方策略禁止计划采集。
settings-schedule-provider-scheduling-is-paused = 提供方计划已暂停。
settings-schedule-scan-schedule-is-not-set = 尚未设置扫描计划。
settings-schedule-cancel-the-queued-manual-scan = 更改此时间前，请先取消排队中的手动扫描。

## features/settings/useDialDrag.ts
settings-use-dial-drag-drag-a-mark-to-reschedule = 拖动标记可重新安排 · 点击可设定精确时间
settings-use-dial-drag-moved-to = { $company } { $scan } 已移至 { $time }。
settings-use-dial-drag-couldn-t-move-that-scan = 无法移动该扫描。请重试。

## features/settings/usePlanDrag.ts
settings-use-plan-drag-quick-scans-moved-one-at = 快速扫描已移动：一次在 { $time }。
settings-use-plan-drag-full-scan-moved-to-done = 完整扫描已移至 { $start }，{ $doneBy } 前完成。

## routes/SettingsRoute.tsx
settings-route-settings-sections = 设置分区

## features/settings/charts/plan.ts (by hand)
settings-plan-usually-off = 通常关机
settings-plan-all-day = 全天

## features/settings/ChronographInspector.tsx
settings-chronograph-inspector-every = { $unit ->
    [day] 每 { $count } 天
   *[hour] 每 { $count } 小时
}
settings-chronograph-inspector-no-cadence = -
settings-chronograph-inspector-time = { $company } { $scan }时间
settings-chronograph-inspector-no = 否

## features/settings/RecipesSection.tsx
settings-recipes-section-saved = 保存于 { $created_at }
settings-recipes-section-load-failed = 无法加载规则
settings-recipes-section-refresh-failed = 无法更新规则。显示的是上一次的结果。
settings-recipes-section-versions-load-failed = 无法加载此规则的版本
settings-recipes-section-versions-refresh-failed = 无法更新此规则的版本。显示的是上一次的结果。

## features/settings/RetentionSection.tsx
settings-retention-section-days = { $days } 天
settings-retention-section-due = { $days }（{ $due } 条到期）
settings-retention-section-load-failed = 无法加载数据保留设置

## features/settings/ScheduleChronograph.tsx
settings-schedule-chronograph-companies = { $count } 家公司
settings-schedule-chronograph-in-hours-minutes = { $hours } 小时 { $minutes } 分钟后
settings-schedule-chronograph-in-minutes = { $minutes } 分钟后
settings-schedule-chronograph-since = 自 { $time } 起

## features/settings/ScheduleSection.tsx
settings-schedule-section-every = 每 { $cadence }
settings-schedule-section-loading = 正在加载扫描计划…
settings-schedule-section-load-failed = 无法加载扫描计划
settings-schedule-section-empty = 暂无扫描计划
settings-schedule-section-now = 现在

## features/settings/charts/plan.ts
settings-plan-min = { $minutes } 分钟
settings-plan-to = { $start } 至 { $end }
settings-plan-about = 约 { $duration }

## 计划的频率和快速扫描间隔，以小时或天为单位。
settings-schedule-hours = { $hours } 小时
settings-schedule-days = { $days } 天

settings-plugins-section-coming-soon = 即将推出
settings-plugins-section-coming-soon-note = 在这里启用和管理插件的功能将在后续版本中推出。
settings-plugins-section-title = 插件
settings-plugins-section-intro = 可选的附加组件，带来更多数据和功能。
settings-plugins-section-search = 搜索插件
settings-plugins-section-on-count = 已开启 { $on }/{ $total }
settings-plugins-section-none = 尚未安装插件。
settings-price-feed-title = 股价
settings-price-feed-intro = 上市公司的每日收盘价，显示在它们的资料页上，每天更新一次。
settings-price-feed-source = Tiingo
settings-price-feed-source-terms = 使用你自己的密钥，个人使用免费。
settings-price-feed-key-state =
    { $origin ->
        [settings] 密钥已保存
        [environment] 密钥在应用外设置
       *[none] 尚无密钥
    }
settings-price-feed-priced =
    { $count ->
       *[other] { $count } 家公司 · 最新收盘 { $date }
    }
settings-price-feed-updated = 更新于 { $ago }
settings-price-feed-add = 添加密钥
settings-price-feed-replace = 替换密钥
settings-price-feed-remove = 移除密钥
settings-price-feed-dialog-title = Tiingo 密钥
settings-price-feed-dialog-note = 粘贴你 Tiingo 账户中的密钥。它保存在这台电脑上，只会发送给 Tiingo。
settings-price-feed-dialog-field = 密钥
settings-price-feed-dialog-save =
    { $choice ->
        [yes] 正在保存
       *[no] 保存密钥
    }
settings-price-feed-unauthorized = 上次更新时 Tiingo 拒绝了这个密钥。请在你的 Tiingo 账户中核对后重新保存。
settings-price-feed-rate-limited = 已达到 Tiingo 的每小时上限。其余股价将在上限重置后到达。
settings-price-feed-saved =
    { $check ->
        [ok] 已保存，Tiingo 已回应。其余股价将在其上限允许时陆续到达。
       *[other] 已保存。Tiingo 暂时无法核对这个密钥；它回应后股价会陆续到达。
    }
settings-price-feed-waiting = 还有 { $count } 个，{ $time }
settings-price-feed-updating = 正在更新股价…
settings-price-feed-update-now = 立即更新
settings-price-feed-removed = 已移除。已显示的股价会保留。
settings-price-feed-load-failed = 无法加载股价设置
settings-plugins-section-no-match = 没有已安装的插件符合你的搜索。
settings-plugins-section-state =
    { $state ->
        [needs_approval] 需要批准
        [enabled] 已开启
        [disabled] 已关闭
        [paused] 已暂停
        [updating] 正在更新
        [removed] 已卸载
       *[other] 已安装
    }
settings-plugins-section-slot = { $slot ->
        [pay_levels] 职级薪酬
        [pay_observations] 薪酬估算
        [company_facts] 公司信息
        [company_benefits] 福利
       *[other] 其他数据
    }
settings-plugins-section-answers = 提供 { $slots }
settings-plugins-section-brings = 带来 { $slots }
settings-plugins-section-waiting = 等待首次更新
settings-plugins-section-read =
    { $companies ->
       *[other] 已读取 { $read }/{ $companies } 家{ -company }
    }
settings-plugins-section-next-update = 下次更新 { $when }
settings-plugins-section-paused = 已暂停
settings-plugins-section-use = 使用 { $name }
settings-plugins-section-open-settings = { $name } 的设置
settings-plugins-section-start = 开始
settings-plugins-section-start-name = 开始 { $name }
settings-plugins-section-pause = 暂停
settings-plugins-section-resume = 继续
settings-plugins-section-turn-on-first = 请先开启
settings-plugins-section-approve-first = 请先批准
settings-plugins-section-more = 更多插件
settings-plugins-section-more-note = 很快就能在这里查找和添加插件。目前请在 RoleBand 文件夹中，用命令行安装：
settings-plugins-section-waiting-wake = 这台 Mac 完全唤醒后开始更新。
settings-plugins-section-moved =
    { $moved ->
       *[other] { $when }，{ $companies ->
           *[other] { $companies } 家公司
        }的 { $moved } 个职位估算发生了变化。
    }
settings-plugins-section-pending =
    { $pending ->
       *[other] 正在更新估算：还剩 { $pending } 个职位。
    }
settings-plugins-section-review = 审核并批准
settings-plugins-section-approve-title = 批准这个插件？
settings-plugins-section-robots-heading = 网站规则
settings-plugins-section-robots-reading = 正在读取各网站的规则
settings-plugins-section-robots-failed = 暂时无法读取这些网站的规则。它会在每次更新时按读到的规则执行。
settings-plugins-section-robots-site =
    { $state ->
        [none] 没有设置针对 RoleBand 的规则。
        [refused] 不公开它的规则，因此 RoleBand 视其为不开放。
        [failed] 无法访问；每次更新时都会读取它的规则。
       *[rules] 要求 RoleBand 跳过这些页面：
    }
settings-plugins-section-robots-more = 以及另外 { $count } 条
settings-plugins-section-robots-allow = 越过这些规则读取
settings-plugins-section-robots-allow-note = 除非你允许，否则会遵守这些规则，而网站可能因此减慢或阻止这台电脑的访问。如果某个网站更改了规则，会再次询问你。
settings-plugins-section-robots-title = 越过网站的规则读取？
settings-plugins-section-robots-nothing = 目前它的网站都没有设置针对 RoleBand 的规则。
settings-plugins-section-robots-allow-button = 允许
settings-plugins-section-robots-close = 关闭
settings-plugins-section-turn-on-title = 开启这个插件？
settings-plugins-section-turn-on-lead = 开启期间，它带来的内容会替代所有公司的内置数据。
settings-plugins-section-turn-on = 开启
settings-plugins-section-approve-lead = 批准后它可以在这台 Mac 上运行。开启期间，它带来的内容会替代所有公司的内置数据。它会自行运行，只读取下面的网站，绝不会更改你的级别。
settings-plugins-section-approve-gap = 在它读取一家公司之前，这家公司不显示它带来的任何内容，也不会用内置数据代替。
settings-plugins-section-approve-read = 目前已读取：{ $slots }。
settings-plugins-section-approve-slot = { $slot }：{ $count }
settings-plugins-section-approve-left = 读取其余部分大约需要 { $duration } 的更新，每家公司约 { $pace }。
settings-plugins-section-approve-reads = 读取
settings-plugins-section-approve-updates = 更新
settings-plugins-section-approve-licence = 许可证
settings-plugins-section-credit = 署名
settings-plugins-section-approve-code = 代码
settings-plugins-section-approve-identity =
    { $identity ->
        [identified] 它以 RoleBand 的身份公开访问这些网站。
        [browser_identity] 它以网页浏览器的样子访问这些网站。
        [tls_fingerprint] 它以网页浏览器的样子访问这些网站，连连接方式也一样。
        [headless] 它在隐藏的网页浏览器中访问这些网站。
        [proxy] 它通过另一个网络访问这些网站。
       *[other] 它访问这些网站的方式是这个版本无法描述的。
    }
settings-plugins-section-approve-needs =
    { $need ->
        [followed_companies] 它会收到你关注的公司列表。
       *[other] 它会收到这里保存的其他数据。
    }
settings-plugins-section-approve-facts = 它可能提供每家公司的{ $fields }。
settings-plugins-section-fact-field =
    { $field ->
        [display_name] 名称
        [ticker] 股票代码
        [is_public] 是否上市
        [headcount] 员工人数
        [hq_city] 总部城市
        [website] 网站
        [year_founded] 成立年份
        [logo_url] 标志
        [brand_color] 品牌颜色
       *[other] 其他信息
    }
settings-plugins-section-approve-fact-rank = 开启期间，它们会替代内置信息显示，绝不并列显示。
settings-plugins-section-approve-still-on = 它仍处于开启状态。自你批准后它发生了变化，因此会等待你确认后再运行或提供数据。
settings-plugins-section-schedule =
    { $schedule ->
        [daily] 每天，接通电源时
        [weekly] 每周，接通电源时
        [monthly] 每月，接通电源时
        [manual] 仅在你要求时
       *[other] 按它自己的计划
    }
settings-plugins-section-approve = 批准
settings-plugins-section-approve-and-turn-on = 批准并开启
settings-plugins-section-approve-and-use = 批准并继续使用
settings-plugins-section-remove-title = 删除这个插件的数据？
settings-plugins-section-remove-lead = { $what ->
        [rows] 这会删除它添加的{ $kinds }，以及据此得出的估算和薪酬历史。估算会回到内置数据。它记录为历史的内容会保留，但不会被读取。
       *[history] 这会删除据它得出的估算，以及它关于自身读取情况的记录。它记录的{ $kinds }会作为历史保留，关闭期间不会被读取。
    }
settings-plugins-section-remove-confirm = 输入 { $name } 以确认
settings-plugins-section-remove = 删除数据
settings-plugins-section-removed =
    { $rows ->
        [0] 已删除它的数据。
       *[other] 已删除 { $rows } 行。
    }
settings-plugins-section-failed =
    { $action ->
        [review] 无法加载它请求执行的操作。请重试。
        [approve] 无法批准。请重试。
        [on_after_approve] 已批准，但无法开启。请重试。
        [on] 无法开启。请重试。
        [off] 无法关闭。请重试。
        [update] 无法开始更新。请重试。
        [pause] 无法暂停。请重试。
        [resume] 无法继续。请重试。
        [schedule] 无法更改更新频率。请重试。
        [uninstall] 无法卸载。请重试。
        [remove] 无法删除它的数据。请重试。
        [robots] 无法保存你对网站规则的选择。请重试。
       *[other] 操作未成功。请重试。
    }
settings-plugins-section-loading = 正在加载插件…
settings-plugins-section-load-failed = 无法加载插件
settings-plugins-section-refresh-failed = 无法更新插件。显示的是上一次的结果。
settings-plugin-settings-back = 全部插件
settings-plugin-settings-not-found = 这个插件未安装。
settings-plugin-settings-needs-approval = 它需要你的批准才能运行：它是新的，或者自你批准后发生了变化。
settings-plugin-settings-updates = 更新
settings-plugin-settings-how-often = 频率
settings-plugin-settings-option =
    { $schedule ->
        [daily] 每天
        [weekly] 每周
        [monthly] 每月
        [manual] 按需
       *[other] 其他
    }
settings-plugin-settings-suggests =
    { $schedule ->
        [daily] 插件建议每天更新。计划中的更新会等到这台 Mac 接通电源。
        [weekly] 插件建议每周更新。计划中的更新会等到这台 Mac 接通电源。
        [monthly] 插件建议每月更新。计划中的更新会等到这台 Mac 接通电源。
        [manual] 插件建议仅在你要求时更新。计划中的更新会等到这台 Mac 接通电源。
       *[other] 计划中的更新会等到这台 Mac 接通电源。
    }
settings-plugin-settings-next = 下次更新
settings-plugin-settings-next-value =
    { $state ->
        [paused] 已暂停。在你继续之前不会自动更新。
        [manual] 仅在你按下开始时
        [off] 关闭期间不更新
        [first] 下次扫描时
        [approval] 在你批准之前不更新
        [continues] 稍后，以完成上次更新
       *[due] { $when }
    }
settings-plugin-settings-last = 上次更新
settings-plugin-settings-run =
    { $outcome ->
        [clean] 更新于 { $when }
        [partial] 部分更新于 { $when }
        [continues] 部分更新于 { $when }，稍后继续
        [running] 正在更新
        [stopped] 停止于 { $when }
        [bounded] 时间用尽于 { $when }
        [error] 无法更新，{ $when }
       *[other] 上次运行于 { $when }
    }
settings-plugin-settings-run-progress =
    { $outcome ->
        [running] 正在更新 { $read }
        [partial] 部分更新于 { $when }：{ $read }
        [continues] 部分更新于 { $when }：{ $read }，稍后继续
        [stopped] { $read } 后停止于 { $when }
        [bounded] { $read } 后时间用尽于 { $when }
        [error] { $read } 后无法更新，{ $when }
       *[other] 上次运行于 { $when }：{ $read }
    }
settings-plugin-settings-run-summary = { $run }：{ $summary }
settings-plugin-settings-never = 尚未更新
settings-plugin-settings-outcome =
    { $outcome ->
        [clean] 已更新
        [partial] 部分更新
        [continues] 部分更新
        [running] 正在更新
        [stopped] 已停止
        [bounded] 时间用尽
        [error] 无法更新
       *[other] 已运行
    }
settings-plugin-settings-brings = 它带来的内容
settings-plugin-settings-slot-state =
    { $state ->
        [approval] 在你批准之前不使用
       *[off] 关闭期间不使用
    }
settings-plugin-settings-slot-none = { $slot ->
        [pay_levels] 没有估算
        [pay_observations] 没有薪酬估算
        [company_facts] 没有公司规模
        [company_benefits] 没有福利
       *[other] 没有任何相关内容
    }
settings-plugin-settings-slot-gap =
    { $read ->
        [0] 在它读取一家公司之前，这家公司显示{ $none }。
       *[other]
            { $left ->
               *[other] 其余 { $left } 家在被读取之前显示{ $none }。
            }
    }
settings-plugin-settings-left = 待读取
settings-plugin-settings-left-value = 大约 { $duration } 的更新，每家公司约 { $pace }
settings-plugin-settings-reports = 插件报告
settings-plugin-settings-report = { $value } { $label }
settings-plugin-settings-report-at = 截至 { $when }
settings-plugin-settings-robots-state =
    { $state ->
        [lapsed] 自你允许以来 { $hosts } 更改了规则；在你审核之前会跳过这些页面
        [allowed] 按你在 { $when } 的允许，越过其网站的规则读取
       *[follows] 遵守各网站的规则
    }
settings-plugin-settings-robots-review = 审核
settings-plugin-settings-robots-stop = 遵守规则
settings-plugin-settings-version = 版本
settings-plugin-settings-history = 最近的更新
settings-plugin-settings-no-history = 暂无更新。
settings-plugin-settings-published =
    { $rows ->
       *[other] { $rows } 行
    }
settings-plugin-settings-remove-heading = 删除
settings-plugin-settings-remove-note =
    { $what ->
        [rows] 删除它的数据会清除它添加的{ $kinds }；请先关闭它。
       *[history] 删除它的数据会清除据它得出的内容；它记录的{ $kinds }会作为历史保留。
    }卸载会从这台 Mac 上移除它的代码，并保留它的数据（不被读取），直到你删除。
settings-plugin-settings-remove-waiting = 估算仍在读取它的数据。删除数据会等到估算更新完毕。
settings-plugin-settings-uninstall = 卸载
settings-plugin-settings-uninstall-title = 卸载这个插件？
settings-plugin-settings-uninstall-lead = 这会关闭它，并从这台 Mac 上移除它的代码。它添加的数据会保留（不被读取），直到你删除。重新安装需要你的批准。
settings-plugin-settings-loading = 正在加载这个插件…
settings-plugin-settings-load-failed = 无法加载这个插件
settings-plugin-settings-refresh-failed = 无法更新这个插件。显示的是上一次的结果。
