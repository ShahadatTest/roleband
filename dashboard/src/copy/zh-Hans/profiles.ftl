## profiles：en/profiles.ftl 的译文

## features/company-profiles/CompanyOffices.tsx
profiles-company-offices-no-office-matches-that-search = 没有与该搜索匹配的办公地点。
profiles-company-offices-hq = 总部
profiles-company-offices-open = { $open_count } 个在招
profiles-company-offices-location-not-mapped = 地点未对应
profiles-company-offices-search-cities = 搜索城市
profiles-company-offices-search-cities-2 = 搜索城市…
profiles-company-offices-country = 国家/地区
profiles-company-offices-cities = { $count ->
   *[other] 个城市
}
profiles-company-offices-text = { $choice ->
    [yes] { $shownCities }/{ $length } 个城市
   *[no] { $length2 } { $value }
}
profiles-company-offices-offices-in = { $label } 的办公地点
profiles-company-offices-show-fewer = { $choice ->
    [yes] 显示 { $label } 的另外 { $hidden } 个
   *[no] 收起
}

## features/company-profiles/CompanyProfilePanel.tsx
profiles-company-profile-panel-says = { $source_label } 显示 { $value }
profiles-company-profile-panel-conflicting-signal = 信息冲突：
profiles-company-profile-panel-no-level-in-this-company = 这家公司的职级体系中还没有级别对应到标准级别。
profiles-company-profile-panel-no-comp-bands-yet = 暂无职级薪酬
profiles-company-profile-panel-band = 级别
profiles-company-profile-panel-level = 公司职级
profiles-company-profile-panel-total-comp = 总薪酬
profiles-company-profile-panel-composition = 构成
profiles-company-profile-panel-stock = 股权
profiles-company-profile-panel-profile-unavailable = 资料不可用
profiles-company-profile-panel-retry = 重试
profiles-company-profile-panel-open = { $open_roles } 个在招
profiles-company-profile-panel-not-on-your-board = 不在你的雷达上
profiles-company-profile-panel-0-open = 0 个在招
profiles-company-profile-panel-values-come-from-the-source = 除非标签另有说明，数值均来自本面板底部注明的来源。来源不一致时，以最可信的来源为准，分歧会标记待审核。
profiles-company-profile-panel-offices-open-roles = 办公地点与在招职位
profiles-company-profile-panel-countries = { $count ->
   *[other] { $countryCount } 个国家/地区
}
profiles-company-profile-panel-where-this-company-is-hiring = 根据在招的招聘信息，这家公司目前在哪些地方招聘。
profiles-company-profile-panel-comp-baseline = 职级薪酬
profiles-company-profile-panel-base = 基本工资
profiles-company-profile-panel-bonus = 奖金
profiles-company-profile-panel-what-a-role-at-each = 各级别职位的薪酬，以及其中股权与现金的比例。
profiles-company-profile-panel-benefits = 福利
profiles-company-profile-panel-base-stock-bonus = 基本工资 { $base_usd } · 股权 { $stock_usd } · 奖金 { $bonus_usd }
profiles-company-profile-panel-see-open-roles = 查看在招职位
profiles-company-profile-panel-see-open-roles-at = { $count ->
   *[other] 查看 { $display_name } 的 { $open_roles } 个在招职位
}
profiles-company-profile-panel-loading = 正在加载这家公司的资料…

