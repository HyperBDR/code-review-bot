---
name: go-code-review
description: Go review rules for correctness, concurrency, context handling, errors, security, performance, testing, modules, and idiomatic Go. Apply when reviewing .go, go.mod, or go.sum changes.
allowed-tools: Read Grep Glob LS
---

# Go Code Review

审查 Go 代码时优先关注正确性、并发安全、错误处理和接口兼容性。风格建议应服从项目已有约定，不要为纯格式问题阻塞合入。

## 优先级

1. **正确性**：业务逻辑、边界条件、nil、错误路径、返回值和调用方预期。
2. **并发与资源**：goroutine 生命周期、channel、锁、context、泄漏、数据竞争。
3. **安全**：输入校验、命令/SQL 注入、路径穿越、敏感信息日志、随机数和加密误用。
4. **API 与兼容性**：导出接口、结构体字段、JSON/YAML tag、配置、数据库、HTTP/gRPC 契约。
5. **可维护性和测试**：命名、包边界、复杂度、可测试性、关键路径覆盖。

## 正确性

- 检查 `nil` 指针、空 slice/map、零值、类型断言和 panic 风险。
- 检查错误返回是否被处理，不要吞掉错误或只记录不返回。
- 检查 defer 的执行顺序、循环中的 defer、闭包捕获循环变量。
- 检查时间、超时、重试、幂等、分页、排序和边界输入。
- 检查 map 访问、slice 下标、字符串/字节转换是否安全。

## 错误处理

- 错误要包含足够上下文，推荐 `fmt.Errorf("...: %w", err)` 保留根因。
- 不要用字符串比较错误，优先 `errors.Is` / `errors.As`。
- 对外暴露错误信息时避免泄露敏感数据。
- 不要把可恢复错误变成 panic；panic 只用于不可恢复或初始化失败等明确场景。

## Context 与并发

- I/O、RPC、数据库、外部命令应传递 `context.Context`。
- 不要把 context 存进结构体长期保存，除非项目有明确约定。
- goroutine 必须有退出路径；检查 channel 关闭、cancel、WaitGroup 使用。
- 锁保护的共享状态要完整；避免读写 map 数据竞争。
- channel 发送/接收要考虑阻塞、缓冲、关闭和 select 默认分支。

## 资源管理

- 文件、网络连接、response body、rows 等资源必须关闭。
- `defer resp.Body.Close()` 前要检查 `err` 和 `resp != nil`。
- 数据库 rows 需要 `Close`，并检查 `rows.Err()`。
- 临时文件和目录要有清理路径。

## 安全

- SQL 必须参数化，禁止拼接未信任输入。
- shell/exec 参数要分离，避免拼接命令字符串。
- 路径处理要防目录穿越，尤其是上传、解压、下载、静态文件。
- 日志不能输出 token、密码、认证 URL、请求头中的敏感字段。
- 加密、随机数和 token 生成应使用 `crypto/*`，不要使用 `math/rand`。

## Idiomatic Go

- 包名短小清晰，不用下划线或驼峰。
- 接口在消费方定义，避免过早抽象。
- 小接口优先，避免巨大 interface。
- 命名遵循 Go 习惯：`ID`、`HTTP` 等初始缩写保持一致。
- 不要过度使用全局可变状态。
- 简单逻辑保持直接，不要为了“设计模式”增加复杂度。

## 性能

- 避免不必要的大对象复制，关注 slice/map 预分配。
- 字符串拼接多次时使用 `strings.Builder`。
- 热路径避免重复正则编译、重复 JSON 编解码、重复数据库查询。
- 性能建议必须基于明确风险，不要过早优化。

## 测试

- 关键路径应有 table-driven tests。
- 并发、超时、错误路径、边界输入应有覆盖。
- 测试避免依赖真实时间、外部网络和全局状态；必要时使用 fake clock / mock。

## 输出要求

不要输出本 skill 的英文模板。将 Go 发现合并到 `git-review` 的中文结构中：

- 正确性、安全、并发泄漏、数据竞争、兼容性破坏使用 `[严重]`
- 风格、可维护性、测试补强使用 `[建议]`
- 指明文件、函数或相关代码片段
- 给出具体、可操作的修复方向
