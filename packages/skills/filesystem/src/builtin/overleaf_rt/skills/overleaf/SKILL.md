---
name: overleaf
description: 在 Overleaf 中登录和检查连接、阅读与编辑项目文档、管理审阅评论、编译 LaTeX 和排查错误。需要操作 Overleaf 时加载本技能，再按任务读取对应参考文档。
argument-hint: "[任务、项目或 Overleaf 地址]"
required-tools: []
tools:
  - overleaf_list_hosts
  - overleaf_list_projects
  - overleaf_get_project_tree
  - overleaf_read_doc
  - overleaf_read_doc_range
  - overleaf_edit_doc
  - overleaf_write_doc
  - overleaf_create_doc
  - overleaf_create_folder
  - overleaf_delete_entity
  - overleaf_move
  - overleaf_rename
  - overleaf_upload_file
  - overleaf_list_comments
  - overleaf_add_comment
  - overleaf_reply_comment
  - overleaf_resolve_comment
  - overleaf_compile
  - overleaf_download_pdf
  - overleaf_read_compile_log
---

# Overleaf

这是唯一的 Overleaf 技能入口。先确定用户任务，再读取对应的一份参考文档，
不要预先加载整个 references 目录，也不要把参考文档当成独立技能调用。

| 用户任务 | 按需读取 |
| --- | --- |
| 首次连接、安装、认证或连接故障 | references/setup.md |
| 登录或刷新会话 | references/login.md |
| 检查登录、主机与连接状态 | references/status.md |
| 阅读、编辑和管理项目文件 | references/editing.md |
| 添加、回复、查看和解决评论 | references/comments.md |
| 编译、PDF、日志和 LaTeX 工作流 | references/compilation.md |

使用技能工具读取相关参考文档，例如：

```json
{"name": "overleaf", "resource": "references/comments.md"}
```

工具名是 `skill`。只有任务涉及另一个方面时，才继续读取另一份参考文档。

## 工具与连接状态

入口与参考资料可以在 Overleaf 工具尚未启动时读取，便于指导设置和登录。
这不表示执行服务已连接：实际操作只能使用当前工具列表中可用的 overleaf_* 工具。
如果缺少相应工具，先读取 setup.md，说明缺少连接，不要伪造操作结果。
工具未加载和技能未安装是不同状态。

登录由用户在浏览器完成，不索要密码、cookie 或读取凭据文件正文。
修改文档和发布评论时遵循所读取参考文档的约束与用户请求。
