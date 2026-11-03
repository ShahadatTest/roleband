## compare：按原样迁移（wording=as-is）

## features/compare/CompareScreen.tsx
compare-screen-back = 返回
compare-screen-clear = 清空
compare-screen-compare = 对比
compare-screen-on-your-or-in-use = 在你的{ $radar }或{ $saved }中，点击某一行的{ $icon } 按钮即可将其加入这里。
compare-screen-radar = 雷达
compare-screen-saved = 已保存
compare-screen-same = 相同
compare-screen-fields = 个字段
compare-screen-descriptions = 职位描述
compare-screen-no-description-for-this-role = 该职位没有描述。
compare-screen-shared-passages-hidden = { $count ->
   *[other] 已隐藏 { $hidden } 处共同段落
}
compare-screen-picking = { $needed ->
    [pair] 对比中 { $picked } 个 · 选两个
   *[another] 对比中 { $picked } 个 · 再选一个
}
compare-screen-comparing = { $capacity ->
    [full] 正在对比 { $count } 个职位 · 完整
   *[open] 正在对比 { $count } 个职位
}
compare-screen-back-aria = 返回
compare-screen-comparison = 对比
compare-screen-pick-at-least-two = 至少选择两个
compare-screen-not-for-me = 不适合我：{ $title }
compare-screen-not-for-me-hide-this = 不适合我
compare-screen-remove-from-comparison = 移除{ $title }
compare-screen-remove = 移除
compare-screen-show-or-hide-matching-fields = { $fields ->
    [open] 隐藏 { $count } 个相同字段
   *[folded] 显示 { $count } 个相同字段
}
compare-screen-show-or-hide = { $fields ->
    [open] 隐藏
   *[folded] 显示
}
compare-screen-passages-legend = { $passages ->
    [shared] 琥珀色段落并非出现在每条招聘信息中。
   *[none] 这些招聘信息没有共同的段落。
}
compare-screen-description-view = { $view ->
    [differences] 显示完整描述
   *[full] 仅显示差异
}
compare-screen-loading = 正在加载对比…
compare-screen-load-failed = 无法加载对比

## features/compare/attributes.tsx
compare-attributes-level = 级别
compare-attributes-est-comp = 估算总薪酬
compare-attributes-locations = 地点
compare-attributes-regions = 地区
compare-attributes-workplace = 办公方式
compare-attributes-listed-for = 发布时长
compare-attributes-status = 状态
compare-attributes-reposts = 重新发布次数

## features/compare/useCompareController.ts
compare-use-compare-controller-removed-from-compare = 已从对比中移除{ $title }
compare-use-compare-controller-undo = 撤销
compare-use-compare-controller-could-not-unsave = { $direction ->
    [save] 无法保存{ $title }
   *[unsave] 无法将{ $title }从已保存中移除
}
compare-use-compare-controller-couldn-t-restore = 无法恢复{ $title }
compare-use-compare-controller-not-for-me = 不适合我 · { $title }
compare-use-compare-controller-could-not-hide = 无法将{ $title }标记为不适合我

## 从对比中再添加一个职位。
compare-screen-add-another = 再添加一个
