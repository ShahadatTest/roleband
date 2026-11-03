## 编译器测试用例，未接入界面（docs/copy.md）。

spike-role-count = { $count ->
   *[other] { $count } 个{ -role(num: "other") }
}
spike-saved-closed = { $company } 关闭了一个你保存的职位
spike-saved-closed-count = { $count ->
   *[other] { $company } 关闭了 { $count } 个你保存的{ -role(num: "other") }
}
