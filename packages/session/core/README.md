# Session core

不依赖后端或数据库的会话事实层：`Session`、`SessionHeader`、`SessionEvent`、`SurfaceManager`、工具调用/进度记录和检查点协议。循环插件、持久化适配器和 UI 投影共享同一套事件与错误类型。

PostgreSQL 存储、恢复、标题服务和会话存储装配仍由后端提供。旧 `backend/agents/runtime/session` 对这些公共类型保留兼容导入，所有实现与类型身份都来自本包。