## features/company-profiles/CompanyProfilesView.tsx
profiles-company-profiles-view-to-see = 以查看{ $value }
profiles-company-profiles-view-show-all-companies = 显示所有公司
profiles-company-profiles-view-to-start-over = 以重新开始。
profiles-company-profiles-view-clear-the-search = 清除搜索
profiles-company-profiles-view-companies-unavailable = 公司不可用
profiles-company-profiles-view-could-not-load-companies = 无法加载你的公司。请重试。
profiles-company-profiles-view-loading-companies = 正在加载你的公司…
profiles-company-profiles-view-track-one-in-and-its = 在 { $link } 中关注一家公司，其资料就会显示在这里：职级薪酬、股权类型、员工人数，以及每项信息的依据。
profiles-company-profiles-view-settings-companies = 设置 › 公司
profiles-company-profiles-view-all-profiles-current = 所有资料均为最新
profiles-company-profiles-view-show-all = 显示全部
profiles-company-profiles-view-needs-review-only = 仅显示待审核
profiles-company-profiles-view-enrich-fields = 补充字段
profiles-company-profiles-view-no-companies-to-show = { $choice ->
    [v1] 没有与“{ $query }”匹配的已标记公司。
    [v2] 没有与“{ $query2 }”匹配的公司。
    [v3] 目前没有需要审核的内容。
   *[v4] 没有可显示的公司。
}
profiles-company-profiles-view-match = { $count ->
   *[other] 匹配
}
profiles-company-profiles-view-all = { $choice ->
    [yes] { $released } 家{ $value }的公司
   *[no] 全部 { $released2 } 家
}
profiles-company-profiles-view-companies = 公司
profiles-company-profiles-view-you-are-not-tracking-any = 你还没有关注任何公司
profiles-company-profiles-view-search-companies = 搜索公司
profiles-company-profiles-view-find-a-company-or-ticker = 查找公司或股票代码
profiles-company-profiles-view-that-need-review = { $count ->
   *[other] 需要审核
}
profiles-company-profiles-view-need-review = { $count ->
   *[other] 需要审核
}
profiles-company-profiles-view-back-to-every-company-profile = 返回所有公司资料

## features/company-profiles/FieldReview.tsx
profiles-field-review-suggested = 建议
profiles-field-review-save = 保存
profiles-field-review-couldn-t-save-it-try = 无法保存。请重试。
profiles-field-review-set-to-from = 根据 { $source_label } 将 { $label } 设为 { $field }
profiles-field-review-or-enter-a-value = 或输入一个值…
profiles-field-review-custom-value-for = { $label } 的自定义值
profiles-field-review-or-choose-a-value = 或选择一个值…
profiles-field-review-not-a-whole-number = 请输入整数，例如 { $example }。
profiles-field-review-pinned = 已将 { $label } 设为 { $value }
profiles-field-unpinned = { $label } 已恢复为来源提供的值
profiles-field-use-sources = 使用来源
profiles-field-use-sources-for = 使用来源：{ $label }
profiles-field-could-not-use-sources = 无法恢复为来源提供的值。请重试。
profiles-field-could-not-undo = 无法撤销此更改。请重试。

## features/company-profiles/StockPricePanel.tsx
profiles-stock-price-panel-stock-price = 股价
profiles-stock-price-panel-price-history-unavailable-right-now = 价格历史暂不可用。
profiles-stock-price-panel-price-range = 价格区间
profiles-stock-price-panel-stock-price-2 = { $slug } 股价，{ $range }
profiles-stock-price-panel-daily-closes-over-latest-unknown = { $choice ->
    [yes] { $range } 内共 { $length } 个每日收盘价，最新为 ${ $toFixed }。
   *[no] { $range } 内共 { $length } 个每日收盘价，最新价格未知。
}
profiles-stock-price-panel-loading = 正在加载股价…

