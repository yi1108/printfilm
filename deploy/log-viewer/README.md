# 独立生产日志页面

入口：`http://8.136.41.61:8066/`。独立 HTTP 服务直接监听 8066，不经过 Nginx，不依赖域名或业务账号。使用专用 HTTP Basic 账号密码；页面、脚本及所有日志接口均要求认证。按用户要求保留原始日志，不做脱敏。

- 采集器每 5 秒读取固定来源：API 最近一小时最多 1000 行，主站/后台 Nginx 最近访问和错误日志各最多 500 行。读取有大小上限，原子替换快照。
- 快照目录 `/run/printfilm-log-viewer` 权限 0750，文件 0640，仅 root 和专用 printfilm-logs 组可读。
- 网页服务使用无特权动态用户，只读快照，无法读取 Docker socket、业务配置或原始日志文件。
- `/etc/printfilm-log-viewer/auth.json` 权限 0600，保存用户名及随机密码的 SHA-256；通过 systemd LoadCredential 交给服务。更换密码后重启日志服务。
- 页面支持来源、关键词、级别筛选、每 5 秒更新、暂停和手机布局。快照超过 30 秒提示采集延迟。日志通过 textContent 显示，防止 HTML 注入。
- 限制请求速率和并发连接。没有修改日志、执行命令或读取任意文件的接口。

检查：`python3 -m unittest discover -s deploy/log-viewer -p 'test_*.py'`。
服务：`printfilm-log-viewer.service`、`printfilm-log-collector.timer`。
发布目录：`/opt/printfilm-log-viewer/releases/<version>`，`current` 指向当前版本。
停用：停止并禁用上述服务、定时器，关闭此次新增的 TCP 8066 防火墙规则；无需操作 Nginx、业务 API 或数据库。