## features/company-profiles/labels.ts
profiles-labels-current = 最新
profiles-labels-stale = 已过时
profiles-labels-conflicting-signals = 信息冲突
profiles-labels-incomplete = 不完整
profiles-labels-senior = 高级
profiles-labels-staff = 资深
profiles-labels-principal = 首席
profiles-labels-director = 总监及以上
profiles-labels-listed = 上市
profiles-labels-ticker = 股票代码
profiles-labels-headcount = 员工人数
profiles-labels-website = 网站
profiles-labels-equity-vehicle = 股权类型
profiles-labels-vesting = 归属
profiles-labels-options = 期权
profiles-labels-none = 无
profiles-labels-cash-election = 可选现金
profiles-labels-sources-disagree = 来源不一致
profiles-labels-not-checked-recently = 近期未核查
profiles-labels-nothing-on-record = 暂无记录
profiles-labels-no-value = 无
profiles-yes-no = { $answer ->
    [yes] 是
   *[no] 否
}
profiles-equity-policy = { $rule ->
    [none] 这家公司不授予股权，因此它的薪酬不随股价变动。
   *[election] 每位员工自行选择薪酬中有多少以股权形式发放，因此随股价变动的程度由各人决定。
}
profiles-roster-dataset = 已调研的公司
profiles-roster-dataset-hint = 级别与录用条件，逐家公司调研。
profiles-roster-no-sector = 不属于任何行业
profiles-roster-other-hint = 从更广泛的市场中关注。
profiles-stock-price-panel-needs-key = 股价来自 Tiingo 集成。{ $key }，即可填满这张图表。
profiles-stock-price-panel-waiting = 股价将很快到达，取决于 Tiingo 的上限。
profiles-stock-price-panel-empty-title = 暂无股价
profiles-stock-price-panel-range =
    { $range ->
        [m1] 1个月
        [m3] 3个月
        [m6] 6个月
       *[y1] 1年
    }
profiles-stock-price-panel-day-move = { $money }（{ $percent }）
profiles-stock-price-panel-close = 收盘 { $date }
profiles-stock-price-panel-range-move =
    { $range ->
        [m1] 1 个月内
        [m3] 3 个月内
        [m6] 6 个月内
       *[y1] 1 年内
    } { $move }
profiles-stock-price-panel-add-key = 添加密钥
profiles-labels-one-year-grants = 一年期授予
profiles-labels-vested-at-grant = 授予即归属
profiles-benefits-category =
    { $category ->
        [health_wellbeing] 健康与福祉
        [insurance_protection] 保险与保障
        [retirement_financial] 退休与理财计划
        [time_off] 休假
        [family_care] 家庭与照护
        [work_flexibility_equipment] 工作弹性与设备
        [learning_development] 学习与发展
        [mobility_housing] 出行与住房
        [meals_workplace] 餐饮与办公设施
        [discounts_community] 折扣与社区
        [company_specific] 其他公司福利
       *[other] 其他
    }
profiles-benefits-type =
    { $type ->
        [medical_insurance] 医疗保险
        [dental_insurance] 牙科保险
        [vision_insurance] 视力保险
        [health_savings_account] 健康储蓄账户（HSA）
        [flexible_spending_account] 灵活支出账户（FSA）
        [employee_assistance] 员工援助计划
        [wellness_allowance] 健身与健康报销
        [onsite_gym] 公司内健身房
        [fitness_classes] 公司内健身课程
        [gym_discount] 健身房折扣
        [onsite_clinic] 公司内诊所
        [life_insurance] 人寿保险
        [disability_insurance] 伤残保险
        [accident_insurance] 意外死亡与伤残（AD&D）保险
        [travel_insurance] 商务差旅保险
        [pet_insurance] 宠物保险
        [retirement_plan] 401k
        [roth_retirement_option] Roth 401k
        [after_tax_retirement_option] Mega Backdoor Roth
        [employee_share_purchase] 员工购股计划（ESPP）
        [student_loan_support] 学生贷款还款计划
        [employee_credit] 员工信贷
        [vacation] 带薪假（休假 / 个人假）
        [sick_leave] 病假
        [bereavement_leave] 丧假
        [sabbatical] 学术休假
        [military_leave] 兵役假
        [volunteer_leave] 志愿服务假
        [maternity_leave] 产假
        [paternity_leave] 陪产假
        [fertility_support] 生育辅助
        [adoption_support] 收养协助
        [surrogacy_support] 代孕协助
        [nursing_facilities] 公司内母婴室
        [remote_work] 远程办公
        [workstation_equipment] 定制工位
        [phone_allowance] 话费报销
        [company_phone] 公司手机
        [learning_support] 学习与发展
        [tuition_support] 学费报销
        [immigration_support] 移民协助
        [relocation_support] 搬迁奖金
        [transport_allowance] 交通补贴
        [company_shuttle] 公司班车
        [campus_bikes] 园区自行车
        [public_transport] 区域公共交通
        [housing_support] 住房补贴
        [snacks] 免费零食
        [lunch] 免费午餐
        [drinks] 免费饮品
        [breakfast] 免费早餐
        [dinner] 免费晚餐
        [pet_friendly_workplace] 可带宠物上班
        [inclusive_facilities] 无性别卫生间
        [onsite_laundry] 公司内洗衣房
        [onsite_shops] 公司内员工商店
        [vehicle_maintenance] 公司内更换轮胎
        [vehicle_cleaning] 公司内洗车
        [employee_discounts] 员工折扣
        [charitable_matching] 捐款配捐
        [referral_bonus] 内推奖金
        [company_specific_perk] 独特福利
        [pandemic_support] 新冠相关福利
        [parental_leave] 育儿假
        [paid_holidays] 带薪节假日
        [flexible_hours] 弹性工作时间
        [hybrid_work] 混合办公
        [home_office_allowance] 居家办公补贴
        [mental_health_support] 心理健康支持
        [childcare_support] 托育支持
        [caregiver_leave] 照护假
        [food_allowance] 餐饮补贴
        [financial_advice] 理财咨询
       *[other] 其他
    }
profiles-benefits-in-country = 适用于 { $country }
profiles-offer-heading = 录用方案如何构成
profiles-offer-sub = 这家公司如何构成薪酬，依据公司的说明或员工的反馈。
profiles-offer-not-researched = 尚未调研这家公司如何构成录用方案。
profiles-offer-searched-not-found = 已查找，未找到
profiles-offer-checked = 核对于 { $date }
profiles-offer-fact =
    { $fact ->
        [equity_rule] 股权
        [bonus_rule] 年度奖金
        [annual_refresh] 续授
        [sign_on_bridges_vesting] 签约奖金
       *[base_cap_usd] 基本工资上限
    }
profiles-offer-equity-rule =
    { $rule ->
        [dollar_grant_by_level] 按级别授予美元额度
        [tc_target_minus_base] 补足目标薪酬
        [employee_election] 由你选择组合
       *[none] 无股权
    }
profiles-offer-bonus-rule =
    { $rule ->
        [pct_of_base] 基本工资的固定比例
       *[none] 无年度奖金
    }
profiles-offer-refresh =
    { $choice ->
        [yes] 每年，按绩效
       *[no] 无年度续授
    }
profiles-offer-sign-on = 弥补后置归属
profiles-benefits-unreviewed = 按发现时的原样收集，尚未审核。
profiles-benefits-unscoped = 除非显示了国家，否则不记录福利适用的地区。
profiles-level-base-sub = { $stock ->
        [yes] 其软件工程职级中每个级别的估算基本工资、奖金和股权。只有各部分都已知时才显示总额。
       *[no] 其软件工程职级中每个级别的估算基本工资和奖金。股权尚不清楚，因此没有总额。
    }
profiles-level-base-bonus =
    { $choice ->
        [pct] { $amount }（目标 { $pct }）
        [none] 无年度奖金
       *[unknown] 未知
    }
profiles-level-base-below-lower = 低于下一级
profiles-level-base-unknown = 未知
profiles-level-base-no-stock = 无股权
profiles-level-base-none = 还没有这家公司软件工程各级别的基本工资。
profiles-benefits-estimate = { $value }/年，估算
profiles-benefits-mentions =
    { $count ->
       *[other] 在招聘信息中出现 { $count } 次
    }
profiles-benefits-other-wordings =
    { $open ->
        [yes] 隐藏其他表述
       *[no] { $count } 种其他表述
    }
profiles-benefits-also-listed = 另列有：{ $names }
profiles-benefits-shared = 招聘信息中同时提到多项福利的说法
profiles-benefits-not-collected = 尚未收集这家公司的福利。这并不代表它没有福利。
profiles-not-covered = { $plugin } 尚未读取这家公司。请在 设置 › 插件 中关闭它，以查看内置数据。
profiles-field-not-covered = { $plugin } 尚未读取
